"""Send the catalog to the site's database: Cloudflare D1, through the Worker's ingest API.

The home server runs ``hackmash sync`` on a timer: fetch every platform and rebuild
the catalog (``hackmash.pipeline``), then push only what changed. Every hackathon
is one row:

* ``card``: the fields the board needs, without long text. The Worker joins the
  cards of everything still current into the feed the web app downloads.
* ``detail``: every field, served when someone opens the notice.
* ``hash``: of everything in the row, so unchanged rows are not sent again.
* ``listed_until``: when the event stops being current (it ended, or registration
  and submissions both closed), so the feed can leave it out.

The ingest API (``worker/src/ingest.ts``) takes a bearer key and four calls:
``GET state`` (id and hash of every row), ``POST upsert``, ``POST delete`` and
``POST commit`` (taxonomy, exchange rates, platform health and the new version).
The commit goes last, so readers switch to the new data once every row is in.
Because each run compares against what the database really holds, a run that
fails halfway is repaired by the next one.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import time
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from . import __version__

log = logging.getLogger("hackmash.sync")

DEFAULT_API = "https://hackmash.xyz"
DETAIL_ONLY = frozenset({"description", "eligibility", "image_url", "logo_url"})  # only the detail view uses these
FAR_FUTURE = "9999-12-31T23:59:59Z"
CHUNK_BYTES = 600_000  # per upsert request (D1 caps one bound value at 2 MB)
DELETE_CHUNK = 500
MIN_ITEMS = 100  # a catalog smaller than this means scraping broke: don't publish it
MIN_HEALTHY_SOURCES = 3


class IngestError(RuntimeError):
    """The push was refused or failed; the database keeps its previous data."""


# -- rows ---------------------------------------------------------------------------


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def utc_text(dt: datetime | None) -> str | None:
    """ISO 8601 in UTC ending in Z: one format, so the database can compare times as text."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def listed_until(item: dict[str, Any]) -> str:
    """When the event stops being current. Mirrors ``models.lifecycle`` reaching "ended"."""
    sub = _parse(item.get("submission_deadline"))
    reg = _parse(item.get("registration_deadline"))
    end = _parse(item.get("ends_at")) or sub
    if sub:
        # closed out: submissions shut two days ago and registration is shut too
        closed = max(sub + timedelta(days=2), reg) if reg else sub + timedelta(days=2)
        end = min(end, closed) if end else closed
    return utc_text(end) or FAR_FUTURE


def _significant(x: float, digits: int = 3) -> float | int:
    """Exchange rates move every day; a prize's size in dollars doesn't need to."""
    if not x:
        return x
    r = round(x, digits - 1 - math.floor(math.log10(abs(x))))
    return int(r) if r == int(r) else r


def _stable(item: dict[str, Any]) -> dict[str, Any]:
    """The item without values that change on every run while the listing doesn't."""
    out = dict(item)
    if not out.get("delisted"):
        out.pop("last_seen_at", None)  # "checked X ago" comes from the platform's last good run
    if isinstance(out.get("prize_usd"), (int, float)):
        out["prize_usd"] = _significant(out["prize_usd"])
    return out


def _dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


@dataclass(frozen=True)
class Row:
    id: str
    source: str
    title: str
    card: str  # JSON text
    detail: str  # JSON text
    hash: str
    starts_at: str | None
    ends_at: str | None
    registration_deadline: str | None
    submission_deadline: str | None
    listed_until: str
    aliases: tuple[str, ...]  # ids of the same event on other platforms

    def payload(self) -> dict[str, Any]:
        d = asdict(self)
        d["aliases"] = list(self.aliases)
        return d


def make_row(item: dict[str, Any]) -> Row:
    detail = _stable(item)
    card = {k: v for k, v in detail.items() if k not in DETAIL_ONLY}
    card_text, detail_text = _dumps(card), _dumps(detail)
    until = listed_until(item)
    aliases = tuple(sorted({o["id"] for o in item.get("also_on") or [] if o.get("id") and o["id"] != item["id"]}))
    digest = hashlib.sha256("\x1f".join((card_text, detail_text, until, ",".join(aliases))).encode()).hexdigest()
    return Row(
        id=item["id"],
        source=item["source"],
        title=item["title"],
        card=card_text,
        detail=detail_text,
        hash=digest[:20],
        starts_at=utc_text(_parse(item.get("starts_at"))),
        ends_at=utc_text(_parse(item.get("ends_at"))),
        registration_deadline=utc_text(_parse(item.get("registration_deadline"))),
        submission_deadline=utc_text(_parse(item.get("submission_deadline"))),
        listed_until=until,
        aliases=aliases,
    )


def rows_from_catalog(doc: dict[str, Any]) -> list[Row]:
    rows: dict[str, Row] = {}
    for item in doc.get("items", []):
        row = make_row(item)
        rows[row.id] = row
    return list(rows.values())


def meta_from_catalog(doc: dict[str, Any], rows: list[Row]) -> dict[str, Any]:
    """Everything the feed needs besides the rows. ``version`` changes with every run."""
    generated = _parse(doc.get("generated_at")) or datetime.now(timezone.utc)
    h = hashlib.sha256()
    for row in sorted(rows, key=lambda r: r.id):
        h.update(f"{row.id}:{row.hash};".encode())
    h.update(_dumps([doc.get("taxonomy"), doc.get("fx"), doc.get("sources")]).encode())
    return {
        "version": f"{generated:%Y%m%dT%H%M%SZ}-{h.hexdigest()[:10]}",
        "generated_at": utc_text(generated),
        "taxonomy": doc.get("taxonomy") or {},
        "fx": doc.get("fx") or {},
        "sources": doc.get("sources") or [],
    }


