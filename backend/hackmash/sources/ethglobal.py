"""ETHGlobal: in-person and async (online) Ethereum hackathons.

ethglobal.com is a Next.js App Router site with no public API. The data lives in
the React Server Components "flight" payload pushed via ``self.__next_f.push``:

* ``/events`` embeds every event (hackathons, summits, meetups, cafes) with
  slug, type, medium, status, start/end, signup deadline and city.
* ``/events/<slug>`` embeds the full event (IANA timezone, exact signup and
  submission deadlines, venue), its schedule, sponsors with prize amounts and
  the FAQ. Future event pages currently answer HTTP 500 while still streaming
  the complete payload, so we accept 5xx responses that carry it.

``startTime``/``endTime`` of upcoming events are often bare dates stored as
midnight UTC; we then take exact times from the schedule (doors open / closing)
or fall back to local midnight / end of day in the event's timezone.

The prize pool mirrors what the event page renders:
``25000 * round((20000 + sum(sponsor prizes)) / 25000)`` USD.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import re
from datetime import datetime, time, timedelta, timezone
from typing import Any

import httpx
from dateutil import tz as date_tz

from ..models import RawHackathon
from .base import Source, clean_text, gather_limited, get_text, html_to_text, to_utc

log = logging.getLogger(__name__)

SITE = "https://ethglobal.com"
EVENTS_URL = f"{SITE}/events"
CDN = "https://ethglobal.b-cdn.net/events"

# "Themes and Topics" block rendered on every ETHGlobal hackathon page
THEMES = [
    "Zero Knowledge Proofs",
    "AI x Crypto",
    "DeFi",
    "Crypto Consumer",
    "Layer 2s",
    "Interoperability",
    "Public Goods",
    "Privacy & Security",
    "TEEs",
    "Data Availability",
    "Identity",
    "DevTools",
]

_PUSH_RE = re.compile(r"self\.__next_f\.push\((\[.*?\])\)</script>", re.S)
_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}  # fmt: skip
_TEAM_RE = re.compile(
    r"(?:maximum of|up to|at most)\s+(?:a\s+maximum\s+of\s+)?\**\s*(\d+|[a-z]+)\s*\**\s+"
    r"(?:team\s+)?(?:members|people|hackers|persons)",
    re.I,
)


# ---------------------------------------------------------------------------
# RSC flight payload
# ---------------------------------------------------------------------------


def flight_rows(html: str) -> dict[str, Any]:
    """Decode the Next.js flight payload into ``{row_id: json_value | text}``."""
    parts: list[str] = []
    for m in _PUSH_RE.finditer(html):
        try:
            arr = json.loads(m.group(1))
        except ValueError:
            continue
        if len(arr) > 1 and arr[0] == 1 and isinstance(arr[1], str):
            parts.append(arr[1])
    data = "".join(parts).encode("utf-8")
    rows: dict[str, Any] = {}
    pos, n = 0, len(data)
    while pos < n:
        colon = data.find(b":", pos)
        if colon < 0:
            break
        rid = data[pos:colon].decode("ascii", "replace").strip()
        pos = colon + 1
        if data[pos : pos + 1] == b"T":  # text row: T<hex length>,<bytes>
            comma = data.find(b",", pos)
            try:
                length = int(data[pos + 1 : comma], 16)
            except ValueError:
                break
            rows[rid] = data[comma + 1 : comma + 1 + length].decode("utf-8", "replace")
            pos = comma + 1 + length
            continue
        end = data.find(b"\n", pos)
        end = n if end < 0 else end
        body = data[pos:end].decode("utf-8", "replace")
        pos = end + 1
        if body[:1] in ("[", "{"):
            try:
                rows[rid] = json.loads(body)
            except ValueError:
                pass
    return rows


def _walk(value: Any):
    stack = [value]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            yield node
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _is_bare_date(value: Any) -> bool:
    return isinstance(value, str) and value.endswith("T00:00:00.000Z")


def _local_date(value: Any, zone) -> Any:
    dt = to_utc(value)
    if dt is None:
        return None
    return dt.date() if _is_bare_date(value) else dt.astimezone(zone).date()


def _round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


def _prize_pool(event: dict[str, Any], sponsors: list[dict[str, Any]]) -> int | None:
    """Same total the event page shows ("$X Available in prizes")."""
    legacy = str(event.get("startTime") or "")[:10] < "2023-11-01"
    seen: set[Any] = set()
    total = 0.0
    for s in sponsors:
        key = s.get("uuid") or s.get("slug") or s.get("id")
        if key in seen:
            continue
        seen.add(key)
        amount = s.get("prizeAmount") or 0
        if not legacy and (s.get("totalPrizeAmount") or 0) > 0:
            amount = s["totalPrizeAmount"]
        total += float(amount or 0)
    if total <= 0:
        return None
    return 25000 * _round_half_up((20000 + total) / 25000)


def _faq(faqs: list[dict[str, Any]], question: str) -> str | None:
    for f in faqs:
        if re.search(question, str(f.get("name") or ""), re.I):
            return clean_text(f.get("answer"))
    return None


class ETHGlobal(Source):
    key = "ethglobal"
    name = "ETHGlobal"
    homepage = "https://ethglobal.com/events"
    region = "global"
    focus = "Ethereum hackathons, in person and online"
    description = (
        "The largest series of Ethereum hackathons: weekend in-person events in cities around "
        "the world and multi-week async online hackathons, with big sponsor prize pools."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        rows = flight_rows(await get_text(client, EVENTS_URL))
        events: dict[Any, dict[str, Any]] = {}
        for node in _walk(rows):
            if "slug" in node and "startTime" in node and "medium" in node and "type" in node:
                events.setdefault(node.get("id") or node["slug"], node)

        now = datetime.now(timezone.utc)
        current = []
        for ev in events.values():
            if ev.get("type") != "hackathon" or ev.get("status") in ("finished", "cancelled"):
                continue
            end = to_utc(ev.get("endTime")) or to_utc(ev.get("startTime"))
            if end is None or end + timedelta(days=1) < now:
                continue
            current.append(ev)

        pages = await gather_limited((self._event_page(client, ev["slug"]) for ev in current), limit=4)
        items: list[RawHackathon] = []
        for ev, page in zip(current, pages, strict=True):
            props = page if isinstance(page, dict) else None
            try:
                item = self._build(ev, props)
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("ethglobal: could not parse event %s", ev.get("slug"))
                continue
            end = item.ends_at or item.submission_deadline
            if end is None or end >= now - timedelta(hours=1):
                items.append(item)
        return items

    async def _event_page(self, client: httpx.AsyncClient, slug: str) -> dict[str, Any] | None:
        url = f"{SITE}/events/{slug}"
        for attempt in range(3):
            try:
                resp = await client.get(url)
            except httpx.TransportError as exc:
                log.warning("ethglobal: %s failed: %s", url, exc)
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            text = resp.text
            # upcoming event pages currently render with HTTP 500 but stream the full payload
            if resp.status_code == 200 or (resp.status_code >= 500 and "self.__next_f" in text):
                for node in _walk(flight_rows(text)):
                    if isinstance(node.get("event"), dict) and "sponsors" in node:
                        if node["event"].get("slug") in (slug, None):
                            return node
                return None
            if resp.status_code != 429 and resp.status_code < 500:
                return None
            await asyncio.sleep(1.5 * (attempt + 1))
        return None

    def _build(self, ev: dict[str, Any], props: dict[str, Any] | None) -> RawHackathon:
        detail = (props or {}).get("event") or {}
        e = {**ev, **{k: v for k, v in detail.items() if v is not None}}
        slug = e["slug"]

        tz_name = (e.get("timezone") or {}).get("name") if isinstance(e.get("timezone"), dict) else None
        zone = date_tz.gettz(tz_name) if tz_name else None

        start = to_utc(e.get("startTime"))
        end = to_utc(e.get("endTime"))
        hacking_starts = None
        if zone and (_is_bare_date(e.get("startTime")) or _is_bare_date(e.get("endTime"))):
            start_day = _local_date(e.get("startTime"), zone)
            end_day = _local_date(e.get("endTime"), zone) or start_day
            in_event: list[tuple[datetime, datetime]] = []
            schedule_items = [
                item
                for group in (props or {}).get("schedule") or []
                if isinstance(group, dict)
                for day in group.get("dates") or []
                if isinstance(day, dict)
                for item in day.get("items") or []
                if isinstance(item, dict)
            ]
            for item in schedule_items:
                at = to_utc(item.get("startTime"))
                if at is None or not (start_day <= at.astimezone(zone).date() <= end_day):
                    continue
                length = item.get("length") or 0
                finish = at + timedelta(minutes=length if length > 1 else 0)
                in_event.append((at, finish))
                if (
                    item.get("slug") == "hacking-begins"
                    or "hacking begins" in str(item.get("name") or "").lower()
                ):
                    hacking_starts = at
            if _is_bare_date(e.get("startTime")) and start_day:
                start = min((a for a, _ in in_event), default=None) or datetime.combine(
                    start_day, time.min, zone
                ).astimezone(timezone.utc)
            if _is_bare_date(e.get("endTime")) and end_day:
                end = max((f for _, f in in_event), default=None) or datetime.combine(
                    end_day, time(23, 59), zone
                ).astimezone(timezone.utc)
        if start and end and end < start:
            end = None

        medium = str(e.get("medium") or "").lower()
        mode = {"physical": "in_person", "virtual": "online", "hybrid": "hybrid"}.get(medium)
        city_info = e.get("city") if isinstance(e.get("city"), dict) else {}
        city = clean_text(city_info.get("name"))
        country = clean_text((city_info.get("country") or {}).get("name")) or clean_text(
            city_info.get("countryCode")
        )
        venue = e.get("venueLocation") if isinstance(e.get("venueLocation"), dict) else {}
        if mode == "online":
            location = "Online"
        else:
            vname, vaddr = clean_text(venue.get("name")), clean_text(venue.get("address"))
            if vname and vaddr and vname.lower() in vaddr.lower():
                vname = None
            location = (
                ", ".join(x for x in (vname, vaddr) if x)
                or ", ".join(x for x in (city, country) if x)
                or None
            )

        sponsors = [s for s in (props or {}).get("sponsors") or [] if isinstance(s, dict)]
        pool = _prize_pool(e, sponsors)

        faqs = [f for f in (props or {}).get("faqs") or [] if isinstance(f, dict)]
        team_max = None
        team_answer = _faq(faqs, r"members.*team|team.*members|team size")
        if team_answer and (m := _TEAM_RE.search(team_answer)):
            word = m.group(1).lower()
            team_max = int(word) if word.isdigit() else _NUMBER_WORDS.get(word)
        solo = _faq(faqs, r"hack solo|participate alone|on my own")
        cost = _faq(faqs, r"\bcost\b|how much|\bprice\b|\bfees?\b")
        travel = _faq(faqs, r"travel")
        newbie = _faq(faqs, r"new to|beginner")
        about = _faq(faqs, rf"^what is {re.escape(str(e.get('name') or ''))}")

        style_meta = ((e.get("style") or {}).get("global") or {}).get("meta") or {}
        og_image = style_meta.get("ogImage") if isinstance(style_meta, dict) else None

        return RawHackathon(
            source=self.key,
            source_id=str(e.get("id") or slug),
            title=clean_text(e.get("name")) or slug,
            url=f"{SITE}/events/{slug}",
            organizer="ETHGlobal",
            tagline=clean_text(e.get("tagline")),
            description=html_to_text(e.get("description")) or about,
            image_url=og_image or f"{CDN}/{slug}/banner/default.png",
            logo_url=f"{CDN}/{slug}/square-logo/default.png",
            mode=mode,
            location=location,
            city=city if mode != "online" else None,
            country=country if mode != "online" else None,
            starts_at=start,
            ends_at=end,
            registration_deadline=to_utc(e.get("signupDeadline")),
            submission_deadline=to_utc(e.get("submissionDeadline")),
            timezone=tz_name,
            prize_text=f"${pool:,} in prizes" if pool else None,
            prize_amount=float(pool) if pool else None,
            prize_currency="USD" if pool else None,
            tags=["Ethereum", *THEMES],
            team_size_min=1 if solo and re.match(r"\W*yes", solo, re.I) else None,
            team_size_max=team_max,
            registration_fee=False if cost and re.search(r"\bfree\b", cost, re.I) else None,
            travel_reimbursement=(
                False if travel and re.search(r"(does not|doesn't|do not|not) cover", travel, re.I) else None
            ),
            beginner_friendly=(
                True
                if newbie and re.search(r"absolutely|\byes\b|open to both beginners", newbie, re.I)
                else None
            ),
            extra={
                "apply_url": f"{SITE}/events/{slug}/apply",
                "status": e.get("status"),
                "venue": clean_text(venue.get("name")),
                "venue_map_url": venue.get("url"),
                "hacking_starts_at": hacking_starts.isoformat() if hacking_starts else None,
                "judging_starts_at": e.get("judgingStartTime"),
                "sponsors": [clean_text(s.get("name")) for s in sponsors if s.get("name")],
                "staking_required": not bool((e.get("flags") or {}).get("disableStaking", False)),
            },
        )
