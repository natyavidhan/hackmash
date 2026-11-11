"""In-memory view of a catalog snapshot, with server-side search for the public API.

The web app filters client-side from /api/catalog; this module powers
/api/hackathons for scripts, bots and third-party integrations. It works on
plain dicts from the snapshot (no model validation) to stay cheap per request.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

from .models import lifecycle

_DATE_FIELDS = ("starts_at", "ends_at", "registration_opens_at", "registration_deadline", "submission_deadline")


def _term_in(term: str, text: str) -> bool:
    """Short terms ("ai", "ml") match at a word start, so "ai" doesn't hit "Chennai"."""
    if len(term) > 3:
        return term in text
    return re.search(r"(?<![^\W_])" + re.escape(term), text) is not None


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass
class Query:
    q: str | None = None
    source: list[str] = field(default_factory=list)
    mode: list[str] = field(default_factory=list)
    kind: list[str] = field(default_factory=list)
    theme: list[str] = field(default_factory=list)
    audience: list[str] = field(default_factory=list)
    country: list[str] = field(default_factory=list)
    state: list[str] = field(default_factory=list)  # Indian state or union territory
    city: list[str] = field(default_factory=list)
    region: list[str] = field(default_factory=list)
    status: list[str] = field(default_factory=list)  # open | live | upcoming | ended
    min_prize_usd: float | None = None
    beginner: bool | None = None
    free: bool | None = None  # True = hide paid-entry events
    ids: list[str] = field(default_factory=list)
    sort: str = "deadline"  # deadline | starts | prize | newest | popular | relevance
    page: int = 1
    page_size: int = 30


class LoadedCatalog:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.etag = '"' + hashlib.sha1(data).hexdigest()[:20] + '"'
        self.doc: dict[str, Any] = json.loads(data)
        self.items: list[dict[str, Any]] = self.doc.get("items", [])
        self.sources: list[dict[str, Any]] = self.doc.get("sources", [])
        self.source_names = {s["key"]: s.get("name", s["key"]) for s in self.sources}
        self.by_id: dict[str, dict[str, Any]] = {}
        self._dates: dict[str, SimpleNamespace] = {}
        self._text: dict[str, str] = {}
        for it in self.items:
            it.setdefault("source_name", self.source_names.get(it["source"], it["source"]))
            self.by_id[it["id"]] = it
            for alt in it.get("also_on", []):
                self.by_id.setdefault(alt["id"], it)
            ns = SimpleNamespace(**{f: _dt(it.get(f)) for f in _DATE_FIELDS})
            ns.invite_only = it.get("invite_only")
            ns.mode = it.get("mode")
            self._dates[it["id"]] = ns
            self._text[it["id"]] = " ".join(
                str(x)
                for x in (
                    it.get("title"), it.get("organizer"), it.get("tagline"), it.get("location"),
                    it.get("city"), it.get("state"), it.get("country"), it.get("source_name"), *(it.get("tags") or []),
                )
                if x
            ).lower()

    # -- derived fields -------------------------------------------------------

    def lifecycle(self, it: dict[str, Any], now: datetime) -> tuple[str, bool]:
        status, reg_open = lifecycle(self._dates[it["id"]], now)  # type: ignore[arg-type]
        if it.get("delisted") and not self._dates[it["id"]].registration_deadline:
            reg_open = False
        return status, reg_open

    def next_deadline(self, it: dict[str, Any], now: datetime) -> datetime | None:
        d = self._dates[it["id"]]
        upcoming = [x for x in (d.registration_deadline, d.submission_deadline, d.ends_at) if x and x > now]
        return min(upcoming) if upcoming else None

    def enrich(self, it: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
        now = now or datetime.now(timezone.utc)
        status, reg_open = self.lifecycle(it, now)
        nd = self.next_deadline(it, now)
        return {**it, "status": status, "registration_open": reg_open, "next_deadline": nd.isoformat() if nd else None}

    # -- search -----------------------------------------------------------------

    def search(self, query: Query, now: datetime | None = None) -> tuple[int, list[dict[str, Any]]]:
        now = now or datetime.now(timezone.utc)
        if query.ids:
            found, seen = [], set()
            for i in query.ids:
                it = self.by_id.get(i)
                if it and it["id"] not in seen:
                    seen.add(it["id"])
                    found.append(self.enrich(it, now))
            return len(found), found

        terms = [t for t in re.split(r"\s+", (query.q or "").lower().strip()) if t]
        status_filter = set(query.status) or {"open", "live", "upcoming"}
        results: list[tuple[float, dict[str, Any]]] = []
        for it in self.items:
            if query.source and it["source"] not in query.source and not any(
                a["source"] in query.source for a in it.get("also_on", [])
            ):
                continue
            if query.mode and it.get("mode") not in query.mode:
                continue
            if query.kind and it.get("kind") not in query.kind:
                continue
            if query.theme and not set(query.theme) & set(it.get("themes", [])):
                continue
            if query.audience and not set(query.audience) & set(it.get("audience", [])):
                continue
            if query.country and it.get("country") not in query.country:
                continue
            if query.state and it.get("state") not in query.state:
                continue
            if query.city and it.get("city") not in query.city:
                continue
            if query.region and it.get("region") not in query.region:
                continue
            if query.min_prize_usd and (it.get("prize_usd") or 0) < query.min_prize_usd:
                continue
            if query.beginner and not it.get("beginner_friendly"):
                continue
            if query.free and it.get("registration_fee"):
                continue
            status, reg_open = self.lifecycle(it, now)
            buckets = {status} | ({"open"} if reg_open else set())
            if not buckets & status_filter:
                continue
            if it.get("delisted") and "ended" not in status_filter and status != "live":
                continue
            score = 0.0
            if terms:
                text = self._text[it["id"]]
                if not all(_term_in(t, text) for t in terms):
                    continue
                title = (it.get("title") or "").lower()
                score = sum(3 if t in title else 1 for t in terms)
            results.append((score, it))

        far = datetime.max.replace(tzinfo=timezone.utc)
        if query.sort == "relevance" and terms:
            results.sort(key=lambda r: -r[0])
        elif query.sort == "starts":
            results.sort(key=lambda r: self._dates[r[1]["id"]].starts_at or far)
        elif query.sort == "prize":
            results.sort(key=lambda r: -(r[1].get("prize_usd") or 0))
        elif query.sort == "newest":
            results.sort(key=lambda r: r[1].get("first_seen_at") or "", reverse=True)
        elif query.sort == "popular":
            results.sort(key=lambda r: -(r[1].get("participants") or 0))
        else:
            results.sort(key=lambda r: self.next_deadline(r[1], now) or far)

        total = len(results)
        size = max(1, min(query.page_size, 100))
        start = (max(query.page, 1) - 1) * size
        return total, [self.enrich(it, now) for _, it in results[start : start + size]]

    def is_stale(self, max_age: timedelta) -> bool:
        generated = _dt(self.doc.get("generated_at"))
        return generated is None or datetime.now(timezone.utc) - generated > max_age
