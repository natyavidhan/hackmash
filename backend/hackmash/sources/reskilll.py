"""Reskilll: Indian corporate hackathon platform (iQOO, Adobe, Wadhwani AI, AWS...).

Listing (server-rendered HTML, every hackathon ever hosted, newest first):
    https://reskilll.com/allhacks
Each card has the name, link, banner, a one-line description and the
registration window as calendar dates (IST). Event pages are per-event apps
(https://reskilll.com/hack/<slug>/ or <slug>.reskilll.com) whose HTML carries a
schema.org ``Event`` (start/end day, attendance mode, organisers) and meta
descriptions that spell out the prize ("Five winners share $5,000 in cash").
"""

from __future__ import annotations

import html as html_lib
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from ..models import RawHackathon
from .base import IST, Source, clean_text, gather_limited, get_text, mode_from, parse_money

log = logging.getLogger(__name__)

LIST_URL = "https://reskilll.com/allhacks"
# cards whose registration closed more recently than this are checked for a later event end
LOOKBACK = timedelta(days=30)

_CARD_SPLIT = re.compile(r'<div class="col-12 col-lg-3 col-md-6 py-3 hackathonCard">')
_NAME_RE = re.compile(r'class="allhackname eventName[^"]*"\s+href="([^"]+)"[^>]*>(.*?)</a>', re.S)
_DESC_RE = re.compile(r'class="d-none eventDescription">(.*?)</div>', re.S)
_DATE_RE = re.compile(r'<div class="hackregisterdatehead">\s*(.*?)\s*</div>\s*<div class="hackresgiterdate">\s*([^<]*?)\s*</div>', re.S)
_IMG_RE = re.compile(r'<img src="([^"]+)"[^>]*class="img-fluid allhacksbanner"')
_LD_RE = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
_META_RE = re.compile(r'<meta\s+(?:name|property)="(description|og:description)"\s+content="([^"]*)"', re.I)
_CASH_RE = re.compile(
    r"((?:₹|\$|rs\.?\s?|inr\s?|usd\s?)[\d,.]+\s*(?:k|lakhs?|lacs?|crores?)?)\s+(?:in\s+)?(?:total\s+)?(?:cash|prize money|prize pool|in prizes|in cash)",
    re.I,
)
_SHARE_RE = re.compile(r"share\s+((?:₹|\$|rs\.?\s?|inr\s?|usd\s?)[\d,.]+\s*(?:k|lakhs?|lacs?|crores?)?)", re.I)


def _day(text: str | None, end_of_day: bool = False) -> datetime | None:
    try:
        day = datetime.strptime((text or "").strip()[:10], "%Y-%m-%d")
    except ValueError:
        return None
    if end_of_day:
        day += timedelta(hours=23, minutes=59)
    return day.replace(tzinfo=IST).astimezone(timezone.utc)


def parse_cards(page: str) -> list[dict[str, Any]]:
    cards = []
    for chunk in _CARD_SPLIT.split(page)[1:]:
        m = _NAME_RE.search(chunk)
        if not m:
            continue
        dates = {clean_text(k.rstrip(":")).lower(): v for k, v in _DATE_RE.findall(chunk)}
        desc = _DESC_RE.search(chunk)
        img = _IMG_RE.search(chunk)
        cards.append(
            {
                "url": html_lib.unescape(m.group(1)).strip(),
                "title": clean_text(re.sub(r"<[^>]+>", " ", m.group(2))),
                "description": clean_text(desc.group(1)) if desc else None,
                "image": img.group(1) if img else None,
                "reg_start": _day(dates.get("registration start")),
                "reg_end": _day(dates.get("registration end"), end_of_day=True),
                "open": "Register Now" in chunk,
            }
        )
    return cards


