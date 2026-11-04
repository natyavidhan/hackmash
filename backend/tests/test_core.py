from datetime import datetime, timedelta, timezone

import pytest

from hackmash.catalog import build_items, is_junk
from hackmash.dedupe import dedupe, title_key
from hackmash.ics import calendar
from hackmash.models import Hackathon, RawHackathon, lifecycle
from hackmash.normalize import STATIC_USD_RATES, classify_audience, classify_themes, normalize, resolve_place
from hackmash.query import LoadedCatalog, Query
from hackmash.sources.base import parse_money, to_utc
from hackmash.sources.devpost import parse_period
from hackmash.state import ListingState, RunInfo, SourceState, State, dumps

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def raw(**kw) -> RawHackathon:
    base = {"source": "devpost", "source_id": "1", "title": "Test Hack", "url": "https://example.com"}
    base.update(kw)
    return RawHackathon(**base)


def hack(**kw) -> Hackathon:
    r = raw(**kw)
    return normalize(r, STATIC_USD_RATES, NOW, NOW)


# -- parsing -------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("$10,000 in prizes", (10000.0, "USD")),
        ("₹1.5 Lakh", (150000.0, "INR")),
        ("INR 50K", (50000.0, "INR")),
        ("Prizes worth Rs. 2,00,000", (200000.0, "INR")),
        ("€5k + swag", (5000.0, "EUR")),
        ("10,000 USDC", (10000.0, "USD")),
        ("1 crore", (None, None)),  # no currency marker and no default
        ("Swag and certificates", (None, None)),
    ],
)
def test_parse_money(text, expected):
    assert parse_money(text) == expected


def test_parse_money_takes_largest_amount():
    assert parse_money("1st: $5,000, 2nd: $3,000, total $10,000") == (10000.0, "USD")


def test_to_utc_handles_naive_local_and_epochs():
    assert to_utc("2026-11-14 10:00", "Asia/Kolkata") == datetime(2026, 11, 14, 4, 30, tzinfo=timezone.utc)
    assert to_utc(1797078600) == datetime.fromtimestamp(1797078600, tz=timezone.utc)
    assert to_utc(1797078600000) == datetime.fromtimestamp(1797078600, tz=timezone.utc)
    assert to_utc("") is None and to_utc("not a date") is None


def test_devpost_period_crosses_year_boundary():
    start, end = parse_period("Dec 15 - Jan 20, 2027")
    assert start.year == 2026 and start.month == 12 and end.year == 2027


def test_raw_rejects_naive_datetimes():
    with pytest.raises(ValueError):
        raw(starts_at=datetime(2026, 1, 1))


# -- normalisation ---------------------------------------------------------------


def test_resolve_place_from_location_strings():
    assert resolve_place(raw(mode="in_person", location="Boston, MA"))[1:] == ("United States", "US")
    assert resolve_place(raw(mode="in_person", location="Bengaluru, Karnataka, India"))[0] == "Bengaluru"
    assert resolve_place(raw(mode="in_person", location="Toronto, ON, Canada"))[1] == "Canada"
    assert resolve_place(raw(mode="online", location="Online")) == (None, None, None)


def test_themes_from_tags_and_title():
    themes = classify_themes(raw(title="GenAI for Healthcare", tags=["Machine Learning/AI", "Blockchain"]))
    assert {"ai", "health", "web3"} <= set(themes)
    assert "web" not in classify_themes(raw(title="Web3 Builders Summit"))


def test_audience_from_eligibility_and_source():
    assert "students" in classify_audience(raw(eligibility=["Engineering Students"]))
    assert "high_school" in classify_audience(raw(source="hackclub"))
    assert "women" in classify_audience(raw(title="Women in Tech Hackathon"))


def test_normalize_converts_prize_and_duration():
    h = hack(
        prize_amount=100000,
        prize_currency="INR",
        starts_at=NOW,
        ends_at=NOW + timedelta(hours=36),
        image_url="https://x.com/defaults/thumbnail-placeholder.gif",
    )
    assert h.prize_usd == pytest.approx(100000 * STATIC_USD_RATES["INR"])
    assert h.duration_hours == 36.0
    assert h.image_url is None  # placeholder art dropped


# -- lifecycle -------------------------------------------------------------------


def test_lifecycle_states():
    assert lifecycle(raw(starts_at=NOW + timedelta(days=5)), NOW) == ("open", True)
    assert lifecycle(raw(starts_at=NOW - timedelta(days=1), ends_at=NOW + timedelta(days=1)), NOW) == ("live", True)
    assert lifecycle(raw(ends_at=NOW - timedelta(minutes=1)), NOW) == ("ended", False)
    closed = raw(starts_at=NOW + timedelta(days=5), registration_deadline=NOW - timedelta(hours=1))
    assert lifecycle(closed, NOW) == ("upcoming", False)


def test_lifecycle_closed_out_listing_with_far_future_end():
    zombie = raw(
        starts_at=NOW - timedelta(days=400),
        ends_at=NOW + timedelta(days=380),
        registration_deadline=NOW - timedelta(days=370),
        submission_deadline=NOW - timedelta(days=365),
    )
    assert lifecycle(zombie, NOW)[0] == "ended"


