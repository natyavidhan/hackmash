"""DoraHacks: the largest Web3 hackathon platform (BUIDL), also AI / quantum / space.

The site is a Nuxt app that talks to a public "hub" JSON API (found in the
``entry.*.js`` bundle: ``ae.hub -> https://dorahacks.io/api/v1/hub/``):

    GET https://dorahacks.io/api/v1/hub/hackathons?status=ongoing|upcoming&page=N&page_size=50
    GET https://dorahacks.io/api/v1/hub/hackathons/<id>          (markdown description, venue)

Timeline fields are epoch seconds. When ``timeline_pre_register`` is set the
page shows "Pre-registration <timeline_start> / Submission <timeline_pre_register>
/ Deadline <timeline_end>", so registration opens at ``timeline_start`` and
building starts at ``timeline_pre_register``.

Venue country/city are numeric ids resolved through the site's own lookup table
``https://cdn.dorahacks.io/script/region.const.mjs`` (only fetched when an
in-person event is listed). City ids follow the simplemaps scheme
``1<ISO-3166 numeric><6 digits>``, which we use as a fallback for the country.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pycountry

from ..models import RawHackathon
from .base import (
    Source,
    as_int,
    clean_text,
    gather_limited,
    get_json,
    get_text,
    html_to_text,
    to_utc,
)

log = logging.getLogger(__name__)

API = "https://dorahacks.io/api/v1/hub/hackathons"
REGION_URL = "https://cdn.dorahacks.io/script/region.const.mjs"
SITE = "https://dorahacks.io"
PAGE_SIZE = 50  # the API caps page_size at 50
MAX_PAGES = 30

# fiat / stablecoin prize tokens we can express as an ISO-4217 amount
_FIAT = {"USD", "EUR", "GBP", "INR", "CAD", "CHF", "AUD", "SGD", "JPY", "CNY", "HKD", "KRW", "AED", "BRL"}
_STABLE = {"USDC": "USD", "USDT": "USD", "USDG": "USD", "PYUSD": "USD", "DAI": "USD", "BUSD": "USD"}
_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹"}

_VISIBILITY = {0: "public", 1: "password_required_for_submission", 2: "private"}
_PLACEHOLDER_RE = re.compile(r"to be announced|\btba\b|\btbd\b|disclosed|will be shared|coming soon", re.I)

_COUNTRY_RE = re.compile(r'\[\s*(\d+),\s*"((?:[^"\\]|\\.)*)",\s*\[')
_CITY_RE = re.compile(r'\[\s*(\d{6,}),\s*"((?:[^"\\]|\\.)*)",\s*"((?:[^"\\]|\\.)*)"\s*\]')

_region_cache: tuple[dict[int, str], dict[int, tuple[str, str]]] | None = None


def _unquote(s: str) -> str:
    try:
        return json.loads(f'"{s}"')
    except ValueError:
        return s


def md_to_text(value: Any, max_len: int = 1500) -> str | None:
    """Markdown (with stray HTML) to readable plain text."""
    if not value:
        return None
    text = str(value)
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)  # images
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links -> label
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)  # headings
    text = re.sub(r"(?m)^\s*(?:[-*+]|\d+\.)\s+", "• ", text)  # list bullets
    text = re.sub(r"(?m)^\s*>\s?", "", text)  # quotes
    text = re.sub(r"(?m)^\s*(?:-{3,}|\*{3,}|_{3,}|\|[-:| ]+\|)\s*$", "", text)  # rules / table separators
    text = re.sub(r"(\*\*|__|~~|`)", "", text)
    text = re.sub(r"(?<!\w)\*(?!\s)([^*\n]+)(?<!\s)\*(?!\w)", r"\1", text)
    text = text.replace("\\", "")
    return html_to_text(text.replace("\n", "<br>"), max_len=max_len)


def _split_tags(*values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        for part in str(value or "").split(","):
            tag = clean_text(part)
            if tag and tag.lower() not in seen:
                seen.add(tag.lower())
                out.append(tag)
    return out


def _country_from_city_id(city_id: Any) -> str | None:
    digits = str(city_id or "")
    if len(digits) != 10 or not digits.startswith("1"):
        return None
    country = pycountry.countries.get(numeric=digits[1:4])
    return getattr(country, "name", None) if country else None


class DoraHacks(Source):
    key = "dorahacks"
    name = "DoraHacks"
    homepage = "https://dorahacks.io/hackathon"
    region = "global"
    focus = "Web3 hackathons and BUIDL competitions"
    description = (
        "The largest Web3 hackathon platform: online and in-person hackathons, bounties and "
        "builder programmes run by blockchain ecosystems, plus AI, quantum and space-tech events."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        rows: dict[int, dict[str, Any]] = {}
        for status in ("ongoing", "upcoming"):
            for page in range(1, MAX_PAGES + 1):
                data = await get_json(
                    client, API, params={"status": status, "page": page, "page_size": PAGE_SIZE}
                )
                batch = data.get("results") or []
                for row in batch:
                    if isinstance(row, dict) and row.get("id") is not None:
                        rows.setdefault(int(row["id"]), row)
                if not batch or not data.get("next"):
                    break

        now = datetime.now(timezone.utc)
        current = [
            r for r in rows.values() if (to_utc(r.get("timeline_end")) or now) >= now - timedelta(hours=1)
        ]
        # private hackathons (visibility 2) answer 404 on the detail endpoint
        details = await gather_limited(
            (self._detail(client, r["id"]) for r in current if r.get("visibility") != 2), limit=6
        )
        by_id = {d["id"]: d for d in details if isinstance(d, dict) and d.get("id") is not None}

        regions = None
        if any(r.get("venue_country_id") or r.get("venue_city_id") for r in current):
            regions = await self._regions(client)

        items: list[RawHackathon] = []
        for row in current:
            try:
                items.append(self._build(row, by_id.get(row["id"]), regions))
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("dorahacks: could not parse hackathon %s", row.get("id"))
        return items

    async def _detail(self, client: httpx.AsyncClient, hid: Any) -> dict[str, Any] | None:
        try:
            return await get_json(client, f"{API}/{hid}", retries=2)
        except Exception as exc:  # noqa: BLE001
            log.warning("dorahacks: detail failed for %s: %s", hid, exc)
            return None

    async def _regions(
        self, client: httpx.AsyncClient
    ) -> tuple[dict[int, str], dict[int, tuple[str, str]]] | None:
        global _region_cache
        if _region_cache is not None:
            return _region_cache
        try:
            text = await get_text(client, REGION_URL, retries=2)
        except Exception as exc:  # noqa: BLE001
            log.warning("dorahacks: region table unavailable: %s", exc)
            return None
        countries = {int(m.group(1)): _unquote(m.group(2)) for m in _COUNTRY_RE.finditer(text)}
        cities = {
            int(m.group(1)): (_unquote(m.group(2)), _unquote(m.group(3))) for m in _CITY_RE.finditer(text)
        }
        if countries:
            _region_cache = (countries, cities)
        return countries, cities

    def _build(
        self,
        row: dict[str, Any],
        detail: dict[str, Any] | None,
        regions: tuple[dict[int, str], dict[int, tuple[str, str]]] | None,
    ) -> RawHackathon:
        d = {**row, **(detail or {})}
        hid = int(row["id"])
        slug = clean_text(d.get("uname")) or str(hid)

        start = to_utc(d.get("timeline_start") or None)
        end = to_utc(d.get("timeline_end") or None)
        pre = to_utc(d.get("timeline_pre_register") or None)
        registration_opens = None
        if pre and start and pre != start:
            registration_opens, start = min(pre, start), max(pre, start)

        venue_form = str(d.get("venue_form") or "").strip().lower()
        mode = {"virtual": "online", "online": "online", "irl": "in_person", "hybrid": "hybrid"}.get(
            venue_form
        )

        city = country = province = None
        country_id, city_id = as_int(d.get("venue_country_id")), as_int(d.get("venue_city_id"))
        if regions:
            countries, cities = regions
            country = countries.get(country_id) if country_id else None
            if city_id and city_id in cities:
                city, province = cities[city_id]
        if city_id and not country:
            country = _country_from_city_id(city_id)

        location = None
        if mode == "online":
            location = "Online"
        else:
            venue = clean_text(d.get("venue_name"))
            address = clean_text(d.get("venue_address"))
            parts = [p for p in (venue, address) if p and not _PLACEHOLDER_RE.search(p)]
            if len(parts) == 2 and parts[0].lower() in parts[1].lower():
                parts = parts[1:]
            place = ", ".join(x for x in (city, province if province != city else None, country) if x)
            if parts and place and city and city.lower() not in " ".join(parts).lower():
                parts.append(place)
            location = ", ".join(parts) or place or None

        price = d.get("bonus_price")
        token = str(d.get("bonus_token") or "").strip()
        prize_amount = prize_currency = prize_text = None
        if isinstance(price, (int, float)) and price > 0 and token:
            currency = _STABLE.get(token.upper()) or (token.upper() if token.upper() in _FIAT else None)
            if currency:
                prize_amount, prize_currency = float(price), currency
                symbol = _SYMBOLS.get(currency)
                prize_text = f"{symbol}{price:,.0f}" if symbol else f"{price:,.0f} {currency}"
            else:
                prize_text = f"{price:,.0f} {token}"  # token-denominated pool, e.g. ADA
        bonus = [clean_text(b.get("name")) for b in d.get("bonus_description") or [] if isinstance(b, dict)]
        bonus = [b for b in bonus if b]

        visibility = as_int(d.get("visibility")) or 0
        owner = d.get("owner") or {}
        original_end = to_utc(d.get("timeline_old_end") or None)
        tracks = [
            clean_text(t.get("name"))
            for t in d.get("tracks") or []
            if isinstance(t, dict) and t.get("name") and "DEFAULT" not in str(t.get("name"))
        ]

        return RawHackathon(
            source=self.key,
            source_id=str(hid),
            title=clean_text(d.get("title")) or "Untitled hackathon",
            url=f"{SITE}/hackathon/{slug}",
            organizer=clean_text(owner.get("name")),
            tagline=clean_text(d.get("summary")),
            description=md_to_text(d.get("description")),
            image_url=d.get("image_url") or None,
            logo_url=None if "default-avatar" in str(owner.get("logo")) else owner.get("logo") or None,
            mode=mode,
            location=location,
            city=city,
            country=country,
            starts_at=start,
            ends_at=end,
            registration_opens_at=registration_opens,
            submission_deadline=end,
            prize_text=prize_text,
            prize_amount=prize_amount,
            prize_currency=prize_currency,
            non_cash_prizes=True if bonus else None,
            tags=_split_tags(d.get("tags"), d.get("ecosystem")),
            participants=as_int(d.get("hackers_count")),
            invite_only=visibility in (1, 2),
            extra={
                "visibility": _VISIBILITY.get(visibility, visibility),
                "buidls_count": as_int(d.get("buidls_count")),
                "is_extended": bool(d.get("is_extended")),
                "original_end": original_end.isoformat() if original_end else None,
                "venue_name": clean_text(d.get("venue_name")),
                "tracks": [t for t in tracks if t],
                "other_prizes": bonus,
            },
        )
