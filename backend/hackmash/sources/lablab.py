"""lablab.ai: AI hackathons (online, hybrid and on-site), run with AI companies.

``lablab.ai/event`` 308-redirects to ``/ai-hackathons``, a Next.js App Router
page whose React Server Components payload carries every event
(``sortedEvents``) with exact UTC start/end, IANA timezone, event type
(ONLINE / HYBRID / ONSITE), team limits and participant counts.

Each event page ``/ai-hackathons/<slug>`` adds the venues (city, country). Prize
pools are not structured (``eventPrizes`` is empty) and only appear in the
page's custom HTML ("Prize Pool $17,000+", "$10,000+ in prizes"), so we pull
the first such phrase from the rendered text.
"""

from __future__ import annotations

import html as html_lib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..models import RawHackathon
from .base import Source, as_int, clean_text, gather_limited, get_text, parse_money, to_utc

log = logging.getLogger(__name__)

SITE = "https://lablab.ai"
LIST_URL = f"{SITE}/ai-hackathons"

_PUSH_RE = re.compile(r"self\.__next_f\.push\((\[.*?\])\)</script>", re.S)
_MONEY = r"(?:US)?[$€£]\s?\d[\d,.]*\s*[kKmM]?\+?"
_PRIZE_RES = [
    re.compile(rf"prize\s+pool\s*[:\-–]?\s*((?:up\s+to\s+)?{_MONEY})", re.I),
    re.compile(
        rf"((?:up\s+to\s+)?{_MONEY})\s+(?:in\s+)?(?:total\s+)?(?:cash\s+)?(?:prizes|prize\s+pool)\b", re.I
    ),
]
_TRAVEL_NO_RE = re.compile(
    r"travel[^.]{0,60}\bnot\s+(?:be\s+)?(?:covered|reimbursed|provided)|not\s+cover[^.]{0,30}travel", re.I
)
_MODES = {"ONLINE": "online", "HYBRID": "hybrid", "ONSITE": "in_person", "OFFLINE": "in_person"}


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


def _is_event(node: dict[str, Any]) -> bool:
    return "startAt" in node and "endAt" in node and "slug" in node and "eventType" in node


def visible_text(page: str) -> str:
    body = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    body = re.sub(r"<[^>]+>", "\n", body)
    lines = [html_lib.unescape(line).strip() for line in body.split("\n")]
    return "\n".join(line for line in lines if line)


def find_prize(text: str) -> str | None:
    flat = re.sub(r"\s+", " ", text)
    best: tuple[int, str] | None = None
    for rx in _PRIZE_RES:
        m = rx.search(flat)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), m.group(1).strip())
    return best[1] if best else None


