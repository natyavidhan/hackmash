"""Devpost: the largest global hackathon platform (online + in-person).

List endpoint (public JSON, 40 per page max):
    https://devpost.com/api/hackathons?page=N&per_page=40&status[]=open&status[]=upcoming
Each hackathon page embeds schema.org JSON-LD with exact start/end datetimes,
address, attendance mode and the prize pool currency, so we enrich every
listing from its page (bounded concurrency).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from typing import Any

import httpx

from ..models import RawHackathon
from .base import (
    Source,
    abs_url,
    as_int,
    clean_text,
    gather_limited,
    get_json,
    get_text,
    html_to_text,
    parse_money,
    to_utc,
)

log = logging.getLogger(__name__)

LIST_URL = "https://devpost.com/api/hackathons"
PER_PAGE = 40
MAX_PAGES = 30

_LD_RE = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
_MONTHS = "Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec"


def parse_period(text: str | None) -> tuple[datetime | None, datetime | None]:
    """Parse Devpost's "Oct 01 - Nov 12, 2026" / "Dec 15, 2026 - Jan 20, 2027"."""
    if not text:
        return None, None
    parts = [p.strip() for p in text.split(" - ")]
    if len(parts) == 1:
        d = to_utc(parts[0])
        return d, d
    left, right = parts[0], parts[-1]
    end = to_utc(right)
    if end is None:
        return None, None
    if not re.search(r"\d{4}", left):
        # left side has no year: same year as the end, or the year before if it wraps
        m = re.match(rf"({_MONTHS})\w*\s+(\d{{1,2}})", left)
        if m is None:
            return None, end
        start = to_utc(f"{m.group(1)} {m.group(2)}, {end.year}")
        if start and start > end:
            start = start.replace(year=end.year - 1)
        return start, end
    return to_utc(left), end


def _ld_event(html: str) -> dict[str, Any] | None:
    for m in _LD_RE.finditer(html):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        for node in data if isinstance(data, list) else [data]:
            types = node.get("@type") if isinstance(node, dict) else None
            types = types if isinstance(types, list) else [types]
            if "Event" in types or "Hackathon" in types:
                return node
    return None


class Devpost(Source):
    key = "devpost"
    name = "Devpost"
    homepage = "https://devpost.com/hackathons"
    region = "global"
    focus = "The biggest global hackathon platform"
    description = (
        "Home of thousands of online and in-person hackathons run by companies like "
        "Google, Microsoft and AWS, plus university events."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        rows: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            data = await get_json(
                client,
                LIST_URL,
                params={"page": page, "per_page": PER_PAGE, "status[]": ["open", "upcoming"]},
            )
            batch = data.get("hackathons") or []
            rows.extend(batch)
            total = (data.get("meta") or {}).get("total_count") or 0
            if not batch or len(rows) >= total:
                break

        details = await gather_limited((self._detail(client, r["url"]) for r in rows), limit=8)
        items: list[RawHackathon] = []
        seen: set[str] = set()
        for row, detail in zip(rows, details, strict=True):
            if str(row.get("id")) in seen:
                continue
            seen.add(str(row.get("id")))
            ld = detail if isinstance(detail, dict) else None
            try:
                items.append(self._build(row, ld))
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("devpost: could not parse %s", row.get("url"))
        return items

    async def _detail(self, client: httpx.AsyncClient, url: str) -> dict[str, Any] | None:
        try:
            return _ld_event(await get_text(client, url, retries=2))
        except Exception as exc:  # noqa: BLE001
            log.warning("devpost: detail page failed %s: %s", url, exc)
            return None

    def _build(self, row: dict[str, Any], ld: dict[str, Any] | None) -> RawHackathon:
        location = (row.get("displayed_location") or {}).get("location")
        icon = (row.get("displayed_location") or {}).get("icon")
        mode = "online" if icon == "globe" or (location or "").lower() == "online" else "in_person"

        start, end = parse_period(row.get("submission_period_dates"))
        city = region = country = None
        image = description = None
        prize_amount, prize_currency = parse_money(html_to_text(row.get("prize_amount")))

        if ld:
            start = to_utc(ld.get("startDate")) or start
            end = to_utc(ld.get("endDate")) or end
            image = ld.get("image") if isinstance(ld.get("image"), str) else None
            description = clean_text(ld.get("description"))
            if description:
                description = re.sub(r"^About the challenge\s*", "", description).strip() or None
            attendance = str(ld.get("eventAttendanceMode") or "")
            if "Mixed" in attendance:
                mode = "hybrid"
            elif "Offline" in attendance:
                mode = "in_person"
            elif "Online" in attendance:
                mode = "online"
            address = ((ld.get("location") or {}).get("address")) or {}
            if isinstance(address, dict):
                city = clean_text(address.get("addressLocality"))
                region = clean_text(address.get("addressRegion"))
                country = clean_text(address.get("addressCountry"))
                street = clean_text(address.get("streetAddress"))
                if street and mode != "online":
                    if not country and "," in street:
                        country = street.rsplit(",", 1)[1].strip()  # "51 College Ave, Troy, NY 12180, USA"
                    venue = clean_text(address.get("name"))
                    if venue and venue.lower() == (clean_text(row.get("title")) or "").lower():
                        venue = None  # Devpost repeats the event name when no venue is set
                    location = street if not venue or venue in street else f"{venue}, {street}"
            for prop in ld.get("additionalProperty") or []:
                if isinstance(prop, dict) and "prize" in str(prop.get("name", "")).lower():
                    value = as_int(prop.get("value"))
                    if value:
                        prize_amount = float(value)
                        prize_currency = (prop.get("unitText") or prize_currency or "USD").upper()

        if mode == "online":
            location = "Online"
        elif not location or location == (row.get("displayed_location") or {}).get("location"):
            venue = location
            location = ", ".join(x for x in (venue, city, region, country) if x) or None

        logo = abs_url("https://devpost.com", row.get("thumbnail_url"))
        if logo and "placeholder" in logo:
            logo = None
        if image and "placeholder" in image:
            image = None

        prize_text = None
        if prize_amount:
            symbol = {"USD": "$", "INR": "₹", "EUR": "€", "GBP": "£"}.get(prize_currency or "", "")
            prize_text = f"{symbol}{prize_amount:,.0f}" if symbol else f"{prize_amount:,.0f} {prize_currency}"
        counts = row.get("prizes_counts") or {}

        return RawHackathon(
            source=self.key,
            source_id=str(row["id"]),
            title=clean_text(row.get("title")) or "Untitled hackathon",
            url=row["url"],
            organizer=clean_text(row.get("organization_name")),
            description=description,
            image_url=image,
            logo_url=logo,
            mode=mode,
            location=location,
            city=city,
            country=country,
            starts_at=start,
            ends_at=end,
            submission_deadline=end,
            prize_text=prize_text,
            prize_amount=prize_amount,
            prize_currency=prize_currency if prize_amount else None,
            non_cash_prizes=bool(counts.get("other")) or None,
            tags=[t["name"] for t in row.get("themes") or [] if t.get("name")],
            participants=as_int(row.get("registrations_count")),
            eligibility=[
                e
                for e in [clean_text(row.get("eligibility_requirement_invite_only_description"))]
                if e
            ],
            invite_only=bool(row.get("invite_only")),
            extra={
                "featured": bool(row.get("featured")),
                "open_state": row.get("open_state"),
                "gallery_url": row.get("submission_gallery_url"),
            },
        )
