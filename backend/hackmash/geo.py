"""Where an in-person event is: a canonical city, its state and the city's coordinates.

Pins on the map mark the city, never the venue. Platforms give the venue as free
text ("CMR College of Engineering, Kandlakoya, Medchal") plus a city and a
state; a city is as precise as we can be without guessing.

In India the city is looked up in a bundled list of places (GeoNames, every
place with more than 5,000 people, CC BY 4.0; ``scripts/build_places.py``
regenerates it):

1. the alias table first, for spellings platforms use that the list lacks:
   districts ("Bangalore Urban"), localities ("Pitampura"), campuses
   ("KSR Kalvi Nagar");
2. then a place's own name, then its other names ("Bangalore", "Gurgaon").

A match must lie in the state the platform gave. GeoNames also knows Itanagar
as "Kalyanpur", and IIT Kanpur (in Kanpur's Kalyanpur) must not land in
Arunachal Pradesh. Without a state, another name only counts for a big place.

Outside India only coordinates the platform itself published are used. When
nothing matches, the event gets no pin: the map counts it instead of guessing.
"""

from __future__ import annotations

import gzip
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Hackathon, RawHackathon

PLACES_FILE = Path(__file__).with_name("data") / "places_in.tsv.gz"

# States and union territories, as the site names them.
STATES = (
    "Andaman and Nicobar", "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar", "Chandigarh",
    "Chhattisgarh", "Dadra and Nagar Haveli and Daman and Diu", "Delhi", "Goa", "Gujarat", "Haryana",
    "Himachal Pradesh", "Jammu and Kashmir", "Jharkhand", "Karnataka", "Kerala", "Ladakh", "Lakshadweep",
    "Madhya Pradesh", "Maharashtra", "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha", "Puducherry",
    "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana", "Tripura", "Uttar Pradesh", "Uttarakhand",
    "West Bengal",
)


def fold(text: str | None) -> str:
    """Lowercase ASCII words: "Bengalūru, (KA)" -> "bengaluru ka"."""
    text = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", text.replace("&", " and ")).strip()


_STATE_BY_KEY = {fold(s): s for s in STATES}
_STATE_BY_KEY.update(
    {
        "andaman and nicobar islands": "Andaman and Nicobar", "andaman": "Andaman and Nicobar",
        "orissa": "Odisha", "pondicherry": "Puducherry", "uttaranchal": "Uttarakhand",
        "tamilnadu": "Tamil Nadu", "telengana": "Telangana", "chattisgarh": "Chhattisgarh",
        "chhattishgarh": "Chhattisgarh", "new delhi": "Delhi", "nct of delhi": "Delhi", "delhi ncr": "Delhi",
        "national capital territory of delhi": "Delhi", "j and k": "Jammu and Kashmir",
        "dadra and nagar haveli": "Dadra and Nagar Haveli and Daman and Diu",
        "daman and diu": "Dadra and Nagar Haveli and Daman and Diu",
    }
)


def canonical_state(value: str | None) -> str | None:
    """The site's name for an Indian state or union territory, or None if it isn't one."""
    return _STATE_BY_KEY.get(fold(value))


@dataclass(frozen=True)
class Place:
    name: str
    state: str
    lat: float
    lng: float
    pop: int


@lru_cache(maxsize=1)
def _places() -> tuple[dict[str, list[Place]], dict[str, list[Place]]]:
    """(by own name, by other names), both keyed by folded name."""
    own: dict[str, list[Place]] = {}
    other: dict[str, list[Place]] = {}
    for line in gzip.decompress(PLACES_FILE.read_bytes()).decode("utf-8").splitlines():
        name, state, lat, lng, pop, alts = line.split("\t")
        place = Place(name, state, float(lat), float(lng), int(pop))
        own.setdefault(fold(name), []).append(place)
        for alt in alts.split("|") if alts else ():
            other.setdefault(alt, []).append(place)
    return own, other


