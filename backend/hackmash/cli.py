"""Command line entry point.

    hackmash sources                 list registered source adapters
    hackmash fetch <key> [--json]    run one adapter and print a quality report
    hackmash refresh [keys...]       fetch sources, update state, write the catalog
    hackmash rebuild                 rewrite the catalog from saved state (no fetching)
    hackmash push [--dry-run]        send the catalog's changes to the site's database
    hackmash sync [--dry-run]        refresh, push, then draw link previews: what the home server runs
    hackmash og [--force] [--out D]  draw link-preview posters that changed (or all) and send them
    hackmash serve                   run the API server locally

push and sync read HACKMASH_API (default https://hackmash.xyz) and
HACKMASH_INGEST_KEY (the Worker's INGEST_KEY secret) from the environment.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone

from .models import RawHackathon
from .sources import discover, import_errors
from .sources.base import make_client


def _cmd_sources(_: argparse.Namespace) -> int:
    for key, cls in discover().items():
        flag = "" if cls.enabled else "  (disabled)"
        print(f"{key:<16} {cls.name:<20} {cls.region:<7} {cls.focus}{flag}")
    for mod, err in import_errors.items():
        print(f"!! {mod}: import failed: {err}", file=sys.stderr)
    return 0


def quality_report(items: list[RawHackathon], elapsed: float) -> list[str]:
    """Human readable checks an adapter author should look at."""
    now = datetime.now(timezone.utc)
    lines: list[str] = []
    n = len(items)
    lines.append(f"{n} items in {elapsed:.1f}s")
    if not n:
        lines.append("!! no items returned")
        return lines

    def pct(pred) -> str:
        c = sum(1 for i in items if pred(i))
        return f"{c}/{n} ({100 * c // n}%)"

    fields = {
        "starts_at": lambda i: i.starts_at,
        "ends_at": lambda i: i.ends_at,
        "registration_deadline": lambda i: i.registration_deadline,
        "submission_deadline": lambda i: i.submission_deadline,
        "mode": lambda i: i.mode,
        "location/city/country": lambda i: i.location or i.city or i.country,
        "prize_text": lambda i: i.prize_text,
        "prize_amount+currency": lambda i: i.prize_amount and i.prize_currency,
        "organizer": lambda i: i.organizer,
        "tagline/description": lambda i: i.tagline or i.description,
        "image_url/logo_url": lambda i: i.image_url or i.logo_url,
        "tags": lambda i: i.tags,
        "participants": lambda i: i.participants is not None,
        "team_size_max": lambda i: i.team_size_max,
        "eligibility": lambda i: i.eligibility,
        "registration_fee known": lambda i: i.registration_fee is not None,
    }
    lines.append("field coverage:")
    for name, pred in fields.items():
        lines.append(f"  {name:<24} {pct(pred)}")

    kinds = Counter(i.kind for i in items)
    modes = Counter(i.mode for i in items)
    lines.append(f"kinds: {dict(kinds)}")
    lines.append(f"modes: {dict(modes)}")

    problems: list[str] = []
    ids = Counter(i.source_id for i in items)
    dupes = [k for k, v in ids.items() if v > 1]
    if dupes:
        problems.append(f"duplicate source_id values: {dupes[:5]}")
    for i in items:
        end = i.ends_at or i.submission_deadline
        if end and end < now - timedelta(days=1):
            problems.append(f"already ended ({end:%Y-%m-%d}): {i.title}")
        if i.starts_at and i.ends_at and i.starts_at > i.ends_at:
            problems.append(f"starts after it ends: {i.title}")
        for fname in ("starts_at", "ends_at", "registration_deadline", "submission_deadline"):
            v = getattr(i, fname)
            if v and not (2015 <= v.year <= now.year + 3):
                problems.append(f"suspicious {fname} {v.isoformat()}: {i.title}")
        if not i.url.startswith(("http://", "https://")):
            problems.append(f"url not absolute: {i.url}")
        if "&amp;" in i.title or "<" in i.title or "  " in i.title:
            problems.append(f"title needs cleaning: {i.title!r}")
        if i.prize_amount and not i.prize_currency:
            problems.append(f"prize_amount without currency: {i.title}")
    if problems:
        lines.append(f"!! {len(problems)} problems:")
        lines.extend(f"   - {p}" for p in problems[:25])
        if len(problems) > 25:
            lines.append(f"   … {len(problems) - 25} more")
    else:
        lines.append("no problems found")
    return lines


async def _run_source(key: str) -> tuple[list[RawHackathon], float]:
    registry = discover()
    if key not in registry:
        raise SystemExit(f"unknown source {key!r}; known: {', '.join(registry)}")
    source = registry[key]()
    started = time.monotonic()
    async with make_client() as client:
        items = await source.fetch(client)
    return items, time.monotonic() - started


def _cmd_fetch(args: argparse.Namespace) -> int:
    items, elapsed = asyncio.run(_run_source(args.key))
    if args.json:
        data = [i.model_dump(mode="json") for i in items[: args.limit or None]]
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    for line in quality_report(items, elapsed):
        print(line)
    print("\nsample:")
    for i in items[: args.limit or 3]:
        d = i.model_dump(mode="json", exclude_none=True, exclude={"description", "extra"})
        print(json.dumps(d, indent=2, ensure_ascii=False))
    return 0


def _cmd_refresh(args: argparse.Namespace) -> int:
    from .pipeline import refresh_all

    results = asyncio.run(refresh_all(args.keys or None))
    for r in sorted(results, key=lambda r: r.source):
        status = "ok" if r.ok else f"FAILED: {r.error}"
        print(f"{r.source:<16} {r.count:>5} items  {r.elapsed:5.1f}s  {status}")
    return 0 if all(r.ok for r in results) else 1


def _cmd_rebuild(_: argparse.Namespace) -> int:
    from .pipeline import rebuild_catalog

    asyncio.run(rebuild_catalog())
    print("catalog rebuilt from saved state")
    return 0


@contextlib.contextmanager
def _run_lock():
    """One sync at a time (a manual run and the timer must not interleave)."""
    import fcntl

    from .state import FileStore

    path = FileStore().dir / "sync.lock"
    with open(path, "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        try:
            yield True
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _push_catalog(args: argparse.Namespace) -> int:
    from .state import FileStore
    from .sync import DEFAULT_API, IngestClient, IngestError, catalog_problems, push, rows_from_catalog

    data = asyncio.run(FileStore().load_catalog())
    if data is None:
        print("no catalog yet: run `hackmash refresh` first", file=sys.stderr)
        return 1
    doc = json.loads(data)
    api = args.api or os.environ.get("HACKMASH_API") or DEFAULT_API
    key = os.environ.get("HACKMASH_INGEST_KEY", "")
    if not key:
        if args.dry_run:
            problems = catalog_problems(doc)
            print(f"{len(rows_from_catalog(doc))} rows ready; set HACKMASH_INGEST_KEY to compare with {api}")
            for p in problems:
                print(f"!! {p}")
            return 1 if problems else 0
        print("HACKMASH_INGEST_KEY is not set (it must match the Worker's INGEST_KEY secret)", file=sys.stderr)
        return 1
    try:
        report = push(doc, IngestClient(api, key), dry_run=args.dry_run, force=args.force)
    except IngestError as exc:
        print(f"push to {api} failed: {exc}", file=sys.stderr)
        return 1
    print(report.summary())
    return 0


def _cmd_push(args: argparse.Namespace) -> int:
    return _push_catalog(args)


def _publish_posters(args: argparse.Namespace, *, force: bool = False, only: list[str] | None = None, out: str | None = None) -> int:
    """Draw the link-preview posters that changed and send them. 0 = done or skipped, 1 = failed."""
    from pathlib import Path

    from .state import FileStore
    from .sync import DEFAULT_API, IngestClient

    try:
        import playwright  # noqa: F401  (the `og` extra)

        from .og.render import publish_posters
    except ImportError:
        print("link previews skipped: install them with `uv sync --extra og` and `uv run playwright install chromium --only-shell`")
        return 0
    store = FileStore()
    data = asyncio.run(store.load_catalog())
    if data is None:
        print("no catalog yet: run `hackmash refresh` first", file=sys.stderr)
        return 1
    client = None
    if not out:
        key = os.environ.get("HACKMASH_INGEST_KEY", "")
        if not key:
            print("HACKMASH_INGEST_KEY is not set, so posters can't be sent (or pass --out DIR)", file=sys.stderr)
            return 1
        client = IngestClient(args.api or os.environ.get("HACKMASH_API") or DEFAULT_API, key)
    try:
        report = asyncio.run(
            publish_posters(json.loads(data), client, store.dir, force=force, only=set(only) if only else None, out_dir=Path(out) if out else None)
        )
    except Exception as exc:  # noqa: BLE001 - the data is already published; report and move on
        print(f"!! link-preview posters failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(report.summary())
    return 1 if report.failed and not report.drawn else 0


def _cmd_og(args: argparse.Namespace) -> int:
    return _publish_posters(args, force=args.force, only=args.only, out=args.out)


def wait_for_network(url: str, timeout: float = 180.0, interval: float = 5.0) -> bool:
    """Wait until the site's host name resolves.

    A run that was missed while the machine was off starts right after boot, and a
    systemd *user* timer cannot wait for network-online.target (that is a system
    target), so the job waits here instead of failing every fetch.
    """
    import socket
    from urllib.parse import urlparse

    host = urlparse(url).hostname or url
    deadline = time.monotonic() + timeout
    while True:
        try:
            socket.getaddrinfo(host, 443)
            return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(interval)


def _cmd_sync(args: argparse.Namespace) -> int:
    from .sync import DEFAULT_API

    with _run_lock() as got:
        if not got:
            print("another sync is already running; leaving it to finish")
            return 0
        api = args.api or os.environ.get("HACKMASH_API") or DEFAULT_API
        if not wait_for_network(api):
            print("still no network after 3 minutes; trying anyway")
        started = time.monotonic()
        if _cmd_refresh(argparse.Namespace(keys=[])) != 0:
            print("some platforms failed; they keep their previous listings")
        code = _push_catalog(args)
        if code == 0 and not args.dry_run and not args.no_posters:
            code = _publish_posters(args)
        print(f"sync finished in {time.monotonic() - started:.0f}s")
        return code


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("hackmash.server:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # one line per request drowns the summary
    parser = argparse.ArgumentParser(prog="hackmash")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sources", help="list source adapters").set_defaults(func=_cmd_sources)

    p = sub.add_parser("fetch", help="run one adapter and print a quality report")
    p.add_argument("key")
    p.add_argument("--json", action="store_true", help="dump items as JSON")
    p.add_argument("--limit", type=int, default=0)
    p.set_defaults(func=_cmd_fetch)

    p = sub.add_parser("refresh", help="fetch sources and update the database")
    p.add_argument("keys", nargs="*")
    p.set_defaults(func=_cmd_refresh)

    sub.add_parser("rebuild", help="rebuild the catalog from saved state").set_defaults(func=_cmd_rebuild)

    for name, func, text in (
        ("push", _cmd_push, "send the catalog's changes to the site's database"),
        ("sync", _cmd_sync, "fetch every platform, then push (what the home server runs)"),
    ):
        p = sub.add_parser(name, help=text)
        p.add_argument("--dry-run", action="store_true", help="compare with the database but change nothing")
        p.add_argument("--force", action="store_true", help="publish even if the catalog looks broken")
        p.add_argument("--api", help="site to push to (default: $HACKMASH_API or https://hackmash.xyz)")
        if name == "sync":
            p.add_argument("--no-posters", action="store_true", help="skip drawing link-preview posters")
        p.set_defaults(func=func)

    p = sub.add_parser("og", help="draw link-preview posters that changed and send them")
    p.add_argument("--force", action="store_true", help="draw every poster again")
    p.add_argument("--only", nargs="+", metavar="ID", help="just these hackathons")
    p.add_argument("--out", metavar="DIR", help="write the images to DIR instead of sending them")
    p.add_argument("--api", help="site to send to (default: $HACKMASH_API or https://hackmash.xyz)")
    p.set_defaults(func=_cmd_og)

    p = sub.add_parser("serve", help="run the API server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")
    p.set_defaults(func=_cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
