"""Devfolio: the home of Indian college hackathons (ETHIndia, HackOdisha, Innerve...).

Devfolio's web app reads its public Hasura GraphQL endpoint anonymously:
    POST https://api.devfolio.co/v1/graphql
One query returns every public hackathon that has not ended yet, with exact
UTC timestamps, registration window, team size, themes and the prize list
(amount + currency per prize).

Why not the REST search API (``POST /api/search/hackathons``)? Its ``type``
filter only knows ``application_open``, ``upcoming`` (applications open soon)
and ``past``, so hackathons whose applications have closed but that have not
happened yet (or are running right now) fall through the gaps; its index also
misses some listings that GraphQL returns.

Applying through Devfolio is always free (each microsite's FAQ says
"Registration costs? Nada."); ``settings.paid`` is not a participant fee.

Prize amounts are stored per prize, mostly converted to USD by the organiser
(e.g. "Winner - ₹1,25,000" stored as 1291 USD). The microsite's "Prize Pool"
figure is the plain sum of the non-hidden prizes (``quantity`` is ignored),
which is what ``/api/hackathons/<slug>/prizesAggregate`` also returns.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from ..models import RawHackathon
from .base import Source, as_int, clean_text, post_json, to_utc

log = logging.getLogger(__name__)

GRAPHQL_URL = "https://api.devfolio.co/v1/graphql"
PAGE = 100
MAX_ITEMS = 1500

QUERY = """
query HackmashCurrentHackathons($offset: Int!, $limit: Int!) {
  hackathons(
    where: { _and: [{ private: { _eq: false } }, { ends_at: { _gte: now } }] }
    order_by: { ends_at: asc }
    limit: $limit
    offset: $offset
  ) {
    uuid
    slug
    name
    type
    tagline
    desc
    city
    state
    country
    location
    timezone
    starts_at
    ends_at
    is_online
    apply_mode
    devfolio_official
    featured
    verified
    participants_count
    team_min
    team_max: team_size
    cover_img: _cover_img
    favicon: _favicon
    brand { name }
    themes { theme { name } }
    tracks { name }
    settings {
      reg_starts_at
      reg_ends_at
      winner_announce_at
      logo: _logo
      site
      external_apply_url
      is_hybrid
    }
    prizes { name desc amount currency quantity hidden }
    sponsor_tiers { name sponsors { name } }
  }
}
"""

_TZ_ALIASES = {
    "Asia/Calcutta": "Asia/Kolkata",
    "Asia/Katmandu": "Asia/Kathmandu",
    "Asia/Saigon": "Asia/Ho_Chi_Minh",
    "Asia/Rangoon": "Asia/Yangon",
    "US/Pacific": "America/Los_Angeles",
    "US/Eastern": "America/New_York",
    "US/Central": "America/Chicago",
    "US/Mountain": "America/Denver",
    "Europe/Kiev": "Europe/Kyiv",
}
_SYMBOL = {"USD": "$", "INR": "₹", "EUR": "€", "GBP": "£"}
_NO_THEME = {"no restrictions", "open innovation", "none"}
# A prize whose *name* says it is a perk ("CodeCrafters VIP (2-Year Membership)",
# "Fueler Digital Bundle", "Swag Kit") or whose description values a licence /
# credits ("3-Month ElevenLabs Pro Tier license ($297 value)") is not cash.
_PERK_NAME_RE = re.compile(
    r"membership|perk|credits?\b|subscription|swag|goodies|bundle|voucher|coupon|licen[cs]e|\bdomains?\b|"
    r"merch|\bkit\b|\btier\b|internship|\bppo\b|\bppi\b",
    re.I,
)
_PERK_DESC_RE = re.compile(r"membership|licen[cs]e|subscription|credits?\b|\btier\b|voucher|coupon", re.I)
# extras that come on top of cash ("Additional Innerve Goodies & Merchandise")
_EXTRAS_RE = re.compile(r"goodies|swag|merch|internship|credits?\b|in[\s-]kind|voucher|subscription|ppo|ppi", re.I)


def _md_to_text(value: Any, max_len: int = 1500) -> str | None:
    """Markdown (Devfolio descriptions) to readable plain text."""
    if not value:
        return None
    text = str(value)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)  # images
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # links -> label
    text = re.sub(r"<[^>]+>", " ", text)  # inline html
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)  # headings
    text = re.sub(r"^\s*>\s?", "", text, flags=re.M)  # quotes
    text = re.sub(r"^\s*[-*+]\s+", "• ", text, flags=re.M)  # bullets
    text = re.sub(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", "", text, flags=re.M)  # rules
    text = re.sub(r"(\*\*|__|\*|`)", "", text)
    text = clean_text(text) or ""
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"
    return text or None


def _fmt(amount: float, currency: str) -> str:
    symbol = _SYMBOL.get(currency)
    whole = f"{amount:,.0f}"
    return f"{symbol}{whole}" if symbol else f"{whole} {currency}"


def _prizes(prizes: list[dict[str, Any]]) -> tuple[float | None, str | None, str | None, bool | None]:
    """Returns (cash total, currency, display text, non-cash prizes?)."""
    shown: dict[str, float] = {}
    cash: dict[str, float] = {}
    non_cash = False
    visible = [p for p in prizes if isinstance(p, dict) and not p.get("hidden")]
    for p in visible:
        name, desc = str(p.get("name") or ""), str(p.get("desc") or "")
        try:
            amount = float(p.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0.0
        is_perk = bool(_PERK_NAME_RE.search(name)) or bool(
            _PERK_DESC_RE.search(desc) and not re.search(r"\bcash\b", desc, re.I)
        )
        non_cash = non_cash or is_perk or amount <= 0 or bool(_EXTRAS_RE.search(desc))
        if amount <= 0:
            continue
        currency = (p.get("currency") or "USD").upper()
        shown[currency] = shown.get(currency, 0.0) + amount
        if not is_perk:
            cash[currency] = cash.get(currency, 0.0) + amount
    if not visible:
        return None, None, None, None
    text = None
    if shown:
        cur, total = max(shown.items(), key=lambda kv: kv[1])
        text = f"Prize pool {_fmt(total, cur)}"
    if cash:
        cur, total = max(cash.items(), key=lambda kv: kv[1])
        return round(total, 2), cur, text, non_cash
    return None, None, text, non_cash


class Devfolio(Source):
    key = "devfolio"
    name = "Devfolio"
    homepage = "https://devfolio.co/hackathons"
    region = "india"
    focus = "Indian college hackathons and Ethereum events"
    description = (
        "The platform behind most of India's student-run hackathons (ETHIndia, HackOdisha, "
        "Innerve and hundreds of college events), plus web3 hackathons worldwide."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        rows: list[dict[str, Any]] = []
        offset = 0
        while offset < MAX_ITEMS:
            data = await post_json(
                client,
                GRAPHQL_URL,
                {
                    "query": QUERY,
                    "operationName": "HackmashCurrentHackathons",
                    "variables": {"offset": offset, "limit": PAGE},
                },
            )
            if data.get("errors"):
                raise RuntimeError(f"devfolio graphql: {data['errors'][0].get('message')}")
            batch = (data.get("data") or {}).get("hackathons") or []
            rows.extend(batch)
            if len(batch) < PAGE:
                break
            offset += PAGE

        items: list[RawHackathon] = []
        seen: set[str] = set()
        for row in rows:
            uid = str(row.get("uuid") or row.get("slug") or "")
            if not uid or uid in seen:
                continue
            seen.add(uid)
            try:
                items.append(self._build(row))
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("devfolio: could not parse %s", row.get("slug"))
        return items

    def _build(self, row: dict[str, Any]) -> RawHackathon:
        settings = row.get("settings") or {}
        slug = str(row["slug"]).strip()
        url = f"https://{slug.lower()}.devfolio.co/"

        if row.get("is_online"):
            mode = "online"
        elif settings.get("is_hybrid"):
            mode = "hybrid"
        else:
            mode = "in_person"
        city = clean_text(row.get("city"))
        state = clean_text(row.get("state"))
        country = clean_text(row.get("country"))
        if mode == "online":
            location = "Online"
        else:
            location = clean_text(row.get("location")) or ", ".join(x for x in (city, state, country) if x) or None

        tz = clean_text(row.get("timezone"))
        tz = _TZ_ALIASES.get(tz or "", tz)

        amount, currency, prize_text, non_cash = _prizes(row.get("prizes") or [])

        tags: list[str] = []
        for name in [((t or {}).get("theme") or {}).get("name") for t in row.get("themes") or []] + [
            (t or {}).get("name") for t in row.get("tracks") or []
        ]:
            name = clean_text(name)
            if name and name.lower() not in _NO_THEME and name not in tags:
                tags.append(name)

        sponsors = [
            clean_text(s.get("name"))
            for tier in row.get("sponsor_tiers") or []
            for s in (tier or {}).get("sponsors") or []
            if s and s.get("name")
        ]
        brand = clean_text((row.get("brand") or {}).get("name"))
        kind = "hackathon" if str(row.get("type") or "HACKATHON").upper() == "HACKATHON" else "other"

        return RawHackathon(
            source=self.key,
            source_id=str(row.get("uuid") or slug),
            title=clean_text(row.get("name")) or slug,
            url=url,
            kind=kind,
            organizer=brand,
            tagline=clean_text(row.get("tagline")),
            description=_md_to_text(row.get("desc")),
            image_url=row.get("cover_img") or None,
            logo_url=settings.get("logo") or row.get("favicon") or None,
            mode=mode,
            location=location,
            city=city if mode != "online" else None,
            country=country if mode != "online" else None,
            starts_at=to_utc(row.get("starts_at")),
            ends_at=to_utc(row.get("ends_at")),
            registration_opens_at=to_utc(settings.get("reg_starts_at")),
            registration_deadline=to_utc(settings.get("reg_ends_at")),
            timezone=tz,
            prize_text=prize_text,
            prize_amount=amount,
            prize_currency=currency if amount else None,
            non_cash_prizes=non_cash,
            tags=tags,
            participants=as_int(row.get("participants_count")),
            team_size_min=as_int(row.get("team_min")),
            team_size_max=as_int(row.get("team_max")),
            # Every Devfolio microsite answers "Registration costs? Nada." (applying is free).
            registration_fee=False,
            extra={
                "slug": slug,
                "type": row.get("type"),
                "state": state,
                "website": settings.get("site"),
                "external_apply_url": settings.get("external_apply_url"),
                "apply_mode": row.get("apply_mode"),
                "devfolio_official": bool(row.get("devfolio_official")),
                "featured": bool(row.get("featured")),
                "verified": bool(row.get("verified")),
                "winner_announce_at": settings.get("winner_announce_at"),
                "sponsors": [s for s in sponsors if s][:30],
            },
        )
