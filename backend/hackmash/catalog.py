"""Build the catalog snapshot from the refresher's state.

The catalog is one JSON document: every live and upcoming listing, ended ones
for a while (so direct links and trackers keep working), taxonomy labels and
per-source health. ``hackmash.sync`` turns it into database rows for the site;
the local server (``hackmash serve``) serves it as-is.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from .dedupe import dedupe
from .models import Hackathon, closed_out, lifecycle
from .normalize import AUDIENCES, KINDS, MODES, REGIONS, STATIC_USD_RATES, THEME_LABELS, normalize
from .state import State, dumps

CATALOG_VERSION = 1
ENDED_KEEP = timedelta(days=90)  # ended events stay reachable by direct link this long
DELISTED_KEEP = timedelta(days=45)  # keep listings a platform dropped this long
DELIST_GRACE = timedelta(hours=36)  # missing from this many hours of successful runs = delisted
DESCRIPTION_MAX = 3000  # only the detail view loads it; the board never downloads descriptions
EXTENSION_SHOWN = timedelta(days=21)  # show an "extended" badge this long after we notice it
DISPLAY_CURRENCIES = ("USD", "INR", "EUR", "GBP", "CAD", "AUD", "SGD")

_ITEM_EXCLUDE = {"extra", "duplicate_of", "source_id"}


def _item_json(h: Hackathon) -> dict[str, Any]:
    d = h.model_dump(mode="json", exclude=_ITEM_EXCLUDE, exclude_none=True)
    for key in ("tags", "themes", "audience", "eligibility", "also_on"):
        if not d.get(key):
            d.pop(key, None)
    if not d.get("delisted"):
        d.pop("delisted", None)
    desc = d.get("description")
    if desc and len(desc) > DESCRIPTION_MAX:
        d["description"] = desc[:DESCRIPTION_MAX].rsplit(" ", 1)[0].rstrip(" ,.;:") + "…"
    return d


def on_board(h: Hackathon, now: datetime) -> bool:
    """Shown on the board: registration is open (mirrors the frontend's rule)."""
    status, reg_open = lifecycle(h, now)
    if h.delisted and not h.registration_deadline:
        reg_open = False  # a platform that stopped listing an event usually closed registration
    return status != "ended" and reg_open


_JUNK_TITLE = re.compile(r"\b(test(ing)?|mock|dummy|sample|sandbox|do not join)\b", re.I)


def is_junk(h: Hackathon) -> bool:
    """Listings nobody outside can join, or obvious test events."""
    if h.invite_only:
        return True
    return bool(_JUNK_TITLE.search(h.title)) and (h.participants or 0) < 25 and not h.prize_amount


def build_items(state: State, now: datetime | None = None, enabled: set[str] | None = None) -> list[Hackathon]:
    now = now or datetime.now(timezone.utc)
    rates = {**STATIC_USD_RATES, **state.fx_rates, "USD": 1.0}
    items: list[Hackathon] = []
    for listing in state.listings.values():
        if enabled is not None and listing.raw.source not in enabled:
            continue  # adapter switched off: its old listings go too
        try:
            h = normalize(listing.raw, rates, listing.first_seen_at, listing.last_seen_at)
        except ValueError:
            continue
        if is_junk(h):
            continue
        recent = [c for c in listing.changes if c.seen_at > now - EXTENSION_SHOWN and c.new > now]
        if recent:
            h.deadline_extended = recent[-1]
        src = state.sources.get(h.source)
        last_ok = src.last_ok.started_at if src and src.last_ok else None
        if last_ok and listing.last_seen_at < last_ok - DELIST_GRACE:
            h.delisted = True
        end = h.ends_at or h.submission_deadline
        if closed_out(h, now) and h.submission_deadline:
            end = min(end or h.submission_deadline, h.submission_deadline)
        if end and end < now - ENDED_KEEP:
            continue
        if h.delisted and listing.last_seen_at < now - DELISTED_KEEP:
            continue
        items.append(h)
    return dedupe(items)


def _sort_key(h: Hackathon) -> tuple:
    far = datetime.max.replace(tzinfo=timezone.utc)
    return (h.starts_at or far, h.title.lower())


def build_catalog(state: State, now: datetime | None = None) -> bytes:
    from .sources import discover  # lazy: pulls in every adapter and its HTTP deps

    now = now or datetime.now(timezone.utc)
    registry = discover()
    enabled = {k for k, cls in registry.items() if cls.enabled}
    items = sorted(build_items(state, now, enabled), key=_sort_key)
    rates = {**STATIC_USD_RATES, **state.fx_rates, "USD": 1.0}

    per_source: dict[str, int] = {}  # what each platform contributes to the board right now
    for h in items:
        if not on_board(h, now):
            continue
        for src in [h.source, *(other.source for other in h.also_on)]:
            per_source[src] = per_source.get(src, 0) + 1

    sources = []
    for key in sorted(set(registry) | set(state.sources)):
        cls = registry.get(key)
        st = state.sources.get(key)
        last, last_ok = (st.last_run, st.last_ok) if st else (None, None)
        sources.append(
            {
                "key": key,
                "name": getattr(cls, "name", key),
                "homepage": getattr(cls, "homepage", None),
                "region": getattr(cls, "region", "global"),
                "focus": getattr(cls, "focus", ""),
                "description": getattr(cls, "description", ""),
                "enabled": bool(cls and cls.enabled),
                "count": per_source.get(key, 0),
                "last_run_at": last.finished_at.isoformat() if last else None,
                "last_ok_at": last_ok.finished_at.isoformat() if last_ok else None,
                "ok": bool(last and last.ok),
                "error": last.error if last and not last.ok else None,
            }
        )

    doc = {
        "version": CATALOG_VERSION,
        "generated_at": now.isoformat(),
        "count": len(items),
        "taxonomy": {
            "themes": THEME_LABELS,
            "kinds": KINDS,
            "audiences": AUDIENCES,
            "modes": MODES,
            "regions": REGIONS,
        },
        "fx": {c: rates[c] for c in DISPLAY_CURRENCIES if c in rates},
        "sources": [s for s in sources if s["enabled"] or s["count"]],
        "items": [_item_json(h) for h in items],
    }
    return dumps(doc)
