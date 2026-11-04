"""Unstop (formerly Dare2Compete): India's largest student competition platform.

List endpoint (public JSON, Laravel-style pagination, up to 200 per page):
    GET https://unstop.com/api/public/opportunity/search-new
        ?opportunity=hackathons&oppstatus=<open|closed>&per_page=100&page=N
    ``open`` = registration open, ``closed`` = registration closed but the event
    has not ended yet, ``expired`` = the archive. This is the endpoint the site's
    own listing uses (the older ``search-result`` lacks ``start_date``/banners).
    Do not send ``sort=latest``: combined with ``oppstatus=closed`` it returns
    an empty result.
Detail endpoint (public JSON), fetched for every listing:
    GET https://unstop.com/api/public/competition/<id>
        rounds with exact start/end per stage, the organiser's banner and
        free-text prize summary.

Every timestamp carries an explicit +05:30 offset. The "hackathons" section
mixes real hackathons with CTFs, coding contests, case/pitch competitions and
tech-fest robotics events, and ``subtype`` is almost always
``online_coding_challenge``, so ``kind`` is derived from the title, the round
structure and Unstop's work-function tags instead.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
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
    to_utc,
)

log = logging.getLogger(__name__)

BASE = "https://unstop.com"
LIST_URL = f"{BASE}/api/public/opportunity/search-new"
DETAIL_URL = f"{BASE}/api/public/competition/{{id}}"
PER_PAGE = 100
MAX_ITEMS = 1500

_CURRENCY = {"fa-rupee": "INR", "fa-inr": "INR", "fa-dollar": "USD", "fa-usd": "USD", "fa-euro": "EUR"}
_SYMBOL = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}

_ROUND_TYPES = {
    "App\\Model\\Rounds": "submission",
    "App\\Model\\OfflineRound": "offline",
    "App\\Models\\AssessmentRound\\AssessmentRound": "assessment",
    "App\\Model\\Quiz": "quiz",
    "App\\Model\\CodeContests": "code",
}

# Rounds that only exist to collect registrations / make announcements; they say
# nothing about when the competition itself starts.
_ADMIN_ROUND_RE = re.compile(
    r"registration|register|join (our|the)|whatsapp|community|form fill|notice|must read|rsvp|"
    r"payment|result|announcement|shortlist|screening|verification|mock practice",
    re.I,
)

# --- kind classification ----------------------------------------------------

_KIND_IDEATHON_EXPLICIT = re.compile(r"\bidea[\s-]?a?[\s-]?thon|\bideation\b", re.I)
_KIND_CONTEST = re.compile(
    r"\bctf\b|ctf\b|capture[\s-]+the[\s-]+flag|competitive programming|programming (contest|league|challenge)|"
    r"cod(e|ing) (contest|challenge|clash|duel)|reverse coding|\bdsa\b|leetcode|codechef|codeforces|"
    r"\bduel\b|\bprocon\b|\bsql\b|bug[\s-]?bounty|bug hunt|speed coding|code golf|\bdebugging\b",
    re.I,
)
_KIND_DATA = re.compile(
    r"data[\s-]?a?[\s-]?thon|\bml (challenge|competition|olympiad)|machine learning (challenge|competition)|"
    r"data science (challenge|competition)|kaggle|prediction (challenge|competition)",
    re.I,
)
_KIND_HACK = re.compile(r"hack|[a-z]-?a?-?thon\b|\bbuild|codefest|code ?fest|innovat(ion|e)[\s-]?thon", re.I)
_KIND_OTHER = re.compile(
    r"\brobo|robot|\bdrone|\brover|multirotor|hover|grand prix|aeromodel|\bquiz|treasure hunt|"
    r"\btrad(e|ing)\b|\bmarkets?\b|\bquant\b|\bstock|\bmun\b|prompt battle|\bdebate|\bessay|photograph|esports",
    re.I,
)
_KIND_IDEA = re.compile(
    r"\bideas?\b|\bpitch|case[\s-]?(study|challenge|competition)|\bb-?plan\b|business plan|strategy|"
    r"product challenge|\bconsult|paper presentation|\bpolicy\b",
    re.I,
)
_ROUND_DATA = re.compile(r"model submission|prediction|leaderboard|kaggle", re.I)
_ROUND_CODE = re.compile(r"cod(e|ing)|program|algorithm|contest|\bdsa\b|\bcp\b", re.I)
_ROUND_QUIZ = re.compile(r"quiz|mcq|trivia", re.I)
_ROUND_IDEA = re.compile(r"idea|ppt|pitch|presentation|abstract|proposal|case|deck|essay", re.I)
_ROUND_BUILD = re.compile(r"build|prototype|hack|develop|code|coding|demo|mvp|product|project", re.I)

_WF_OTHER = {
    "Robotics Engineer",
    "Mechanical Engineer",
    "Design Engineer Mechanical",
    "Investment Management",
    "Investment Research",
    "Games & Sports",
    "Online Gaming & Esports",
}
_WF_IDEA = {"Strategy & Planning", "Founder’s Office", "Founder's Office", "Product Management"}
# AI-assigned work functions that carry no topical information
_WF_NOISE = {"Quizzes & Treasure Hunt", "Others", "Conferences", "Event Management", "Games & Sports"}

_CATEGORY_KIND = {
    "hackathon": "hackathon",
    "coding challenge": "coding_contest",
    "programming": "coding_contest",
    "data science": "data_science",
    "data analytics": "data_science",
    "online quiz": "other",
    "product focused": "ideathon",
}

_NON_CASH_RE = re.compile(
    r"intern|ppi|ppo|pre[\s-]?placement|placement|job|goodies|swag|merch|credit|voucher|coupon|trophy|"
    r"trophies|medal|subscription|membership|incubat|mentorship|gift|hamper|kit|domain|interview|tickets?",
    re.I,
)
_IN_KIND_RANK_RE = re.compile(r"in[\s-]?kind|goodies|swag|voucher|credits?\b|gift", re.I)
_POOL_RANK_RE = re.compile(r"pool|total|overall|worth|in all|cumulative", re.I)
_CREDITS_RE = re.compile(r"credits?\b|vouchers?\b|coupons?\b|subscriptions?\b|memberships?\b", re.I)
_FREE_MONEY_RE = re.compile(
    r"(?P<cur>₹|\brs\.?|\binr\b|us\$|\$|\busd\b)?\s*(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<mult>k\b|lakhs?\b|lacs?\b|crores?\b|cr\b)?\s*(?P<cur2>/-|\binr\b|\busd\b|\$)?",
    re.I,
)
_FREE_MULT = {"k": 1e3, "lakh": 1e5, "lakhs": 1e5, "lac": 1e5, "lacs": 1e5, "crore": 1e7, "crores": 1e7, "cr": 1e7}


def classify_kind(
    title: str,
    rounds: list[dict[str, Any]],
    workfunctions: list[str],
    categories: list[str],
    subtype: str | None,
) -> str:
    """Best-effort mapping of an Unstop "hackathon" listing to our ``Kind``."""
    cat_kinds = {_CATEGORY_KIND.get(c.strip().lower()) for c in categories} - {None}
    for kind in ("hackathon", "data_science", "coding_contest", "ideathon", "other"):
        if kind in cat_kinds:
            return kind
    t = re.sub(r"\s+", " ", title or "")
    round_titles = " | ".join(r["title"] for r in rounds if r.get("title"))
    if _KIND_IDEATHON_EXPLICIT.search(t):
        return "ideathon"
    if _KIND_CONTEST.search(t):
        return "coding_contest"
    if _KIND_DATA.search(t) or _KIND_DATA.search(round_titles):
        return "data_science"
    if _KIND_HACK.search(t):
        return "hackathon"
    if _KIND_OTHER.search(t):
        return "other"
    if _KIND_IDEA.search(t):
        return "ideathon"
    if subtype == "hiring_challenge":
        return "coding_contest"

    # No signal in the title: look at the stages.
    stages = [r for r in rounds if not _ADMIN_ROUND_RE.search(r.get("title") or "")]
    if stages:
        if _ROUND_DATA.search(round_titles):
            return "data_science"
        if all(r["type"] in ("assessment", "quiz", "code") for r in stages):
            if any(_ROUND_CODE.search(r.get("title") or "") or r["type"] == "code" for r in stages):
                return "coding_contest"
            if any(_ROUND_QUIZ.search(r.get("title") or "") or r["type"] == "quiz" for r in stages):
                return "other"
        if all(_ROUND_IDEA.search(r.get("title") or "") for r in stages) and not any(
            _ROUND_BUILD.search(r.get("title") or "") for r in stages
        ):
            return "ideathon"
        if any(_ROUND_CODE.search(r.get("title") or "") for r in stages) and all(
            r["type"] in ("assessment", "code") for r in stages
        ):
            return "coding_contest"

    wfs = {w for w in workfunctions if w not in _WF_NOISE}
    if wfs and wfs <= _WF_OTHER | {"Embedded Systems Engineer"} and wfs & _WF_OTHER:
        return "other"
    if wfs and wfs <= _WF_IDEA:
        return "ideathon"
    if "Cyber Security" in wfs and "Ethical Hacking" in wfs and not _KIND_HACK.search(t):
        return "coding_contest"  # CTF-style security contests without "CTF" in the name
    return "hackathon"


# --- helpers -------------------------------------------------------------------


def _fmt_amount(amount: float, currency: str) -> str:
    """₹1,00,000 (Indian digit grouping) / $10,000."""
    whole = int(round(amount))
    if currency == "INR":
        s = str(whole)
        if len(s) > 3:
            head, tail = s[:-3], s[-3:]
            groups = []
            while len(head) > 2:
                groups.insert(0, head[-2:])
                head = head[:-2]
            if head:
                groups.insert(0, head)
            s = ",".join(groups) + "," + tail
        return f"₹{s}"
    symbol = _SYMBOL.get(currency)
    return f"{symbol}{whole:,}" if symbol else f"{whole:,} {currency}"


def _rounds(detail: dict[str, Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in (detail or {}).get("rounds") or []:
        if not isinstance(r, dict) or r.get("is_hidden"):
            continue
        if r.get("is_inactive") and not r.get("display_only"):
            continue  # inactive rounds are only shown when they are informational ("display only")
        det = (r.get("details") or [{}])[0] or {}
        out.append(
            {
                "title": clean_text(det.get("title")) or "",
                "type": _ROUND_TYPES.get(r.get("entity_type") or "", "other"),
                "subtype": r.get("subtype"),
                "start": to_utc(det.get("start_date")),
                "end": to_utc(det.get("end_date")),
            }
        )
    return out


def _prizes(
    prizes: list[dict[str, Any]], overall: str | None
) -> tuple[float | None, str | None, str | None, bool | None]:
    """Returns (cash total, currency, display text, non-cash prizes?).

    The display text mirrors Unstop's own "Prizes worth ₹X" badge, which sums every
    prize's ``cash`` except ``prize_type == "kind"`` ones (so it includes values such as
    an "In Kind Prize" worth ₹90,000). The cash total leaves those in-kind values out.
    """
    per_currency: dict[str, float] = {}
    pools: dict[str, float] = {}
    shown: dict[str, float] = {}
    non_cash = False
    for p in prizes:
        if not isinstance(p, dict):
            continue
        rank = clean_text(p.get("rank")) or ""
        others = clean_text(p.get("others")) or ""
        if others and _NON_CASH_RE.search(others):
            non_cash = True
        if p.get("pre_placement_internship") or p.get("pre_placement_opportunity"):
            non_cash = True
        cash = p.get("cash")
        try:
            cash = float(cash) if cash not in (None, "") else None
        except (TypeError, ValueError):
            cash = None
        if not cash or cash <= 0:
            continue
        currency = (p.get("currencyCode") or _CURRENCY.get(p.get("currency") or "") or "INR").upper()
        if p.get("prize_type") != "kind":
            shown[currency] = shown.get(currency, 0.0) + cash
        if (
            p.get("prize_type") == "kind"
            or _IN_KIND_RANK_RE.search(rank)
            # the "cash" figure is the INR value of credits, e.g. "upto 30,000$ worth of koyeb ai credits"
            or (p.get("prize_type") != "cash" and _CREDITS_RE.search(others) and not re.search(r"cash", others, re.I))
        ):
            non_cash = True
            continue
        if _POOL_RANK_RE.search(rank):
            pools[currency] = max(pools.get(currency, 0.0), cash)
        else:
            per_currency[currency] = per_currency.get(currency, 0.0) + cash
    for cur, pool in pools.items():
        per_currency[cur] = max(per_currency.get(cur, 0.0), pool)

    overall_text = clean_text(overall)
    if overall_text and _NON_CASH_RE.search(overall_text):
        non_cash = True
    if shown:
        shown_currency, shown_amount = max(shown.items(), key=lambda kv: kv[1])
        text = f"Prizes worth {_fmt_amount(shown_amount, shown_currency)}"
        if per_currency:
            currency, amount = max(per_currency.items(), key=lambda kv: kv[1])
            return amount, currency, text, non_cash
        return None, None, text, True
    # No structured cash prize: fall back to the organiser's summary, e.g. "1,30,000/-"
    # or "₹50,000 in cash prizes" (but not "$700 credits for all participants").
    if overall_text:
        amount, currency = _money_from_text(overall_text)
        text = overall_text if len(overall_text) <= 160 else overall_text[:157].rsplit(" ", 1)[0] + "…"
        return amount, currency, text, non_cash or None
    return None, None, None, (True if non_cash else (False if prizes else None))


def _money_from_text(text: str) -> tuple[float | None, str | None]:
    """First plausible cash amount in organiser free text.

    "Upto ₹5 lakh (prize and seed grant) and a chance of ₹1 crore of investment" -> 5 lakh,
    "1,30,000/-" -> 130000 INR, "1.5 Lakh Prize Pool" -> 150000 INR. Credits/vouchers,
    years and bare small numbers ("Top 10 teams") are ignored. ``parse_money`` from base
    returns the *largest* amount, which over-counts texts like the first one.
    """
    if _CREDITS_RE.search(text) and not re.search(r"cash|prize money|prize pool", text, re.I):
        return None, None
    prize_words = re.search(r"cash|prize|pool|worth|reward|win", text, re.I)
    for m in _FREE_MONEY_RE.finditer(text):
        cur = (m.group("cur") or m.group("cur2") or "").lower().rstrip(".")
        mult = (m.group("mult") or "").lower()
        try:
            num = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        if cur in ("$", "us$", "usd"):
            currency = "USD"
        elif cur in ("₹", "rs", "inr", "/-") or mult in _FREE_MULT and mult != "k":
            currency = "INR"
        elif prize_words and (mult == "k" or num >= 1000) and not (1990 <= num <= 2100 and not mult):
            currency = "INR"  # Unstop amounts without a symbol are rupees
        else:
            continue
        amount = num * _FREE_MULT.get(mult, 1)
        if amount >= 100:
            return amount, currency
    return None, None


_HTML_TAG_RE = re.compile(r"</?(b|i|u|em|strong|span|p|div|br|a|sup|sub|small|font|h[1-6])\b[^<>]*>", re.I)


def _clean_title(value: Any) -> str:
    title = clean_text(value) or "Untitled hackathon"
    title = _HTML_TAG_RE.sub(" ", title)  # stray HTML tags
    title = title.replace("<", "‹").replace(">", "›")  # literal brackets, e.g. "Hack<N>Pitch"
    return re.sub(r"\s{2,}", " ", title).strip()


def _round_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


class Unstop(Source):
    key = "unstop"
    name = "Unstop"
    homepage = "https://unstop.com/hackathons"
    region = "india"
    focus = "India's largest student hackathon and competition platform"
    description = (
        "Formerly Dare2Compete: thousands of college, corporate and government hackathons, "
        "coding contests and CTFs across India, with registration, rounds and prizes in one place."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        rows: list[dict[str, Any]] = []
        rows += await self._list(client, "open")
        try:
            rows += await self._list(client, "closed")
        except Exception as exc:  # noqa: BLE001 - still emit the open ones
            log.warning("unstop: closed-registration listing failed: %s", exc)

        unique: dict[int, dict[str, Any]] = {}
        for row in rows:
            if isinstance(row, dict) and row.get("id") is not None:
                unique.setdefault(row["id"], row)
        rows = list(unique.values())[:MAX_ITEMS]

        details = await gather_limited((self._detail(client, r["id"]) for r in rows), limit=8)
        now = datetime.now().astimezone()
        items: list[RawHackathon] = []
        for row, detail in zip(rows, details, strict=True):
            try:
                item = self._build(row, detail if isinstance(detail, dict) else None)
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("unstop: could not parse %s", row.get("id"))
                continue
            end = item.ends_at or item.submission_deadline
            if end and end < now:
                continue  # the index lags a little behind the event's end
            items.append(item)
        return items

    async def _list(self, client: httpx.AsyncClient, status: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        page = 1
        while len(out) < MAX_ITEMS:
            data = await get_json(
                client,
                LIST_URL,
                params={"opportunity": "hackathons", "oppstatus": status, "per_page": PER_PAGE, "page": page},
            )
            block = (data or {}).get("data") or {}
            batch = block.get("data") or []
            out.extend(batch)
            last = as_int(block.get("last_page")) or page
            if not batch or page >= last:
                break
            page += 1
        return out

    async def _detail(self, client: httpx.AsyncClient, opp_id: Any) -> dict[str, Any] | None:
        try:
            data = await get_json(client, DETAIL_URL.format(id=opp_id), retries=2)
        except Exception as exc:  # noqa: BLE001
            log.warning("unstop: detail failed for %s: %s", opp_id, exc)
            return None
        comp = ((data or {}).get("data") or {}).get("competition")
        return comp if isinstance(comp, dict) else None

    def _build(self, row: dict[str, Any], detail: dict[str, Any] | None) -> RawHackathon:
        d = detail or {}
        regn = row.get("regnRequirements") or d.get("regnRequirements") or {}
        title = _clean_title(row.get("title") or d.get("title"))
        rounds = _rounds(detail)

        # ---- dates -------------------------------------------------------
        reg_open = to_utc(regn.get("start_regn_dt"))
        reg_close = to_utc(regn.get("end_regn_dt"))
        ends = to_utc(row.get("end_date") or d.get("end_date"))
        stages = [r for r in rounds if r["start"] and not _ADMIN_ROUND_RE.search(r["title"])]
        starts = min((r["start"] for r in stages), default=None)
        if ends is None:
            ends = max((r["end"] for r in rounds if r["end"]), default=None)
        if starts and ends and starts > ends:
            starts = None
        submission = next(
            (
                r["end"]
                for r in rounds
                if r["end"]
                and r["subtype"] != "screening"
                and (r["type"] == "submission" or re.search(r"submi(ssion|t)", r["title"], re.I))
                and not _ADMIN_ROUND_RE.search(r["title"])
            ),
            None,
        )
        if submission and ends and submission > ends:
            submission = ends

        # ---- place -------------------------------------------------------
        region = (row.get("region") or d.get("region") or "").lower()
        mode = {"online": "online", "offline": "in_person", "hybrid": "hybrid"}.get(region)
        addr = row.get("address_with_country_logo") or d.get("address_with_country_logo") or {}
        city = clean_text(addr.get("city"))
        state = clean_text(addr.get("state"))
        country_obj = addr.get("country") if isinstance(addr.get("country"), dict) else {}
        country = clean_text(country_obj.get("name")) if country_obj else None
        address = clean_text(addr.get("address"))
        if mode == "online":
            location = "Online"
        else:
            # "CMR College of Engineering & Technology, Kandlakoya, Medchal." + ", Hyderabad, Telangana, India"
            parts = [address.rstrip(" ,.")] if address else []
            for extra_part in (city, state, country):
                if extra_part and extra_part.lower() not in ", ".join(parts).lower():
                    parts.append(extra_part)
            location = ", ".join(parts) or None
        tz = "Asia/Kolkata" if (country in (None, "India") or mode == "online") else None

        # ---- prizes ------------------------------------------------------
        prize_rows = d.get("prizes") if d.get("prizes") else row.get("prizes") or []
        amount, currency, prize_text, non_cash = _prizes(prize_rows, d.get("overall_prizes"))

        # ---- people ------------------------------------------------------
        org = row.get("organisation") or d.get("organisation") or {}
        config = row.get("opportunity_config") or d.get("display_configs") or {}
        participants = as_int(row.get("registerCount") if row.get("registerCount") is not None else d.get("registerCount"))
        if str(config.get("show_registrations_count", 1)) == "0":
            participants = None

        filters = row.get("filters") or d.get("filters") or []
        eligibility = [f["name"] for f in filters if f.get("type") == "eligible" and f.get("name")]
        categories = [f["name"] for f in filters if f.get("type") == "category" and f.get("name")]

        skills = row.get("required_skills") or d.get("skills") or []
        workfunctions = [w.get("name") for w in row.get("workfunction") or d.get("workfunction") or [] if w.get("name")]
        tags: list[str] = []
        seen: set[str] = set()
        for name in [s.get("skill_name") or s.get("skill") for s in skills] + [
            w for w in workfunctions if w not in _WF_NOISE
        ]:
            name = clean_text(name)
            if name and name.lower() not in seen:
                seen.add(name.lower())
                tags.append(name)

        fee = None
        for svc in row.get("payment_services") or d.get("payment_services") or []:
            if isinstance(svc, dict) and svc.get("amount"):
                fee = float(svc["amount"])
                break
        paid = row.get("isPaid")
        registration_fee = bool(paid) if paid is not None else (True if fee else None)

        # ---- images --------------------------------------------------------
        banner = (d.get("banner") or {}).get("image_url") if isinstance(d.get("banner"), dict) else None
        banner = banner or ((row.get("banner_mobile") or d.get("banner_mobile") or {}).get("image_url"))
        logo = org.get("logoUrl2") or org.get("logoUrl") or row.get("logoUrl2") or d.get("logoUrl2")

        url = row.get("seo_url") or d.get("seo_url") or f"{BASE}/{row.get('public_url') or ''}"
        festival = row.get("festival") or d.get("festival") or {}
        kind = classify_kind(title, rounds, workfunctions, categories, row.get("subtype") or d.get("subtype"))

        return RawHackathon(
            source=self.key,
            source_id=str(row["id"]),
            title=title,
            url=url,
            kind=kind,
            organizer=clean_text(org.get("name")),
            description=html_to_text(row.get("details") or d.get("details")),
            image_url=banner,
            logo_url=logo,
            mode=mode,
            location=location,
            city=city if mode != "online" else None,
            country=country if mode != "online" else None,
            starts_at=starts,
            ends_at=ends,
            registration_opens_at=reg_open,
            registration_deadline=reg_close,
            submission_deadline=submission,
            timezone=tz,
            prize_text=prize_text,
            prize_amount=amount,
            prize_currency=currency if amount else None,
            non_cash_prizes=non_cash,
            tags=tags[:15],
            participants=participants,
            team_size_min=as_int(regn.get("min_team_size")),
            team_size_max=as_int(regn.get("max_team_size")),
            eligibility=eligibility,
            registration_fee=registration_fee,
            extra={
                "subtype": row.get("subtype") or d.get("subtype"),
                "short_url": row.get("short_url") or d.get("short_url"),
                "festival": clean_text(festival.get("name")) if isinstance(festival, dict) else None,
                "state": state,
                "registration_fee_amount": fee,
                "registration_fee_currency": "INR" if fee else None,
                "registration_status": regn.get("reg_status"),
                "views": as_int(row.get("viewsCount")),
                "overall_prizes": clean_text(d.get("overall_prizes")),
                "rounds": [
                    {
                        "title": r["title"],
                        "type": r["type"],
                        "starts_at": _round_iso(r["start"]),
                        "ends_at": _round_iso(r["end"]),
                    }
                    for r in rounds
                ],
            },
        )