def catalog_problems(doc: dict[str, Any]) -> list[str]:
    """Reasons not to publish this catalog at all (scraping broke)."""
    problems = []
    count = len(doc.get("items", []))
    healthy = [s["key"] for s in doc.get("sources", []) if s.get("ok")]
    if count < MIN_ITEMS:
        problems.append(f"only {count} listings (expected at least {MIN_ITEMS})")
    if len(healthy) < MIN_HEALTHY_SOURCES:
        problems.append(f"only {len(healthy)} platforms fetched successfully")
    return problems


# -- the ingest API -------------------------------------------------------------------


class IngestClient:
    """Talks to ``<api>/api/ingest/*`` on the Worker."""

    def __init__(self, api: str, key: str, *, client: httpx.Client | None = None, timeout: float = 90.0) -> None:
        self.base = api.rstrip("/") + "/api/ingest"
        self.http = client or httpx.Client(timeout=timeout)
        self.headers = {"Authorization": f"Bearer {key}", "User-Agent": f"hackmash-sync/{__version__}"}
        self.requests = 0

    def _call(self, method: str, path: str, body: str | None = None) -> dict[str, Any]:
        headers = dict(self.headers)
        if body is not None:
            headers["Content-Type"] = "application/json"
        last: Exception | None = None
        for attempt in range(4):
            if attempt:
                time.sleep(2 * 2**attempt)
            self.requests += 1
            try:
                res = self.http.request(method, f"{self.base}/{path}", content=body, headers=headers)
            except httpx.TransportError as exc:
                last = exc
                continue
            if res.status_code == 429 or res.status_code >= 500:
                last = IngestError(f"{method} {path}: HTTP {res.status_code}: {res.text[:300]}")
                continue
            if res.status_code >= 400:
                raise IngestError(f"{method} {path}: HTTP {res.status_code}: {res.text[:300]}")
            return res.json()
        raise IngestError(f"{method} {path} failed after retries: {last}")

    def state(self) -> dict[str, Any]:
        return self._call("GET", "state")

    def upsert(self, body: str) -> dict[str, Any]:
        return self._call("POST", "upsert", body)

    def delete(self, ids: list[str]) -> dict[str, Any]:
        return self._call("POST", "delete", _dumps(ids))

    def commit(self, meta: dict[str, Any]) -> dict[str, Any]:
        return self._call("POST", "commit", _dumps(meta))


def upsert_bodies(rows: list[Row], limit: int | None = None) -> Iterator[str]:
    """JSON arrays of row payloads, each under ``limit`` bytes (default ``CHUNK_BYTES``)."""
    limit = limit or CHUNK_BYTES
    parts: list[str] = []
    size = 2
    for row in rows:
        part = _dumps(row.payload())
        n = len(part.encode()) + 1
        if parts and size + n > limit:
            yield "[" + ",".join(parts) + "]"
            parts, size = [], 2
        parts.append(part)
        size += n
    if parts:
        yield "[" + ",".join(parts) + "]"


@dataclass
class PushReport:
    version: str
    total: int
    upserted: int
    deleted: int
    unchanged: int
    requests: int
    elapsed: float
    dry_run: bool = False

    def summary(self) -> str:
        verb = "would send" if self.dry_run else "sent"
        return (
            f"{verb} {self.upserted} changed and {self.deleted} removed listings "
            f"({self.unchanged} unchanged, {self.total} in all) as {self.version} "
            f"in {self.requests} requests, {self.elapsed:.1f}s"
        )


def push(doc: dict[str, Any], client: IngestClient, *, dry_run: bool = False, force: bool = False) -> PushReport:
    """Make the database match ``doc``: send changed rows, delete gone ones, then commit."""
    started = time.monotonic()
    problems = catalog_problems(doc)
    if problems and not force:
        raise IngestError("refusing to publish this catalog: " + "; ".join(problems))
    rows = rows_from_catalog(doc)
    meta = meta_from_catalog(doc, rows)

    remote: dict[str, str] = client.state().get("hashes") or {}
    changed = [r for r in rows if remote.get(r.id) != r.hash]
    gone = sorted(set(remote) - {r.id for r in rows})
    if remote and len(gone) > max(100, len(remote) // 2) and not force:
        raise IngestError(f"refusing to delete {len(gone)} of {len(remote)} listings in one run (pass --force if that is right)")

    if not dry_run:
        for body in upsert_bodies(changed):
            client.upsert(body)
        for i in range(0, len(gone), DELETE_CHUNK):
            client.delete(gone[i : i + DELETE_CHUNK])
        client.commit(meta)
    report = PushReport(
        version=meta["version"],
        total=len(rows),
        upserted=len(changed),
        deleted=len(gone),
        unchanged=len(rows) - len(changed),
        requests=client.requests,
        elapsed=time.monotonic() - started,
        dry_run=dry_run,
    )
    log.debug(report.summary())
    return report
