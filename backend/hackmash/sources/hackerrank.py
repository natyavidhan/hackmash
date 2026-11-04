"""HackerRank: public contests, which today means mostly the monthly Orchestrate hackathon.

List endpoint (JSON, epoch seconds):

    https://www.hackerrank.com/rest/contests/upcoming?offset=N&limit=50

Despite the name it returns every public contest ever (newest start first, ~380 rows), so
we stop paging once rows started months ago, and keep contests that are not archived and
not over. Quirks: each page has ``limit + 1`` rows and repeats the newest contest, and a
page that contains a contest tied to a hidden track 404s ("Couldn't find Track ..."), so a
failing page is split into smaller pages / single rows.

Contests with a registration page (``has_codesprint_reg_page``) have a landing page at
``https://www.hackerrank.com/<slug>`` whose ``__NEXT_DATA__`` holds the schedule, reward
tiers and registration count; we read details there (robots.txt disallows /rest/ and
/contests/ for crawlers, so the adapter makes as few /rest/ calls as possible).

HackerRank runs no public hackathon directory (``/hackathons`` is a 404); its only public
hackathon is Orchestrate ("a 24-hour hackathon to design, build, and ship an agent"), a
solo, open-to-anyone event. Everything else is a coding contest.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..models import RawHackathon
from .base import (
    Source,
    SourceError,
    as_int,
    clean_text,
    gather_limited,
    get_json,
    get_text,
    html_to_text,
    to_utc,
)

log = logging.getLogger(__name__)

BASE = "https://www.hackerrank.com"
LIST_URL = f"{BASE}/rest/contests/upcoming"
PAGE = 50
MAX_ROWS = 1500
STALE_AFTER = timedelta(days=180)  # rows are sorted by start; older starts are long over

_NEXT_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
_META_RE = re.compile(r'<meta[^>]+(?:property|name)="(og:image|description|og:title)"[^>]*content="([^"]*)"', re.I)
_PLACEHOLDER = "please provide a short description of your contest"
_HACKATHON_RE = re.compile(r"hackathon|hack[- ]?a[- ]?thon|buildathon|orchestrate", re.I)
_DATA_RE = re.compile(r"machine learning|data science|\bml\b|\bai\b challenge", re.I)
_MONEY_RE = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)")


def _landing(html: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    m = _NEXT_RE.search(html)
    if m:
        try:
            out["props"] = (json.loads(m.group(1)).get("props") or {}).get("pageProps") or {}
        except ValueError:
            out["props"] = {}
    for key, value in _META_RE.findall(html):
        out.setdefault(key.lower(), clean_text(value))
    return out


def _prizes(tiers: list[dict[str, Any]]) -> tuple[float | None, str | None, bool | None]:
    """Total cash and a display string from Orchestrate-style reward tiers."""
    total = 0.0
    parts: list[str] = []
    non_cash = False
    for tier in tiers or []:
        lo, hi = as_int(tier.get("rank_from")), as_int(tier.get("rank_to"))
        winners = (hi - lo + 1) if lo and hi and hi >= lo else 1
        cash = None
        for benefit in tier.get("benefits") or []:
            text = f"{benefit.get('title') or ''} {benefit.get('description') or ''}"
            m = _MONEY_RE.search(text)
            if m and "cash" in text.lower():
                cash = float(m.group(1).replace(",", ""))
            else:
                non_cash = True
        if cash:
            total += cash * winners
            each = " each" if winners > 1 else ""
            parts.append(f"{clean_text(tier.get('title')) or 'Prize'}: ${cash:,.0f}{each}")
    return (total or None), (" · ".join(parts) or None), (non_cash or None)


class HackerRank(Source):
    # robots.txt disallows /rest/ and /contests/, which is where the listing lives.
    # Off until HackerRank offers a permitted source; the adapter is kept for reference.
    enabled = False
    key = "hackerrank"
    name = "HackerRank"
    homepage = "https://www.hackerrank.com/contests"
    region = "global"
    focus = "Coding contests and the Orchestrate AI-agent hackathon"
    description = (
        "The developer skills platform's public contests: competitive programming rounds and "
        "Orchestrate, a monthly 24-hour solo hackathon to build and ship an AI agent."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        rows = await self._rows(client)
        now = datetime.now(timezone.utc)
        current = []
        for row in rows:
            end = to_utc(row.get("epoch_endtime")) or to_utc(row.get("get_endtimeiso"))
            start = to_utc(row.get("epoch_starttime")) or to_utc(row.get("get_starttimeiso"))
            # ("visible" is False for upcoming contests: challenges are hidden until the start)
            if row.get("archived") or row.get("ended"):
                continue
            if (end and end < now) or (not end and (not start or start < now)):
                continue
            current.append(row)

        landings = await gather_limited((self._landing(client, r) for r in current), limit=4)
        items: list[RawHackathon] = []
        for row, landing in zip(current, landings, strict=True):
            try:
                items.append(self._build(row, landing if isinstance(landing, dict) else {}))
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("hackerrank: could not parse %s", row.get("slug"))
        return items

    async def _page(self, client: httpx.AsyncClient, offset: int, limit: int) -> dict[str, Any] | None:
        try:
            return await get_json(client, LIST_URL, params={"offset": offset, "limit": limit}, retries=2)
        except SourceError as exc:
            cause = exc.__cause__
            if isinstance(cause, httpx.HTTPStatusError) and cause.response.status_code == 404:
                return None  # page contains a contest on a hidden track
            raise

    async def _rows(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        rows: dict[int, dict[str, Any]] = {}
        stale_before = datetime.now(timezone.utc) - STALE_AFTER

        async def take(offset: int, limit: int) -> tuple[bool, int | None]:
            """Fetch rows [offset, offset+limit); returns (all rows stale?, total)."""
            data = await self._page(client, offset, limit)
            if data is None:
                if limit == 1:
                    return False, None
                step = max(1, limit // 5)
                stale, total = True, None
                for sub in range(offset, offset + limit, step):
                    s, t = await take(sub, min(step, offset + limit - sub))
                    stale, total = stale and s, total or t
                return stale, total
            batch = data.get("models") or []
            for row in batch:
                if isinstance(row.get("id"), int):
                    rows.setdefault(row["id"], row)
            starts = [to_utc(r.get("epoch_starttime")) for r in batch[1:]]  # [0] repeats the newest
            stale = bool(starts) and all(s and s < stale_before for s in starts)
            return stale, as_int(data.get("total"))

        offset, total = 0, None
        while offset < MAX_ROWS and (total is None or offset < total):
            stale, page_total = await take(offset, PAGE)
            total = page_total or total
            if stale:
                break
            offset += PAGE
        return list(rows.values())

    async def _landing(self, client: httpx.AsyncClient, row: dict[str, Any]) -> dict[str, Any]:
        if not row.get("has_codesprint_reg_page") or not row.get("slug"):
            return {}
        try:
            return _landing(await get_text(client, f"{BASE}/{row['slug']}", retries=2))
        except SourceError as exc:
            log.warning("hackerrank: landing page failed for %s: %s", row.get("slug"), exc)
            return {}

    def _build(self, row: dict[str, Any], landing: dict[str, Any]) -> RawHackathon:
        slug = row["slug"]
        props = landing.get("props") or {}
        title = clean_text(row.get("name")) or slug
        meta_desc = landing.get("description")
        description = html_to_text(row.get("description_html")) or clean_text(row.get("description"))
        if description and _PLACEHOLDER in description.lower():
            description = None
        page_title = landing.get("og:title") or ""

        orchestrate = bool(props.get("rewards")) or "orchestrate" in slug.lower()
        text = " ".join(x for x in (title, page_title, meta_desc or "", description or "") if x)
        if orchestrate or _HACKATHON_RE.search(text):
            kind = "hackathon"
        elif _DATA_RE.search(title):
            kind = "data_science"
        else:
            kind = "coding_contest"

        schedule = props.get("schedule") or {}
        starts_at = to_utc(row.get("epoch_starttime")) or to_utc(props.get("startIso"))
        ends_at = to_utc(row.get("epoch_endtime")) or to_utc(schedule.get("contestEndTime"))
        prize_amount, prize_text, non_cash = _prizes((props.get("rewards") or {}).get("tiers") or [])

        url = f"{BASE}/{slug}" if landing else f"{BASE}/contests/{slug}"
        participants = as_int(props.get("registeredCount")) or as_int(row.get("signup_count"))
        domains = row.get("domain_restrictions")
        eligibility = []
        if orchestrate:
            eligibility.append("Open to everyone")  # Orchestrate FAQ: "Anyone can participate."
        if domains:
            domains = json.loads(domains) if isinstance(domains, str) else domains
            eligibility.append("Restricted to accounts at " + ", ".join(map(str, domains)))

        return RawHackathon(
            source=self.key,
            source_id=str(row["id"]),
            title=title,
            url=url,
            kind=kind,
            organizer=clean_text(row.get("organization_name")) or "HackerRank",
            tagline=meta_desc if meta_desc and _PLACEHOLDER not in meta_desc.lower() else None,
            description=description,
            image_url=landing.get("og:image") or None,
            mode="online",
            location="Online",
            starts_at=starts_at,
            ends_at=ends_at,
            submission_deadline=ends_at,
            prize_text=prize_text,
            prize_amount=prize_amount,
            prize_currency="USD" if prize_amount else None,
            non_cash_prizes=non_cash,
            participants=participants,
            # Orchestrate FAQ: "This is a solo challenge."
            team_size_min=1 if orchestrate else None,
            team_size_max=1 if orchestrate else None,
            eligibility=eligibility,
            registration_fee=False,
            extra={
                "contest_url": f"{BASE}/contests/{slug}",
                "results_date": schedule.get("resultDate"),
                "rated": row.get("rated"),
                "track": (row.get("track") or {}).get("name") if isinstance(row.get("track"), dict) else None,
            },
        )
