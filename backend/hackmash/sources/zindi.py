"""Zindi: data-science competitions and hackathons focused on Africa and the Global South.

Public JSON API used by zindi.world (zindi.africa redirects there):

    GET https://api.zindi.world/v1/competitions?status=open&page=0&per_page=50
    GET https://api.zindi.world/v1/competitions/<id>    team size, skills, rules, description

Rewards are display strings such as "$5 000 USD", "R25 000 ZAR", "10000USD",
"500 Points" (Zindi points, not cash) or "To be awarded".
"""

from __future__ import annotations

import html as html_lib
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pycountry

from ..models import RawHackathon
from .base import Source, as_int, clean_text, gather_limited, get_json, html_to_text, to_utc

log = logging.getLogger(__name__)

API = "https://api.zindi.world/v1/competitions"
SITE = "https://zindi.world"
PER_PAGE = 50
MAX_PAGES = 30

_REWARD_RE = re.compile(r"(\d[\d\s,.]*?)\s*([A-Z]{3})\b")
_WHO_RE = re.compile(r"Who can compete\s*:\s*(.+?)(?=\s+[A-Z][A-Za-z ]{2,40}?\s?:|$)")


def parse_reward(text: Any) -> tuple[float | None, str | None]:
    """'$5 000 USD' -> (5000.0, 'USD'); points / 'To be awarded' -> (None, None)."""
    if not text:
        return None, None
    m = _REWARD_RE.search(str(text))
    if not m:
        return None, None
    number, code = m.group(1).strip(), m.group(2)
    if pycountry.currencies.get(alpha_3=code) is None:
        return None, None
    if re.fullmatch(r"\d{1,3}(?:\.\d{3})+", number):  # "9.000" thousands dots
        number = number.replace(".", "")
    number = re.sub(r"[\s,]", "", number)
    try:
        amount = float(number)
    except ValueError:
        return None, None
    return (amount, code) if amount > 0 else (None, None)


def _page_text(detail: dict[str, Any], *titles: str) -> str:
    for page in detail.get("pages") or []:
        if isinstance(page, dict) and str(page.get("title") or "").strip().lower() in titles:
            return page.get("content_html") or ""
    return ""


class Zindi(Source):
    key = "zindi"
    name = "Zindi"
    homepage = "https://zindi.world/competitions"
    region = "global"
    focus = "Data-science competitions for Africa and the Global South"
    description = (
        "Africa's largest data-science competition platform: machine-learning challenges and "
        "data hackathons from companies, NGOs and governments, scored on public leaderboards."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        rows: list[dict[str, Any]] = []
        for page in range(MAX_PAGES):
            data = await get_json(client, API, params={"status": "open", "page": page, "per_page": PER_PAGE})
            batch = [r for r in data.get("data") or [] if isinstance(r, dict)]
            rows.extend(batch)
            total = as_int((data.get("meta") or {}).get("total_count")) or 0
            if not batch or len(rows) >= total:
                break

        now = datetime.now(timezone.utc)
        current = [
            r for r in rows if r.get("id") and (to_utc(r.get("end_time")) or now) >= now - timedelta(hours=1)
        ]
        details = await gather_limited((self._detail(client, r["id"]) for r in current), limit=6)
        items: list[RawHackathon] = []
        seen: set[str] = set()
        for row, detail in zip(current, details, strict=True):
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            try:
                items.append(self._build({**row, **(detail if isinstance(detail, dict) else {})}))
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("zindi: could not parse %s", row.get("id"))
        return items

    async def _detail(self, client: httpx.AsyncClient, cid: str) -> dict[str, Any] | None:
        try:
            data = await get_json(client, f"{API}/{cid}", retries=2)
        except Exception as exc:  # noqa: BLE001
            log.warning("zindi: detail failed %s: %s", cid, exc)
            return None
        return data.get("data", data) if isinstance(data, dict) else None

    def _build(self, c: dict[str, Any]) -> RawHackathon:
        cid = c["id"]
        reward = clean_text(c.get("reward"))
        amount, currency = parse_reward(reward)
        non_cash = None
        if reward and amount is None and re.search(r"points?|knowledge|swag|credits?", reward, re.I):
            non_cash = True

        org = c.get("organization")
        if isinstance(org, dict):
            org = org.get("name")
        rules = html_lib.unescape(re.sub(r"<[^>]+>", " ", _page_text(c, "rules")))
        rules = re.sub(r"\s+", " ", rules)
        eligibility = []
        if m := _WHO_RE.search(rules):
            who = m.group(1).strip().rstrip(".")
            if who and not re.fullmatch(r"open to (?:all|everyone|anyone)", who, re.I):
                eligibility.append(who)

        team_max = as_int(c.get("max_number_of_participants_per_team"))
        if c.get("allow_teams") is False:
            team_max = 1
        tags: list[str] = []
        for value in [*(c.get("skills") or []), *(c.get("industry") or [])]:
            tag = clean_text(value)
            if tag and tag.lower() not in {t.lower() for t in tags}:
                tags.append(tag)

        kind = str(c.get("kind") or "competition").lower()
        end = to_utc(c.get("end_time"))
        submissions_close = to_utc(c.get("submissions_closed_at")) or end
        return RawHackathon(
            source=self.key,
            source_id=cid,
            title=clean_text(c.get("title")) or cid,
            url=f"{SITE}/competitions/{cid}",
            kind="data_science",
            organizer=clean_text(org) if isinstance(org, str) else None,
            tagline=clean_text(c.get("subtitle")),
            description=html_to_text(_page_text(c, "description", "overview")),
            image_url=c.get("header_image") or c.get("image") or None,
            logo_url=c.get("image") or None,
            mode="online" if kind == "competition" else None,
            location="Online" if kind == "competition" else None,
            starts_at=to_utc(c.get("start_time")),
            ends_at=end,
            registration_deadline=to_utc(c.get("entries_close_at")),
            submission_deadline=submissions_close,
            prize_text=reward,
            prize_amount=amount,
            prize_currency=currency if amount else None,
            non_cash_prizes=non_cash,
            tags=tags,
            participants=as_int(c.get("participations_count")),
            team_size_min=1,
            team_size_max=team_max if team_max else None,
            eligibility=eligibility,
            beginner_friendly=c.get("is_beginner_friendly")
            if isinstance(c.get("is_beginner_friendly"), bool)
            else None,
            invite_only=bool(c.get("secret_code_required")),
            extra={
                "zindi_kind": kind,
                "access_restricted": bool(c.get("is_access_restricted")),
                "difficulty": c.get("difficulty"),
                "country_code": (c.get("helping_countrycode") or c.get("countrycode") or None),
                "reward_type": c.get("reward_type"),
                "private_leaderboard_reveal": c.get("reveal_time"),
            },
        )
