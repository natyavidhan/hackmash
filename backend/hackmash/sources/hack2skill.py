"""Hack2skill: Google / government / corporate hackathons in India (Solution Challenge,
GenAI Exchange, Bharatiya Antariksh Hackathon, PromptWars...).

The marketing site is static; data comes from the platform's public API:
    GET https://hack2skill.com/api/v1/innovator/public/event/list?page=1&records=100
        every public event ("flagshipEvents" + "communityEvents", ~80 in total; paging
        is ignored by the server) with registration window, mode, ticket, team size
    GET https://hack2skill.com/api/v1/event/<eventUrl>/event-details
        the event page: submission window, a typed timeline (REGISTRATION,
        PROJECT_SUBMISSION, WEBINAR_WORKSHOP, ...), prize cards (amount + currency),
        problem statements and organiser-written sections
    GET https://hack2skill.com/api/v1/event/<eventUrl>/event-tnc
        {"title", "client" (the organiser), "type": HACKATHON | EVENT}
All timestamps are UTC ("...Z"); deadlines are set in IST (18:29Z = 23:59 IST).
"EVENT" entries are bootcamps / workshops and are skipped.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
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

BASE = "https://hack2skill.com"
LIST_URL = f"{BASE}/api/v1/innovator/public/event/list"
DETAILS_URL = f"{BASE}/api/v1/event/{{slug}}/event-details"
TNC_URL = f"{BASE}/api/v1/event/{{slug}}/event-tnc"
EVENT_PAGE = f"{BASE}/event/{{slug}}"
# events whose registration closed longer ago than this are not looked at again
RECENT = timedelta(days=150)

_MODES = {"VIRTUAL": "online", "ONLINE": "online", "IN_PERSON": "in_person", "OFFLINE": "in_person", "HYBRID": "hybrid"}
_SYMBOL = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}
_SETUP_STAGES = {"REGISTRATION", "TEAM_FORMATION", "FORM"}
_COMPETITION_RE = re.compile(r"hack|thon\b|sprint|challenge|contest|competition|cup\b|wars\b|olympiad", re.I)
_AMOUNT_LINE_RE = re.compile(r"^\s*(₹|rs\.?|inr|\$|usd)\s*[\d,]+(\.\d+)?\s*(/-)?\s*$", re.I)


def classify_kind(title: str, event_type: str | None) -> str | None:
    """None means "not a competition" (bootcamps, workshops, pop-ups)."""
    t = title or ""
    if (event_type or "HACKATHON").upper() != "HACKATHON" and not _COMPETITION_RE.search(t):
        return None
    if re.search(r"idea[\s-]?a?[\s-]?thon|\bideation\b|\bpitch", t, re.I):
        return "ideathon"
    if re.search(r"data[\s-]?a?[\s-]?thon|kaggle|\bml challenge|machine learning challenge", t, re.I):
        return "data_science"
    if re.search(r"\bctf\b|capture the flag|coding contest|code contest|competitive programming", t, re.I):
        return "coding_contest"
    if re.search(r"design (challenge|contest|competition)|\bquiz\b|photograph|\bessay\b|poster", t, re.I):
        return "other"
    return "hackathon"


def _fmt(amount: float, currency: str) -> str:
    whole = int(round(amount))
    if currency == "INR":
        s = str(whole)
        if len(s) > 3:  # Indian digit grouping: 1,05,000
            head, tail = s[:-3], s[-3:]
            groups = []
            while len(head) > 2:
                groups.insert(0, head[-2:])
                head = head[:-2]
            s = ",".join(([head] if head else []) + groups) + "," + tail
        return f"₹{s}"
    symbol = _SYMBOL.get(currency)
    return f"{symbol}{whole:,}" if symbol else f"{whole:,} {currency}"


def _sections(details: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [
        s
        for s in details.get("sections") or []
        if isinstance(s, dict) and s.get("type") == kind and not s.get("isHidden")
    ]


def _items(section: dict[str, Any]) -> list[dict[str, Any]]:
    out = []
    for cat in section.get("category") or []:
        if isinstance(cat, dict) and not cat.get("isHidden"):
            out.extend(d for d in cat.get("data") or [] if isinstance(d, dict) and not d.get("isHidden"))
    return out


def _custom_text(details: dict[str, Any], title_re: str, max_len: int = 1500) -> str | None:
    for s in _sections(details, "CUSTOM"):
        if re.search(title_re, s.get("title") or "", re.I):
            parts = [html_to_text(i.get("description"), max_len=max_len) for i in _items(s)]
            text = "\n".join(p for p in parts if p)
            if text:
                return text
    return None


def _prizes(details: dict[str, Any]) -> tuple[float | None, str | None, str | None, bool | None]:
    """(cash total, currency, display text, non-cash prizes?)."""
    totals: dict[str, float] = {}
    cards = 0
    for s in _sections(details, "PRIZES"):
        for card in _items(s):
            cards += 1
            try:
                amount = float(str(card.get("amount") or "0").replace(",", ""))
            except ValueError:
                amount = 0.0
            if amount > 0:
                cur = (card.get("currency") or "INR").upper()
                totals[cur] = totals.get(cur, 0.0) + amount
    if totals:
        cur, total = max(totals.items(), key=lambda kv: kv[1])
        return total, cur, _fmt(total, cur), None
    # Organiser-written rewards section, e.g. "1st Place\n₹ 50,000\n2nd Place\n₹ 35,000..."
    text = _custom_text(details, r"reward|prize", max_len=4000)
    if not text:
        return None, None, None, (True if cards else None)
    non_cash = bool(re.search(r"intern|goodies|swag|credits?\b|certificate|mentorship|incubat|ppo|ppi", text, re.I))
    pool = re.search(r"(total|pool|worth)[^\n]{0,40}?((₹|rs\.?|inr|\$|usd)\s*[\d,.]+\s*(lakhs?|lacs?|crores?|k)?)", text, re.I)
    if pool:
        amount, cur = parse_money(pool.group(2))
        if amount:
            return amount, cur, clean_text(pool.group(0)), non_cash or None
    lines = [ln for ln in text.split("\n") if _AMOUNT_LINE_RE.match(ln)]
    if lines:
        amounts = [parse_money(ln, "INR") for ln in lines]
        currencies = {c for _, c in amounts if c}
        if len(currencies) == 1:
            total = sum(a for a, _ in amounts if a)
            cur = currencies.pop()
            return total, cur, _fmt(total, cur), non_cash or None
    first = next((ln for ln in text.split("\n") if re.search(r"[₹$]|\brs\.?\s*\d|\binr\b|lakh", ln, re.I)), None)
    return None, None, (clean_text(first)[:160] if first else None), non_cash or None


class Hack2skill(Source):
    key = "hack2skill"
    name = "Hack2skill"
    homepage = "https://hack2skill.com/hackathons-listing"
    region = "india"
    focus = "Google, government and corporate hackathons in India"
    description = (
        "Runs large national challenges for Google (Solution Challenge, GenAI Exchange), ISRO, "
        "NASSCOM and other companies, mostly online with in-person finales."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        data = await get_json(
            client, LIST_URL, params={"page": 1, "records": 100}, headers={"Accept": "application/json"}
        )
        block = (data or {}).get("data") or {}
        rows: dict[str, dict[str, Any]] = {}
        for group in ("flagshipEvents", "communityEvents"):
            for row in block.get(group) or []:
                if isinstance(row, dict) and row.get("eventUrl") and row.get("status", "APPROVED") == "APPROVED":
                    rows.setdefault(row["eventUrl"], row)

        now = datetime.now(timezone.utc)
        candidates = [
            r for r in rows.values() if (to_utc(r.get("registrationEnd")) or now) > now - RECENT
        ]
        details = await gather_limited((self._detail(client, r["eventUrl"]) for r in candidates), limit=6)
        items: list[RawHackathon] = []
        for row, detail in zip(candidates, details, strict=True):
            try:
                item = self._build(row, detail if isinstance(detail, dict) else {})
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("hack2skill: could not parse %s", row.get("eventUrl"))
                continue
            if item is None:
                continue
            end = item.ends_at or item.submission_deadline
            if end is None:  # no end date published: current while registration is open / not started
                end = max((x for x in (item.registration_deadline, item.starts_at) if x), default=None)
            if end and end < now:
                continue
            items.append(item)
        return items

    async def _detail(self, client: httpx.AsyncClient, slug: str) -> dict[str, Any]:
        out: dict[str, Any] = {}
        try:
            out["details"] = ((await get_json(client, DETAILS_URL.format(slug=slug), retries=2)) or {}).get("data") or {}
        except Exception as exc:  # noqa: BLE001
            log.warning("hack2skill: event-details failed for %s: %s", slug, exc)
        try:
            out["tnc"] = ((await get_json(client, TNC_URL.format(slug=slug), retries=2)) or {}).get("data") or {}
        except Exception as exc:  # noqa: BLE001
            log.warning("hack2skill: event-tnc failed for %s: %s", slug, exc)
        return out

    def _build(self, row: dict[str, Any], detail: dict[str, Any]) -> RawHackathon | None:
        d = detail.get("details") or {}
        tnc = detail.get("tnc") or {}
        slug = row["eventUrl"]
        title = clean_text(row.get("title") or d.get("title") or tnc.get("title")) or slug
        kind = classify_kind(title, tnc.get("type") or d.get("type"))
        if kind is None:
            return None
        tags = d.get("tags") or row.get("tags") or {}

        # ---- dates -------------------------------------------------------
        reg_open = to_utc(d.get("registrationStart") or row.get("registrationStart"))
        reg_close = to_utc(d.get("registrationEnd") or row.get("registrationEnd"))
        sub_open, sub_close = to_utc(d.get("submissionStart")), to_utc(d.get("submissionEnd"))
        stages = []
        for s in _sections(d, "TIMELINE"):
            for st in _items(s):
                start, end = to_utc(st.get("start")), to_utc(st.get("end"))
                if start or end:
                    stages.append({"title": clean_text(st.get("title")) or "", "type": st.get("type"), "start": start, "end": end})
        work = [s for s in stages if (s["type"] or "").upper() not in _SETUP_STAGES and s["start"]]
        starts = min([s["start"] for s in work] + ([sub_open] if sub_open else []), default=None)
        # The registration close is not an end date: in-person finales often come later.
        ends = max([s["end"] for s in stages if s["end"]] + ([sub_close] if sub_close else []), default=None)
        if starts and ends and starts > ends:
            ends = None
        # Multi-stage / rolling events have several submission rounds: report the next one.
        sub_ends = sorted(
            {x for x in [sub_close] + [s["end"] for s in stages if "SUBMISSION" in (s["type"] or "").upper()] if x}
        )
        now = datetime.now(timezone.utc)
        submission = next((x for x in sub_ends if x > now), sub_ends[-1] if sub_ends else None)

        # ---- place / people ----------------------------------------------
        mode = _MODES.get(str((tags.get("mode") or {}).get("value") or "").upper())
        regions = (tags.get("region") or {}).get("value") or []
        regions = [clean_text(r if isinstance(r, str) else (r or {}).get("label") or (r or {}).get("value")) for r in regions]
        regions = [r for r in regions if r]
        if mode == "online":
            location = "Online"
        else:
            location = ", ".join(regions) or None
        team = tags.get("teamSize") or {}
        regs = tags.get("registrations") or {}
        participants = None if regs.get("isHidden") else as_int(regs.get("value"))
        ticket = str((tags.get("ticket") or {}).get("value") or "").upper()
        fee = True if ticket == "PAID" else (False if ticket == "FREE" else None)

        eligibility: list[str] = []
        age = tags.get("age") or {}
        if not age.get("isHidden") and (age.get("min") or age.get("max")):
            eligibility.append(f"Age {age.get('min') or '?'}–{age.get('max') or '?'}")
        who = _custom_text(d, r"who can|eligib")
        if who:
            eligibility += [ln.strip(" •-") for ln in who.split("\n") if 2 < len(ln.strip(" •-")) <= 200][:6]

        topics: list[str] = []
        for s in _sections(d, "CHALLANGES"):  # sic
            for ch in _items(s):
                name = clean_text(ch.get("title"))
                if name and name not in topics:
                    topics.append(name)
        tech = tags.get("technology") or {}
        if not tech.get("isHidden"):
            for t in tech.get("value") or []:
                name = clean_text(t if isinstance(t, str) else (t or {}).get("label") or (t or {}).get("value"))
                if name and name not in topics:
                    topics.append(name)

        # ---- content -----------------------------------------------------
        description = None
        for s in _sections(d, "ABOUT"):
            parts = [html_to_text(i.get("description")) for i in _items(s)]
            description = "\n".join(p for p in parts if p) or None
            if description:
                break
        if description and len(description) > 1500:
            description = description[:1500].rsplit(" ", 1)[0] + "…"
        banner = None
        for s in _sections(d, "OVERVIEW"):
            for cat in s.get("category") or []:
                if (cat or {}).get("type") == "BANNER":
                    for item in cat.get("data") or []:
                        for c in item.get("content") or []:
                            if c.get("value") and not c.get("isHidden") and not c.get("isDeleted"):
                                banner = banner or c["value"]

        amount, currency, prize_text, non_cash = _prizes(d)
        organizer = clean_text(tnc.get("client"))

        return RawHackathon(
            source=self.key,
            source_id=str(row.get("_id") or slug),
            title=title,
            url=EVENT_PAGE.format(slug=slug),
            kind=kind,
            organizer=organizer,
            description=description,
            image_url=banner or row.get("thumbnail") or None,
            logo_url=d.get("logo") or None,
            mode=mode,
            location=location,
            city=regions[0] if mode != "online" and len(regions) == 1 else None,
            starts_at=starts,
            ends_at=ends,
            registration_opens_at=reg_open,
            registration_deadline=reg_close,
            submission_deadline=submission,
            timezone="Asia/Kolkata",
            prize_text=prize_text,
            prize_amount=amount,
            prize_currency=currency if amount else None,
            non_cash_prizes=non_cash,
            tags=topics[:15],
            participants=participants,
            team_size_min=as_int(team.get("min")),
            team_size_max=as_int(team.get("max")),
            eligibility=eligibility,
            registration_fee=fee,
            extra={
                "slug": slug,
                "flag": row.get("flag"),
                "event_type": tnc.get("type") or d.get("type"),
                "microsite": clean_text(row.get("customEventUrl")) or None,
                "registrations_hidden": bool(regs.get("isHidden")),
                "registrations": as_int(regs.get("value")),
                "timeline": [
                    {
                        "title": s["title"],
                        "type": s["type"],
                        "starts_at": s["start"].isoformat() if s["start"] else None,
                        "ends_at": s["end"].isoformat() if s["end"] else None,
                    }
                    for s in stages
                ],
            },
        )
