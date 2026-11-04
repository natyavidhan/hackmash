"""Major League Hacking (MLH): the official student hackathon league.

MLH's site is an Inertia.js app; every season page embeds the season's events as JSON in
``<script data-page="app" type="application/json">``:

    https://www.mlh.com/events                  -> redirects to the current season page
    https://www.mlh.com/seasons/<season>/events -> props.upcomingEvents / props.pastEvents

Seasons are named after the year they end (Aug 2026 - Jul 2027 is season "2027"). We read
the current season and probe the next one (404 until MLH publishes it).

Times are real UTC. Events whose times are not set yet carry sentinels instead: start
``T01:11:11Z`` and/or end ``T23:59:59Z`` (MLH itself renders them as "1:11 AM ... 11:59 PM
UTC"). The date part is the event's local date, so those are converted to local midnight /
end of day in the venue's timezone and flagged in ``extra``.

The public API (api.mlh.com) needs an OAuth app, and the event detail pages add nothing
beyond sponsor challenges, so one or two page loads cover the whole league.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from importlib import resources
from typing import Any

import httpx
import pycountry
from rapidfuzz import process

from ..models import RawHackathon
from .base import Source, SourceError, abs_url, clean_text, get_text, to_utc

log = logging.getLogger(__name__)

BASE = "https://www.mlh.com"
EVENTS_URL = f"{BASE}/events"
SEASON_URL = BASE + "/seasons/{season}/events"

_PAGE_RE = re.compile(r'<script[^>]*data-page="app"[^>]*>(.*?)</script>', re.S)
_PAGE_ATTR_RE = re.compile(r'data-page="([^"]+)"')

# MLH's ``customFields.underserved_types`` -> eligibility wording. "Other Diversity Focus" is
# too vague to show and only kept in ``extra``.
_DIVERSITY = {
    "high school students only": "High school students only",
    "women only": "Women only",
    "underrepresented genders in tech": "Underrepresented genders in tech",
    "gender equality (50/50)": "Gender-balanced admissions (50/50)",
    "people of color focused": "People of color focused",
}


# ---------------------------------------------------------------------------
# Timezone helper (shared with hackclub.py)
# ---------------------------------------------------------------------------

_US_STATES = {
    "AL": ("alabama", "America/Chicago"), "AK": ("alaska", "America/Anchorage"),
    "AZ": ("arizona", "America/Phoenix"), "AR": ("arkansas", "America/Chicago"),
    "CA": ("california", "America/Los_Angeles"), "CO": ("colorado", "America/Denver"),
    "CT": ("connecticut", "America/New_York"), "DE": ("delaware", "America/New_York"),
    "DC": ("district of columbia", "America/New_York"), "FL": ("florida", "America/New_York"),
    "GA": ("georgia", "America/New_York"), "HI": ("hawaii", "Pacific/Honolulu"),
    "ID": ("idaho", "America/Boise"), "IL": ("illinois", "America/Chicago"),
    "IN": ("indiana", "America/Indiana/Indianapolis"), "IA": ("iowa", "America/Chicago"),
    "KS": ("kansas", "America/Chicago"), "KY": ("kentucky", "America/New_York"),
    "LA": ("louisiana", "America/Chicago"), "ME": ("maine", "America/New_York"),
    "MD": ("maryland", "America/New_York"), "MA": ("massachusetts", "America/New_York"),
    "MI": ("michigan", "America/Detroit"), "MN": ("minnesota", "America/Chicago"),
    "MS": ("mississippi", "America/Chicago"), "MO": ("missouri", "America/Chicago"),
    "MT": ("montana", "America/Denver"), "NE": ("nebraska", "America/Chicago"),
    "NV": ("nevada", "America/Los_Angeles"), "NH": ("new hampshire", "America/New_York"),
    "NJ": ("new jersey", "America/New_York"), "NM": ("new mexico", "America/Denver"),
    "NY": ("new york", "America/New_York"), "NC": ("north carolina", "America/New_York"),
    "ND": ("north dakota", "America/Chicago"), "OH": ("ohio", "America/New_York"),
    "OK": ("oklahoma", "America/Chicago"), "OR": ("oregon", "America/Los_Angeles"),
    "PA": ("pennsylvania", "America/New_York"), "PR": ("puerto rico", "America/Puerto_Rico"),
    "RI": ("rhode island", "America/New_York"), "SC": ("south carolina", "America/New_York"),
    "SD": ("south dakota", "America/Chicago"), "TN": ("tennessee", "America/Chicago"),
    "TX": ("texas", "America/Chicago"), "UT": ("utah", "America/Denver"),
    "VT": ("vermont", "America/New_York"), "VA": ("virginia", "America/New_York"),
    "WA": ("washington", "America/Los_Angeles"), "WV": ("west virginia", "America/New_York"),
    "WI": ("wisconsin", "America/Chicago"), "WY": ("wyoming", "America/Denver"),
}
_CA_PROVINCES = {
    "AB": ("alberta", "America/Edmonton"), "BC": ("british columbia", "America/Vancouver"),
    "MB": ("manitoba", "America/Winnipeg"), "NB": ("new brunswick", "America/Moncton"),
    "NL": ("newfoundland and labrador", "America/St_Johns"), "NS": ("nova scotia", "America/Halifax"),
    "NT": ("northwest territories", "America/Yellowknife"), "NU": ("nunavut", "America/Iqaluit"),
    "ON": ("ontario", "America/Toronto"), "PE": ("prince edward island", "America/Halifax"),
    "QC": ("quebec", "America/Toronto"), "SK": ("saskatchewan", "America/Regina"),
    "YT": ("yukon", "America/Whitehorse"),
}
_AU_STATES = {
    "NSW": ("new south wales", "Australia/Sydney"), "VIC": ("victoria", "Australia/Melbourne"),
    "QLD": ("queensland", "Australia/Brisbane"), "SA": ("south australia", "Australia/Adelaide"),
    "WA": ("western australia", "Australia/Perth"), "TAS": ("tasmania", "Australia/Hobart"),
    "ACT": ("australian capital territory", "Australia/Sydney"),
    "NT": ("northern territory", "Australia/Darwin"),
}
_SUBDIVISIONS = {"US": _US_STATES, "CA": _CA_PROVINCES, "AU": _AU_STATES}

# Cities on the "wrong" side of their state's dominant zone (college towns included).
_CITY_TZ = {
    ("US", "el paso"): "America/Denver",
    ("US", "moscow"): "America/Los_Angeles",  # University of Idaho
    ("US", "pensacola"): "America/Chicago",
    ("US", "knoxville"): "America/New_York",
    ("US", "chattanooga"): "America/New_York",
    ("US", "johnson city"): "America/New_York",
    ("US", "evansville"): "America/Chicago",
    ("US", "gary"): "America/Chicago",
    ("US", "bowling green"): "America/Chicago",
    ("CA", "thunder bay"): "America/Toronto",
    ("CA", "kenora"): "America/Winnipeg",
    ("CA", "lloydminster"): "America/Edmonton",
}

# Countries with one timezone, or one that nearly everyone lives in.
_COUNTRY_TZ = {
    "GB": "Europe/London", "IE": "Europe/Dublin", "FR": "Europe/Paris", "DE": "Europe/Berlin",
    "NL": "Europe/Amsterdam", "BE": "Europe/Brussels", "LU": "Europe/Luxembourg",
    "CH": "Europe/Zurich", "AT": "Europe/Vienna", "IT": "Europe/Rome", "ES": "Europe/Madrid",
    "PT": "Europe/Lisbon", "DK": "Europe/Copenhagen", "NO": "Europe/Oslo", "SE": "Europe/Stockholm",
    "FI": "Europe/Helsinki", "IS": "Atlantic/Reykjavik", "PL": "Europe/Warsaw", "CZ": "Europe/Prague",
    "SK": "Europe/Bratislava", "HU": "Europe/Budapest", "RO": "Europe/Bucharest", "BG": "Europe/Sofia",
    "GR": "Europe/Athens", "TR": "Europe/Istanbul", "UA": "Europe/Kyiv", "EE": "Europe/Tallinn",
    "LV": "Europe/Riga", "LT": "Europe/Vilnius", "SI": "Europe/Ljubljana", "HR": "Europe/Zagreb",
    "RS": "Europe/Belgrade", "BA": "Europe/Sarajevo", "MK": "Europe/Skopje", "AL": "Europe/Tirane",
    "MT": "Europe/Malta", "CY": "Asia/Nicosia", "MD": "Europe/Chisinau", "GE": "Asia/Tbilisi",
    "AM": "Asia/Yerevan", "AZ": "Asia/Baku", "IL": "Asia/Jerusalem", "AE": "Asia/Dubai",
    "SA": "Asia/Riyadh", "QA": "Asia/Qatar", "KW": "Asia/Kuwait", "BH": "Asia/Bahrain",
    "OM": "Asia/Muscat", "JO": "Asia/Amman", "LB": "Asia/Beirut", "EG": "Africa/Cairo",
    "MA": "Africa/Casablanca", "TN": "Africa/Tunis", "DZ": "Africa/Algiers", "NG": "Africa/Lagos",
    "GH": "Africa/Accra", "KE": "Africa/Nairobi", "UG": "Africa/Kampala", "TZ": "Africa/Dar_es_Salaam",
    "RW": "Africa/Kigali", "ET": "Africa/Addis_Ababa", "ZA": "Africa/Johannesburg",
    "ZW": "Africa/Harare", "ZM": "Africa/Lusaka", "CM": "Africa/Douala", "SN": "Africa/Dakar",
    "CI": "Africa/Abidjan", "IN": "Asia/Kolkata", "PK": "Asia/Karachi", "BD": "Asia/Dhaka",
    "LK": "Asia/Colombo", "NP": "Asia/Kathmandu", "CN": "Asia/Shanghai", "HK": "Asia/Hong_Kong",
    "TW": "Asia/Taipei", "JP": "Asia/Tokyo", "KR": "Asia/Seoul", "SG": "Asia/Singapore",
    "MY": "Asia/Kuala_Lumpur", "TH": "Asia/Bangkok", "VN": "Asia/Ho_Chi_Minh", "PH": "Asia/Manila",
    "NZ": "Pacific/Auckland", "AR": "America/Argentina/Buenos_Aires", "CL": "America/Santiago",
    "CO": "America/Bogota", "PE": "America/Lima", "EC": "America/Guayaquil", "VE": "America/Caracas",
    "UY": "America/Montevideo", "PY": "America/Asuncion", "BO": "America/La_Paz",
    "CR": "America/Costa_Rica", "PA": "America/Panama", "GT": "America/Guatemala",
    "SV": "America/El_Salvador", "HN": "America/Tegucigalpa", "DO": "America/Santo_Domingo",
    "PR": "America/Puerto_Rico", "JM": "America/Jamaica", "TT": "America/Port_of_Spain",
}

# Multi-zone countries without a known subdivision: the westernmost / easternmost common
# zones. Local midnight in the west and end-of-day in the east keep a date-only event on
# the right calendar day everywhere in the country.
_DATE_BOUNDS_TZ = {
    "US": ("America/Los_Angeles", "America/New_York"),
    "CA": ("America/Vancouver", "America/Halifax"),
    "AU": ("Australia/Perth", "Australia/Sydney"),
    "MX": ("America/Tijuana", "America/Cancun"),
    "BR": ("America/Manaus", "America/Sao_Paulo"),
    "ID": ("Asia/Jakarta", "Asia/Jayapura"),
    "RU": ("Europe/Kaliningrad", "Asia/Vladivostok"),
}


# Legacy / alias zone names that zone.tab does not list (value: canonical zone or ISO-2 code).
_TZ_ALIASES = {
    "Asia/Calcutta": "Asia/Kolkata", "Asia/Saigon": "Asia/Ho_Chi_Minh", "Asia/Katmandu": "Asia/Kathmandu",
    "Asia/Rangoon": "Asia/Yangon", "Asia/Dacca": "Asia/Dhaka", "Asia/Ujung_Pandang": "Asia/Makassar",
    "Europe/Kiev": "Europe/Kyiv", "Europe/Belfast": "Europe/London", "America/Montreal": "America/Toronto",
    "America/Buenos_Aires": "America/Argentina/Buenos_Aires", "America/Indianapolis": "America/Indiana/Indianapolis",
    "GB": "GB", "Japan": "JP", "Singapore": "SG", "Hongkong": "HK", "Israel": "IL", "Egypt": "EG",
    "Turkey": "TR", "Iran": "IR", "NZ": "NZ", "PRC": "CN", "ROC": "TW", "ROK": "KR", "Eire": "IE",
    "Poland": "PL", "Portugal": "PT", "Iceland": "IS", "Jamaica": "JM", "Cuba": "CU",
}
_TZ_PREFIXES = {"US/": "US", "Canada/": "CA", "Australia/": "AU", "Brazil/": "BR", "Mexico/": "MX", "Chile/": "CL"}


@lru_cache(maxsize=1)
def _zone_countries() -> dict[str, str]:
    """zone name -> ISO-2, from tzdata's zone.tab (falls back to the system copy / our tables)."""
    text = ""
    try:
        text = resources.files("tzdata").joinpath("zoneinfo/zone.tab").read_text(encoding="utf-8")
    except Exception:  # noqa: BLE001 - tzdata wheel missing or unreadable
        try:
            with open("/usr/share/zoneinfo/zone.tab", encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            text = ""
    zones: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split("\t")
        if len(parts) >= 3 and not line.startswith("#"):
            zones[parts[2].strip()] = parts[0].strip().upper()
    for code, tz in _COUNTRY_TZ.items():
        zones.setdefault(tz, code)
    for code, subdivisions in _SUBDIVISIONS.items():
        for _, tz in subdivisions.values():
            zones.setdefault(tz, code)
    return zones


def tz_country(name: str | None) -> str | None:
    """ISO-2 country of an IANA zone name ("Europe/Berlin" -> "DE"); None for UTC/EST/unknown."""
    name = (name or "").strip()
    if not name:
        return None
    name = _TZ_ALIASES.get(name, name)
    if len(name) == 2 and name.isupper():
        return name
    zone = _zone_countries().get(name)
    if zone:
        return zone
    for prefix, code in _TZ_PREFIXES.items():
        if name.startswith(prefix):
            return code
    return None


def _norm(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").replace(".", " ")).strip().lower()


def local_timezone(country: str | None, state: str | None = None, city: str | None = None) -> str | None:
    """Best-effort IANA timezone for an ISO-2 country plus optional state / city names."""
    code = (country or "").strip().upper()
    if len(code) != 2:
        found = pycountry.countries.get(name=country) if country else None
        code = found.alpha_2 if found else ""
    if not code:
        return None
    if (code, _norm(city)) in _CITY_TZ:
        return _CITY_TZ[(code, _norm(city))]
    subdivisions = _SUBDIVISIONS.get(code)
    if subdivisions is None:
        return _COUNTRY_TZ.get(code)
    state_norm = _norm(state)
    if not state_norm:
        return None
    if state_norm.upper() in subdivisions:
        return subdivisions[state_norm.upper()][1]
    names = {name: tz for name, tz in subdivisions.values()}
    for name, tz in names.items():  # "Newfoundland and Labrador / Avalon Peninsula"
        if state_norm.startswith(name):
            return tz
    match = process.extractOne(state_norm, list(names), score_cutoff=85)  # "Massachesetts"
    return names[match[0]] if match else None


def date_bound_timezone(country: str | None, *, end: bool) -> str | None:
    """Zone to anchor a date-only start (west) or end (east) when the real zone is unknown."""
    bounds = _DATE_BOUNDS_TZ.get((country or "").upper())
    return (bounds[1] if end else bounds[0]) if bounds else None


def country_name(code: str | None) -> str | None:
    if not code:
        return None
    found = pycountry.countries.get(alpha_2=code.upper()) if len(code) == 2 else None
    if not found:
        return code
    return getattr(found, "common_name", None) or found.name


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


def _inertia_page(html: str) -> dict[str, Any]:
    m = _PAGE_RE.search(html)
    if m:
        return json.loads(m.group(1))
    m = _PAGE_ATTR_RE.search(html)
    if m:
        import html as html_lib

        return json.loads(html_lib.unescape(m.group(1)))
    raise SourceError("mlh: no Inertia page data found")


def _website(url: str | None) -> str | None:
    url = (url or "").strip()
    if not url:
        return None
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url.lstrip("/")
    return url


def _sentinel(dt: datetime, *, end: bool) -> bool:
    if end:
        return (dt.hour, dt.minute, dt.second) == (23, 59, 59)
    return (dt.hour, dt.minute, dt.second) == (1, 11, 11)


def _event_time(value: Any, tz: str | None, country: str | None, *, end: bool) -> tuple[datetime | None, bool]:
    """Parse an MLH timestamp; date-only sentinels become local start / end of day."""
    dt = to_utc(value)
    if dt is None or not _sentinel(dt, end=end):
        return dt, False
    anchor = tz or date_bound_timezone(country, end=end) or "UTC"
    local = datetime(dt.year, dt.month, dt.day, 23, 59, 59) if end else datetime(dt.year, dt.month, dt.day)
    return to_utc(local, anchor), True


class MLH(Source):
    key = "mlh"
    name = "Major League Hacking"
    homepage = "https://www.mlh.com/events"
    region = "global"
    focus = "Student hackathons (MLH member events)"
    description = (
        "The official student hackathon league: hundreds of free, beginner-friendly weekend "
        "hackathons at universities and high schools across North America, Europe and Asia."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        page = _inertia_page(await get_text(client, EVENTS_URL))
        if "upcomingEvents" not in (page.get("props") or {}):
            # /events no longer lands on a season page: compute the season (named after its end year)
            today = datetime.now(timezone.utc)
            guess = today.year + (1 if today.month >= 8 else 0)
            page = _inertia_page(await get_text(client, SEASON_URL.format(season=guess)))
            if "upcomingEvents" not in (page.get("props") or {}):
                raise SourceError("mlh: season page has no upcomingEvents")
        pages = [page]
        season = str((page.get("props") or {}).get("seriesName") or "")
        if season.isdigit():
            try:  # the next season appears around the end of the current one
                pages.append(_inertia_page(await get_text(client, SEASON_URL.format(season=int(season) + 1))))
            except SourceError:
                pass
            except ValueError:
                log.warning("mlh: unreadable page for season %s", int(season) + 1)

        now = datetime.now(timezone.utc)
        items: list[RawHackathon] = []
        seen: set[str] = set()
        for pg in pages:
            props = pg.get("props") or {}
            season_name = props.get("seriesName")
            # live events may already sit in pastEvents; keep anything not yet over
            for row in (props.get("upcomingEvents") or []) + (props.get("pastEvents") or []):
                rid = str(row.get("id") or row.get("slug") or "")
                if not rid or rid in seen:
                    continue
                try:
                    item = self._build(row, season_name)
                except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                    log.exception("mlh: could not parse %s", row.get("slug"))
                    continue
                end = item.ends_at or item.starts_at
                if row.get("status") in ("ended", "cancelled", "canceled") or (end and end < now - timedelta(hours=1)):
                    continue
                seen.add(rid)
                items.append(item)
        return items

    def _build(self, row: dict[str, Any], season: Any) -> RawHackathon:
        venue = row.get("venueAddress") or {}
        city = clean_text(venue.get("city"))
        state = clean_text(venue.get("state"))
        country = (clean_text(venue.get("country")) or "").upper() or None
        fmt = str(row.get("formatType") or "").lower()
        if "hybrid" in fmt:
            mode = "hybrid"
        elif fmt in ("digital", "online", "virtual"):
            mode = "online"
        elif fmt:
            mode = "in_person"
        else:
            mode = None

        tz = local_timezone(country, state, city) if mode != "online" else None
        starts_at, start_tba = _event_time(row.get("startsAt"), tz, country, end=False)
        ends_at, end_tba = _event_time(row.get("endsAt"), tz, country, end=True)

        cname = country_name(country)
        if state and (state.lower() == (city or "").lower() or (cname and cname.lower() in state.lower())):
            state = None  # "Edinburgh, Edinburgh", "Lleida, Lleida, Spain"
        if mode == "online":
            location = "Online"
        else:
            location = ", ".join(x for x in (city, state, cname) if x) or None

        custom = row.get("customFields") or {}
        underserved = [clean_text(x) for x in custom.get("underserved_types") or [] if clean_text(x)]
        high_school_only = any("high school" in x.lower() for x in underserved)
        eligibility = (
            []
            if high_school_only
            else ["Students", "Recent graduates (within the last 12 months)"]
        )
        for value in underserved:
            label = _DIVERSITY.get(value.lower())
            if label and label not in eligibility:
                eligibility.append(label)

        slug = row.get("slug")
        mlh_page = f"{BASE}/events/{slug}" if slug else None
        website = _website(row.get("websiteUrl"))
        url = website or mlh_page
        if not url:
            raise ValueError("event without any URL")

        return RawHackathon(
            source=self.key,
            source_id=str(row.get("id") or slug),
            title=clean_text(row.get("name")) or "Untitled hackathon",
            url=url,
            kind="hackathon",
            image_url=row.get("backgroundUrl") or None,
            logo_url=row.get("logoUrl") or None,
            mode=mode,
            location=location,
            city=city if mode != "online" else None,
            country=country if mode != "online" else None,
            starts_at=starts_at,
            ends_at=ends_at,
            timezone=tz,
            tags=[clean_text(t) for t in custom.get("hackathon_focus") or [] if clean_text(t)],
            eligibility=eligibility,
            # MLH community values: member events are open to students and "do not have entry fees"
            registration_fee=False,
            beginner_friendly=True,
            extra={
                "mlh_url": mlh_page,
                "mlh_prizes_url": abs_url(BASE, row.get("url")),
                "season": str(season) if season else None,
                "mlh_region": row.get("region"),
                "format_type": row.get("formatType"),
                "high_school_only": high_school_only,
                "diversity_focus": underserved,
                "date_range": row.get("dateRange"),
                "start_time_tba": start_tba,
                "end_time_tba": end_tba,
            },
        )
