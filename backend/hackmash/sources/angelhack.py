"""AngelHack: global hackathon organiser (virtual, hybrid and in-person, often Web3 / AI).

AngelHack's site is WordPress + Elementor. The events page renders one loop item per event
with ``event-status-<upcoming|ongoing|past>`` and ``event-type-<...>`` classes, and the card
shows type, title, start / end date, format and region:

    https://angelhack.com/events/

Only dates are published (no times or timezone), so start is the start date at 00:00 UTC and
end the end date at 23:59:59 UTC (flagged ``date_only``). Hackathons are kept as
``hackathon``, "Learn & Earn" build quests as ``other``; conferences, incubators,
accelerators and grant programmes are skipped. Most of the time there are only a handful of
current events (sometimes none).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, time, timezone
from typing import Any

import httpx
import pycountry
from bs4 import BeautifulSoup, Tag

from ..models import RawHackathon
from .base import Source, SourceError, clean_text, get_text, mode_from

log = logging.getLogger(__name__)

EVENTS_URL = "https://angelhack.com/events/"
_STATUS_RE = re.compile(r"\bevent-status-([a-z-]+)")
_TYPE_RE = re.compile(r"\bevent-type-([a-z-]+)")
_DATE_RE = re.compile(r"^\d{1,2} [A-Za-z]{3,9} \d{4}$")
_HACK_TITLE = re.compile(r"hack|buildathon|build-?a-?thon|challenge|quest", re.I)
KEEP_TYPES = {"hackathon": "hackathon", "learn-earn": "other"}


def _date(text: str, end: bool) -> datetime | None:
    try:
        day = datetime.strptime(text.strip(), "%d %b %Y")
    except ValueError:
        try:
            day = datetime.strptime(text.strip(), "%d %B %Y")
        except ValueError:
            return None
    return datetime.combine(day.date(), time(23, 59, 59) if end else time(0, 0), tzinfo=timezone.utc)


def _img_src(img: Any) -> str | None:
    """Real image URL behind WP Rocket's lazy-load placeholder."""
    if not isinstance(img, Tag):
        return None
    for attr in ("data-lazy-src", "data-src", "src"):
        value = img.get(attr)
        if isinstance(value, str) and value.startswith("http"):
            return value
    srcset = img.get("data-lazy-srcset") or img.get("srcset") or ""
    first = str(srcset).split(",")[0].strip().split(" ")[0]
    return first if first.startswith("http") else None


def _country(region: str | None) -> str | None:
    if not region:
        return None
    try:
        return pycountry.countries.lookup(region).alpha_2
    except LookupError:
        return None  # "Global", "APAC", "Europe", "South-East Asia"


class AngelHack(Source):
    key = "angelhack"
    name = "AngelHack"
    homepage = "https://angelhack.com/events/"
    region = "global"
    focus = "Global corporate & Web3 hackathons"
    description = (
        "One of the longest-running hackathon organisers, running virtual, hybrid and in-person "
        "hackathons and developer quests for companies and blockchain ecosystems worldwide."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        soup = BeautifulSoup(await get_text(client, EVENTS_URL), "lxml")
        now = datetime.now(timezone.utc)
        items: list[RawHackathon] = []
        seen: set[str] = set()
        cards = soup.find_all(class_=_STATUS_RE)
        if not cards:  # the page always lists past events too, so this means the markup changed
            raise SourceError("angelhack: no event cards found on the events page")
        for loop_item in cards:
            classes = " ".join(loop_item.get("class") or [])
            status = (_STATUS_RE.search(classes) or [None, None])[1]
            etype = (_TYPE_RE.search(classes) or [None, None])[1]
            if status not in ("upcoming", "ongoing"):
                continue
            link = loop_item.find("a", href=re.compile(r"/event/"))
            if not isinstance(link, Tag) or link["href"] in seen:
                continue
            try:
                item = self._build(link, etype, status)
            except Exception:  # noqa: BLE001 - skip one bad card, keep the rest
                log.exception("angelhack: could not parse %s", link.get("href"))
                continue
            if item is None or (item.ends_at and item.ends_at < now):
                continue
            seen.add(link["href"])
            items.append(item)
        return items

    def _build(self, link: Tag, etype: str | None, status: str) -> RawHackathon | None:
        texts = [t for t in (clean_text(h.get_text(" ")) for h in link.select(".elementor-heading-title")) if t]
        title_el = link.find(["h2", "h3"])
        title = clean_text(title_el.get_text(" ")) if title_el else None
        if not title:
            return None
        kind = KEEP_TYPES.get(etype or "")
        if kind is None and etype == "partnered-programs-events" and _HACK_TITLE.search(title):
            kind = "hackathon"
        if kind is None:
            return None  # conference / incubator / accelerator / grants

        dates = [t for t in texts if _DATE_RE.match(t)]
        after_dates = texts[texts.index(dates[-1]) + 1:] if dates else []
        fmt = after_dates[0] if after_dates else None
        region = after_dates[1] if len(after_dates) > 1 else None
        mode = mode_from(fmt)
        country = _country(region) if mode != "online" else None
        img = link.find("img")
        slug = link["href"].rstrip("/").rsplit("/", 1)[-1]

        return RawHackathon(
            source=self.key,
            source_id=slug,
            title=title,
            url=link["href"],
            kind=kind,
            organizer="AngelHack",
            image_url=_img_src(img),
            mode=mode,
            location="Online" if mode == "online" else (region or None),
            country=country,
            starts_at=_date(dates[0], end=False) if dates else None,
            ends_at=_date(dates[-1], end=True) if len(dates) > 1 else None,
            extra={
                "status": status,
                "event_type": etype,
                "region": region,
                "format": fmt,
                "date_only": True,
            },
        )
