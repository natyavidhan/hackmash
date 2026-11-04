"""Kaggle competitions (machine learning / data science, plus a few judged "hackathons").

The official API (``/api/v1/competitions/list``) needs a username + key, but the website's
own JSON endpoint works anonymously once the page has handed out an XSRF cookie:

    GET  https://www.kaggle.com/competitions                       -> XSRF-TOKEN cookie
    POST https://www.kaggle.com/api/i/competitions.CompetitionService/ListCompetitions
         {"selector": {"listOption": "LIST_OPTION_ACTIVE", "hostSegmentIdFilter": N, ...},
          "pageToken": "", "pageSize": 100}                         header x-xsrf-token

``hostSegmentIdFilter`` 0 returns every active Featured / Research / Playground / Getting
Started competition; 10 returns the ~800 user-hosted Community competitions, most of them
class assignments. We keep:

* everything except "Getting Started" (perpetual tutorials such as Titanic, deadline 2030);
* Community competitions only when they offer a real cash prize (>= 100), are open to
  everyone (no limited participation group / email allow-list) and end within ~13 months.

All Kaggle deadlines are 11:59 PM UTC. Image URLs in the payload are signed and expire
within hours, so we link the stable ``/competitions/<id>/images/...`` redirects instead.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..models import RawHackathon
from .base import Source, SourceError, clean_text, post_json, request, to_utc

log = logging.getLogger(__name__)

BASE = "https://www.kaggle.com"
BOOT_URL = f"{BASE}/competitions"
LIST_URL = f"{BASE}/api/i/competitions.CompetitionService/ListCompetitions"
PAGE_SIZE = 100
MAX_PAGES = 15  # cap ~1500 rows per segment

SEGMENT_ALL = 0
SEGMENT_COMMUNITY = 10
SEGMENTS = {
    1: "Featured",
    2: "Research",
    3: "Recruitment",
    5: "Getting Started",
    6: "Masters",
    8: "Playground",
    10: "Community",
}
GETTING_STARTED = 5

NON_CURRENCY_REWARDS = {"SWAG", "KUDOS", "KNOWLEDGE", "NON_MONETARY", "POINTS", "JOBS", "MEDALS"}
_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "INR": "₹", "JPY": "¥"}
_HACKATHON_RE = re.compile(r"hackathon|hack[- ]?a[- ]?thon|buildathon", re.I)


def _selector(segment: int) -> dict[str, Any]:
    return {
        "competitionIds": [],
        "listOption": "LIST_OPTION_ACTIVE",
        "sortOption": "SORT_OPTION_NEWEST",
        "hostSegmentIdFilter": segment,
        "searchQuery": "",
        "prestigeFilter": "PRESTIGE_FILTER_UNSPECIFIED",
        "participationFilter": "PARTICIPATION_FILTER_UNSPECIFIED",
        "tagIds": [],
        "requireSimulations": False,
    }


def _xsrf_token(client: httpx.AsyncClient) -> str | None:
    for cookie in client.cookies.jar:
        if cookie.name == "XSRF-TOKEN" and "kaggle.com" in (cookie.domain or ""):
            return cookie.value
    return None


def _money(amount: float, currency: str) -> str:
    symbol = _SYMBOLS.get(currency)
    return f"{symbol}{amount:,.0f}" if symbol else f"{amount:,.0f} {currency}"


class Kaggle(Source):
    key = "kaggle"
    name = "Kaggle"
    homepage = "https://www.kaggle.com/competitions"
    region = "global"
    focus = "Machine learning and data science competitions"
    description = (
        "Google's data science platform: leaderboard competitions in ML, AI agents, forecasting "
        "and analytics from companies and research labs, with prizes up to six figures."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        await request(client, "GET", BOOT_URL)
        token = _xsrf_token(client)
        headers = {"x-xsrf-token": token} if token else {}

        rows: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for segment in (SEGMENT_ALL, SEGMENT_COMMUNITY):
            try:
                rows.extend(await self._list(client, segment, headers))
            except SourceError:
                if segment == SEGMENT_ALL:
                    raise
                log.warning("kaggle: community competitions unavailable", exc_info=True)

        now = datetime.now(timezone.utc)
        items: list[RawHackathon] = []
        seen: set[str] = set()
        for row, images in rows:
            rid = str(row.get("id") or "")
            if not rid or rid in seen:
                continue
            seen.add(rid)
            try:
                if not self._wanted(row, now):
                    continue
                items.append(self._build(row, images))
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("kaggle: could not parse %s", row.get("competitionName"))
        return items

    async def _list(
        self, client: httpx.AsyncClient, segment: int, headers: dict[str, str]
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        out: list[tuple[dict[str, Any], dict[str, Any]]] = []
        token = ""
        for _ in range(MAX_PAGES):
            data = await post_json(
                client,
                LIST_URL,
                {"selector": _selector(segment), "pageToken": token, "pageSize": PAGE_SIZE},
                headers=headers,
            )
            images = {
                "thumbs": data.get("thumbnailImageUrls") or {},
                "headers": data.get("headerImageUrls") or {},
            }
            out.extend((row, images) for row in data.get("competitions") or [])
            token = data.get("nextPageToken") or ""
            if not token or not data.get("competitions"):
                break
        return out

    @staticmethod
    def _wanted(row: dict[str, Any], now: datetime) -> bool:
        deadline = to_utc(row.get("deadline"))
        if deadline is None or deadline < now or row.get("launched") is False:
            return False
        segment = row.get("competitionHostSegmentId")
        if segment == GETTING_STARTED:
            return False  # perpetual tutorial competitions (Titanic, House Prices, ...)
        if segment == SEGMENT_COMMUNITY:
            reward = row.get("reward") or {}
            rid = str(reward.get("id") or "").upper()
            cash = rid not in NON_CURRENCY_REWARDS and len(rid) == 3 and (reward.get("quantity") or 0) >= 100
            restricted = row.get("limitedParticipationGroupId") or row.get("restrictLinkToEmailList")
            start = to_utc(row.get("dateEnabled"))
            # year-long community "competitions" are course assignments, not challenges
            long_running = start is not None and deadline - start > timedelta(days=300)
            return bool(cash) and not restricted and not long_running and deadline < now + timedelta(days=400)
        return True

    def _build(self, row: dict[str, Any], images: dict[str, Any]) -> RawHackathon:
        cid = str(row["id"])
        slug = row.get("competitionName") or cid
        title = clean_text(row.get("title")) or slug
        tagline = clean_text(row.get("briefDescription"))
        org = row.get("organization") or {}
        organizer = clean_text(org.get("name")) or clean_text(row.get("hostName"))

        reward = row.get("reward") or {}
        reward_id = str(reward.get("id") or "").upper()
        quantity = reward.get("quantity")
        prize_amount = prize_currency = prize_text = None
        non_cash = None
        if reward_id and reward_id not in NON_CURRENCY_REWARDS and len(reward_id) == 3 and quantity:
            prize_amount, prize_currency = float(quantity), reward_id
            prize_text = _money(prize_amount, prize_currency)
        elif reward_id == "SWAG":
            prize_text, non_cash = "Swag", True
        elif reward_id == "NON_MONETARY":
            prize_text, non_cash = "Non-monetary prizes", True
        elif reward_id in ("KNOWLEDGE", "KUDOS"):
            non_cash = False

        tags: list[str] = []
        beginner = None
        for cat in row.get("categories") or []:
            path = cat.get("fullPath") or ""
            label = clean_text(cat.get("displayName") or cat.get("name"))
            if not path or not label:
                continue  # evaluation metrics have no category path
            if path.startswith("audience"):
                if label.lower() == "beginner":
                    beginner = True
                continue
            if label not in tags:
                tags.append(label)

        deadline = to_utc(row.get("deadline"))
        entry_deadline = to_utc(row.get("prohibitNewEntrantsExplicitDeadline"))
        if entry_deadline and deadline and entry_deadline > deadline:
            entry_deadline = deadline
        judged = bool(row.get("hackathon"))
        kind = "hackathon" if _HACKATHON_RE.search(title) else "data_science"
        max_team = row.get("maxTeamSize")

        logo = f"{BASE}/competitions/{cid}/images/thumbnail" if cid in images.get("thumbs", {}) else None
        logo = logo or org.get("thumbnailImageUrl") or None
        has_cover = row.get("hasCoverImageUrl") or cid in images.get("headers", {})
        image = f"{BASE}/competitions/{cid}/images/header" if has_cover else None

        return RawHackathon(
            source=self.key,
            source_id=cid,
            title=title,
            url=f"{BASE}/competitions/{slug}",
            kind=kind,
            organizer=organizer,
            tagline=tagline,
            image_url=image,
            logo_url=logo,
            mode="online",
            location="Online",
            starts_at=to_utc(row.get("dateEnabled")),
            ends_at=deadline,
            registration_deadline=entry_deadline,
            submission_deadline=deadline,
            timezone="UTC",
            prize_text=prize_text,
            prize_amount=prize_amount,
            prize_currency=prize_currency,
            non_cash_prizes=non_cash,
            tags=tags,
            participants=row.get("totalJoinedUsers"),
            team_size_min=1 if max_team else None,
            team_size_max=max_team if isinstance(max_team, int) and max_team > 0 else None,
            registration_fee=False,
            beginner_friendly=beginner,
            extra={
                "segment": SEGMENTS.get(row.get("competitionHostSegmentId")),
                "judged_writeups": judged,
                "simulation": bool(row.get("simulation")),
                "teams": row.get("totalTeams"),
                "competitors": row.get("totalCompetitors"),
                "submissions": row.get("totalSubmissions"),
                "team_merger_deadline": row.get("teamMergerExplicitDeadline"),
                "prize_note": clean_text(reward.get("clarification")),
                "num_prizes": row.get("numPrizes"),
                "metric": (row.get("evaluationAlgorithm") or {}).get("name"),
                "medals": row.get("medalsAllowed"),
                "identity_verification_required": bool(row.get("requiresIdentityVerification")),
            },
        )
