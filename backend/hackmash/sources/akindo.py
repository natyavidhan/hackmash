"""AKINDO: Web3 "WaveHack" builder programmes and hackathons (Japan / global).

Public JSON API used by app.akindo.io (no auth):

    GET https://api.akindo.io/public/wave-hacks?page=N        10 per page
    GET https://api.akindo.io/public/wave-hacks/<id>          markdown description, techs
    GET https://api.akindo.io/public/hackathons?page=N        classic one-off hackathons

A WaveHack is a recurring grant programme split into "waves" (a build window
followed by judging). We list a WaveHack while its active wave still accepts
submissions; dates are those of the current wave and the prize is the grant
pool of that wave, which is what the site shows ("5,000 USDT").
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..models import RawHackathon
from .base import Source, as_int, clean_text, gather_limited, get_json, html_to_text, to_utc

log = logging.getLogger(__name__)

API = "https://api.akindo.io/public"
SITE = "https://app.akindo.io"
MAX_PAGES = 50

_STABLE = {"USDC": "USD", "USDT": "USD", "USDG": "USD", "DAI": "USD", "PYUSD": "USD", "JPYC": "JPY"}


def md_to_text(value: Any, max_len: int = 1500) -> str | None:
    if not value:
        return None
    text = str(value)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*>\s?(?:#{1,6}\s*)?", "", text)
    text = re.sub(r"(?m)^\s*(?:[-*+]|\d+\.)\s+", "• ", text)
    text = re.sub(r"(?m)^\s*(?:-{3,}|\*{3,}|_{3,}|\|?[\s:|-]+\|[\s:|-]*)\s*$", "", text)
    text = text.replace("|", " ")
    text = re.sub(r"(\*\*|__|~~|`)", "", text)
    return html_to_text(text.replace("\n", "<br>"), max_len=max_len)


def _amount(value: Any) -> float | None:
    try:
        amount = float(str(value))
    except (TypeError, ValueError):
        return None
    return amount if amount > 0 else None


def _money(amount: float | None, token: str) -> tuple[str | None, float | None, str | None]:
    """(display text, amount, ISO currency) for a token-denominated amount."""
    if not amount or not token:
        return None, None, None
    shown = f"{amount:,.0f}" if amount == int(amount) else f"{amount:,.2f}"
    currency = _STABLE.get(token.upper()) or (
        token.upper() if token.upper() in ("USD", "JPY", "EUR") else None
    )
    return f"{shown} {token}", (amount if currency else None), currency


def _tags(*groups: Any) -> list[str]:
    out: list[str] = []
    for group in groups:
        for entry in group or []:
            if not isinstance(entry, dict):
                continue
            name = clean_text((entry.get("tag") or entry.get("tech") or {}).get("name"))
            if name and name.lower() not in {t.lower() for t in out}:
                out.append(name)
    return out


class Akindo(Source):
    key = "akindo"
    name = "AKINDO"
    homepage = "https://app.akindo.io/wave-hacks"
    region = "global"
    focus = "Web3 WaveHack grant sprints and hackathons"
    description = (
        "Japanese Web3 builder platform whose WaveHacks pay grants every few weeks for shipped "
        "progress, run with ecosystems like Midnight, Mezo and Arbitrum."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        wave_hacks = await self._list(client, "wave-hacks")
        hackathons = await self._list(client, "hackathons")
        now = datetime.now(timezone.utc)

        live_waves = []
        for wh in wave_hacks:
            wave = wh.get("activeWave") or {}
            deadline = to_utc(wave.get("submissionDeadline"))
            if wh.get("isPublic") is False or not wave or deadline is None or deadline < now:
                continue
            live_waves.append(wh)
        details = await gather_limited((self._detail(client, wh["id"]) for wh in live_waves), limit=4)

        items: list[RawHackathon] = []
        for wh, detail in zip(live_waves, details, strict=True):
            try:
                items.append(self._build_wave_hack({**wh, **(detail if isinstance(detail, dict) else {})}))
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("akindo: could not parse wave hack %s", wh.get("id"))
        for hk in hackathons:
            end = to_utc(hk.get("expiredAt"))
            if hk.get("isPublic") is False or end is None or end < now - timedelta(hours=1):
                continue
            try:
                items.append(self._build_hackathon(hk))
            except Exception:  # noqa: BLE001
                log.exception("akindo: could not parse hackathon %s", hk.get("id"))
        return items

    async def _list(self, client: httpx.AsyncClient, kind: str) -> list[dict[str, Any]]:
        first = await get_json(client, f"{API}/{kind}", params={"page": 1})
        rows = list(first.get("items") or [])
        pages = min(as_int((first.get("meta") or {}).get("totalPages")) or 1, MAX_PAGES)
        rest = await gather_limited(
            (get_json(client, f"{API}/{kind}", params={"page": p}, retries=2) for p in range(2, pages + 1)),
            limit=4,
        )
        for page in rest:
            if isinstance(page, dict):
                rows.extend(page.get("items") or [])
            else:
                log.warning("akindo: a %s page failed: %s", kind, page)
        seen: set[str] = set()
        unique = []
        for row in rows:
            if isinstance(row, dict) and row.get("id") and row["id"] not in seen:
                seen.add(row["id"])
                unique.append(row)
        return unique

    async def _detail(self, client: httpx.AsyncClient, wid: str) -> dict[str, Any] | None:
        try:
            return await get_json(client, f"{API}/wave-hacks/{wid}", retries=2)
        except Exception as exc:  # noqa: BLE001
            log.warning("akindo: wave hack detail failed %s: %s", wid, exc)
            return None

    def _build_wave_hack(self, wh: dict[str, Any]) -> RawHackathon:
        wave = wh.get("activeWave") or {}
        community = wh.get("community") or {}
        token = str((wh.get("grantDenomination") or {}).get("name") or "")
        text, amount, currency = _money(_amount(wave.get("grantAmount")), token)
        number = as_int(wave.get("waveCount"))
        category = clean_text((wh.get("hackathonCategory") or {}).get("name"))
        tags = _tags(wh.get("waveHackTags"), wh.get("waveHackTechs"))
        if category and category.lower() not in ("unlimited", "other"):
            tags.append(category)
        return RawHackathon(
            source=self.key,
            source_id=f"wavehack-{wh['id']}",
            title=clean_text(wh.get("title")) or wh["id"],
            url=f"{SITE}/wave-hacks/{wh['id']}",
            organizer=clean_text(community.get("name")),
            tagline=clean_text(wh.get("tagline")),
            description=md_to_text(wh.get("description")),
            logo_url=((community.get("iconAsset") or {}).get("url")) or None,
            mode="online",
            location="Online",
            starts_at=to_utc(wave.get("startedAt") or wave.get("openedAt")),
            ends_at=to_utc(wave.get("submissionDeadline")),
            submission_deadline=to_utc(wave.get("submissionDeadline")),
            prize_text=f"{text} (wave {number} grant pool)" if text and number else text,
            prize_amount=amount,
            prize_currency=currency,
            tags=tags,
            participants=as_int(wh.get("builderCount")),
            extra={
                "format": "wavehack",
                "wave_number": number,
                "judging_ends_at": wave.get("judgementDeadline"),
                "next_wave_enabled": wave.get("nextWaveEnabled"),
                "building_days": as_int(wh.get("buildingDays")),
                "judging_days": as_int(wh.get("judgingDays")),
                "grant_distribution": wave.get("grantDistributionMode"),
                "program_started_at": wh.get("firstWaveStartedAt"),
                "grant_chain": (wh.get("grantEvmChain") or {}).get("chainName"),
            },
        )

    def _build_hackathon(self, hk: dict[str, Any]) -> RawHackathon:
        community = hk.get("community") or {}
        token = str((hk.get("rewardDenomination") or {}).get("name") or "")
        text, amount, currency = _money(_amount(hk.get("rewardAmount")), token)
        source_url = hk.get("sourceUrl") or None
        return RawHackathon(
            source=self.key,
            source_id=f"hackathon-{hk['id']}",
            title=clean_text(hk.get("title")) or hk["id"],
            url=f"{SITE}/hackathons/{hk['id']}",
            organizer=clean_text(community.get("name")),
            description=md_to_text(hk.get("description")),
            logo_url=((community.get("iconAsset") or {}).get("url")) or None,
            mode="online",
            location="Online",
            starts_at=to_utc(hk.get("openedAt")),
            ends_at=to_utc(hk.get("expiredAt")),
            submission_deadline=to_utc(hk.get("expiredAt")),
            prize_text=text,
            prize_amount=amount,
            prize_currency=currency,
            tags=_tags(hk.get("hackathonTags")),
            participants=as_int(hk.get("builderCount")),
            extra={
                "format": "hackathon",
                "winners_announced_at": hk.get("winnersAnnouncedAt"),
                "curated": hk.get("isCurated"),
                "source_url": source_url,
            },
        )
