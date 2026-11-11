"""What a shared link to a hackathon shows: the poster image's text and the
description that WhatsApp, X, LinkedIn and Slack print under it.

Dates are absolute ("Last date · 13 Nov"), never countdowns: those apps keep a
preview for days, so "3 days left" would soon be wrong while a date stays true.
They are written in the event's own calendar (its timezone, else IST for events
in India, else UTC), the way the platform publishes them.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

# Bump when the poster's design changes: every image is drawn again on the next sync.
TEMPLATE_VERSION = "poster-1"

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sept", "Oct", "Nov", "Dec")
KINDS = {
    "hackathon": "Hackathon",
    "ideathon": "Ideathon",
    "coding_contest": "Coding contest",
    "data_science": "Data science",
    "other": "Challenge",
}
STOCK = {"hackathon": "white", "ideathon": "yellow", "coding_contest": "blue", "data_science": "green", "other": "pink"}
IST = ZoneInfo("Asia/Kolkata")


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _zone(item: dict[str, Any]) -> ZoneInfo:
    if item.get("timezone"):
        try:
            return ZoneInfo(item["timezone"])
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return IST if item.get("country") == "India" else ZoneInfo("UTC")


def day(dt: datetime, tz: ZoneInfo) -> str:
    d = dt.astimezone(tz)
    return f"{d.day} {MONTHS[d.month - 1]}"


def day_range(start: datetime | None, end: datetime | None, tz: ZoneInfo) -> str | None:
    if not start:
        return f"Until {day(end, tz)}" if end else None
    if not end:
        return f"From {day(start, tz)}"
    a, b = start.astimezone(tz), end.astimezone(tz)
    if (a.year, a.month) == (b.year, b.month):
        return day(a, tz) if a.day == b.day else f"{a.day}–{b.day} {MONTHS[b.month - 1]}"
    return f"{day(a, tz)} – {day(b, tz)}"


def _trim(x: float) -> str:
    return f"{x:.1f}".rstrip("0").rstrip(".")


def inr(amount: float) -> str:
    if amount >= 1e7:
        return f"₹{_trim(amount / 1e7)} crore"
    if amount >= 1e5:
        return f"₹{_trim(amount / 1e5)} lakh"
    return f"₹{amount:,.0f}"


def usd(amount: float) -> str:
    if amount >= 1e6:
        return f"${_trim(amount / 1e6)}M"
    if amount >= 1e4:
        return f"${amount / 1e3:.0f}k"
    return f"${amount:,.0f}"


@dataclass(frozen=True)
class ShareContext:
    """What a card needs from the catalog as a whole."""

    names: dict[str, str]  # source key -> platform name
    themes: dict[str, str]  # theme key -> label
    usd_per_inr: float | None  # the catalog's rate, for "≈ ₹9.4 crore"
    now: datetime

    @classmethod
    def from_catalog(cls, doc: dict[str, Any], now: datetime | None = None) -> ShareContext:
        return cls(
            names={s["key"]: s.get("name") or s["key"] for s in doc.get("sources", [])},
            themes=dict((doc.get("taxonomy") or {}).get("themes") or {}),
            usd_per_inr=(doc.get("fx") or {}).get("INR"),
            now=now or datetime.now(timezone.utc),
        )


@dataclass(frozen=True)
class Card:
    """Everything printed on a hackathon's poster."""

    id: str
    title: str
    platform: str
    organizer: str | None
    logo_url: str | None
    kind: str
    stock: str
    stamp: dict[str, str] | None  # {"label": "Last date", "date": "13 Nov", "tone": "red" | "live" | "quiet"}
    when: str | None
    where: str
    prize: str | None
    prize_alt: str | None
    team: str | None
    registered: str | None
    themes: tuple[str, ...] = field(default=())

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["themes"] = list(self.themes)
        return d

    @property
    def hash(self) -> str:
        """Changes whenever the poster would look different."""
        text = json.dumps([TEMPLATE_VERSION, self.to_dict()], ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(text.encode()).hexdigest()[:16]


def _stamp(item: dict[str, Any], tz: ZoneInfo, now: datetime) -> dict[str, str] | None:
    reg, sub = _dt(item.get("registration_deadline")), _dt(item.get("submission_deadline"))
    start, end = _dt(item.get("starts_at")), _dt(item.get("ends_at"))
    if reg and reg > now:
        return {"label": "Last date", "date": day(reg, tz), "tone": "red"}
    if sub and sub > now:
        return {"label": "Submit by", "date": day(sub, tz), "tone": "red"}
    if start and start > now:
        return {"label": "Starts", "date": day(start, tz), "tone": "quiet"}
    if end and end > now:
        return {"label": "Ends", "date": day(end, tz), "tone": "live"}
    last = end or sub
    return {"label": "Ended", "date": day(last, tz), "tone": "quiet"} if last else None


def _where(item: dict[str, Any]) -> str:
    mode, city = item.get("mode"), item.get("city")
    if mode == "online":
        return "Online"
    if mode == "hybrid":
        return f"{city} + online" if city else "Hybrid"
    return ", ".join(x for x in (city, item.get("country")) if x) or "In person"


def _team(item: dict[str, Any]) -> str | None:
    lo, hi = item.get("team_size_min"), item.get("team_size_max")
    if hi == 1:
        return "Solo"
    if lo and hi and lo > 1:
        return f"Teams of {lo}–{hi}"
    if hi:
        return f"Up to {hi} people"
    return None


def _prize(item: dict[str, Any], ctx: ShareContext) -> tuple[str | None, str | None]:
    amount, currency = item.get("prize_amount"), item.get("prize_currency")
    if amount and currency == "INR":
        return inr(amount), None
    if amount and currency == "USD":
        return usd(amount), (f"≈ {inr(amount / ctx.usd_per_inr)}" if ctx.usd_per_inr else None)
    if item.get("prize_usd"):  # another currency: show its dollar value, as the board does
        value = item["prize_usd"]
        return usd(value), (f"≈ {inr(value / ctx.usd_per_inr)}" if ctx.usd_per_inr else None)
    return None, None


def card_for(item: dict[str, Any], ctx: ShareContext) -> Card:
    tz = _zone(item)
    start, end = _dt(item.get("starts_at")), _dt(item.get("ends_at"))
    prize, prize_alt = _prize(item, ctx)
    return Card(
        id=item["id"],
        title=item["title"],
        platform=ctx.names.get(item["source"], item["source"]),
        organizer=item.get("organizer"),
        logo_url=item.get("logo_url"),
        kind=KINDS.get(item.get("kind") or "hackathon", "Hackathon"),
        stock=STOCK.get(item.get("kind") or "hackathon", "white"),
        stamp=_stamp(item, tz, ctx.now),
        when=day_range(start, end or _dt(item.get("submission_deadline")), tz),
        where=_where(item),
        prize=prize,
        prize_alt=prize_alt,
        team=_team(item),
        registered=f"{item['participants']:,}" if item.get("participants") else None,
        themes=tuple(ctx.themes.get(t, t) for t in (item.get("themes") or [])[:3]),
    )


def blurb(card: Card) -> str:
    """The line under a link preview: the facts that decide whether to click."""
    facts = []
    if card.stamp:
        facts.append(f"{card.stamp['label']} {card.stamp['date']}")
    facts.append(card.where)
    if card.prize:
        facts.append(f"{card.prize} prize pool")
    if card.team:
        facts.append(card.team)
    if card.registered:
        facts.append(f"{card.registered} registered")
    by = f", by {card.organizer}" if card.organizer and card.organizer.lower() != card.platform.lower() else ""
    return f"{' · '.join(facts)}. On {card.platform}{by}."
