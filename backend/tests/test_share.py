"""Link previews: the poster's text, the line under it, and drawing and sending posters."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from hackmash import share
from hackmash.share import Card, ShareContext, blurb, card_for
from hackmash.sync import IngestClient, make_row

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
CTX = ShareContext(names={"unstop": "Unstop", "devpost": "Devpost"}, themes={"ai": "AI & ML"}, usd_per_inr=0.0106433, now=NOW)


def iso(dt: datetime) -> str:
    return dt.isoformat()


def bharat(**kw) -> dict:
    item = {
        "id": "unstop-1",
        "source": "unstop",
        "title": "Build Your Bharat Hackathon",
        "url": "https://unstop.com/1",
        "organizer": "Next Bharat Ventures",
        "mode": "in_person",
        "city": "Hyderabad",
        "country": "India",
        "timezone": "Asia/Kolkata",
        "starts_at": iso(datetime(2026, 10, 13, 18, 30, tzinfo=timezone.utc)),
        "ends_at": iso(datetime(2026, 11, 21, 12, 30, tzinfo=timezone.utc)),
        "registration_deadline": iso(datetime(2026, 11, 13, 18, 29, tzinfo=timezone.utc)),
        "prize_amount": 500000,
        "prize_currency": "INR",
        "participants": 1383,
        "team_size_min": 3,
        "team_size_max": 5,
        "themes": ["ai"],
    }
    item.update(kw)
    return item


def test_poster_text_uses_the_events_own_calendar():
    card = card_for(bharat(), CTX)
    # 13 Nov 18:29 UTC is 13 Nov 23:59 in India
    assert card.stamp == {"label": "Last date", "date": "13 Nov", "tone": "red"}
    assert (card.when, card.where, card.prize, card.team, card.registered) == (
        "14 Oct – 21 Nov",
        "Hyderabad, India",
        "₹5 lakh",
        "Teams of 3–5",
        "1,383",
    )
    assert card.platform == "Unstop" and card.themes == ("AI & ML",)


def test_stamp_follows_what_is_next():
    later = NOW + timedelta(days=3)
    assert card_for(bharat(registration_deadline=None, submission_deadline=iso(later)), CTX).stamp["label"] == "Submit by"
    upcoming = bharat(registration_deadline=iso(NOW - timedelta(hours=1)), starts_at=iso(NOW + timedelta(days=2)))
    assert card_for(upcoming, CTX).stamp == {"label": "Starts", "date": "13 Nov", "tone": "quiet"}
    running = bharat(registration_deadline=None)
    assert card_for(running, CTX).stamp == {"label": "Ends", "date": "21 Nov", "tone": "live"}
    over = bharat(registration_deadline=None, ends_at=iso(NOW - timedelta(days=1)))
    assert card_for(over, CTX).stamp["label"] == "Ended"


def test_dollar_prizes_get_a_rupee_estimate_and_compact_amounts():
    card = card_for(bharat(prize_amount=1_000_000, prize_currency="USD", country=None, timezone=None, mode="online"), CTX)
    assert (card.prize, card.prize_alt, card.where) == ("$1M", "≈ ₹9.4 crore", "Online")
    assert share.usd(150_000) == "$150k" and share.usd(2_500) == "$2,500"
    assert share.inr(13_000_000) == "₹1.3 crore" and share.inr(45_000) == "₹45,000"
    solo = card_for(bharat(team_size_min=1, team_size_max=1, mode="hybrid", prize_amount=None), CTX)
    assert (solo.team, solo.where, solo.prize) == ("Solo", "Hyderabad + online", None)


def test_blurb_reads_like_the_facts_that_decide_a_click():
    text = blurb(card_for(bharat(), CTX))
    assert text == "Last date 13 Nov · Hyderabad, India · ₹5 lakh prize pool · Teams of 3–5 · 1,383 registered. On Unstop, by Next Bharat Ventures."


def test_poster_hash_changes_with_what_is_drawn():
    base = card_for(bharat(), CTX)
    assert base.hash == card_for(bharat(), CTX).hash
    assert base.hash != card_for(bharat(participants=1400), CTX).hash
    assert base.hash != card_for(bharat(), ShareContext(CTX.names, CTX.themes, CTX.usd_per_inr, NOW + timedelta(days=3))).hash  # stamp moved on
    old, before = share.TEMPLATE_VERSION, base.hash
    try:
        share.TEMPLATE_VERSION = "poster-2"
        assert card_for(bharat(), CTX).hash != before  # a redesign redraws everything
    finally:
        share.TEMPLATE_VERSION = old


def test_rows_carry_the_preview_line_and_poster_hash():
    row = make_row(bharat(), CTX)
    assert row.blurb.startswith("Last date 13 Nov") and row.og == card_for(bharat(), CTX).hash
    assert row.payload()["og"] == row.og


class FakePosters:
    def __init__(self, have: dict[str, str] | None = None) -> None:
        self.have = dict(have or {})
        self.puts: list[tuple[str, str, bytes]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/ingest/")
        if path == "og" and request.method == "GET":
            return httpx.Response(200, json={"hashes": self.have})
        if path.startswith("og/") and request.method == "PUT":
            hid, digest = path.removeprefix("og/"), request.url.params["hash"]
            self.puts.append((hid, digest, request.content))
            self.have[hid] = digest
            return httpx.Response(200, json={"id": hid, "hash": digest})
        return httpx.Response(404)


def test_only_changed_posters_are_drawn_and_sent(monkeypatch, tmp_path):
    from hackmash.og import render

    drawn: list[str] = []

    class StubRenderer:
        def __init__(self, pages: int = 3) -> None: ...

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def render(self, card: dict) -> bytes:
            drawn.append(card["id"])
            assert card["logo"] is None  # no logo_url in these items
            return b"\xff\xd8\xff" + card["id"].encode()

    monkeypatch.setattr(render, "Renderer", StubRenderer)
    doc = {"sources": [{"key": "unstop", "name": "Unstop"}], "fx": {"INR": 0.0106433}, "items": [bharat(id=f"unstop-{i}") for i in range(4)]}
    ctx_now = ShareContext.from_catalog(doc)
    unchanged = card_for(doc["items"][0], ctx_now).hash
    fake = FakePosters(have={"unstop-0": unchanged, "unstop-1": "stale"})
    client = IngestClient("https://example.test", "k" * 64, client=httpx.Client(transport=httpx.MockTransport(fake)))
    report = asyncio.run(render.publish_posters(doc, client, tmp_path))
    assert sorted(drawn) == ["unstop-1", "unstop-2", "unstop-3"]
    assert (report.drawn, report.failed, report.total) == (3, 0, 4)
    assert all(body.startswith(b"\xff\xd8\xff") for _, _, body in fake.puts)
    report = asyncio.run(render.publish_posters(doc, client, tmp_path))
    assert report.drawn == 0  # nothing changed since


def test_logo_cache_refuses_private_addresses_and_non_images(tmp_path):
    from hackmash.og.render import LogoCache, sniff

    assert sniff(b"\x89PNG\r\n\x1a\nxxxx") == "image/png" and sniff(b"<html>nope") is None
    cache = LogoCache(tmp_path)

    async def run(url: str) -> str | None:
        async with httpx.AsyncClient() as http:
            return await cache.data_uri(http, url)

    assert asyncio.run(run("http://example.com/logo.png")) is None  # https only
    assert asyncio.run(run("https://127.0.0.1/logo.png")) is None  # never the home network
    assert asyncio.run(run("https://localhost/logo.png")) is None


def test_a_real_poster_renders(tmp_path):
    pytest.importorskip("playwright")
    from hackmash.og.render import Renderer

    async def draw() -> bytes:
        try:
            async with Renderer(pages=1) as renderer:
                return await renderer.render({**card_for(bharat(title="<img src=x onerror=alert(1)>"), CTX).to_dict(), "logo": None})
        except Exception as exc:  # no browser installed here (CI)
            pytest.skip(f"no headless Chromium: {exc}")

    jpeg = asyncio.run(draw())
    assert jpeg[:3] == b"\xff\xd8\xff" and 20_000 < len(jpeg) < 400_000


def test_card_round_trips_through_json():
    card = card_for(bharat(), CTX)
    assert Card(**{**json.loads(json.dumps(card.to_dict())), "themes": tuple(card.themes)}) == card