# Platform spellings the list lacks -> (place in the list, its state). Keyed by
# (folded name, state the platform gave), or (folded name, None) for any state.
_ALIASES: dict[tuple[str, str | None], tuple[str, str]] = {
    ("bangalore urban", None): ("Bengaluru", "Karnataka"),
    ("bangalore rural", None): ("Bengaluru", "Karnataka"),
    ("bengaluru urban", None): ("Bengaluru", "Karnataka"),
    ("soladevanahalli", None): ("Bengaluru", "Karnataka"),
    ("tumakur", None): ("Tumakuru", "Karnataka"),
    ("gautam buddha nagar", None): ("Noida", "Uttar Pradesh"),
    ("sahibabad", None): ("Ghaziabad", "Uttar Pradesh"),
    ("kalyanpur", "Uttar Pradesh"): ("Kanpur", "Uttar Pradesh"),  # IIT Kanpur's locality
    ("bandra", None): ("Mumbai", "Maharashtra"),
    ("andheri", None): ("Mumbai", "Maharashtra"),
    ("south goa", None): ("Margao", "Goa"),
    ("north goa", None): ("Panaji", "Goa"),
    ("goa", None): ("Panaji", "Goa"),
    ("myladi", None): ("Nagercoil", "Tamil Nadu"),
    ("ksr kalvi nagar", None): ("Tiruchengode", "Tamil Nadu"),
    ("bidhannagar", None): ("Kolkata", "West Bengal"),
    ("salt lake", None): ("Kolkata", "West Bengal"),
    ("salt lake city", "West Bengal"): ("Kolkata", "West Bengal"),
    ("purba medinipur", None): ("Tamluk", "West Bengal"),
    ("purba medinipur district", None): ("Tamluk", "West Bengal"),
    ("madhuravada", None): ("Visakhapatnam", "Andhra Pradesh"),
    ("atal nagar nava raipur", None): ("Raipur", "Chhattisgarh"),
    ("nava raipur", None): ("Raipur", "Chhattisgarh"),
    ("naya raipur", None): ("Raipur", "Chhattisgarh"),
    ("kothri kalan", None): ("Bhopal", "Madhya Pradesh"),  # VIT Bhopal's campus
}
for _part in ("west", "south", "north", "east", "central", "north west", "south west", "north east", "new"):
    _ALIASES[(f"{_part} delhi", None)] = ("Delhi", "Delhi")
for _locality in ("pitampura", "dwarka", "rohini", "okhla", "karol bagh", "connaught place", "saket", "vasant kunj"):
    _ALIASES[(_locality, None)] = ("Delhi", "Delhi")

BIG_PLACE = 200_000  # without a state, another name ("Bangalore") only counts for a place this big


def _named(name: str, state: str) -> Place | None:
    found = [p for p in _places()[0].get(fold(name), []) if p.state == state]
    return max(found, key=lambda p: p.pop) if found else None


def find_place(name: str | None, state: str | None = None) -> Place | None:
    """The place in India a platform's city string means, honouring its state."""
    key = fold(name)
    if not key:
        return None
    alias = _ALIASES.get((key, state)) or _ALIASES.get((key, None))
    if alias:
        return _named(*alias)
    own, other = _places()
    found = [p for p in own.get(key, []) if not state or p.state == state]
    if not found:
        found = [p for p in other.get(key, []) if (p.state == state if state else p.pop >= BIG_PLACE)]
    return max(found, key=lambda p: p.pop) if found else None


def _state_in(text: str | None) -> str | None:
    """A state named in an address, reading from the end: "..., Pune, Maharashtra 411001, India"."""
    for part in reversed([fold(p) for p in (text or "").split(",")]):
        part = re.sub(r"\s*\d+$", "", part)
        if part in _STATE_BY_KEY:
            return _STATE_BY_KEY[part]
    return None


def _coord(value: object, limit: float) -> float | None:
    try:
        x = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return round(x, 3) if -limit <= x <= limit and x != 0 else None


@dataclass(frozen=True)
class Located:
    city: str | None
    state: str | None = None
    lat: float | None = None
    lng: float | None = None


def locate(raw: RawHackathon, city: str | None, country_code: str | None) -> Located:
    """City, state and city-level coordinates for an in-person or hybrid listing."""
    if raw.mode == "online" or not country_code:
        return Located(city)
    extra = raw.extra or {}
    lat = _coord(raw.lat if raw.lat is not None else extra.get("latitude"), 90)
    lng = _coord(raw.lng if raw.lng is not None else extra.get("longitude"), 180)
    published = (lat, lng) if lat is not None and lng is not None else (None, None)
    if country_code != "IN":
        return Located(city, None, *published)

    hint = canonical_state(raw.state or extra.get("state")) or _state_in(raw.location)
    place = find_place(city or raw.city, hint)
    if not place:
        for part in reversed((raw.location or "").split(",")):
            place = find_place(part, hint)
            if place:
                break
    if place:
        return Located(place.name, place.state, round(place.lat, 3), round(place.lng, 3))
    return Located(city, hint or _state_in(raw.location), *published)


def unplaced(items: list[Hackathon]) -> Counter[str]:
    """In-person listings in India with no pin, by the place they gave (for the sync log)."""
    missing: Counter[str] = Counter()
    for h in items:
        if h.mode != "online" and h.country == "India" and h.lat is None:
            missing[", ".join(x for x in (h.city or h.location or "no place given", h.state) if x)] += 1
    return missing
