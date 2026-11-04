"""HackQuest: Web3 learning platform hosting ecosystem hackathons (Asia, India, LATAM).

Public GraphQL API used by hackquest.io (no auth):

    POST https://api.hackquest.io/graphql
    listHackathons(page, limit, orderBy: [{createdAt: desc}])

Each hackathon carries a structured timeline (registration open/close,
submission open/close, reward announcement) with its IANA time zone, reward
tracks with currency, host, mode and a free-text venue address. The status
enum is not documented (introspection and suggestions are off), so we page
through the newest-first list and keep events whose registration or
submission window is still open.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..models import RawHackathon
from .base import Source, as_int, clean_text, html_to_text, post_json, to_utc

log = logging.getLogger(__name__)

API = "https://api.hackquest.io/graphql"
SITE = "https://www.hackquest.io"
PAGE_SIZE = 100
MAX_PAGES = 15

QUERY = """
query HackmashHackathons($page: Int, $limit: Int, $orderBy: [HackathonOrderByWithRelationInput!]) {
  listHackathons(page: $page, limit: $limit, orderBy: $orderBy) {
    total
    data {
      id name alias status participants totalRewards createdAt
      ecosystem { type }
      info { host image intro levelTag mode teachStack description address }
      timeline {
        registrationOpen registrationClose submissionOpen submissionClose rewardTime timeZone
      }
      rewards { totalRewards currency }
    }
  }
}
"""

_MODES = {
    "ONLINE": "online",
    "HYBRID": "hybrid",
    "OFFLINE": "in_person",
    "IRL": "in_person",
    "ONSITE": "in_person",
}
_STABLE = {"USDC": "USD", "USDT": "USD"}
_SYMBOLS = {"USD": "$", "INR": "₹", "EUR": "€", "GBP": "£"}
_PLACEHOLDER_RE = re.compile(r"to be announced|\btba\b|\btbd\b|报名后告知|^global$|^online$", re.I)


class HackQuest(Source):
    key = "hackquest"
    name = "HackQuest"
    homepage = "https://www.hackquest.io/hackathons"
    region = "global"
    focus = "Web3 ecosystem hackathons and buildathons"
    description = (
        "Web3 developer education platform that hosts online and hybrid hackathons for "
        "ecosystems such as Arbitrum, Solana, Mantle and 0G, popular in Asia, India and LATAM."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        rows: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            data = await post_json(
                client,
                API,
                {
                    "query": QUERY,
                    "variables": {"page": page, "limit": PAGE_SIZE, "orderBy": [{"createdAt": "desc"}]},
                },
            )
            if data.get("errors") and not data.get("data"):
                raise RuntimeError(f"hackquest graphql error: {data['errors'][0].get('message')}")
            listing = (data.get("data") or {}).get("listHackathons") or {}
            batch = listing.get("data") or []
            rows.extend(batch)
            if not batch or len(rows) >= (as_int(listing.get("total")) or 0):
                break

        now = datetime.now(timezone.utc)
        items: list[RawHackathon] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict) or not row.get("alias") or row.get("id") in seen:
                continue
            seen.add(row.get("id"))
            if row.get("status") not in (None, "publish"):
                continue
            tl = row.get("timeline") or {}
            closes = [to_utc(tl.get("submissionClose")), to_utc(tl.get("registrationClose"))]
            closes = [c for c in closes if c]
            if not closes or max(closes) < now - timedelta(hours=1):
                continue
            try:
                items.append(self._build(row))
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("hackquest: could not parse %s", row.get("alias"))
        return items

    def _build(self, row: dict[str, Any]) -> RawHackathon:
        info = row.get("info") or {}
        tl = row.get("timeline") or {}
        mode = _MODES.get(str(info.get("mode") or "").upper())

        address = clean_text(info.get("address"))
        if address and _PLACEHOLDER_RE.search(address):
            address = None
        location = "Online" if mode == "online" else address

        sums: dict[str, float] = {}
        for reward in row.get("rewards") or []:
            if not isinstance(reward, dict):
                continue
            amount = reward.get("totalRewards")
            cur = str(reward.get("currency") or "").strip()
            if isinstance(amount, (int, float)) and amount > 0 and cur:
                sums[cur] = sums.get(cur, 0.0) + float(amount)
        prize_text = (
            " + ".join(
                f"{_SYMBOLS[c]}{a:,.0f}" if c in _SYMBOLS else f"{a:,.0f} {c}" for c, a in sums.items()
            )
            or None
        )
        iso: dict[str, float] = {}
        for cur, amount in sums.items():
            code = _STABLE.get(cur.upper(), cur.upper())
            iso[code] = iso.get(code, 0.0) + amount
        prize_amount = prize_currency = None
        if len(iso) == 1:
            code, total = next(iter(iso.items()))
            if code in ("USD", "INR", "EUR", "GBP", "CNY", "MYR", "SGD", "JPY", "BRL", "HKD", "AUD", "CAD"):
                prize_amount, prize_currency = total, code

        tags: list[str] = []
        for value in [
            *((e or {}).get("type") for e in row.get("ecosystem") or []),
            *(info.get("teachStack") or []),
        ]:
            tag = clean_text(value)
            if tag and tag.lower() not in {t.lower() for t in tags}:
                tags.append(tag)

        level = str(info.get("levelTag") or "").lower()
        reg_close = to_utc(tl.get("registrationClose"))
        sub_open, sub_close = to_utc(tl.get("submissionOpen")), to_utc(tl.get("submissionClose"))
        return RawHackathon(
            source=self.key,
            source_id=str(row.get("id") or row["alias"]),
            title=clean_text(row.get("name")) or row["alias"],
            url=f"{SITE}/hackathons/{row['alias']}",
            organizer=clean_text(info.get("host")),
            tagline=clean_text(info.get("intro")),
            description=html_to_text(info.get("description")),
            image_url=info.get("image") or None,
            mode=mode,
            location=location,
            starts_at=sub_open,
            ends_at=sub_close,
            registration_opens_at=to_utc(tl.get("registrationOpen")),
            registration_deadline=reg_close,
            submission_deadline=sub_close,
            timezone=clean_text(tl.get("timeZone")),
            prize_text=prize_text,
            prize_amount=prize_amount,
            prize_currency=prize_currency,
            tags=tags,
            participants=as_int(row.get("participants")),
            beginner_friendly=True if level == "newbie" else None,
            extra={
                "level": level or None,
                "results_at": tl.get("rewardTime"),
                "venue": address,
            },
        )
