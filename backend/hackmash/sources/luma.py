"""Luma (luma.com, formerly lu.ma): hackathons among the events Luma features per city.

Luma has no public search (``/search/get-results`` needs a login), but the Discover pages
are backed by an anonymous JSON API:

    https://api.lu.ma/discover/bootstrap-page                      ~90 featured cities ("places")
    https://api.lu.ma/discover/get-paginated-events
        ?discover_place_api_id=<place>&pagination_limit=50&pagination_cursor=<cursor>

Each place feed is Luma's curated list of upcoming events for that city (SF ~80, London ~60,
Bengaluru ~15), with exact UTC times, the IANA timezone, address, host calendar, ticket
price and guest count. We keep only events whose title says they are a hackathon /
buildathon / game jam, dropping kick-offs, info sessions, workshops, "hacking" talks etc.

The API rate-limits bursts (403/429 after ~50 quick requests, for several minutes), so we
walk the places one request at a time, biggest cities first, within a time budget, and stop
early (keeping what we have) if Luma starts refusing. Online-only events are not tied to a
city and are mostly missed; so are hackathons Luma does not feature.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from ..models import RawHackathon
from .base import Source, SourceError, as_int, clean_text, get_json, request, to_utc

log = logging.getLogger(__name__)

API = "https://api.lu.ma"
BOOT_URL = f"{API}/discover/bootstrap-page"
FEED_URL = f"{API}/discover/get-paginated-events"
SITE = "https://luma.com"
PAGE_LIMIT = 50  # API maximum
MAX_PAGES_PER_PLACE = 4
REQUEST_GAP = 0.8  # seconds between request starts (~75/min; bursts of ~50 trip the limiter)
TIME_BUDGET = 80.0

_INCLUDE = re.compile(
    r"hack|(build|data|idea|design|make|prompt|agent|vibe)[- ]?a?[- ]?thon\b|game ?jam|code ?fest", re.I
)
_EXCLUDE = re.compile(
    r"\bhacking\b|\bhackers?\b|growth ?hack|life ?hacks?|hacktoberfest|hacker ?house|"
    r"\bkick-?off\b|\binfo(rmation)? ?session\b|\bworkshops?\b|\bwebinars?\b|\bmeet-?ups?\b|\bmixer\b|"
    r"\bnetworking\b|happy ?hour|demo ?day|watch ?party|office ?hours|\bpre-?hack(athon)?\b|"
    r"\bpost-?hack(athon)?\b|after ?party|\bpanel\b|fireside|\bbreakfast\b|\bdinner\b|\bbrunch\b|"
    r"launch ?party|\bshowcase\b|\bjudging\b|\bawards?\b|\brecap\b|\bcelebration\b",
    re.I,
)
_DEFAULT_IMAGE = re.compile(r"event-defaults|avatars-default", re.I)


def is_hackathon_title(title: str) -> bool:
    return bool(_INCLUDE.search(title)) and not _EXCLUDE.search(title)


def _status(exc: BaseException) -> int | None:
    cause = exc.__cause__
    return cause.response.status_code if isinstance(cause, httpx.HTTPStatusError) else None


class _Pacer:
    """Sequential requests whose start times are at least ``gap`` seconds apart."""

    def __init__(self, gap: float) -> None:
        self.gap = gap
        self.next_at = 0.0

    async def wait(self) -> None:
        now = time.monotonic()
        if now < self.next_at:
            await asyncio.sleep(self.next_at - now)
        self.next_at = max(now, self.next_at) + self.gap


def _image(url: Any) -> str | None:
    return url if isinstance(url, str) and url.startswith("http") and not _DEFAULT_IMAGE.search(url) else None


class Luma(Source):
    key = "luma"
    name = "Luma"
    homepage = "https://luma.com/discover"
    region = "global"
    focus = "City tech & AI hackathons (SF, NYC, London, Bengaluru...)"
    description = (
        "The event platform behind most AI and startup community events: one-day and weekend "
        "hackathons, buildathons and hack nights featured on Luma's city pages worldwide."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        started = time.monotonic()
        boot = await get_json(client, BOOT_URL)
        places = [p.get("place") or p for p in boot.get("places") or []]
        places = [p for p in places if p.get("api_id")]
        places.sort(key=lambda p: -(as_int(p.get("event_count")) or 0))
        if not places:
            raise SourceError("luma: discover bootstrap returned no places")

        entries: dict[str, dict[str, Any]] = {}
        pacer = _Pacer(REQUEST_GAP)
        blocked = False
        visited = pages_ok = 0
        for place in places:
            if blocked or time.monotonic() - started > TIME_BUDGET:
                break
            visited += 1
            cursor = None
            for _ in range(MAX_PAGES_PER_PLACE):
                await pacer.wait()
                params: dict[str, Any] = {"discover_place_api_id": place["api_id"], "pagination_limit": PAGE_LIMIT}
                if cursor:
                    params["pagination_cursor"] = cursor
                try:
                    resp = await request(client, "GET", FEED_URL, params=params, retries=2)
                    data = resp.json()
                except SourceError as exc:
                    if _status(exc) in (403, 429):
                        log.warning("luma: rate limited after %d places; keeping partial results", visited)
                        blocked = True
                    else:
                        log.warning("luma: feed failed for %s: %s", place.get("slug"), exc)
                    break
                pages_ok += 1
                for entry in data.get("entries") or []:
                    eid = (entry.get("event") or {}).get("api_id") or entry.get("api_id")
                    if eid:
                        entries.setdefault(eid, entry)
                cursor = data.get("next_cursor")
                if not data.get("has_more") or not cursor:
                    break
        if not pages_ok:
            # never return an empty list for a blocked run: callers would read it as "no events"
            raise SourceError("luma: no discover feed could be fetched (rate limited?)")
        if visited < len(places):
            log.warning("luma: visited %d of %d places", visited, len(places))

        now = datetime.now(timezone.utc)
        items: list[RawHackathon] = []
        for entry in entries.values():
            event = entry.get("event") or {}
            if not is_hackathon_title(clean_text(event.get("name")) or ""):
                continue
            try:
                item = self._build(entry)
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("luma: could not parse %s", event.get("url"))
                continue
            end = item.ends_at or item.starts_at
            if end and end < now:
                continue
            items.append(item)
        return items

    def _build(self, entry: dict[str, Any]) -> RawHackathon:
        ev = entry["event"]
        slug = ev.get("url")
        if not slug:
            raise ValueError("event without url slug")
        calendar = entry.get("calendar") or {}
        hosts = [clean_text(h.get("name")) for h in entry.get("hosts") or [] if clean_text(h.get("name"))]
        if calendar.get("name") and not calendar.get("is_personal"):
            organizer = clean_text(calendar.get("name"))
        else:
            organizer = ", ".join(hosts[:3]) or None

        loc_type = str(ev.get("location_type") or "").lower()
        if loc_type == "offline":
            mode = "in_person"
        elif loc_type in ("online", "zoom", "meet", "virtual"):
            mode = "online"
        else:
            mode = None

        geo = ev.get("geo_address_info") or {}
        city = clean_text(geo.get("city"))
        region = clean_text(geo.get("region"))
        country = (clean_text(geo.get("country_code")) or "").upper() or None
        if mode == "online":
            location, city, country = "Online", None, None
        else:
            if region and city and region.lower() == city.lower():
                region = None
            location = ", ".join(x for x in (city, region, clean_text(geo.get("country"))) if x) or None

        ticket = entry.get("ticket_info") or {}
        if ticket.get("is_free") is True:
            fee: bool | None = False
        elif ticket.get("is_free") is False or ticket.get("price"):
            fee = True
        else:
            fee = None
        guests = as_int(entry.get("guest_count"))
        title = clean_text(ev.get("name")) or "Untitled hackathon"

        return RawHackathon(
            source=self.key,
            source_id=str(ev.get("api_id") or entry.get("api_id")),
            title=title,
            url=f"{SITE}/{slug}",
            kind="ideathon" if re.search(r"ideathon", title, re.I) else "hackathon",
            organizer=organizer,
            image_url=_image(ev.get("cover_url")) or _image(ev.get("social_image_url")),
            logo_url=_image(calendar.get("avatar_url")),
            mode=mode,
            location=location,
            city=city,
            country=country,
            starts_at=to_utc(ev.get("start_at") or entry.get("start_at")),
            ends_at=to_utc(ev.get("end_at")),
            timezone=clean_text(ev.get("timezone")),
            participants=guests if ev.get("show_guest_list") and guests else None,
            registration_fee=fee,
            extra={
                "calendar_url": f"{SITE}/{calendar['slug']}" if calendar.get("slug") else None,
                "hosts": hosts,
                "featured_city": (entry.get("featured_city") or {}).get("name"),
                "registration": entry.get("registration_availability"),
                "requires_approval": ticket.get("require_approval"),
                "sold_out": ticket.get("is_sold_out"),
                "waitlist": entry.get("waitlist_active"),
                "address_visibility": ev.get("geo_address_visibility"),
            },
        )
