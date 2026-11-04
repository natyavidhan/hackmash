"""Command line entry point.

    hackmash sources                 list registered source adapters
    hackmash fetch <key> [--json]    run one adapter and print a quality report
    hackmash refresh [keys...]       fetch sources, update state, publish the catalog
    hackmash rebuild                 re-publish the catalog from saved state (no fetching)
    hackmash serve                   run the API server
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
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


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("hackmash.server:app", host=args.host, port=args.port, reload=args.reload)
    return 0


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
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

    p = sub.add_parser("serve", help="run the API server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--reload", action="store_true")
    p.set_defaults(func=_cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
