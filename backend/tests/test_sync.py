"""The push to the site's database: rows, diffs, ordering and safety checks."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from hackmash.models import RawHackathon, lifecycle
from hackmash.sync import (
    FAR_FUTURE,
    IngestClient,
    IngestError,
    listed_until,
    make_row,
    push,
)

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def item(i: int, **kw) -> dict:
    base = {
        "id": f"devpost-{i}",
        "source": "devpost",
        "title": f"Hack {i}",
        "url": f"https://devpost.com/{i}",
        "description": "Long text " * 50,
        "image_url": "https://img/x.png",
        "starts_at": iso(NOW + timedelta(days=10)),
        "ends_at": iso(NOW + timedelta(days=12)),
        "first_seen_at": iso(NOW - timedelta(days=3)),
        "last_seen_at": iso(NOW),
    }
    base.update(kw)
    return base


def catalog(items: list[dict], generated: datetime = NOW) -> dict:
    sources = [{"key": k, "ok": True} for k in ("devpost", "unstop", "mlh")]
    return {"generated_at": iso(generated), "taxonomy": {"themes": {}}, "fx": {"USD": 1}, "sources": sources, "items": items}


class FakeIngest:
    """The Worker's ingest API, in memory."""

    def __init__(self, key: str = "k" * 64) -> None:
        self.key = key
        self.rows: dict[str, dict] = {}
        self.meta: dict = {}
        self.calls: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.headers.get("authorization") != f"Bearer {self.key}":
            return httpx.Response(401, json={"error": "unauthorized"})
        path = request.url.path.removeprefix("/api/ingest/")
        self.calls.append(path)
        if path == "state":
            return httpx.Response(200, json={"version": self.meta.get("version"), "hashes": {k: v["hash"] for k, v in self.rows.items()}})
        body = json.loads(request.content)
        if path == "upsert":
            for row in body:
                self.rows[row["id"]] = row
            return httpx.Response(200, json={"upserted": len(body)})
        if path == "delete":
            for rid in body:
                self.rows.pop(rid, None)
            return httpx.Response(200, json={"deleted": len(body)})
        if path == "commit":
            self.meta = body
            return httpx.Response(200, json={"version": body["version"]})
        return httpx.Response(404)


def client_for(fake: FakeIngest) -> IngestClient:
    return IngestClient("https://example.test", fake.key, client=httpx.Client(transport=httpx.MockTransport(fake)))


def test_card_leaves_out_long_text_and_volatile_fields():
    row = make_row(item(1, prize_usd=12345.678))
    card, detail = json.loads(row.card), json.loads(row.detail)
    assert "description" not in card and "image_url" not in card
    assert detail["description"].startswith("Long text")
    assert "last_seen_at" not in card and "last_seen_at" not in detail
    assert card["prize_usd"] == 12300
    # a delisted listing keeps the time it was last seen: it no longer changes
    assert "last_seen_at" in json.loads(make_row(item(2, delisted=True)).card)


def test_hash_ignores_last_seen_but_not_real_changes():
    a = make_row(item(1, last_seen_at=iso(NOW)))
    b = make_row(item(1, last_seen_at=iso(NOW + timedelta(hours=3))))
    c = make_row(item(1, participants=40))
    assert a.hash == b.hash != c.hash


def test_listed_until_matches_lifecycle():
    ends = item(1)
    assert listed_until(ends) == "2026-11-23T12:00:00Z"
    # submissions closed long ago, registration too: off the feed two days after submissions closed
    zombie = item(2, ends_at=iso(NOW + timedelta(days=300)), submission_deadline=iso(NOW - timedelta(days=5)),
                  registration_deadline=iso(NOW - timedelta(days=9)))
    assert listed_until(zombie) == "2026-11-08T12:00:00Z"
    raw = RawHackathon(source="devpost", source_id="2", title="z", url="https://x",
                       ends_at=NOW + timedelta(days=300), submission_deadline=NOW - timedelta(days=5),
                       registration_deadline=NOW - timedelta(days=9))
    assert lifecycle(raw, NOW)[0] == "ended"
    assert listed_until(item(3, starts_at=None, ends_at=None)) == FAR_FUTURE


def test_in_person_event_under_way_takes_no_registrations():
    started = dict(source="mlh", source_id="1", title="x", url="https://x", starts_at=NOW - timedelta(hours=2),
                   ends_at=NOW + timedelta(days=1))
    assert lifecycle(RawHackathon(**started, mode="in_person"), NOW) == ("live", False)
    assert lifecycle(RawHackathon(**started, mode="online"), NOW) == ("live", True)
    stated = RawHackathon(**started, mode="in_person", registration_deadline=NOW + timedelta(hours=5))
    assert lifecycle(stated, NOW) == ("live", True)


def test_push_sends_only_changes_and_commits_last():
    fake = FakeIngest()
    items = [item(i) for i in range(120)]
    first = push(catalog(items), client_for(fake))
    assert first.upserted == 120 and first.deleted == 0
    assert fake.calls[0] == "state" and fake.calls[-1] == "commit"
    assert fake.meta["version"].startswith("20261111T120000Z-")

    fake.calls.clear()
    again = push(catalog(items, NOW + timedelta(hours=3)), client_for(fake))
    assert again.upserted == 0 and fake.calls == ["state", "commit"]
    assert fake.meta["version"].startswith("20261111T150000Z-")  # every run is a new version

    items[5]["participants"] = 99
    gone = items.pop()
    third = push(catalog(items), client_for(fake))
    assert (third.upserted, third.deleted) == (1, 1)
    assert gone["id"] not in fake.rows and json.loads(fake.rows["devpost-5"]["card"])["participants"] == 99


def test_push_splits_large_uploads():
    fake = FakeIngest()
    from hackmash import sync

    big = [item(i, tagline="x" * 3000) for i in range(150)]
    original = sync.CHUNK_BYTES
    try:
        sync.CHUNK_BYTES = 100_000
        push(catalog(big), client_for(fake))
    finally:
        sync.CHUNK_BYTES = original
    assert fake.calls.count("upsert") >= 5 and len(fake.rows) == 150


def test_push_refuses_broken_catalogs_and_mass_deletes():
    fake = FakeIngest()
    with pytest.raises(IngestError, match="only 3 listings"):
        push(catalog([item(i) for i in range(3)]), client_for(fake))
    assert fake.calls == []  # nothing was even read

    push(catalog([item(i) for i in range(400)]), client_for(fake))
    with pytest.raises(IngestError, match="refusing to delete"):
        push(catalog([item(i) for i in range(150)]), client_for(fake))
    assert len(fake.rows) == 400
    push(catalog([item(i) for i in range(150)]), client_for(fake), force=True)
    assert len(fake.rows) == 150


def test_dry_run_changes_nothing_and_wrong_key_fails():
    fake = FakeIngest()
    report = push(catalog([item(i) for i in range(120)]), client_for(fake), dry_run=True)
    assert report.upserted == 120 and fake.rows == {} and fake.calls == ["state"]
    bad = IngestClient("https://example.test", "nope", client=httpx.Client(transport=httpx.MockTransport(fake)))
    with pytest.raises(IngestError, match="401"):
        push(catalog([item(i) for i in range(120)]), bad)
