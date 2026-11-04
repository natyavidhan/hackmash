"""Hackathon.com: BeMyApp's public hackathon listing (corporate innovation challenges).

    https://www.hackathon.com/          upcoming events (cards linking to /event/<slug>-<id>)
    https://www.hackathon.com/event/... schema.org Event JSON-LD + theme chips + description
    https://www.bemyapp.com/events/     the same events with the organising country

The JSON-LD times are the organiser's local wall-clock time labelled as UTC: IBM Z Day,
"8AM - 4:30PM ET" on its own site, is published as 08:00Z-16:30Z, and the AI Builders
Challenge's "5:00 PM EST" deadline as 17:00Z. So we re-read them in the timezone of the
event's country, taken from BeMyApp's events page (US events are run on Eastern time,
as both events we could verify were) and flag that in ``extra``.

Virtual conferences cross-posted to the site (IBM Z Day) are skipped.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
import pycountry
from bs4 import BeautifulSoup

from ..models import RawHackathon
from .base import (
    Source,
    SourceError,
    abs_url,
    clean_text,
    gather_limited,
    get_text,
    html_to_text,
    parse_money,
    to_utc,
)
from .mlh import country_name, local_timezone

log = logging.getLogger(__name__)

BASE = "https://www.hackathon.com"
LIST_URLS = [f"{BASE}/", f"{BASE}/online"]
BEMYAPP_EVENTS = "https://www.bemyapp.com/events/"

_EVENT_LINK = re.compile(r'href="(/event/[^"#?]+)"')
_LD_RE = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
_META_THEMES = {"student", "high school", "university", "virtual", "hybrid", "beginner friendly", "online"}
_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "ten": 10}
_TEAM_RE = re.compile(r"teams? of (?:up to |between \w+ and |\d+\s*-\s*)?(\d+|one|two|three|four|five|six|seven|eight|ten)\b", re.I)
_MONEY_PHRASE = re.compile(r"(?:US\$|[$€£₹])\s?\d[\d,.]*\d\s*(?:[kKmM]\b)?[^,.;:!?\n]{0,70}")
_CONFERENCE_RE = re.compile(r"\b(conference|summit|webinar|meetup|expo)\b", re.I)
_BUILD_RE = re.compile(r"hackathon|challenge|competition|compete|prize|build|prototype|submission", re.I)
# BeMyApp runs its US programmes on Eastern time (verified on two events, see module doc).
_COUNTRY_TZ_OVERRIDE = {"US": "America/New_York", "CA": "America/Toronto"}


def _strip_tracking(url: str) -> str:
    parts = urlsplit(url)
    query = "&".join(q for q in parts.query.split("&") if q and not q.lower().startswith("utm_"))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))


def _ld_event(page: str) -> dict[str, Any]:
    for m in _LD_RE.finditer(page):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if isinstance(node, dict) and node.get("@type") == "Event":
                return node
    return {}


def _country_code(name: str | None) -> str | None:
    if not name:
        return None
    try:
        found = pycountry.countries.lookup(name.strip())
    except LookupError:
        return None
    return found.alpha_2


def _bemyapp_countries(page: str) -> dict[str, str]:
    """BeMyApp events page: lower-cased title -> ISO-2 country."""
    soup = BeautifulSoup(page, "lxml")
    out: dict[str, str] = {}
    for card in soup.select(".events-card"):
        title = card.select_one(".events-card__title")
        place = card.select_one(".events-card__header__overlay")
        if not title or not place:
            continue
        country = clean_text(place.get_text(" ")) or ""
        country = country.rsplit(" - ", 1)[-1]  # "Durham, NC - United States"
        code = _country_code(country)
        if code:
            out[(clean_text(title.get_text(" ")) or "").lower()] = code
    return out


def _wall_clock(value: Any, tz: str | None) -> datetime | None:
    """Re-read a fake-UTC JSON-LD timestamp as wall-clock time in ``tz``."""
    dt = to_utc(value)
    if dt is None or not tz:
        return dt
    return to_utc(dt.replace(tzinfo=None), tz)


class HackathonCom(Source):
    key = "hackathoncom"
    name = "Hackathon.com"
    homepage = "https://www.hackathon.com/"
    region = "global"
    focus = "Corporate innovation challenges run by BeMyApp"
    description = (
        "BeMyApp's hackathon directory: online and hybrid innovation challenges for students and "
        "developers sponsored by companies such as IBM, Huawei and Xylem."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        links: list[str] = []
        for list_url in LIST_URLS:
            try:
                page = await get_text(client, list_url)
            except SourceError as exc:
                if list_url == LIST_URLS[0]:
                    raise
                log.warning("hackathoncom: %s unavailable: %s", list_url, exc)
                continue
            for path in _EVENT_LINK.findall(page):
                url = abs_url(BASE, path)
                if url and url not in links:
                    links.append(url)
        try:
            countries = _bemyapp_countries(await get_text(client, BEMYAPP_EVENTS, retries=2))
        except SourceError as exc:
            log.warning("hackathoncom: BeMyApp events page unavailable (%s); times stay as published", exc)
            countries = {}

        pages = await gather_limited((get_text(client, url, retries=2) for url in links), limit=4)
        now = datetime.now(timezone.utc)
        items: list[RawHackathon] = []
        for url, page in zip(links, pages, strict=True):
            if not isinstance(page, str):
                log.warning("hackathoncom: event page failed %s: %s", url, page)
                continue
            try:
                item = self._build(url, page, countries)
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("hackathoncom: could not parse %s", url)
                continue
            if item is None or (item.ends_at and item.ends_at < now):
                continue
            items.append(item)
        return items

    def _build(self, url: str, page: str, countries: dict[str, str]) -> RawHackathon | None:
        ld = _ld_event(page)
        if not ld:
            raise ValueError("no Event JSON-LD")
        title = clean_text(ld.get("name")) or ""
        soup = BeautifulSoup(page, "lxml")
        desc_el = soup.select_one(".event__content__desc")
        full_text = html_to_text(str(desc_el), max_len=20000) if desc_el else None
        full_text = re.sub(r"\s+([,.;:!?])", r"\1", full_text) if full_text else None  # "America , a"
        description = full_text
        if description and len(description) > 1500:
            description = description[:1500].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"
        tagline_el = soup.select_one(".event__baseline__title")
        tagline = clean_text(tagline_el.get_text(" ")) if tagline_el else None

        if _CONFERENCE_RE.search(full_text or "") and not _BUILD_RE.search(full_text or ""):
            return None  # a conference cross-posted as an event

        chips = soup.select("a.ht-event-topics__tag") or soup.select('a[href^="/theme/"]')
        themes = list(dict.fromkeys(t for t in (clean_text(a.get_text(" ")) for a in chips) if t))
        lowered = {t.lower() for t in themes}

        attendance = str(ld.get("eventAttendanceMode") or "")
        if "hybrid" in lowered or "Mixed" in attendance:
            mode = "hybrid"
        elif "Offline" in attendance:
            mode = "in_person"
        else:
            mode = "online"

        address = ((ld.get("location") or {}).get("address") or {}) if isinstance(ld.get("location"), dict) else {}
        city = clean_text(address.get("addressLocality")) if isinstance(address, dict) else None
        country = _country_code(address.get("addressCountry")) if isinstance(address, dict) else None
        country = country or countries.get(title.lower())
        tz = _COUNTRY_TZ_OVERRIDE.get(country or "") or local_timezone(country, None, city)

        website = None
        for a in soup.find_all("a", href=True):
            if "see event website" in (a.get_text(" ") or "").lower():
                website = _strip_tracking(a["href"])
                break

        prize_amount = prize_currency = prize_text = None
        for m in _MONEY_PHRASE.finditer(full_text or ""):
            phrase = m.group(0)
            if "prize" not in phrase.lower() and "prize" not in (full_text or "")[max(0, m.start() - 40):m.start()].lower():
                continue
            amount, currency = parse_money(phrase)
            if amount and (prize_amount is None or amount > prize_amount):
                cut = phrase if len(phrase) <= 70 else phrase[:70].rsplit(" ", 1)[0]
                prize_amount, prize_currency, prize_text = amount, currency, cut.strip(" ,.;:")
        team = _TEAM_RE.search(full_text or "")
        team_max = None
        if team:
            raw = team.group(1).lower()
            team_max = int(raw) if raw.isdigit() else _NUMBERS.get(raw)

        eligibility = []
        if "student" in lowered:
            eligibility.append("Students")
        if "high school" in lowered:
            eligibility.append("High school students")
        if "university" in lowered:
            eligibility.append("University students")
        for m in re.finditer(r"(?:open to [^.\n]{5,120}|ages? \d{1,2}\s*[-–]\s*\d{1,2})", full_text or "", re.I):
            phrase = (clean_text(m.group(0)) or "").rstrip(" .,;:")
            eligibility.append(phrase[:1].upper() + phrase[1:])
        eligibility = [e for e in dict.fromkeys(eligibility) if e]

        organizer = clean_text(((ld.get("organizer") or {}) if isinstance(ld.get("organizer"), dict) else {}).get("name"))

        return RawHackathon(
            source=self.key,
            source_id=url.rstrip("/").rsplit("-", 1)[-1],
            title=title or "Untitled hackathon",
            url=website or url,
            kind="hackathon",
            organizer=organizer,
            tagline=tagline,
            description=description,
            image_url=ld.get("image") if isinstance(ld.get("image"), str) else None,
            mode=mode,
            location="Online" if mode == "online" else (", ".join(x for x in (city, country_name(country)) if x) or None),
            city=city if mode != "online" else None,
            country=country if mode != "online" else None,
            starts_at=_wall_clock(ld.get("startDate"), tz),
            ends_at=_wall_clock(ld.get("endDate"), tz),
            submission_deadline=_wall_clock(ld.get("endDate"), tz),
            timezone=tz,
            prize_text=prize_text,
            prize_amount=prize_amount,
            prize_currency=prize_currency if prize_amount else None,
            tags=[t for t in themes if t.lower() not in _META_THEMES],
            team_size_min=1 if team_max else None,
            team_size_max=team_max,
            eligibility=eligibility,
            beginner_friendly=True if "beginner friendly" in lowered else None,
            extra={
                "listing_url": url,
                "organizer_country": country,
                "time_basis": f"published wall-clock read as {tz}" if tz else "published as UTC",
            },
        )
