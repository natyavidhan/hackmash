from datetime import datetime, timezone

from hackmash.dedupe import dedupe
from hackmash.geo import canonical_state, find_place, unplaced
from hackmash.models import RawHackathon
from hackmash.normalize import STATIC_USD_RATES, normalize

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def place(**kw):
    base = {"source": "unstop", "source_id": "1", "title": "Test Hack", "url": "https://example.com", "mode": "in_person"}
    base.update(kw)
    return normalize(RawHackathon(**base), STATIC_USD_RATES, NOW, NOW)


def test_state_spellings_platforms_use():
    assert canonical_state("Tamilnadu") == "Tamil Nadu"
    assert canonical_state("Orissa") == "Odisha"
    assert canonical_state("Jammu & Kashmir") == "Jammu and Kashmir"
    assert canonical_state("NCT of Delhi") == "Delhi"
    assert canonical_state("California") is None
    assert canonical_state(None) is None


def test_a_place_must_be_in_the_state_the_platform_gave():
    # GeoNames also calls Itanagar "Kalyanpur": IIT Kanpur's fest must stay in Kanpur
    kanpur = find_place("Kalyanpur", "Uttar Pradesh")
    assert (kanpur.name, kanpur.state) == ("Kanpur", "Uttar Pradesh")
    assert find_place("Manali", "Himachal Pradesh").state == "Himachal Pradesh"
    assert find_place("Manali", "Tamil Nadu").state == "Tamil Nadu"
    stray = find_place("Kalyanpur")
    assert stray is None or stray.state != "Arunachal Pradesh"


def test_other_names_and_aliases():
    assert find_place("Bangalore").name == "Bengaluru"
    assert find_place("Gurgaon", "Haryana").name == "Gurugram"
    assert find_place("Bangalore Urban", "Karnataka").name == "Bengaluru"
    assert find_place("West Delhi", "Delhi").name == "Delhi"
    assert find_place("Gautam Buddha Nagar", "Uttar Pradesh").name == "Noida"
    assert find_place("") is None and find_place("Nowhereville") is None


def test_an_indian_listing_gets_city_state_and_a_city_pin():
    h = place(city="Bangalore", state="Karnataka", country="India",
              location="BMS Institute of Technology and Management, Bangalore, Karnataka, India")
    assert (h.city, h.state, h.country) == ("Bengaluru", "Karnataka", "India")
    assert abs(h.lat - 12.97) < 0.05 and abs(h.lng - 77.59) < 0.05


def test_state_from_old_saved_listings_and_from_the_address():
    # listings saved before `state` existed keep it in extra
    old = place(city="Kalyanpur", country="India", extra={"state": "Uttar Pradesh"})
    assert (old.city, old.state) == ("Kanpur", "Uttar Pradesh")
    # no city field: read the address from the end
    venue = place(source="devnovate", country="India", location="Microsoft Office , New Delhi")
    assert (venue.city, venue.state) == ("Delhi", "Delhi") and venue.lat is not None


def test_no_pin_rather_than_a_guess():
    h = place(city="Nowhereville", state="Goa", country="India")
    assert (h.city, h.state, h.lat, h.lng) == ("Nowhereville", "Goa", None, None)
    assert unplaced([h]) == {"Nowhereville, Goa": 1}


def test_online_and_listings_abroad():
    online = place(mode="online", city="Pune", state="Maharashtra", country="India")
    assert (online.state, online.lat) == (None, None)
    belmont = place(source="hackclub", city="Belmont", country="US", lat=37.508536, lng=-122.291951,
                    location="Belmont, California, United States")
    assert (belmont.state, belmont.lat, belmont.lng) == (None, 37.509, -122.292)
    austin = place(source="mlh", city="Austin", country="US")
    assert austin.lat is None


def test_merged_listing_keeps_a_pin_only_for_its_own_city():
    start = datetime(2026, 12, 1, tzinfo=timezone.utc)
    devpost = place(source="devpost", source_id="a", title="Build Week Hackathon", starts_at=start, city="Pune", country="India")
    unstop = place(source="unstop", source_id="b", title="Build Week Hackathon", starts_at=start, city="Pune", country="India",
                   state="Maharashtra")
    devpost_no_pin = devpost.model_copy(update={"lat": None, "lng": None, "state": None})
    [merged] = dedupe([devpost_no_pin, unstop])
    assert merged.state == "Maharashtra" and merged.lat == unstop.lat