def parse_event_page(page: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for m in _LD_RE.finditer(page):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        for node in data if isinstance(data, list) else [data]:
            if isinstance(node, dict) and node.get("@type") in ("Event", "Hackathon"):
                out["event"] = node
                break
    out["meta"] = [html_lib.unescape(v) for _, v in _META_RE.findall(page)]
    return out


class Reskilll(Source):
    key = "reskilll"
    name = "Reskilll"
    homepage = "https://reskilll.com/allhacks"
    region = "india"
    focus = "Corporate and brand hackathons in India"
    description = (
        "Indian hackathon platform used by brands and foundations such as iQOO, Adobe and Wadhwani AI "
        "for mostly online, national-level hackathons."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        cards = parse_cards(await get_text(client, LIST_URL))
        now = datetime.now(timezone.utc)
        candidates = [c for c in cards if c["open"] or (c["reg_end"] and c["reg_end"] > now - LOOKBACK)]
        pages = await gather_limited((self._page(client, c["url"]) for c in candidates), limit=4)
        items: list[RawHackathon] = []
        seen: set[str] = set()
        for card, page in zip(candidates, pages, strict=True):
            try:
                item = self._build(card, page if isinstance(page, dict) else {})
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("reskilll: could not parse %s", card.get("url"))
                continue
            end = item.ends_at or item.registration_deadline
            if not end or end < now or item.source_id in seen:
                continue
            seen.add(item.source_id)
            items.append(item)
        return items

    async def _page(self, client: httpx.AsyncClient, url: str) -> dict[str, Any]:
        host = urlparse(url).hostname or ""
        if not host.endswith("reskilll.com"):
            return {}  # external microsites (e.g. mastryhub.com) are not parsed
        try:
            return parse_event_page(await get_text(client, url, retries=2))
        except Exception as exc:  # noqa: BLE001
            log.warning("reskilll: page failed %s: %s", url, exc)
            return {}

    def _build(self, card: dict[str, Any], page: dict[str, Any]) -> RawHackathon:
        ev = page.get("event") or {}
        url = card["url"]
        parsed = urlparse(url)
        slug = parsed.path.strip("/").split("/")[-1] if parsed.hostname == "reskilll.com" and parsed.path.strip("/") else (parsed.hostname or url)

        starts = _day(ev.get("startDate")) if ev.get("startDate") else None
        ends = _day(ev.get("endDate"), end_of_day=True) if ev.get("endDate") else None
        reg_close = card.get("reg_end")
        if ends is None:
            ends = reg_close  # the card's window is the only schedule we have
        if starts and ends and starts > ends:
            starts = None

        attendance = str(ev.get("eventAttendanceMode") or "")
        mode = "hybrid" if "Mixed" in attendance else "in_person" if "Offline" in attendance else "online" if "Online" in attendance else None
        meta = " ".join(page.get("meta") or [])
        mode = mode or mode_from(meta)
        location = None
        loc = ev.get("location") if isinstance(ev.get("location"), dict) else {}
        if mode == "online":
            location = "Online"
        elif loc.get("name") or loc.get("address"):
            address = loc.get("address")
            location = clean_text(loc.get("name")) or clean_text(address if isinstance(address, str) else None)

        organizers = ev.get("organizer") or []
        organizers = organizers if isinstance(organizers, list) else [organizers]
        names = [clean_text(o.get("name")) for o in organizers if isinstance(o, dict) and o.get("name")]
        organizer = next((n for n in names if n and n.lower() != "reskilll"), None)

        text = " ".join([meta, card.get("description") or "", clean_text(ev.get("description")) or ""])
        prize_amount = prize_currency = prize_text = None
        cash = _SHARE_RE.search(text) or _CASH_RE.search(text)
        if cash:
            prize_amount, prize_currency = parse_money(cash.group(1))
            sentence = re.search(r"[^.]*" + re.escape(cash.group(0)) + r"[^.]*", text)
            prize_text = clean_text(sentence.group(0)) if sentence else clean_text(cash.group(0))
        else:
            win = re.search(r"win(?:ning)?[^.]{0,40}?(?:₹|\$|rs\.?)\s?[\d,.]+\s*(?:k|lakhs?)?[^.]{0,30}", text, re.I)
            prize_text = clean_text(win.group(0)) if win else None
        if prize_text and len(prize_text) > 160:
            prize_text = prize_text[:157].rsplit(" ", 1)[0] + "…"

        return RawHackathon(
            source=self.key,
            source_id=slug,
            title=card["title"] or clean_text(ev.get("name")) or slug,
            url=url,
            organizer=organizer,
            tagline=card.get("description"),
            description=clean_text(ev.get("description")) or card.get("description"),
            image_url=card.get("image"),
            mode=mode,
            location=location,
            starts_at=starts,
            ends_at=ends,
            registration_opens_at=card.get("reg_start"),
            registration_deadline=reg_close,
            timezone="Asia/Kolkata",
            prize_text=prize_text,
            prize_amount=prize_amount,
            prize_currency=prize_currency if prize_amount else None,
            non_cash_prizes=True if re.search(r"plan|credits?|swag|goodies|internship", meta, re.I) else None,
            extra={"registration_open": card.get("open"), "organizers": names},
        )
