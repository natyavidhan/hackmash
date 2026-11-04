"""Hackster.io contests: sponsored online hardware build competitions (Arduino, AMD, Nordic...).

The contests page server-renders its React props as JSON inside
``<script type="application/json" data-hypernova-key="ContestsPage"><!--{...}--></script>``:

    https://www.hackster.io/contests   -> competition[] / challenge[] (active), recent[] (judged)

Each active contest has exact start / end timestamps with their US-Pacific offset, the cover
image, sponsors and the top prize (name + value). Contest detail pages sit behind a
Cloudflare bot challenge, so the listing is all we read; the full prize pool is not on it.
The blob also carries an unrelated ``current_user`` object, which we never touch.
"""

from __future__ import annotations

import html as html_lib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from ..models import RawHackathon
from .base import Source, SourceError, abs_url, clean_text, get_text, to_utc

log = logging.getLogger(__name__)

BASE = "https://www.hackster.io"
LIST_URL = f"{BASE}/contests"
_PROPS_RE = re.compile(
    r'<script[^>]*data-hypernova-key="ContestsPage"[^>]*>\s*<!--(.*?)-->\s*</script>', re.S
)
_OVER = {"JUDGED", "JUDGING", "ENDED", "CLOSED", "CANCELED", "CANCELLED"}


def _contests_props(page: str) -> dict[str, Any]:
    m = _PROPS_RE.search(page)
    if not m:
        raise SourceError("hackster: ContestsPage props not found")
    return json.loads(m.group(1))


class Hackster(Source):
    key = "hackster"
    name = "Hackster.io"
    homepage = "https://www.hackster.io/contests"
    region = "global"
    focus = "Online hardware & embedded build contests"
    description = (
        "Avnet's hardware community runs sponsored online contests where makers build and "
        "document projects with boards from Arduino, AMD, Infineon, Nordic and others."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        props = _contests_props(await get_text(client, LIST_URL))
        rows = [r for key in ("competition", "challenge") for r in props.get(key) or [] if isinstance(r, dict)]
        now = datetime.now(timezone.utc)
        items: list[RawHackathon] = []
        seen: set[str] = set()
        for row in rows:
            rid = str(row.get("id") or "")
            if not rid or rid in seen or str(row.get("status") or "").upper() in _OVER:
                continue
            try:
                item = self._build(row)
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("hackster: could not parse %s", row.get("url"))
                continue
            if item.ends_at and item.ends_at < now:
                continue
            seen.add(rid)
            items.append(item)
        return items

    def _build(self, row: dict[str, Any]) -> RawHackathon:
        url = abs_url(BASE, row.get("url"))
        if not url:
            raise ValueError("contest without url")
        sponsors = [s for s in row.get("sponsors") or [] if isinstance(s, dict) and s.get("name")]
        sponsor_names = [clean_text(s["name"]) for s in sponsors]
        prize = row.get("prize") or {}
        prize_name = clean_text(prize.get("name") or (prize.get("category") or {}).get("name"))
        value = prize.get("cash_value")
        if prize_name and isinstance(value, (int, float)) and value > 0:
            prize_text = f"Top prize: {prize_name} (worth ${value:,.0f})"
        else:
            prize_text = f"Top prize: {prize_name}" if prize_name else None
        cover = (row.get("cover_image") or {}).get("url")
        ends_at = to_utc(row.get("end_date_in_pdt"))

        return RawHackathon(
            source=self.key,
            source_id=str(row["id"]),
            title=clean_text(row.get("name")) or "Untitled contest",
            url=url,
            kind="hackathon",
            organizer=", ".join(n for n in sponsor_names if n) or None,
            tagline=clean_text(row.get("teaser")),
            image_url=html_lib.unescape(cover) if cover else None,
            mode="online",
            location="Online",
            starts_at=to_utc(row.get("start_date_in_pdt")),
            ends_at=ends_at,
            registration_opens_at=to_utc(row.get("pre_registration_start_date")),
            submission_deadline=ends_at,
            timezone="America/Los_Angeles",  # Hackster publishes contest dates in US Pacific time
            prize_text=prize_text,
            tags=[n for n in sponsor_names if n],
            extra={
                "status": row.get("status"),
                "contest_type": row.get("contest_type"),
                "registration_open": row.get("is_registration_open"),
                "top_prize": prize_name,
                "top_prize_value_usd": value,
                "sponsor_urls": [s.get("url") for s in sponsors if s.get("url")],
                "required_user_tier": row.get("required_user_tier"),
            },
        )
