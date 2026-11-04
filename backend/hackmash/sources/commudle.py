"""Commudle: Indian developer-community platform (GDGs, KNOTiC, college clubs).

Public JSON API used by the Angular web app:
    GET https://json.commudle.com/api/v2/hackathons/public/all_hackathons?when=future
    GET https://json.commudle.com/api/v2/hackathons/public/all_hackathons?when=past&after=<cursor>
Cursor-paginated (``page_info``); each entry has exact start/end timestamps,
mode (online / offline / hybrid), team size, prize total per currency, banner
and the hosting community. Pages: https://www.commudle.com/communities/<community>/hackathons/<slug>.
Hackathons that are running right now can show up under either ``future`` or
``past``, so both are read and filtered on the end date.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from ..models import RawHackathon
from .base import Source, as_int, clean_text, get_json, html_to_text, parse_money, to_utc

log = logging.getLogger(__name__)

API = "https://json.commudle.com/api/v2/hackathons/public/all_hackathons"
PAGE_URL = "https://www.commudle.com/communities/{community}/hackathons/{slug}"
MAX_PAST_PAGES = 1  # newest first (~500 KB a page): only the newest can still be running
_MODES = {"online": "online", "offline": "in_person", "hybrid": "hybrid"}
_SYMBOL = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}
_POOL_RE = re.compile(
    r"prize pool(?: of)?[:\s]+((?:₹|\$|usd|inr|rs\.?)\s?[\d,.]+\s*(?:usd|inr|k\b|lakhs?|lacs?)?)", re.I
)


def _fmt(amount: float, currency: str) -> str:
    whole = int(round(amount))
    if currency == "INR":
        s = str(whole)
        if len(s) > 3:
            head, tail = s[:-3], s[-3:]
            groups = []
            while len(head) > 2:
                groups.insert(0, head[-2:])
                head = head[:-2]
            s = ",".join(([head] if head else []) + groups) + "," + tail
        return f"₹{s}"
    symbol = _SYMBOL.get(currency)
    return f"{symbol}{whole:,}" if symbol else f"{whole:,} {currency}"


def classify_kind(name: str, tagline: str) -> str:
    text = f"{name} {tagline}"
    if re.search(r"idea[\s-]?a?thon|\bideation\b|\bpitch", text, re.I):
        return "ideathon"
    if re.search(r"design (competition|challenge|contest)|designathon", text, re.I):
        return "other"
    if re.search(r"\bctf\b|capture the flag|coding contest|competitive programming", text, re.I):
        return "coding_contest"
    if re.search(r"datathon|data[\s-]?thon|kaggle", text, re.I):
        return "data_science"
    return "hackathon"


class Commudle(Source):
    key = "commudle"
    name = "Commudle"
    homepage = "https://www.commudle.com/hackathons"
    region = "india"
    focus = "Community-run developer hackathons"
    description = (
        "Indian developer-community platform where GDGs, college clubs and dev communities run "
        "hackathons alongside their meetups."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        rows: list[dict[str, Any]] = []
        rows += await self._pages(client, "future", pages=10)
        try:
            rows += await self._pages(client, "past", pages=MAX_PAST_PAGES)
        except Exception as exc:  # noqa: BLE001 - "past" only adds hackathons that are still running
            log.warning("commudle: past listing failed: %s", exc)
        now = datetime.now(timezone.utc)
        items: list[RawHackathon] = []
        seen: set[str] = set()
        for row in rows:
            key = str(row.get("id") or row.get("slug") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            try:
                item = self._build(row)
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("commudle: could not parse %s", row.get("slug"))
                continue
            if item.ends_at and item.ends_at < now:
                continue
            items.append(item)
        return items

    async def _pages(self, client: httpx.AsyncClient, when: str, pages: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        cursor = None
        for _ in range(pages):
            params: dict[str, Any] = {"when": when, "limit": 50}
            if cursor:
                params["after"] = cursor
            data = (await get_json(client, API, params=params, headers={"Accept": "application/json"})) or {}
            block = data.get("data") or {}
            out += [x.get("data") for x in block.get("page") or [] if isinstance(x, dict) and x.get("data")]
            info = block.get("page_info") or {}
            cursor = info.get("end_cursor")
            if not info.get("has_next_page") or not cursor:
                break
        return out

    def _build(self, row: dict[str, Any]) -> RawHackathon:
        community = row.get("community") or {}
        slug = clean_text(row.get("slug")) or str(row["id"])
        name = clean_text(row.get("name")) or slug
        tagline = clean_text(row.get("tagline")) or ""
        mode = _MODES.get(str(row.get("hackathon_location_type") or "").lower())
        description_html = row.get("description") or ""
        venue = re.search(r"Venue:\s*(?:</[^>]+>\s*)*([^<\n]{3,80})", description_html, re.I)
        location = "Online" if mode == "online" else (clean_text(venue.group(1)) if venue else None)

        prizes = row.get("total_prize_amount") if isinstance(row.get("total_prize_amount"), dict) else {}
        prizes = {k.upper(): float(v) for k, v in prizes.items() if isinstance(v, (int, float)) and v > 0}
        amount = currency = None
        prize_text = None
        if prizes:
            currency, amount = max(prizes.items(), key=lambda kv: kv[1])
            prize_text = _fmt(amount, currency)
        else:  # organisers often only write it in the description: "a total prize pool of $3,000 USD"
            text = html_to_text(description_html, max_len=20000) or ""
            m = _POOL_RE.search(text)
            if m:
                amount, currency = parse_money(m.group(1))
                prize_text = clean_text(m.group(0))

        team_min = as_int(row.get("min_number_of_teammates"))
        team_max = as_int(row.get("max_number_of_teammates"))
        if str(row.get("participate_types") or "").lower() == "individual":
            team_min = team_max = 1
        banner = (row.get("banner_image") or {}).get("url") if isinstance(row.get("banner_image"), dict) else None
        logo = (community.get("logo_image_path") or {}).get("url") if isinstance(community.get("logo_image_path"), dict) else None
        interested = as_int(row.get("interested_members_count"))
        theme = clean_text(row.get("hackathon_theme"))

        return RawHackathon(
            source=self.key,
            source_id=str(row.get("id") or slug),
            title=name,
            url=PAGE_URL.format(community=community.get("slug") or "commudle", slug=slug),
            kind=classify_kind(name, tagline),
            organizer=clean_text(community.get("name")),
            tagline=tagline or None,
            description=html_to_text(description_html),
            image_url=banner,
            logo_url=logo,
            mode=mode,
            location=location,
            starts_at=to_utc(row.get("start_date")),
            ends_at=to_utc(row.get("end_date")),
            timezone="Asia/Kolkata",
            prize_text=prize_text,
            prize_amount=amount,
            prize_currency=currency if amount else None,
            tags=[theme] if theme else [],
            participants=interested if interested else None,
            team_size_min=team_min,
            team_size_max=team_max,
            extra={
                "status": row.get("status"),
                "community_slug": community.get("slug"),
                "capacity": as_int(row.get("number_of_participants")),
            },
        )
