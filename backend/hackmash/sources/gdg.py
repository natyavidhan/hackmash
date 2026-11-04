"""Google Developer Groups (gdg.community.dev): hackathons run by GDG chapters worldwide.

The platform (Bevy) has a JSON API, but gdg.community.dev's robots.txt disallows ``/api/``
for every crawler and asks for ``Crawl-delay: 2``. So we only use public pages:

    https://gdg.community.dev/sitemap-events-YYYY-MM.xml   event URLs, one sitemap per start month
    https://gdg.community.dev/events/details/<slug>/       __NEXT_DATA__ eventData + JSON-LD Event

Event slugs embed the title ("google-gdg-athlone-presents-hackathlone-2026-..."), so we pick
hackathon-like slugs from the current and next few months, fetch those pages one at a time
2 s apart (soonest first, within a time budget) and re-check the real title. Info sessions,
workshops "at" a hackathon, calls for speakers and security "hacking" talks are dropped.
Events that started in an earlier month and are still running are not seen.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from ..models import RawHackathon
from .base import Source, SourceError, as_int, clean_text, get_text, html_to_text, to_utc
from .mlh import country_name, tz_country

log = logging.getLogger(__name__)

BASE = "https://gdg.community.dev"
SITEMAP_URL = BASE + "/sitemap-events-{ym}.xml"
MONTHS_AHEAD = 5  # current month + 5
CRAWL_DELAY = 2.0  # robots.txt
TIME_BUDGET = 95.0  # seconds for the whole source; remaining pages are skipped (logged)

_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>")
_NEXT_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
_LD_RE = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)

_HACK_RE = re.compile(
    r"hack|buildathon|build[- ]?a[- ]?thon|datathon|ideathon|designathon|makeathon|game[- ]?jam|"
    r"codefest|space[- ]?apps",
    re.I,
)
_NOT_HACK_WORDS = (
    r"workshops?|info[- ]?sessions?|information[- ]session|webinars?|meetups?|talks?|kick[- ]?off|"
    r"briefing|prep|preparation|orientation|call[- ]for[- ][a-z]+|cfp|pre[- ]?event|pre[- ]?hackathon|"
    r"post[- ]?hackathon|watch[- ]party|study[- ]jams?|hacking|hackers?|hackear|hacktoberfest|taller|"
    r"conference|bootcamp|mixer|networking|panel|fireside|demo[- ]day|showcase|recap|info|awards?|"
    r"ceremony|closing|opening|social|party|ama"
)
_NOT_HACK_SLUG = re.compile(rf"(^|-)({_NOT_HACK_WORDS})(-|$)", re.I)
_NOT_HACK_TITLE = re.compile(rf"(^|[^a-z])({_NOT_HACK_WORDS})([^a-z]|$)", re.I)
_DEFAULT_IMAGE = re.compile(r"DefaultEventBanner|SocialSharingThumbnail|event-defaults", re.I)


def is_hackathon_title(title: str) -> bool:
    return bool(_HACK_RE.search(title)) and not _NOT_HACK_TITLE.search(title)


def _slug_title(url: str) -> str:
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return slug.split("-presents-", 1)[-1]


def _months(now: datetime, ahead: int) -> list[str]:
    out = []
    y, m = now.year, now.month
    for _ in range(ahead + 1):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _ld_event(html: str) -> dict[str, Any]:
    for m in _LD_RE.finditer(html):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if isinstance(node, dict) and node.get("@type") == "Event":
                return node
    return {}


def _image(url: Any) -> str | None:
    return url if isinstance(url, str) and url.startswith("http") and not _DEFAULT_IMAGE.search(url) else None


class _Pacer:
    """Sequential requests, at least ``delay`` seconds apart."""

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.next_at = 0.0

    async def wait(self) -> None:
        now = time.monotonic()
        if now < self.next_at:
            await asyncio.sleep(self.next_at - now)
        self.next_at = max(now, self.next_at) + self.delay


class GDG(Source):
    key = "gdg"
    name = "Google Developer Groups"
    homepage = "https://gdg.community.dev/events/"
    region = "global"
    focus = "Hackathons by Google Developer Groups chapters"
    description = (
        "Hackathons, buildathons and game jams organised by the 1,000+ local and campus Google "
        "Developer Groups chapters around the world, usually free and community-run."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        started = time.monotonic()
        pacer = _Pacer(CRAWL_DELAY)
        now = datetime.now(timezone.utc)

        candidates: list[str] = []
        for ym in _months(now, MONTHS_AHEAD):
            await pacer.wait()
            try:
                xml = await get_text(client, SITEMAP_URL.format(ym=ym), retries=2)
            except SourceError as exc:
                log.warning("gdg: sitemap %s unavailable: %s", ym, exc)
                continue
            for url in _LOC_RE.findall(xml):
                part = _slug_title(url)
                if "/events/details/" in url and _HACK_RE.search(part) and not _NOT_HACK_SLUG.search(part):
                    if url not in candidates:
                        candidates.append(url)
        if not candidates:
            raise SourceError("gdg: no hackathon candidates in the event sitemaps")

        items: list[RawHackathon] = []
        seen: set[str] = set()
        pages_ok = 0
        for n, url in enumerate(candidates):
            if time.monotonic() - started > TIME_BUDGET:
                log.warning("gdg: time budget reached, skipped %d of %d pages", len(candidates) - n, len(candidates))
                break
            await pacer.wait()
            try:
                html = await get_text(client, url, retries=2)
            except SourceError as exc:
                log.warning("gdg: event page failed %s: %s", url, exc)
                continue
            pages_ok += 1
            try:
                item = self._parse(url, html)
            except Exception:  # noqa: BLE001 - skip one bad page, keep the rest
                log.exception("gdg: could not parse %s", url)
                continue
            if item is None or item.source_id in seen:
                continue
            end = item.ends_at or item.starts_at
            if end and end < now:
                continue
            seen.add(item.source_id)
            items.append(item)
        if not pages_ok:
            raise SourceError("gdg: none of the event pages could be fetched")
        return items

    def _parse(self, url: str, html: str) -> RawHackathon | None:
        m = _NEXT_RE.search(html)
        if not m:
            raise ValueError("no __NEXT_DATA__")
        props = (json.loads(m.group(1)).get("props") or {}).get("pageProps") or {}
        ev = props.get("eventData") or (props.get("customBlockData") or {}).get("eventData") or {}
        if not ev or ev.get("is_hidden"):
            return None
        title = clean_text(ev.get("title")) or ""
        if not is_hackathon_title(title):
            return None
        return self._build(url, ev, _ld_event(html))

    def _build(self, url: str, ev: dict[str, Any], ld: dict[str, Any]) -> RawHackathon:
        audience = str(ev.get("audience_type") or "").upper()
        mode = {"IN_PERSON": "in_person", "VIRTUAL": "online", "HYBRID": "hybrid"}.get(audience)

        address = ((ld.get("location") or {}).get("address") or {}) if isinstance(ld.get("location"), dict) else {}
        city = clean_text(ev.get("venue_city")) or clean_text(address.get("addressLocality"))
        state = clean_text(ev.get("venue_state")) or clean_text(address.get("addressRegion"))
        # JSON-LD addressCountry defaults to "US" when the venue country is unset ("Münster, NRW,
        # US"). A non-US value was set on purpose; a "US" that contradicts the event's timezone
        # (Europe/Berlin) is that default, so the timezone's country wins then.
        venue_cc = (clean_text(ev.get("venue_country")) or "").upper() or None
        ld_cc = (clean_text(address.get("addressCountry")) or "").upper() or None
        tz_cc = tz_country(ev.get("event_timezone"))
        if venue_cc:
            country = venue_cc
        elif ld_cc and not (ld_cc == "US" and tz_cc and tz_cc != "US"):
            country = ld_cc
        else:
            country = tz_cc or ld_cc
        if mode == "online":
            location = "Online"
            city = state = country = None
        else:
            if city and re.fullmatch(r"(tbd|tba|n/?a|online|virtual)", city, re.I):
                city = None
            if city and city.isupper() and len(city) > 3:
                city = city.title()  # "MAIMI"
            if state and city and state.lower() == city.lower():
                state = None  # "Plovdiv, Plovdiv"
            location = ", ".join(x for x in (city, state, country_name(country)) if x) or None

        offers = ld.get("offers") if isinstance(ld.get("offers"), dict) else {}
        price = offers.get("price")
        reg_type = str(ev.get("event_type_title") or "")
        external = "external" in reg_type.lower() or bool(ev.get("use_external_ticketing"))
        if "paid" in reg_type.lower() or (isinstance(price, (int, float)) and price > 0):
            fee: bool | None = True
        elif "free" in reg_type.lower():
            fee = False
        else:
            fee = None

        starts_at = to_utc(ev.get("start_date") or ld.get("startDate"))
        ends_at = to_utc(ev.get("end_date") or ld.get("endDate"))
        reg_deadline = None if external else to_utc(offers.get("validThrough"))
        if reg_deadline and ends_at and reg_deadline > ends_at:
            reg_deadline = ends_at

        title = clean_text(ev.get("title")) or "Untitled hackathon"
        tagline = clean_text(ev.get("description_short"))
        if tagline and (len(tagline) > 300 or tagline.lower() == title.lower()):
            tagline = None
        attendees = as_int(ev.get("total_attendees"))

        return RawHackathon(
            source=self.key,
            source_id=str(ev.get("id") or url),
            title=title,
            url=ev.get("url") or url,
            kind="ideathon" if re.search(r"ideathon", title, re.I) else "hackathon",
            organizer=clean_text(ev.get("chapter_title")),
            tagline=tagline,
            description=html_to_text(ev.get("description")),
            image_url=_image(ev.get("cropped_banner_url")) or _image(ev.get("event_banner")),
            logo_url=_image(ev.get("cropped_picture_url")) or _image(ev.get("picture")),
            mode=mode,
            location=location,
            city=city,
            country=country,
            starts_at=starts_at,
            ends_at=ends_at,
            registration_deadline=reg_deadline,
            timezone=clean_text(ev.get("event_timezone")),
            tags=[t for t in (clean_text(x) for x in ev.get("tags") or []) if t],
            participants=None if external else attendees,
            registration_fee=fee,
            extra={
                "chapter_url": ev.get("chapter_url"),
                "short_url": ev.get("static_url"),
                "venue": clean_text(ev.get("venue_name")),
                "address": clean_text(ev.get("venue_address")),
                "registration": reg_type or None,
                "capacity": as_int(ev.get("total_capacity")),
            },
        )
