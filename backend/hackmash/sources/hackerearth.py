"""HackerEarth: corporate hackathons, hiring challenges and coding contests (Bengaluru).

Listing (public JSON, no pagination; each returns a curated mix of current and
old challenges, so we keep only those that have not ended):
    GET https://www.hackerearth.com/api/community/challenges/compete/   (the /challenges/ page)
    GET https://www.hackerearth.com/api/community/challenges/hiring/
    GET https://www.hackerearth.com/chrome-extension/events/            (live + upcoming)
Detail, per challenge:
    https://www.hackerearth.com/community/challenges/<type>/<slug>/ embeds an
        ``initialEventData`` object in its React Server Components payload
        (exact UTC start/end, registrations, team size, organiser, online/venue)
    GET https://www.hackerearth.com/challengesapp/api/events/<slug>/        same record as
        JSON (minus dates/registrations); used when the page redirects to an
        external microsite
    GET https://www.hackerearth.com/challengesapp/api/events/<slug>/tabs/[<key>/]
        organiser-written tabs such as "Prizes & Rewards", "Eligibility", "Theme"

Listing times are UTC. ``phases`` in the detail record are sometimes shifted
by the IST offset, so they are only used for submission deadlines when they
agree with the challenge window.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from ..models import RawHackathon
from .base import (
    Source,
    as_int,
    clean_text,
    gather_limited,
    get_json,
    html_to_text,
    parse_money,
    to_utc,
)

log = logging.getLogger(__name__)

BASE = "https://www.hackerearth.com"
COMPETE_URL = f"{BASE}/api/community/challenges/compete/"
HIRING_URL = f"{BASE}/api/community/challenges/hiring/"
EXTENSION_URL = f"{BASE}/chrome-extension/events/"
EVENT_API = f"{BASE}/challengesapp/api/events/{{slug}}/"
PAGE_URL = f"{BASE}/community/challenges/{{type}}/{{slug}}/"

_URL_RE = re.compile(r"/challenges/(?P<type>[a-z-]+)/(?P<slug>[^/?#]+)/?")
_FLIGHT_RE = re.compile(r"self\.__next_f\.push\((\[.*?\])\)</script>", re.S)
_HACK_RE = re.compile(r"hack|[a-z]-?a?-?thon\b|\bbuild|\bsprint", re.I)
_DATA_RE = re.compile(r"machine learning|\bml\b|data science|datathon|kaggle|predict", re.I)
_DATA_CATEGORY_RE = re.compile(r"machine|\bml\b|data-science|datascience|deep-learning|\bai\b", re.I)
_TAB_KEYS = re.compile(r"prize|reward|eligib|theme|track|problem", re.I)


def _flight_text(page: str) -> str:
    out = []
    for chunk in _FLIGHT_RE.findall(page):
        try:
            arr = json.loads(chunk)
        except ValueError:
            continue
        if len(arr) > 1 and isinstance(arr[1], str):
            out.append(arr[1])
    return "".join(out)


def _text_refs(flight: str) -> dict[str, str]:
    """RSC text rows look like ``5c:T12ad,<0x12ad bytes of text>``."""
    refs: dict[str, str] = {}
    raw = flight.encode("utf-8")
    for m in re.finditer(rb"(?:^|\n|\})([0-9a-f]+):T([0-9a-f]+),", raw):
        size = int(m.group(2), 16)
        refs[m.group(1).decode()] = raw[m.end() : m.end() + size].decode("utf-8", "ignore")
    return refs


def page_event_data(page: str) -> dict[str, Any] | None:
    """Pull ``initialEventData`` out of a challenge page, resolving ``$xx`` text refs."""
    flight = _flight_text(page)
    i = flight.find('"initialEventData":')
    if i < 0:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(flight[i + len('"initialEventData":') :])
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    refs = _text_refs(flight)
    for key, value in list(data.items()):
        if isinstance(value, str) and value.startswith("$") and value[1:] in refs:
            data[key] = refs[value[1:]]
    return data


def classify_kind(title: str, event_type: str | None, category: str | None, listing_type: str | None) -> str:
    """hackathons -> hackathon; ML -> data_science; hiring / competitive -> coding_contest."""
    event_type = (event_type or listing_type or "").lower()
    category = (category or "").lower()
    if event_type in ("machine-learning", "data-science") or _DATA_CATEGORY_RE.search(category):
        return "data_science"
    if event_type in ("hackathon", "sprints", "sprint") or _HACK_RE.search(title):
        return "hackathon"
    if _DATA_RE.search(title):
        return "data_science"
    return "coding_contest"


class HackerEarth(Source):
    key = "hackerearth"
    name = "HackerEarth"
    homepage = "https://www.hackerearth.com/challenges/"
    region = "india"
    focus = "Corporate hackathons and hiring challenges"
    description = (
        "Bengaluru-based developer platform where companies such as IBM, Flipkart and GoDaddy run "
        "online hackathons, coding contests and hiring challenges."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        results = await asyncio.gather(
            get_json(client, COMPETE_URL, retries=2),
            get_json(client, HIRING_URL, retries=2),
            get_json(client, EXTENSION_URL, retries=2),
            return_exceptions=True,
        )
        if all(isinstance(r, BaseException) for r in results):
            raise results[0]  # type: ignore[misc]
        compete, hiring, extension = (r if not isinstance(r, BaseException) else {} for r in results)

        now = datetime.now(timezone.utc)
        rows: dict[str, dict[str, Any]] = {}
        for row in (compete.get("data") or []) + (hiring.get("data") or []):
            m = _URL_RE.search(row.get("url") or "")
            slug = row.get("slug") or (m.group("slug") if m else None)
            if not slug:
                continue
            entry = rows.setdefault(slug, {"slug": slug})
            entry["listing"] = row
            entry["type"] = m.group("type") if m else None
            # listing timestamps are naive UTC ("start_str": "Nov 06, 2026 12:30 PM UTC")
            entry["start"] = to_utc(row.get("start"))
            entry["end"] = to_utc(row.get("end"))
        for row in extension.get("response") or []:
            m = _URL_RE.search(row.get("url") or "")
            if not m:
                continue
            entry = rows.setdefault(m.group("slug"), {"slug": m.group("slug")})
            entry["feed"] = row
            entry["type"] = entry.get("type") or m.group("type")
            entry["start"] = to_utc(row.get("start_utc_tz")) or entry.get("start")
            entry["end"] = to_utc(row.get("end_utc_tz")) or entry.get("end")

        current = [e for e in rows.values() if e.get("end") and e["end"] > now]
        details = await gather_limited((self._detail(client, e) for e in current), limit=4)
        items: list[RawHackathon] = []
        for entry, detail in zip(current, details, strict=True):
            try:
                items.append(self._build(entry, detail if isinstance(detail, dict) else {}))
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("hackerearth: could not parse %s", entry.get("slug"))
        return items

    async def _detail(self, client: httpx.AsyncClient, entry: dict[str, Any]) -> dict[str, Any]:
        slug, kind = entry["slug"], entry.get("type") or "competitive"
        out: dict[str, Any] = {}
        try:
            resp = await client.get(PAGE_URL.format(type=kind, slug=slug), follow_redirects=False)
            if resp.status_code == 200:
                out["event"] = page_event_data(resp.text) or {}
            elif resp.is_redirect:
                out["external_url"] = resp.headers.get("location")
        except httpx.HTTPError as exc:
            log.warning("hackerearth: page failed for %s: %s", slug, exc)
        if not out.get("event"):
            try:
                out["event"] = await get_json(client, EVENT_API.format(slug=slug), retries=2)
            except Exception as exc:  # noqa: BLE001
                log.warning("hackerearth: event api failed for %s: %s", slug, exc)
        try:
            tabs = await get_json(client, EVENT_API.format(slug=slug) + "tabs/", retries=1)
        except Exception:  # noqa: BLE001 - tabs are optional
            tabs = []
        out["tabs"] = {}
        for tab in tabs if isinstance(tabs, list) else []:
            key = (tab or {}).get("key") or ""
            if tab.get("is_custom") and _TAB_KEYS.search(key + " " + (tab.get("name") or "")):
                try:
                    body = await get_json(client, EVENT_API.format(slug=slug) + f"tabs/{key}/", retries=1)
                    out["tabs"][tab.get("name") or key] = html_to_text(body.get(key), max_len=3000)
                except Exception:  # noqa: BLE001
                    continue
        return out

    def _build(self, entry: dict[str, Any], detail: dict[str, Any]) -> RawHackathon:
        listing = entry.get("listing") or {}
        feed = entry.get("feed") or {}
        ev = detail.get("event") or {}
        slug = entry["slug"]
        title = clean_text(ev.get("title") or listing.get("title") or feed.get("title")) or slug
        ctype = entry.get("type") or "competitive"
        url = f"{BASE}/challenges/{ctype}/{slug}/"

        starts = to_utc(ev.get("start_date")) or entry.get("start")
        ends = to_utc(ev.get("end_date")) or entry.get("end")

        organizers = [o for o in ev.get("organizer") or [] if isinstance(o, dict)]
        organizer = clean_text(organizers[0].get("title")) if organizers else None
        organizer = organizer or clean_text(listing.get("company_name"))
        logo = (organizers[0].get("image") if organizers else None) or listing.get("image_url") or feed.get("thumbnail")
        banner = (
            ev.get("cover_image")
            or listing.get("listing_image")
            or feed.get("cover_image")
            or None
        )

        description = clean_text(ev.get("description_text")) or html_to_text(ev.get("description_html"))
        description = html_to_text(description) if description and "<" in description else description
        if description and len(description) > 1500:
            description = description[:1500].rsplit(" ", 1)[0] + "…"
        if not description:
            description = clean_text(feed.get("description"))

        location = ev.get("location") if isinstance(ev.get("location"), dict) else {}
        venue = clean_text(location.get("address")) or None
        city = clean_text(location.get("city")) or None
        if ev.get("is_online") is False and (venue or city):
            mode, place = "in_person", ", ".join(x for x in (venue, city) if x)
        else:
            # HackerEarth challenges without a venue are run online on the platform
            mode, place = "online", "Online"

        tabs: dict[str, str | None] = detail.get("tabs") or {}
        prize_tab = next((v for k, v in tabs.items() if v and re.search(r"prize|reward", k, re.I)), None)
        prize_text = prize_amount = prize_currency = None
        if prize_tab:
            line = next((ln for ln in prize_tab.split("\n") if re.search(r"[₹$€£]|\brs\.?\s*\d|\binr\b|\busd\b", ln, re.I)), None)
            prize_text = (line or "").strip()[:160] or None
            pool = re.search(r"(total|pool|worth|in prizes|prize money)[^\n]{0,60}", prize_tab, re.I)
            if pool:
                prize_amount, prize_currency = parse_money(pool.group(0) + " " + (line or ""))
        eligibility = [
            ln.strip(" •-")
            for k, v in tabs.items()
            if v and re.search(r"eligib", k, re.I)
            for ln in v.split("\n")
            if ln.strip(" •-")
        ][:8]
        themes = [
            ln.strip(" •-")
            for k, v in tabs.items()
            if v and re.search(r"theme|track", k, re.I)
            for ln in v.split("\n")
            if 2 < len(ln.strip(" •-")) <= 60
        ][:10]

        phases = [p for p in ev.get("phases") or [] if isinstance(p, dict)]
        submission = None
        for ph in phases:
            if re.search(r"submi", ph.get("title") or "", re.I):
                end = to_utc(ph.get("end"))
                if end and starts and ends and starts <= end <= ends:
                    submission = end
                    break

        participants = as_int((ev.get("members") or {}).get("total_registrations"))
        if participants is None:
            participants = as_int(listing.get("subscription_count"))
        team_min = as_int(ev.get("min_team_size") or listing.get("min_team_size"))
        team_max = as_int(ev.get("max_team_size") or listing.get("max_team_size"))
        if ev.get("is_team") is False:
            team_min = team_max = 1

        kind = classify_kind(title, ev.get("event_type") or ctype, ev.get("event_category"), listing.get("type"))
        return RawHackathon(
            source=self.key,
            source_id=slug,
            title=title,
            url=url,
            kind=kind,
            organizer=organizer,
            description=description,
            image_url=banner,
            logo_url=logo,
            mode=mode,
            location=place,
            city=city if mode != "online" else None,
            starts_at=starts,
            ends_at=ends,
            submission_deadline=submission,
            timezone="Asia/Kolkata" if re.search(r"\bIST\b", feed.get("start_timestamp") or "") else None,
            prize_text=prize_text,
            prize_amount=prize_amount,
            prize_currency=prize_currency if prize_amount else None,
            tags=themes,
            participants=participants,
            team_size_min=team_min,
            team_size_max=team_max,
            eligibility=eligibility,
            invite_only=(ev.get("is_listed") is False) or None,
            extra={
                "challenge_type": ctype,
                "event_type": ev.get("event_type"),
                "event_category": ev.get("event_category"),
                "listing_type": listing.get("type"),
                "external_url": detail.get("external_url"),
                "duration": clean_text(ev.get("event_duration")),
                "webcam_required": (ev.get("widgets") or {}).get("webcam"),
                "college": feed.get("college"),
            },
        )
