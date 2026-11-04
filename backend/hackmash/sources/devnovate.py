"""Devnovate: Indian hackathon platform behind the Hack With India city series.

Public JSON (the React app's own data source, no auth, no pagination):
    GET https://devnovate.co/api/v1/events
returns every event ever listed (~300) with mode, dates, registration deadline,
team size, prize pool text + per-place prizes, themes and registration count.
Event pages live at https://devnovate.co/event/<eventName>.

Dates are calendar days ("14-11-2026" or "2026-11-14") and the registration
deadline is a local timestamp without offset ("2026-11-07T11:39"); both are IST.
The feed also carries organiser contact details, which we deliberately drop.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..models import RawHackathon
from .base import IST, Source, abs_url, as_int, clean_text, get_json, to_utc

log = logging.getLogger(__name__)

BASE = "https://devnovate.co"
EVENTS_URL = f"{BASE}/api/v1/events"
EVENT_PAGE = f"{BASE}/event/{{slug}}"

_MODES = {"ONLINE": "online", "OFFLINE": "in_person", "HYBRID": "hybrid"}
_SKIP_TYPES = {"workshop", "conference", "webinar", "meetup", "bootcamp"}
_COMPETITION_RE = re.compile(r"hack|[a-z]-?a-?thon\b|thon\b|challenge|contest|competition|sprint|dotslash|code ?x\b", re.I)
_NOT_COMPETITION_RE = re.compile(r"workshop|summit|conference|meetup|ambassador|webinar|bootcamp|local host", re.I)
_NON_CASH_RE = re.compile(r"credits?\b|vouchers?\b|coupons?\b|subscriptions?\b|swag|goodies|certificate", re.I)
_MONEY_RE = re.compile(
    r"(?P<cur>₹|\brs\.?|\binr\b|us\$|\$|\busd\b)?\s*(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<mult>k\b|lakhs?\b|lacs?\b|crores?\b|cr\b)?\s*(?P<cur2>/-|\binr\b|\busd\b|\$)?",
    re.I,
)
_MULT = {"k": 1e3, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "crore": 1e7, "crores": 1e7, "cr": 1e7}


def _day(value: Any, end_of_day: bool = False) -> datetime | None:
    """'14-11-2026' / '2026-11-14' (IST calendar day) -> aware UTC datetime."""
    text = str(value or "").strip()
    for fmt in ("%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            day = datetime.strptime(text[:10], fmt)
        except ValueError:
            continue
        if end_of_day:
            day = day + timedelta(hours=23, minutes=59)
        return day.replace(tzinfo=IST).astimezone(timezone.utc)
    return None


def _deadline(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return _day(text, end_of_day=True)
    return to_utc(text, IST)


def _money(text: str) -> tuple[float | None, str | None]:
    """First cash amount in free text; bare numbers are rupees on this platform."""
    for m in _MONEY_RE.finditer(text):
        cur = (m.group("cur") or m.group("cur2") or "").lower().rstrip(".")
        mult = (m.group("mult") or "").lower()
        try:
            num = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        tail = text[m.end() : m.end() + 25]
        if _NON_CASH_RE.match(tail.strip()) or re.match(r"\s*(credits?|vouchers?)", tail, re.I):
            continue  # "$100 Fueler Credits"
        if cur in ("$", "us$", "usd"):
            currency = "USD"
        elif cur in ("₹", "rs", "inr", "/-") or mult:
            currency = "INR"
        elif num >= 1000 and not (1990 <= num <= 2100):
            currency = "INR"
        else:
            continue
        amount = num * _MULT.get(mult, 1)
        if amount >= 100:
            return amount, currency
    return None, None


def _fmt_inr(amount: float) -> str:
    s = str(int(round(amount)))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        s = ",".join(([head] if head else []) + groups) + "," + tail
    return f"₹{s}"


def _team(value: Any) -> tuple[int | None, int | None]:
    text = str(value or "").strip().lower()
    if not text:
        return None, None
    if "individual" in text or "solo" in text:
        return 1, 1
    nums = [int(n) for n in re.findall(r"\d+", text)]
    if len(nums) >= 2:
        return min(nums[:2]), max(nums[:2])
    if len(nums) == 1:
        return (1, nums[0]) if "up to" in text or "upto" in text else (nums[0], nums[0])
    return None, None


def classify_kind(title: str, subtitle: str, event_type: str, duration: str) -> str | None:
    """None = not a competition (workshops, summits, ambassador programmes)."""
    event_type = (event_type or "").lower()
    text = f"{title} {duration}"
    if event_type in _SKIP_TYPES:
        return None
    if event_type not in ("hackathon", "pitching-competition"):
        if _NOT_COMPETITION_RE.search(title) or not _COMPETITION_RE.search(f"{title} {subtitle[:300]}"):
            return None
    if event_type == "pitching-competition" or re.search(r"idea[\s-]?a?thon|ideation|\bpitch", title, re.I):
        return "ideathon"
    if re.search(r"designathon|design (challenge|sprint|competition)|ui/?ux", text, re.I):
        return "other"
    if re.search(r"\bctf\b|capture the flag|coding contest|competitive programming", title, re.I):
        return "coding_contest"
    if re.search(r"datathon|data[\s-]?thon|kaggle|ml challenge", title, re.I):
        return "data_science"
    return "hackathon"


class Devnovate(Source):
    key = "devnovate"
    name = "Devnovate"
    homepage = "https://devnovate.co/events"
    region = "india"
    focus = "Hack With India city hackathons and college events"
    description = (
        "Indian community platform that runs the Hack With India series (Hack With Bangalore, Delhi, "
        "Hyderabad...) and hosts college and startup hackathons, mostly in person."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        rows = await get_json(client, EVENTS_URL, headers={"Accept": "application/json"})
        if not isinstance(rows, list):
            rows = (rows or {}).get("data") or []
        now = datetime.now(timezone.utc)
        items: list[RawHackathon] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict) or row.get("approvalStatus") != "approved":
                continue
            slug = clean_text(row.get("eventName") or row.get("hackathon"))
            if not slug or slug in seen:
                continue
            seen.add(slug)
            try:
                item = self._build(row, slug)
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("devnovate: could not parse %s", slug)
                continue
            if item is None:
                continue
            end = item.ends_at or item.registration_deadline
            if end is None or end < now:
                continue
            items.append(item)
        return items

    def _build(self, row: dict[str, Any], slug: str) -> RawHackathon | None:
        title = clean_text(row.get("name")) or slug
        subtitle = clean_text(row.get("subtitle")) or ""
        duration = clean_text(row.get("time")) or ""
        kind = classify_kind(title, subtitle, row.get("eventType") or "", duration)
        if kind is None:
            return None

        starts = _day(row.get("startDate"))
        ends = _day(row.get("endDate"), end_of_day=True)
        if starts and ends and starts > ends:
            starts, ends = None, None
        mode = _MODES.get(str(row.get("status") or "").upper())
        location = clean_text(row.get("location"))
        if mode == "online" or (location or "").lower() in ("online", "virtual", "remote"):
            mode = mode or "online"
            location = "Online"

        # prizes: the headline "prize pool" text, else the per-place amounts
        pool_text = clean_text(row.get("prizePool"))
        if pool_text and re.fullmatch(r"(tb[ad]|na|n/a|-|none)\.?", pool_text, re.I):
            pool_text = None
        amount, currency = _money(pool_text) if pool_text else (None, None)
        places = [p for p in row.get("prizes") or [] if isinstance(p, dict)]
        if amount is None:
            total = 0.0
            for p in places:
                a, c = _money(str(p.get("amount") or ""))
                if a and c == "INR":
                    total += a
            if total:
                amount, currency = total, "INR"
        prize_text = pool_text
        if prize_text and len(prize_text) > 160:
            prize_text = prize_text[:157].rsplit(" ", 1)[0] + "…"
        if not prize_text and amount:
            prize_text = _fmt_inr(amount)
        extras = " ".join([pool_text or ""] + [f"{p.get('amount') or ''} {p.get('extras') or ''}" for p in places])
        non_cash = bool(re.search(r"credit|voucher|goodies|swag|internship|trophy|merch|gift", extras, re.I)) or None

        team_min, team_max = _team(row.get("teamSize"))
        tags = []
        for t in row.get("theme") or []:
            t = clean_text(t)
            if t and t not in tags:
                tags.append(t)
        price = row.get("price")
        paid = row.get("paid")

        return RawHackathon(
            source=self.key,
            source_id=str(row.get("_id") or slug),
            title=title,
            url=EVENT_PAGE.format(slug=slug),
            kind=kind,
            organizer=clean_text(row.get("organizationName")),
            tagline=subtitle[:200] if subtitle and len(subtitle) <= 200 else None,
            description=subtitle or None,
            image_url=abs_url(BASE, row.get("bannerImage") or row.get("cardImage")),
            logo_url=abs_url(BASE, row.get("organizationLogo")),
            mode=mode,
            location=location,
            starts_at=starts,
            ends_at=ends,
            registration_deadline=_deadline(row.get("registrationDeadline")),
            timezone="Asia/Kolkata",
            prize_text=prize_text,
            prize_amount=amount,
            prize_currency=currency if amount else None,
            non_cash_prizes=non_cash,
            tags=tags[:15],
            participants=as_int(row.get("numberOfRegistrations")),
            team_size_min=team_min,
            team_size_max=team_max,
            eligibility=[s for s in [clean_text(row.get("skillLevel"))] if s],
            registration_fee=bool(paid) if paid is not None else None,
            beginner_friendly=True if re.search(r"all levels|beginner", str(row.get("skillLevel") or ""), re.I) else None,
            extra={
                "slug": slug,
                "event_type": row.get("eventType"),
                "duration": duration or None,
                "registration_open": str(row.get("registrationStatus") or "").upper() == "OPEN",
                "price": price if paid else None,
                "featured": bool(row.get("isFeatured")),
                "verified": bool(row.get("verified")),
            },
        )
