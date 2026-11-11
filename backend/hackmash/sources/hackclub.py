"""Hack Club Hackathons: the directory of high-school-led hackathons worldwide.

Public JSON API (documented at https://hackathons.hackclub.com/api; using it requires
crediting "Hack Club Hackathons" with a link to hackathons.hackclub.com):

    https://hackathons.hackclub.com/api/events/upcoming/   every event with end > now

The site lists every event with a link to its own website (there are no per-event pages on
hackathons.hackclub.com). Organisers are asked to enter start/end "in UTC time" on the
submission form, so we take the values as UTC; a few organisers type local wall-clock times
instead, so treat the time of day as approximate (the date is reliable).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from ..models import RawHackathon
from .base import Source, as_float, clean_text, get_json, to_utc
from .mlh import local_timezone

log = logging.getLogger(__name__)

API_URL = "https://hackathons.hackclub.com/api/events/upcoming/"


def _website(url: str | None) -> str | None:
    url = (url or "").strip()
    if not url:
        return None
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url.lstrip("/")
    return url


class HackClub(Source):
    key = "hackclub"
    name = "Hack Club"
    homepage = "https://hackathons.hackclub.com/"
    region = "global"
    focus = "High-school hackathons worldwide"
    description = (
        "Hack Club's directory of hackathons run by and for high schoolers around the world, "
        "in person and online. Data from Hack Club Hackathons (hackathons.hackclub.com)."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        rows = await get_json(client, API_URL)
        if not isinstance(rows, list):
            rows = (rows or {}).get("data") or []
        now = datetime.now(timezone.utc)
        items: list[RawHackathon] = []
        seen: set[str] = set()
        for row in rows:
            rid = str(row.get("id") or "")
            if not rid or rid in seen:
                continue
            try:
                item = self._build(row)
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("hackclub: could not parse %s", row.get("name"))
                continue
            end = item.ends_at or item.starts_at
            if end and end < now:
                continue
            seen.add(rid)
            items.append(item)
        return items

    def _build(self, row: dict[str, Any]) -> RawHackathon:
        url = _website(row.get("website"))
        if not url:
            raise ValueError("event without a website")
        if row.get("virtual"):
            mode = "online"
        elif row.get("hybrid"):
            mode = "hybrid"
        else:
            mode = "in_person"

        city = clean_text(row.get("city"))
        state = clean_text(row.get("state"))
        country_full = clean_text(row.get("country"))
        code = (clean_text(row.get("countryCode")) or "").upper() or None
        if mode == "online":
            location = "Online"
            city = state = country_full = code = None
        else:
            location = ", ".join(x for x in (city, state, country_full or code) if x) or None
        tz = local_timezone(code or country_full, state, city) if mode != "online" else None

        starts_at = to_utc(row.get("start"))
        ends_at = to_utc(row.get("end"))
        if starts_at and ends_at and ends_at < starts_at:
            ends_at = None

        return RawHackathon(
            source=self.key,
            source_id=str(row["id"]),
            title=clean_text(row.get("name")) or "Untitled hackathon",
            url=url,
            kind="hackathon",
            organizer="Hack Club" if row.get("hack_club_event") else None,
            image_url=row.get("banner") or None,
            logo_url=row.get("logo") or None,
            mode=mode,
            location=location,
            city=city,
            country=code or country_full,
            lat=as_float(row.get("latitude")),
            lng=as_float(row.get("longitude")),
            starts_at=starts_at,
            ends_at=ends_at,
            timezone=tz,
            eligibility=["High school students"],
            extra={
                "latitude": row.get("latitude"),
                "longitude": row.get("longitude"),
                "apac": row.get("apac"),
                "hack_club_event": bool(row.get("hack_club_event")),
                "listed_at": row.get("createdAt"),
                "directory_url": "https://hackathons.hackclub.com/",
            },
        )
