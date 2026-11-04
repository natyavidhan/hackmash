"""TechGig (Times Internet / The Economic Times): corporate AI hackathons in India.

The /hackathons page fills its "Live" and "Upcoming" tabs from a JSON endpoint:
    GET https://techgig.com/quizzes?per_page=48&contest_type=hackathon
        {"active": [...], "upcoming": [...], "past": [...]}
Each entry carries the hackathon name, the *current stage* as ``title``
("Screening", "Prototype Submission"), unix timestamps for the stage window
(``season_*``, equal to the dates shown on the hackathon page) and the
participation window, the prize pool in rupees, registrations, skills and images.

Hackathon pages (https://techgig.com/hackathon/<slug>) are server-rendered but
each event uses its own template, so mode, team size, themes and eligibility are
read from them on a best-effort basis.
"""

from __future__ import annotations

import html as html_lib
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
    get_text,
    html_to_text,
    mode_from,
    to_utc,
)

log = logging.getLogger(__name__)

LIST_URL = "https://techgig.com/quizzes"

# hero facts: "Apr 06 - Dec 30, 2026", "Online", "₹100,000+ Prize Pool", "Teams of 1–5"
_HERO_ITEM_RE = re.compile(r'<(?:span|div) class="(?:hero__meta-item|stat-chip)">(.*?)</(?:span|div)>', re.S)
_THEME_RE = re.compile(r'<h3 class="card__theme-title">(.*?)</h3>', re.S)
_SECTION_RE = r'<section[^>]+id="{id}"[^>]*>(.*?)</section>'
_TEAM_RE = re.compile(
    r"teams? of (?:up ?to |upto |maximum |max\.? )?(\d+)(?:\s*(?:-|–|to)\s*(\d+))?\s*(?:members|participants|people)?",
    re.I,
)


def _ts(value: Any) -> datetime | None:
    n = as_int(value)
    return datetime.fromtimestamp(n, tz=timezone.utc) if n and n > 0 else None


def _strip(fragment: str) -> str:
    text = re.sub(r"<(script|style|svg)[^>]*>.*?</\1>", " ", fragment, flags=re.S | re.I)
    text = html_lib.unescape(re.sub(r"<[^>]+>", " ", text))
    return re.sub(r"\s+", " ", text).strip()


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


def parse_page(page: str) -> dict[str, Any]:
    """Best-effort facts from a hackathon page (templates differ per event)."""
    out: dict[str, Any] = {}
    hero = [_strip(x) for x in _HERO_ITEM_RE.findall(page)]
    body = page[page.find("<body") :] if "<body" in page else page
    for item in hero:
        mode = mode_from(item) if len(item) < 40 else None
        if mode and "mode" not in out:
            out["mode"] = mode
        if re.search(r"[₹$]|\brs\.?\s*\d", item, re.I) and "prize_text" not in out:
            out["prize_text"] = item
    m = next((m for m in map(_TEAM_RE.search, hero) if m), None) or _TEAM_RE.search(_strip(body))
    if m:
        lo, hi = int(m.group(1)), int(m.group(2)) if m.group(2) else None
        out["team"] = (min(lo, hi), max(lo, hi)) if hi else (1, lo)
    themes = [_strip(t) for t in _THEME_RE.findall(page)]
    out["themes"] = [t.title() if t.isupper() else t for t in themes if t][:12]
    sec = re.search(_SECTION_RE.format(id="eligibility"), page, re.S)
    if sec:
        # short labels such as "Startups", "Professionals", "Students"
        labels = re.findall(r"<(?:span|li|h4|div)[^>]*>\s*([A-Z][A-Za-z &/-]{2,40})\s*</(?:span|li|h4|div)>", sec.group(1))
        out["eligibility"] = [lbl.strip() for lbl in labels if not re.search(r"round|team|theme|prototype|finale", lbl, re.I)][:8]
    return out


def classify_kind(name: str) -> str:
    if re.search(r"idea[\s-]?a?thon|\bideation\b|\bpitch", name, re.I):
        return "ideathon"
    if re.search(r"data[\s-]?a?thon|kaggle|\bml challenge", name, re.I):
        return "data_science"
    if re.search(r"\bctf\b|capture the flag|coding contest|code ?gladiators|competitive programming", name, re.I):
        return "coding_contest"
    return "hackathon"