class Lablab(Source):
    # November 2026: lablab.ai now redirects to starfieldlabs.ai ("Starfield Labs"), whose
    # events page lists nothing yet and whose /api/ is disallowed in robots.txt. Off until
    # the new site publishes events in a form we may read; the adapter is kept for reference.
    enabled = False
    key = "lablab"
    name = "lablab.ai"
    homepage = "https://lablab.ai/ai-hackathons"
    region = "global"
    focus = "AI hackathons with AI companies"
    description = (
        "Online, hybrid and on-site AI hackathons run with companies like AMD, IBM, Google and "
        "Vultr, where builders team up to ship AI apps and agents in a few days."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        rows = flight_rows(await get_text(client, LIST_URL))
        events: dict[str, dict[str, Any]] = {}
        for node in _walk(rows):
            if _is_event(node):
                events.setdefault(str(node.get("id") or node["slug"]), node)

        now = datetime.now(timezone.utc)
        current = [
            e
            for e in events.values()
            if not e.get("deletedAt")
            and e.get("active") is not False
            and (to_utc(e.get("endAt")) or now) >= now - timedelta(hours=1)
        ]
        pages = await gather_limited((self._page(client, e["slug"]) for e in current), limit=4)
        items: list[RawHackathon] = []
        for event, page in zip(current, pages, strict=True):
            detail, text, meta = page if isinstance(page, tuple) else ({}, "", None)
            try:
                items.append(self._build(event, detail, text, meta))
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("lablab: could not parse event %s", event.get("slug"))
        return items

    async def _page(self, client: httpx.AsyncClient, slug: str) -> tuple[dict[str, Any], str, str | None]:
        try:
            page = await get_text(client, f"{LIST_URL}/{slug}", retries=2)
        except Exception as exc:  # noqa: BLE001
            log.warning("lablab: event page failed %s: %s", slug, exc)
            return {}, "", None
        detail: dict[str, Any] = {}
        for node in _walk(flight_rows(page)):
            if _is_event(node) and node.get("slug") == slug and len(node) > len(detail):
                detail = node
        meta = re.search(r'<meta name="description" content="([^"]*)"', page)
        return detail, visible_text(page), html_lib.unescape(meta.group(1)) if meta else None

    def _build(
        self, event: dict[str, Any], detail: dict[str, Any], text: str, meta: str | None
    ) -> RawHackathon:
        e = {**event, **{k: v for k, v in detail.items() if v not in (None, [], {})}}
        slug = e["slug"]
        tba = bool(e.get("toBeAnnounced"))
        start = None if tba else to_utc(e.get("startAt"))
        end = None if tba else to_utc(e.get("endAt"))

        mode = _MODES.get(str(e.get("eventType") or "").upper())
        venues = [v for v in e.get("eventVenues") or [] if isinstance(v, dict)]
        cities = list(dict.fromkeys(c for c in (clean_text(v.get("city")) for v in venues) if c))
        countries = list(dict.fromkeys(c for c in (clean_text(v.get("country")) for v in venues) if c))
        city = cities[0] if len(cities) == 1 else None
        country = countries[0] if len(countries) == 1 else None
        if mode == "online":
            location = "Online"
        elif venues:
            places = [
                ", ".join(x for x in (clean_text(v.get("city")), clean_text(v.get("country"))) if x)
                for v in venues
            ]
            location = "; ".join(dict.fromkeys(p for p in places if p)) or None
        else:
            location = None

        description = clean_text(e.get("description"))
        tagline = description.split("\n", 1)[0] if description else None
        if tagline and len(tagline) > 200:
            tagline = None

        prize_text = find_prize(text) if text else None
        prize_amount, prize_currency = parse_money(prize_text) if prize_text else (None, None)
        if prize_text and "prize" not in prize_text.lower():
            prize_text = f"{prize_text} in prizes"

        techs = []
        for t in [*(e.get("techs") or []), *(e.get("technologyList") or [])]:
            name = clean_text(t.get("name") or t.get("techName") if isinstance(t, dict) else t)
            if name and name not in techs:
                techs.append(name)

        payment = e.get("paymentAmount")
        free = (payment in (None, 0, "0")) and bool(meta and re.search(r"\bfree\b", meta, re.I))
        team_min, team_max = as_int(e.get("teamMembersMinimum")), as_int(e.get("teamMembersLimit"))
        return RawHackathon(
            source=self.key,
            source_id=str(e.get("id") or slug),
            title=clean_text(e.get("name")) or slug,
            url=f"{LIST_URL}/{slug}",
            organizer="lablab.ai",
            tagline=tagline,
            description=description,
            image_url=e.get("imageLink") or None,
            logo_url=e.get("thumbnailLink") or None,
            mode=mode,
            location=location,
            city=city,
            country=country,
            starts_at=start,
            ends_at=end,
            timezone=clean_text(e.get("timezone")),
            prize_text=prize_text,
            prize_amount=prize_amount,
            prize_currency=prize_currency if prize_amount else None,
            tags=["AI", *techs],
            participants=as_int((e.get("_count") or {}).get("participants")),
            team_size_min=team_min if team_min else None,
            team_size_max=team_max if team_max else None,
            registration_fee=False if free else (True if payment not in (None, 0, "0") else None),
            travel_reimbursement=False if description and _TRAVEL_NO_RE.search(description) else None,
            extra={
                "signup_active": e.get("signupActive"),
                "dates_tba": tba,
                "venues": [clean_text(v.get("name")) for v in venues if v.get("name")],
                "event_type": e.get("eventType"),
            },
        )
