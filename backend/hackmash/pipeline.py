"""Refresh pipeline: run adapters, merge into state, publish the catalog."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from .catalog import build_catalog
from .fx import update_rates
from .models import DeadlineChange, RawHackathon
from .state import FileStore, ListingState, RunInfo, SourceState, State, Store

log = logging.getLogger("hackmash.refresh")

SOURCE_TIMEOUT = 240  # seconds per adapter
PRUNE_AFTER = timedelta(days=120)  # forget listings not seen for this long


@dataclass
class SourceResult:
    source: str
    ok: bool
    count: int
    elapsed: float
    error: str | None = None
    items: list[RawHackathon] = field(default_factory=list, repr=False)


async def run_source(key: str, client: httpx.AsyncClient, timeout: float = SOURCE_TIMEOUT) -> SourceResult:
    from .sources import discover

    cls = discover()[key]
    started = time.monotonic()
    try:
        items = await asyncio.wait_for(cls().fetch(client), timeout=timeout)
        # guard against adapters emitting the same id twice
        unique: dict[str, RawHackathon] = {}
        for item in items:
            if item.source != key:
                item = item.model_copy(update={"source": key})
            unique.setdefault(item.uid, item)
        items = list(unique.values())
        if not items and not getattr(cls, "allow_empty", False):
            raise RuntimeError("adapter returned no listings")
        return SourceResult(key, True, len(items), time.monotonic() - started, items=items)
    except asyncio.TimeoutError:
        return SourceResult(key, False, 0, time.monotonic() - started, f"timed out after {timeout:.0f}s")
    except Exception as exc:  # noqa: BLE001 - one failing platform must not stop the rest
        log.exception("source %s failed", key)
        return SourceResult(key, False, 0, time.monotonic() - started, f"{type(exc).__name__}: {exc}"[:300])


def merge_results(state: State, results: list[SourceResult], started_at: datetime) -> None:
    now = datetime.now(timezone.utc)
    for res in results:
        run = RunInfo(
            started_at=started_at,
            finished_at=now,
            ok=res.ok,
            count=res.count,
            error=res.error,
            elapsed=round(res.elapsed, 2),
        )
        src = state.sources.setdefault(res.source, SourceState())
        src.last_run = run
        if not res.ok:
            continue
        src.last_ok = run
        for item in res.items:
            existing = state.listings.get(item.uid)
            changes = list(existing.changes) if existing else []
            if existing:
                for field in ("registration_deadline", "submission_deadline"):
                    old, new = getattr(existing.raw, field), getattr(item, field)
                    if old and new and new - old > timedelta(hours=1) and old > now - timedelta(days=2):
                        changes.append(DeadlineChange(field=field, old=old, new=new, seen_at=now))
            state.listings[item.uid] = ListingState(
                raw=item,
                first_seen_at=existing.first_seen_at if existing else now,
                last_seen_at=now,
                changes=changes[-5:],
            )
    cutoff = now - PRUNE_AFTER
    for uid in [uid for uid, ls in state.listings.items() if ls.last_seen_at < cutoff]:
        del state.listings[uid]
    state.updated_at = now


async def refresh_all(keys: list[str] | None = None, store: Store | None = None) -> list[SourceResult]:
    """Fetch the given sources (default: all enabled), update state and publish the catalog."""
    from .sources import enabled_sources
    from .sources.base import make_client

    store = store or FileStore()
    available = enabled_sources()
    selected = [k for k in (keys or list(available)) if k in available]
    unknown = set(keys or []) - set(available)
    if unknown:
        log.warning("ignoring unknown/disabled sources: %s", ", ".join(sorted(unknown)))

    state = await store.load_state()
    started_at = datetime.now(timezone.utc)
    async with make_client() as client:
        await update_rates(state, client)
        results = await asyncio.gather(*(run_source(k, client) for k in selected))
    merge_results(state, list(results), started_at)
    await store.save_state(state)
    await store.save_catalog(build_catalog(state))
    return list(results)


async def rebuild_catalog(store: Store | None = None) -> None:
    """Re-publish the catalog from saved state without fetching (e.g. after a code change)."""
    store = store or FileStore()
    state = await store.load_state()
    await store.save_catalog(build_catalog(state))
