"""Encode Club: Web3 and AI hackathons, bootcamps and accelerators (London based, mostly online).

encodeclub.com is a client-side React app backed by Supabase. Programme data is
read anonymously from the public PostgREST endpoint with the site's public
``anon`` key (shipped in the site's JS bundle; row-level security limits it to
published, public data). If the key ever rotates we re-discover it from the
bundle.

    GET https://bwrubpasqybdchurwjhs.supabase.co/rest/v1/Encode%20Programmes
        ?type=eq.Hackathon&published=eq.true&end_date=gte.<now>
    GET .../programme_challenges?programme_id=in.(...)      prize tracks + amounts
    GET .../programme_partner_links?programme_id=in.(...)   partner names
    GET .../venue?id=in.(...)                               in-person venues

Bootcamps, "Educate" courses, accelerators and grants are skipped.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..models import RawHackathon
from .base import Source, SourceError, as_int, clean_text, get_text, html_to_text, request, to_utc

log = logging.getLogger(__name__)

SITE = "https://www.encodeclub.com"
SUPABASE = "https://bwrubpasqybdchurwjhs.supabase.co"
REST = f"{SUPABASE}/rest/v1"
# Public anon key from encodeclub.com's own JS bundle (role "anon", read-only).
ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJ3cnVicGFzcXliZGNodXJ3amhzIiwicm9sZSI6ImFub24iLCJpYXQiOj"
    "E3NDA5Mzg0MjksImV4cCI6MjA1NjUxNDQyOX0."
    "5E5e62NEjISDKFj8zP15mj-Ttg3FXxYQtGqNu1j_KmU"
)

PROGRAMME_FIELDS = (
    'id,slug,"programme name",type,location,"start date",end_date,registration_deadline,timezone,'
    "image,image_hero,tagline,about_content,about_features,total_registrations,is_team_based,"
    "checkpoints,difficulty,duration,venue_id,featured,registration_approval,allow_waitlist"
)
_JWT_RE = re.compile(r"eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9\.[\w-]+\.[\w-]+")
_TEAM_RE = re.compile(r"teams?\s+of\s+(?:up\s+to|at\s+most|max(?:imum)?(?:\s+of)?)\s+(\d+|[a-z]+)", re.I)
_NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8}
_MODES = {"online": "online", "in-person": "in_person", "in person": "in_person", "hybrid": "hybrid"}
_SYMBOL_CURRENCY = [("€", "EUR"), ("£", "GBP"), ("$", "USD")]

_key_cache: str | None = None


def _jwt_role(token: str) -> str | None:
    try:
        payload = token.split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return None
    return data.get("role") if data.get("ref") == SUPABASE.split("//")[1].split(".")[0] else None


class EncodeClub(Source):
    key = "encode"
    name = "Encode Club"
    homepage = "https://www.encodeclub.com/programmes"
    region = "global"
    focus = "Web3 and AI hackathons with ecosystem partners"
    description = (
        "London-based community running mostly online multi-week hackathons with blockchain "
        "and AI partners such as Solana, Circle and Concordium, with workshops and prize tracks."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        since = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        programmes = await self._get(
            client,
            "Encode%20Programmes",
            {
                "select": PROGRAMME_FIELDS,
                "published": "eq.true",
                "type": "eq.Hackathon",
                "end_date": f"gte.{since}",
                "order": "end_date.asc",
                "limit": "500",
            },
        )
        programmes = [p for p in programmes if isinstance(p, dict) and p.get("slug")]
        if not programmes:
            return []
        ids = ",".join(str(p["id"]) for p in programmes)
        challenges = await self._get_optional(
            client,
            "programme_challenges",
            {"select": "programme_id,title,prizes,general", "programme_id": f"in.({ids})"},
        )
        partners = await self._get_optional(
            client,
            "programme_partner_links",
            {
                "select": "programme_id,partnership_type,sort_order,programme_partners(name)",
                "programme_id": f"in.({ids})",
                "order": "sort_order.asc.nullslast",
            },
        )
        venue_ids = ",".join(str(p["venue_id"]) for p in programmes if p.get("venue_id"))
        venues = (
            await self._get_optional(
                client, "venue", {"select": "id,name,address_text", "id": f"in.({venue_ids})"}
            )
            if venue_ids
            else []
        )
        venue_by_id = {v.get("id"): v for v in venues if isinstance(v, dict)}

        items: list[RawHackathon] = []
        for prog in programmes:
            pid = prog.get("id")
            try:
                items.append(
                    self._build(
                        prog,
                        [c for c in challenges if c.get("programme_id") == pid],
                        [p for p in partners if p.get("programme_id") == pid],
                        venue_by_id.get(prog.get("venue_id")),
                    )
                )
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("encode: could not parse programme %s", prog.get("slug"))
        return items

    # -- Supabase access ----------------------------------------------------

    async def _get(self, client: httpx.AsyncClient, table: str, params: dict[str, str]) -> list[Any]:
        global _key_cache
        key = _key_cache or ANON_KEY
        try:
            resp = await request(client, "GET", f"{REST}/{table}", params=params, headers=self._headers(key))
        except SourceError as exc:
            if "HTTP 401" not in str(exc) and "HTTP 403" not in str(exc):
                raise
            fresh = await self._discover_key(client)
            if not fresh or fresh == key:
                raise
            _key_cache = fresh
            resp = await request(
                client, "GET", f"{REST}/{table}", params=params, headers=self._headers(fresh)
            )
        data = resp.json()
        return data if isinstance(data, list) else []

    async def _get_optional(self, client: httpx.AsyncClient, table: str, params: dict[str, str]) -> list[Any]:
        try:
            return [r for r in await self._get(client, table, params) if isinstance(r, dict)]
        except Exception as exc:  # noqa: BLE001 - enrichment only
            log.warning("encode: %s unavailable: %s", table, exc)
            return []

    @staticmethod
    def _headers(key: str) -> dict[str, str]:
        return {"apikey": key, "Authorization": f"Bearer {key}", "Accept": "application/json"}

    async def _discover_key(self, client: httpx.AsyncClient) -> str | None:
        """Find the current anon key in the site's JS bundle (only after a 401)."""
        try:
            home = await get_text(client, f"{SITE}/", retries=2)
            for src in re.findall(r'src="(/assets/index-[^"]+\.js)"', home):
                for token in _JWT_RE.findall(await get_text(client, f"{SITE}{src}", retries=2)):
                    if _jwt_role(token) == "anon":
                        return token
        except Exception as exc:  # noqa: BLE001
            log.warning("encode: could not refresh anon key: %s", exc)
        return None

    # -- mapping -------------------------------------------------------------

    def _build(
        self,
        prog: dict[str, Any],
        challenges: list[dict[str, Any]],
        partners: list[dict[str, Any]],
        venue: dict[str, Any] | None,
    ) -> RawHackathon:
        slug = prog["slug"]
        mode = _MODES.get(str(prog.get("location") or "").strip().lower())
        if mode == "online":
            location = "Online"
        elif venue:
            name, address = clean_text(venue.get("name")), clean_text(venue.get("address_text"))
            if name and address and name.lower() in address.lower():
                name = None
            location = ", ".join(x for x in (name, address) if x) or None
        else:
            location = None

        checkpoints = [c for c in prog.get("checkpoints") or [] if isinstance(c, dict)]
        submission = max(
            (
                to_utc(c.get("deadline"))
                for c in checkpoints
                if c.get("submission_required") and c.get("deadline")
            ),
            default=None,
        )

        prizes = [
            p
            for c in challenges
            for p in (c.get("prizes") if isinstance(c.get("prizes"), list) else [])
            if isinstance(p, dict)
        ]
        cash = sum(float(p.get("amount") or 0) for p in prizes if (p.get("amount") or 0) > 0)
        texts = " ".join(str(p.get("short_description") or "") for p in prizes if (p.get("amount") or 0) > 0)
        currency = next((code for sym, code in _SYMBOL_CURRENCY if sym in texts), None)
        if currency is None and re.search(r"\bUSDC?\b|\bUSDT\b|\bdollars?\b", texts, re.I):
            currency = "USD"
        prize_text = None
        if cash > 0:
            symbol = {"USD": "$", "EUR": "€", "GBP": "£"}.get(currency or "")
            prize_text = f"{symbol}{cash:,.0f} in prizes" if symbol else f"{cash:,.0f} in prizes"
        non_cash = any((p.get("amount") or 0) <= 0 for p in prizes) or None

        partner_names: list[str] = []
        for link in partners:
            name = clean_text((link.get("programme_partners") or {}).get("name"))
            if name and name.lower() != "encode club" and name not in partner_names:
                partner_names.append(name)

        features = [clean_text(f) for f in prog.get("about_features") or [] if isinstance(f, str)]
        team_max = None
        for feature in features:
            if feature and (m := _TEAM_RE.search(feature)):
                word = m.group(1).lower()
                team_max = int(word) if word.isdigit() else _NUMBER_WORDS.get(word)
                break
        if prog.get("is_team_based") is False:
            team_max = 1

        difficulty = clean_text(prog.get("difficulty"))
        return RawHackathon(
            source=self.key,
            source_id=str(prog.get("id") or slug),
            title=clean_text(prog.get("programme name")) or slug,
            url=f"{SITE}/programmes/{slug}",
            organizer="Encode Club",
            tagline=clean_text(prog.get("tagline")),
            description=html_to_text(prog.get("about_content")),
            image_url=prog.get("image_hero") or prog.get("image") or None,
            logo_url=prog.get("image") or None,
            mode=mode,
            location=location or None,
            starts_at=to_utc(prog.get("start date")),
            ends_at=to_utc(prog.get("end_date")),
            registration_deadline=to_utc(prog.get("registration_deadline")),
            submission_deadline=submission,
            timezone=clean_text(prog.get("timezone")),
            prize_text=prize_text,
            prize_amount=cash if cash > 0 and currency else None,
            prize_currency=currency if cash > 0 and currency else None,
            non_cash_prizes=non_cash,
            tags=partner_names,
            participants=as_int(prog.get("total_registrations")),
            team_size_max=team_max,
            beginner_friendly=True if difficulty and difficulty.lower() == "beginner" else None,
            extra={
                "difficulty": difficulty,
                "duration": clean_text(prog.get("duration")),
                "features": [f for f in features if f],
                "prize_tracks": [clean_text(c.get("title")) for c in challenges if c.get("title")],
                "featured": bool(prog.get("featured")),
                "registration_approval": prog.get("registration_approval"),
            },
        )
