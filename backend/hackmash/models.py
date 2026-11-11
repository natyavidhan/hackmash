"""Data models shared by every source adapter, the store and the API.

Source adapters emit ``RawHackathon`` objects. The normaliser turns them into
``Hackathon`` objects (canonical themes, USD prize, country names, dedupe
links), which is what the API serves.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Mode = Literal["online", "in_person", "hybrid"]

# What kind of event this is. Most platforms mix formats under "hackathons".
#   hackathon       build a working project (default)
#   ideathon        idea / pitch deck / case-study / PPT round, no build required
#   coding_contest  competitive programming / DSA contest
#   data_science    ML / data competition scored on a leaderboard
#   other           quizzes, design challenges, anything else
Kind = Literal["hackathon", "ideathon", "coding_contest", "data_science", "other"]

Status = Literal["upcoming", "open", "live", "ended"]


class RawHackathon(BaseModel):
    """One listing as emitted by a source adapter.

    Rules for adapters:
    * Every datetime MUST be timezone-aware (use ``to_utc`` from sources.base).
    * ``url`` is the public page where a user reads about / applies to the event.
    * ``source_id`` must be stable across runs (platform id or slug).
    * Leave a field ``None`` rather than guessing.
    """

    source: str
    source_id: str
    title: str
    url: str

    kind: Kind = "hackathon"
    organizer: str | None = None
    tagline: str | None = None  # one-line summary
    description: str | None = None  # plain text, a few paragraphs at most
    image_url: str | None = None  # wide banner / cover
    logo_url: str | None = None  # square logo / thumbnail

    mode: Mode | None = None
    location: str | None = None  # display string, e.g. "Bengaluru, Karnataka, India"
    city: str | None = None
    country: str | None = None  # full English name or ISO-3166 alpha-2 code

    starts_at: datetime | None = None
    ends_at: datetime | None = None
    registration_opens_at: datetime | None = None
    registration_deadline: datetime | None = None
    submission_deadline: datetime | None = None
    timezone: str | None = None  # IANA name of the event's local timezone, if known

    prize_text: str | None = None  # as displayed by the platform, e.g. "$10,000 in prizes"
    prize_amount: float | None = None  # total cash prize pool, in prize_currency
    prize_currency: str | None = None  # ISO-4217, e.g. "USD", "INR"
    non_cash_prizes: bool | None = None  # swag, credits, internships, PPIs...

    tags: list[str] = Field(default_factory=list)  # raw themes / skills / tracks from the platform
    participants: int | None = None  # registrations or participants count
    team_size_min: int | None = None
    team_size_max: int | None = None
    eligibility: list[str] = Field(default_factory=list)  # raw eligibility strings
    registration_fee: bool | None = None  # True = paid entry
    beginner_friendly: bool | None = None
    travel_reimbursement: bool | None = None
    invite_only: bool | None = None

    extra: dict[str, Any] = Field(default_factory=dict)  # anything else source-specific

    @field_validator(
        "starts_at",
        "ends_at",
        "registration_opens_at",
        "registration_deadline",
        "submission_deadline",
    )
    @classmethod
    def _require_aware(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("datetimes must be timezone-aware; use sources.base.to_utc()")
        return value.astimezone(timezone.utc)

    @field_validator("title", "source_id", "url")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @property
    def uid(self) -> str:
        return make_uid(self.source, self.source_id)


def make_uid(source: str, source_id: str) -> str:
    """URL-safe, globally unique id: ``<source>-<source_id>``."""
    safe = "".join(ch if ch.isalnum() or ch in "-_." else "-" for ch in str(source_id))
    return f"{source}-{safe}".strip("-")


class DeadlineChange(BaseModel):
    """A deadline moved later between two scrapes (an extension)."""

    field: str  # "registration_deadline" | "submission_deadline"
    old: datetime
    new: datetime
    seen_at: datetime


class Listing(BaseModel):
    """Another platform on which the same event is listed (dedupe result)."""

    id: str
    source: str
    url: str


class Hackathon(RawHackathon):
    """A normalised listing, as stored and served by the API."""

    id: str
    themes: list[str] = Field(default_factory=list)  # canonical theme keys, see normalize.THEMES
    audience: list[str] = Field(default_factory=list)  # canonical eligibility keys, see normalize.AUDIENCES
    prize_usd: float | None = None
    region: str | None = None  # continent-ish bucket, e.g. "Asia", "North America"
    duration_hours: float | None = None
    also_on: list[Listing] = Field(default_factory=list)
    duplicate_of: str | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None

    delisted: bool = False  # the platform stopped listing it (closed, cancelled or full)
    hiring: bool = False  # offers jobs, internships or pre-placement interviews
    deadline_extended: DeadlineChange | None = None  # latest recent extension, if any

    def status(self, now: datetime | None = None) -> Status:
        return lifecycle(self, now)[0]

    def registration_open(self, now: datetime | None = None) -> bool:
        return lifecycle(self, now)[1]


def lifecycle(h: RawHackathon, now: datetime | None = None) -> tuple[Status, bool]:
    """(status, registration_open) from an event's dates. Mirrored in the frontend."""
    now = now or datetime.now(timezone.utc)
    end = h.ends_at or h.submission_deadline
    if end and end < now:
        return "ended", False
    if closed_out(h, now):
        return "ended", False
    reg_open = not h.invite_only
    if h.registration_opens_at and h.registration_opens_at > now:
        reg_open = False
    if h.registration_deadline and h.registration_deadline <= now:
        reg_open = False
    if h.starts_at and h.starts_at <= now:
        # nobody walks into an in-person hackathon that is already under way,
        # even when the platform never published a registration deadline
        if getattr(h, "mode", None) == "in_person" and not h.registration_deadline:
            reg_open = False
        return "live", reg_open
    if not reg_open:
        return "upcoming", False
    return "open", True


def closed_out(h: RawHackathon, now: datetime | None = None) -> bool:
    """Submissions closed over two days ago and registration is shut (mirrored in the frontend)."""
    now = now or datetime.now(timezone.utc)
    sub, reg = h.submission_deadline, h.registration_deadline
    return bool(sub and sub < now - timedelta(days=2) and (reg is None or reg < now))
