"""Find the same event listed on several platforms and merge it into one record.

Two listings from *different* sources are the same event when their titles
match closely (after stripping years, edition numbers and filler words) and
their dates line up. The richest listing becomes the primary record, gaps are
filled from the others, and the rest are linked as ``also_on``.
"""

from __future__ import annotations

import re
from datetime import timedelta

from .models import Hackathon, Listing

try:
    from rapidfuzz import fuzz

    def _similarity(a: str, b: str) -> float:
        return fuzz.token_sort_ratio(a, b)

except ImportError:  # pragma: no cover - pure-python fallback (e.g. constrained runtimes)
    from difflib import SequenceMatcher

    def _similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, " ".join(sorted(a.split())), " ".join(sorted(b.split()))).ratio() * 100


DATE_TOLERANCE = timedelta(days=3)

# Sources that link out to the event's own site rather than an application page;
# when the same event is also on a hosting platform, prefer the platform.
_PRIORITY = {"mlh": 1, "hackclub": 1, "luma": 2}
_FILLER = {
    "hackathon", "hack", "hacks", "the", "edition", "online", "virtual", "global", "season", "annual",
    "presents", "in", "person", "inperson", "a", "an", "of", "and", "x", "by", "at", "for",
}


def _base(title: str) -> str:
    t = title.lower()
    t = re.sub(r"\b(19|20)\d\d\b|'\d\d\b", " ", t)  # years: 2026, '26
    t = re.sub(r"\b(v|ver|version|season|s)\s?\d+(\.\d+)?\b", " ", t)  # v5, season 3
    t = re.sub(r"\b\d+(\.\d+)+\b|\b\d+(st|nd|rd|th)\b", " ", t)  # 5.0, 3rd
    t = re.sub(r"[^a-z0-9]+", " ", t)
    return " ".join(t.split())


def title_key(title: str) -> str:
    words = [w for w in _base(title).split() if w not in _FILLER]
    return " ".join(words)


def _dates_match(a: Hackathon, b: Hackathon) -> bool:
    if a.starts_at and b.starts_at:
        return abs(a.starts_at - b.starts_at) <= DATE_TOLERANCE
    ea, eb = a.ends_at or a.submission_deadline, b.ends_at or b.submission_deadline
    if ea and eb:
        return abs(ea - eb) <= DATE_TOLERANCE
    return False


def _compatible(a: Hackathon, b: Hackathon) -> bool:
    if a.source == b.source:
        return False
    modes = {a.mode, b.mode}
    if modes == {"online", "in_person"}:
        return False
    if a.country and b.country and a.country != b.country:
        return False
    return _dates_match(a, b)


def same_event(a: Hackathon, b: Hackathon) -> bool:
    if not _compatible(a, b):
        return False
    ka, kb = title_key(a.title), title_key(b.title)
    if not ka or not kb:
        return False
    if len(ka) < 4 or len(kb) < 4:
        return _base(a.title) == _base(b.title)
    return _similarity(ka, kb) >= 90 and _similarity(_base(a.title), _base(b.title)) >= 75


def _richness(h: Hackathon) -> float:
    fields = (
        h.starts_at, h.ends_at, h.registration_deadline, h.prize_amount, h.image_url, h.logo_url,
        h.organizer, h.description, h.tags, h.participants, h.team_size_max, h.eligibility, h.city,
    )
    score = sum(1 for f in fields if f not in (None, "", []))
    score += 4 * _PRIORITY.get(h.source, 3)
    if h.delisted:
        score -= 20
    return score


_FILL_FIELDS = (
    "organizer", "tagline", "description", "image_url", "logo_url", "mode", "location", "city", "state", "country",
    "region", "starts_at", "ends_at", "registration_opens_at", "registration_deadline",
    "submission_deadline", "timezone", "prize_text", "prize_amount", "prize_currency", "prize_usd",
    "non_cash_prizes", "participants", "team_size_min", "team_size_max", "registration_fee",
    "travel_reimbursement", "duration_hours",
)


def _merge(primary: Hackathon, others: list[Hackathon]) -> Hackathon:
    data = primary.model_dump()
    for other in others:
        o = other.model_dump()
        for f in _FILL_FIELDS:
            if data.get(f) in (None, "", []) and o.get(f) not in (None, "", []):
                data[f] = o[f]
        # a pin only travels with its own city
        if data.get("lat") is None and o.get("lat") is not None and data.get("city") == o.get("city"):
            data["lat"], data["lng"] = o["lat"], o["lng"]
        for f in ("tags", "themes", "audience", "eligibility"):
            for v in o.get(f) or []:
                if v not in data[f]:
                    data[f].append(v)
        if o.get("beginner_friendly"):
            data["beginner_friendly"] = True
        if o.get("first_seen_at") and data.get("first_seen_at") and o["first_seen_at"] < data["first_seen_at"]:
            data["first_seen_at"] = o["first_seen_at"]
    data["also_on"] = [Listing(id=o.id, source=o.source, url=o.url) for o in others]
    data["delisted"] = primary.delisted and all(o.delisted for o in others)
    return Hackathon.model_validate(data)


def dedupe(items: list[Hackathon]) -> list[Hackathon]:
    """Return one record per real-world event (input order is not preserved)."""
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    # sweep over items sorted by start (or end) date, comparing only nearby ones
    def anchor(h: Hackathon):
        return h.starts_at or h.ends_at or h.submission_deadline

    dated = sorted((i for i, h in enumerate(items) if anchor(h)), key=lambda i: anchor(items[i]))
    window = DATE_TOLERANCE + timedelta(days=1)
    for pos, i in enumerate(dated):
        ai = anchor(items[i])
        for j in dated[pos + 1 :]:
            if anchor(items[j]) - ai > window:
                break
            if find(i) != find(j) and same_event(items[i], items[j]):
                parent[find(j)] = find(i)

    groups: dict[int, list[Hackathon]] = {}
    for i, h in enumerate(items):
        groups.setdefault(find(i), []).append(h)

    out: list[Hackathon] = []
    for members in groups.values():
        if len(members) == 1:
            out.append(members[0])
            continue
        members.sort(key=_richness, reverse=True)
        out.append(_merge(members[0], members[1:]))
    return out