# -- dedupe ----------------------------------------------------------------------


def test_title_key_strips_years_and_editions():
    assert title_key("HackMIT 2026") == title_key("HackMIT")
    assert title_key("Hack This Fall 5.0") == title_key("Hack This Fall")


def test_dedupe_merges_same_event_across_platforms():
    start = NOW + timedelta(days=10)
    a = hack(source="devpost", source_id="1", title="HackRPI 2026", starts_at=start, mode="in_person", prize_amount=3850, prize_currency="USD")
    b = hack(source="mlh", source_id="9", title="HackRPI", starts_at=start + timedelta(hours=6), mode="in_person", beginner_friendly=True)
    c = hack(source="unstop", source_id="5", title="Totally Different Hack", starts_at=start, mode="in_person")
    out = dedupe([a, b, c])
    assert len(out) == 2
    merged = next(h for h in out if h.also_on)
    assert merged.source == "devpost" and merged.also_on[0].source == "mlh"
    assert merged.beginner_friendly is True  # filled from the MLH listing


def test_dedupe_keeps_online_and_in_person_editions_apart():
    start = NOW + timedelta(days=10)
    a = hack(source="devpost", title="CityHacks", starts_at=start, mode="online")
    b = hack(source="mlh", source_id="2", title="CityHacks", starts_at=start, mode="in_person")
    assert len(dedupe([a, b])) == 2


# -- catalog + query + ics ----------------------------------------------------------


def _state_with(*items: RawHackathon) -> State:
    state = State()
    for r in items:
        state.listings[r.uid] = ListingState(raw=r, first_seen_at=NOW, last_seen_at=NOW)
    run = RunInfo(started_at=NOW, finished_at=NOW, ok=True, count=len(items))
    state.sources["devpost"] = SourceState(last_run=run, last_ok=run)
    return state


def test_build_items_drops_invite_only_and_test_events():
    state = _state_with(
        raw(source_id="1", title="Real Hack", starts_at=NOW + timedelta(days=3)),
        raw(source_id="2", title="Internal Hack", invite_only=True),
        raw(source_id="3", title="kyc test", participants=2),
    )
    titles = [h.title for h in build_items(state, NOW)]
    assert titles == ["Real Hack"]
    assert is_junk(hack(title="Mock Hackathon", participants=3))


def test_query_search_filters_and_sorts():
    soon = NOW + timedelta(days=2)
    later = NOW + timedelta(days=20)
    items = [
        hack(source_id="1", title="AI Sprint", tags=["AI"], mode="online", submission_deadline=later, ends_at=later),
        hack(source_id="2", title="Climate Jam", mode="in_person", location="Pune", submission_deadline=soon, ends_at=soon),
    ]
    doc = {"generated_at": NOW.isoformat(), "items": [h.model_dump(mode="json") for h in items], "sources": []}
    cat = LoadedCatalog(dumps(doc))
    total, found = cat.search(Query(q="ai"), now=NOW)
    assert total == 1 and found[0]["title"] == "AI Sprint"
    total, found = cat.search(Query(sort="deadline"), now=NOW)
    assert [f["title"] for f in found] == ["Climate Jam", "AI Sprint"]
    total, _ = cat.search(Query(mode=["online"]), now=NOW)
    assert total == 1


def test_ics_has_reminders_and_folded_lines():
    h = hack(
        title="A very long hackathon title that will definitely need folding in the calendar output",
        starts_at=NOW + timedelta(days=5),
        ends_at=NOW + timedelta(days=7),
        registration_deadline=NOW + timedelta(days=3),
    ).model_dump(mode="json")
    text = calendar([h])
    assert text.startswith("BEGIN:VCALENDAR\r\n") and text.endswith("END:VCALENDAR\r\n")
    assert "TRIGGER:-P2D" in text and "Registration closes" in text
    assert all(len(line.encode()) <= 75 for line in text.split("\r\n"))


def test_deadline_extension_is_detected_between_scrapes():
    from hackmash.catalog import build_items
    from hackmash.pipeline import SourceResult, merge_results

    now = datetime.now(timezone.utc)
    first = raw(source_id="7", title="Extend Me", registration_deadline=now + timedelta(days=1), starts_at=now + timedelta(days=9))
    state = State()
    merge_results(state, [SourceResult("devpost", True, 1, 0.1, items=[first])], now)
    later = first.model_copy(update={"registration_deadline": now + timedelta(days=6)})
    merge_results(state, [SourceResult("devpost", True, 1, 0.1, items=[later])], now)
    (item,) = build_items(state)
    assert item.deadline_extended is not None
    assert item.deadline_extended.field == "registration_deadline"


def test_hiring_flag_and_high_school_audience():
    assert hack(title="Flipkart GRiD 7.0: PPO and internship offers").hiring is True
    assert hack(prize_text="Pre-placement interviews for top teams").hiring is True
    assert hack(title="Weekend Build Jam").hiring is False
    audience = classify_audience(raw(eligibility=["High school students only"]))
    assert audience == ["high_school"]