class TechGig(Source):
    key = "techgig"
    name = "TechGig"
    homepage = "https://techgig.com/hackathons"
    region = "india"
    focus = "Corporate AI hackathons by The Economic Times"
    description = (
        "Times Internet's developer community: online AI buildathons and corporate hackathons with "
        "IBM, Intel and Indian enterprises, usually with a screening round and a grand finale."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        data = await get_json(client, LIST_URL, params={"per_page": 48, "contest_type": "hackathon"})
        rows: dict[str, dict[str, Any]] = {}
        for group in ("active", "upcoming"):
            for row in (data or {}).get(group) or []:
                key = str(row.get("entity_id") or row.get("slug") or "")
                if key and row.get("contest_type", "hackathon") == "hackathon":
                    rows.setdefault(key, {**row, "_group": group})
        pages = await gather_limited((self._page(client, r.get("link")) for r in rows.values()), limit=4)
        now = datetime.now(timezone.utc)
        items: list[RawHackathon] = []
        for row, page in zip(rows.values(), pages, strict=True):
            try:
                item = self._build(row, page if isinstance(page, dict) else {})
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("techgig: could not parse %s", row.get("slug"))
                continue
            if item.ends_at and item.ends_at < now:
                continue
            items.append(item)
        return items

    async def _page(self, client: httpx.AsyncClient, url: str | None) -> dict[str, Any]:
        if not url:
            return {}
        try:
            return parse_page(await get_text(client, url, retries=2))
        except Exception as exc:  # noqa: BLE001
            log.warning("techgig: page failed %s: %s", url, exc)
            return {}

    def _build(self, row: dict[str, Any], page: dict[str, Any]) -> RawHackathon:
        name = clean_text(row.get("name")) or clean_text(row.get("title")) or str(row.get("slug"))
        starts = _ts(row.get("season_started_on")) or to_utc(row.get("date_time"), "Asia/Kolkata")
        ends = _ts(row.get("season_ended_on")) or _ts(row.get("participation_ended_on"))
        reg_open = _ts(row.get("participation_started_on"))
        reg_close = _ts(row.get("participation_ended_on"))
        if starts and ends and starts > ends:
            starts = None

        prize = None
        try:
            prize = float(str(row.get("total_prize") or "0").replace(",", "")) or None
        except ValueError:
            prize = None
        prize_text = page.get("prize_text") or (_fmt_inr(prize) if prize else None)

        skills: list[str] = []
        for s in str(row.get("key_skills") or "").split(","):
            s = clean_text(s)
            if s and s.lower() not in {x.lower() for x in skills}:
                skills.append(s)
        for t in page.get("themes") or []:
            if t.lower() not in {x.lower() for x in skills}:
                skills.append(t)

        team = page.get("team") or (None, None)
        mode = page.get("mode")
        description = clean_text(row.get("summary"))
        long_desc = html_to_text(row.get("desc"))
        if long_desc and (not description or len(long_desc) > len(description)):
            description = f"{description}\n\n{long_desc}" if description else long_desc

        return RawHackathon(
            source=self.key,
            source_id=str(row.get("entity_id") or row.get("slug")),
            title=name,
            url=row.get("link") or f"https://techgig.com/hackathon/{row.get('slug')}",
            kind=classify_kind(name),
            tagline=clean_text(row.get("summary")),
            description=description,
            image_url=row.get("contest_big_pic_url") or row.get("medium_logo") or None,
            logo_url=row.get("company_logo_src") or row.get("small_logo") or None,
            mode=mode,
            location="Online" if mode == "online" else None,
            starts_at=starts,
            ends_at=ends,
            registration_opens_at=reg_open,
            registration_deadline=reg_close,
            timezone="Asia/Kolkata",
            prize_text=prize_text,
            prize_amount=prize,
            prize_currency="INR" if prize else None,
            tags=skills[:15],
            participants=as_int(row.get("total_registrations")),
            team_size_min=team[0],
            team_size_max=team[1],
            eligibility=page.get("eligibility") or [],
            extra={
                "slug": row.get("slug"),
                "current_stage": clean_text(row.get("title")),
                "listing": row.get("_group"),
                "registration_open": bool(row.get("is_registration_open")),
                "featured": bool(row.get("is_featured")),
            },
        )
