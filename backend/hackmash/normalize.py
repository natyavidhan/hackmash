"""Turn adapter output (RawHackathon) into canonical Hackathon records.

Everything here is deterministic and offline except FX rates, which the
refresher passes in (live rates when available, static fallback otherwise).
"""

from __future__ import annotations

import re
from datetime import datetime
from functools import lru_cache

from .countries import COUNTRIES
from .geo import locate
from .models import Hackathon, RawHackathon, make_uid

# ---------------------------------------------------------------------------
# Themes
# ---------------------------------------------------------------------------

# key -> (label, keyword patterns matched on title + tagline + tags, word-bounded)
THEMES: dict[str, tuple[str, list[str]]] = {
    "ai": ("AI & ML", [
        r"ai", r"a\.i\.", r"artificial intelligence", r"machine learning", r"ml", r"deep learning",
        r"llms?", r"gen ?ai", r"generative", r"gpt\w*", r"agents?", r"agentic", r"nlp", r"computer vision",
        r"neural", r"rag", r"chatbots?", r"gemini", r"openai", r"claude", r"copilot", r"genai",
    ]),
    "web3": ("Web3 & Blockchain", [
        r"web ?3", r"blockchain", r"crypto\w*", r"defi", r"nfts?", r"ethereum", r"eth\w*global", r"solana",
        r"bitcoin", r"daos?", r"smart contracts?", r"polygon", r"zk\w*", r"zero[- ]knowledge", r"on-?chain",
        r"dapps?", r"stellar", r"aptos", r"starknet", r"polkadot", r"avalanche", r"hedera", r"cardano",
        r"arbitrum", r"optimism", r"tezos", r"algorand", r"chainlink", r"layer ?2", r"evm", r"rollups?",
    ]),
    "fintech": ("FinTech", [
        r"fin ?tech", r"finance", r"financial", r"banking", r"payments?", r"insur\w*", r"trading",
        r"wealth", r"lending", r"upi", r"credit", r"accounting",
    ]),
    "health": ("HealthTech", [
        r"health\w*", r"medical", r"medicine", r"med ?tech", r"biotech", r"bio\w*", r"wellness", r"clinical",
        r"hospitals?", r"pharma\w*", r"genomics", r"fitness", r"mental health", r"covid\w*", r"healthcare",
    ]),
    "edtech": ("EdTech", [
        r"ed ?tech", r"education\w*", r"e-?learning", r"teaching", r"classrooms?", r"tutor\w*",
        r"learning platform", r"upskilling",
    ]),
    "climate": ("Climate & Sustainability", [
        r"climate", r"sustainab\w*", r"green\w*", r"environment\w*", r"energy", r"renewable\w*", r"carbon",
        r"clean ?tech", r"electric vehicles?", r"recycl\w*", r"water", r"net[- ]zero", r"circular economy",
        r"earth", r"planet",
    ]),
    "social": ("Social Good", [
        r"social good", r"social impact", r"impact", r"non-?profits?", r"ngos?", r"accessib\w*",
        r"inclusi\w*", r"civic\w*", r"gov ?tech", r"government", r"humanitarian", r"sdgs?", r"disaster\w*",
        r"public good", r"for good",
    ]),
    "open": ("Open Innovation", [
        r"open innovation", r"open[- ]ended", r"open theme", r"open track", r"freestyle", r"any theme",
        r"general", r"miscellaneous", r"open category",
    ]),
    "gaming": ("Gaming", [
        r"games?", r"gaming", r"game ?jam", r"game ?dev", r"unity", r"unreal", r"e-?sports",
    ]),
    "hardware": ("Hardware & IoT", [
        r"hardware", r"iot", r"internet of things", r"embedded", r"arduino", r"raspberry pi", r"robot\w*",
        r"drones?", r"electronics", r"sensors?", r"fpga", r"wearables?", r"semiconductors?", r"chips?",
    ]),
    "security": ("Cybersecurity", [
        r"security", r"cyber\w*", r"ctf", r"capture the flag", r"privacy", r"infosec", r"forensics",
    ]),
    "mobile": ("Mobile", [r"mobile", r"android", r"ios", r"flutter", r"react native", r"apps? development"]),
    "web": ("Web Dev", [
        r"web", r"web development", r"websites?", r"front-?end", r"full[- ]?stack", r"javascript",
        r"react", r"next\.?js", r"web ?apps?",
    ]),
    "data": ("Data Science", [
        r"data science", r"data analytics", r"analytics", r"big data", r"data visuali[sz]ation",
        r"datathon", r"kaggle", r"datasets?", r"data engineering", r"databases?", r"sql",
    ]),
    "cloud": ("Cloud & DevOps", [
        r"cloud", r"dev ?ops", r"aws", r"azure", r"gcp", r"google cloud", r"kubernetes", r"serverless",
        r"docker", r"infrastructure",
    ]),
    "arvr": ("AR / VR", [
        r"ar", r"vr", r"xr", r"ar/vr", r"augmented reality", r"virtual reality", r"mixed reality",
        r"metaverse", r"spatial computing", r"vision ?pro", r"meta quest",
    ]),
    "design": ("Design & UX", [
        r"design\w*", r"ui/ux", r"ux", r"ui", r"figma", r"design-?a-?thon", r"creative",
    ]),
    "devtools": ("Developer Tools", [
        r"developer tools", r"dev ?tools", r"productivity", r"apis?", r"open[- ]source", r"sdks?",
        r"low[/ -]?no[- ]?code", r"no-?code", r"low-?code", r"automation",
    ]),
    "space": ("Space", [r"space\w*", r"satellites?", r"aerospace", r"nasa", r"isro", r"astronom\w*"]),
    "mobility": ("Smart Cities & Mobility", [
        r"smart cit(y|ies)", r"mobility", r"transport\w*", r"automotive", r"logistics", r"supply chain",
        r"urban",
    ]),
    "agritech": ("AgriTech & Food", [r"agri\w*", r"farm\w*", r"food\w*", r"crops?"]),
    "commerce": ("E-commerce & Retail", [r"e-?commerce", r"retail", r"commerce", r"shopping", r"marketplaces?"]),
    "media": ("Media & Creativity", [
        r"music", r"media", r"entertainment", r"content creat\w*", r"film\w*", r"creators?", r"music/art",
    ]),
    "quantum": ("Quantum", [r"quantum"]),
}

_THEME_RES = {
    key: re.compile(r"(?<![\w])(?:" + "|".join(patterns) + r")(?![\w])", re.I)
    for key, (_, patterns) in THEMES.items()
}

THEME_LABELS = {key: label for key, (label, _) in THEMES.items()}


def classify_themes(raw: RawHackathon) -> list[str]:
    tag_text = " | ".join(raw.tags)
    head_text = " | ".join(x for x in (raw.title, raw.tagline) if x)
    found: list[str] = []
    for key, rx in _THEME_RES.items():
        if rx.search(tag_text) or rx.search(head_text):
            found.append(key)
    return found


# ---------------------------------------------------------------------------
# Audience / eligibility
# ---------------------------------------------------------------------------

AUDIENCES: dict[str, str] = {
    "students": "College students",
    "high_school": "High school",
    "women": "Women & non-binary",
    "professionals": "Professionals",
    "startups": "Startups & founders",
    "open": "Open to all",
}

_AUDIENCE_RES = {
    "high_school": re.compile(
        r"high[- ]?school|secondary school|school students|k-?12|teen|under 18|class (9|10|11|12)|"
        r"grade (9|10|11|12)|middle school|hack ?club",
        re.I,
    ),
    "students": re.compile(
        r"student|college|universit|undergrad|post-?grad|graduate|b\.? ?tech|m\.? ?tech|b\.?e\b|mba|"
        r"engineering|campus|freshers?|phd|bachelor|master'?s",
        re.I,
    ),
    "women": re.compile(r"\bwomen\b|\bwoman\b|female|\bgirls?\b|non-?binary|femme|\bher ?hack", re.I),
    "professionals": re.compile(r"professional|working|experienced|employees|corporate|industry", re.I),
    "startups": re.compile(r"start-?ups?|founders?|entrepreneur", re.I),
    "open": re.compile(r"everyone|open to all|anyone|all can|open for all|no restriction|all are welcome", re.I),
}


def classify_audience(raw: RawHackathon) -> list[str]:
    elig_text = " | ".join(raw.eligibility)
    title_text = " | ".join(x for x in (raw.title, raw.tagline, *raw.tags) if x)
    found: list[str] = []
    for key, rx in _AUDIENCE_RES.items():
        # eligibility strings are authoritative; titles only count for strong signals
        if rx.search(elig_text):
            found.append(key)
        elif key in ("high_school", "women") and rx.search(title_text):
            found.append(key)
    # "High school students" is not a college audience unless college is named too
    if "high_school" in found and "students" in found and not _COLLEGE_RE.search(elig_text):
        found.remove("students")
    if raw.source == "hackclub" and "high_school" not in found:
        found.append("high_school")
    if raw.source == "mlh" and "students" not in found and "high_school" not in found:
        found.append("students")
    return found


_COLLEGE_RE = re.compile(r"college|universit|undergrad|post-?grad|b\.? ?tech|m\.? ?tech|engineering|mba|phd", re.I)
_HIRING_RE = re.compile(
    r"\bhiring\b|recruit|pre-?placement|\bppos?\b|placement|job offers?|internship (offers?|opportunit)|"
    r"interview (call|opportunit)|full[- ]time (role|offer)",
    re.I,
)


def infer_hiring(raw: RawHackathon) -> bool:
    text = " | ".join(x for x in (raw.title, raw.tagline, raw.prize_text, *raw.tags) if x)
    return bool(_HIRING_RE.search(text))


_BEGINNER_RE = re.compile(r"beginner|first[- ]time|newbie|no experience|novice|learn to code", re.I)


def infer_beginner(raw: RawHackathon) -> bool | None:
    if raw.beginner_friendly is not None:
        return raw.beginner_friendly
    text = " | ".join(x for x in (raw.title, raw.tagline, *raw.tags, *raw.eligibility) if x)
    return True if _BEGINNER_RE.search(text) else None


_IDEATHON_RE = re.compile(r"ideathon|idea(tion)? (challenge|contest|competition)|pitch|case[- ]?(study|comp)", re.I)
_CONTEST_RE = re.compile(r"coding (contest|challenge|round)|code ?sprint|dsa|competitive programming|code ?(war|battle)", re.I)
_DATA_RE = re.compile(r"datathon|data science (challenge|competition)|ml challenge|kaggle", re.I)


def infer_kind(raw: RawHackathon) -> str:
    if raw.kind != "hackathon":
        return raw.kind
    title = raw.title
    if re.search(r"hack", title, re.I):
        return "hackathon"
    if _IDEATHON_RE.search(title):
        return "ideathon"
    if _CONTEST_RE.search(title):
        return "coding_contest"
    if _DATA_RE.search(title):
        return "data_science"
    return "hackathon"


KINDS = {
    "hackathon": "Hackathon",
    "ideathon": "Ideathon / pitch",
    "coding_contest": "Coding contest",
    "data_science": "Data science",
    "other": "Other challenge",
}

MODES = {"online": "Online", "in_person": "In person", "hybrid": "Hybrid"}

# ---------------------------------------------------------------------------
# Countries and regions
# ---------------------------------------------------------------------------

_COUNTRY_ALIASES = {
    "usa": "US", "u.s.": "US", "u.s.a.": "US", "us": "US", "united states of america": "US", "america": "US",
    "uk": "GB", "u.k.": "GB", "england": "GB", "scotland": "GB", "wales": "GB", "northern ireland": "GB",
    "great britain": "GB", "britain": "GB", "south korea": "KR", "korea": "KR", "republic of korea": "KR",
    "north korea": "KP", "russia": "RU", "vietnam": "VN", "viet nam": "VN", "uae": "AE",
    "u.a.e.": "AE", "turkey": "TR", "türkiye": "TR", "turkiye": "TR", "czech republic": "CZ",
    "taiwan": "TW", "iran": "IR", "hong kong": "HK", "hong kong sar": "HK", "macau": "MO", "macao": "MO",
    "bolivia": "BO", "venezuela": "VE", "tanzania": "TZ", "laos": "LA", "syria": "SY", "moldova": "MD",
    "palestine": "PS", "ivory coast": "CI", "cote d'ivoire": "CI", "côte d'ivoire": "CI", "holland": "NL",
    "the netherlands": "NL", "deutschland": "DE", "brasil": "BR", "españa": "ES", "méxico": "MX",
    "bharat": "IN", "republic of india": "IN", "kosovo": "XK", "the bahamas": "BS", "the gambia": "GM",
    "drc": "CD", "dr congo": "CD", "democratic republic of the congo": "CD", "republic of the congo": "CG",
    "micronesia": "FM", "brunei": "BN", "cape verde": "CV", "eswatini": "SZ", "swaziland": "SZ",
    "burma": "MM", "east timor": "TL", "vatican": "VA", "st. lucia": "LC", "saint lucia": "LC",
}

_DISPLAY_NAMES = {
    "US": "United States", "GB": "United Kingdom", "KR": "South Korea", "KP": "North Korea",
    "RU": "Russia", "IR": "Iran", "VN": "Vietnam", "TW": "Taiwan", "TZ": "Tanzania", "SY": "Syria",
    "LA": "Laos", "MD": "Moldova", "VE": "Venezuela", "BO": "Bolivia", "CZ": "Czechia", "TR": "Turkey",
    "PS": "Palestine", "XK": "Kosovo", "CD": "DR Congo", "CG": "Congo", "BN": "Brunei", "MO": "Macau",
    "HK": "Hong Kong", "FM": "Micronesia", "VA": "Vatican City", "CI": "Côte d'Ivoire",
}

_US_STATES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "DC": "District of Columbia", "PR": "Puerto Rico",
}
_CA_PROVINCES = {
    "AB": "Alberta", "BC": "British Columbia", "MB": "Manitoba", "NB": "New Brunswick",
    "NL": "Newfoundland and Labrador", "NS": "Nova Scotia", "ON": "Ontario", "PE": "Prince Edward Island",
    "QC": "Quebec", "SK": "Saskatchewan", "NT": "Northwest Territories", "NU": "Nunavut", "YT": "Yukon",
}
_IN_STATES = {
    "andhra pradesh", "arunachal pradesh", "assam", "bihar", "chhattisgarh", "goa", "gujarat", "haryana",
    "himachal pradesh", "jharkhand", "karnataka", "kerala", "madhya pradesh", "maharashtra", "manipur",
    "meghalaya", "mizoram", "nagaland", "odisha", "orissa", "punjab", "rajasthan", "sikkim", "tamil nadu",
    "telangana", "tripura", "uttar pradesh", "uttarakhand", "west bengal", "delhi", "new delhi",
    "jammu and kashmir", "jammu & kashmir", "ladakh", "puducherry", "pondicherry", "chandigarh",
}
_STATE_NAMES_US = {v.lower() for v in _US_STATES.values()} - {"georgia"}  # Georgia is also a country
_STATE_NAMES_CA = {v.lower() for v in _CA_PROVINCES.values()}
_IN_CITIES = {
    "bengaluru", "bangalore", "mumbai", "pune", "hyderabad", "chennai", "kolkata", "noida", "gurugram",
    "gurgaon", "ahmedabad", "jaipur", "indore", "bhopal", "lucknow", "kochi", "chandigarh", "nagpur",
    "coimbatore", "vellore", "bhubaneswar", "ghaziabad", "greater noida", "vizag", "visakhapatnam",
    "thiruvananthapuram", "trivandrum", "mangaluru", "mangalore", "mysuru", "mysore", "surat", "vadodara",
    "patna", "ranchi", "guwahati", "dehradun", "kanpur", "varanasi", "amritsar", "ludhiana", "madurai",
}

_CONTINENTS = {
    "Africa": "DZ AO BJ BW BF BI CV CM CF TD KM CD CG CI DJ EG GQ ER SZ ET GA GM GH GN GW KE LS LR LY "
              "MG MW ML MR MU MA MZ NA NE NG RW ST SN SC SL SO ZA SS SD TZ TG TN UG ZM ZW RE YT EH",
    "Asia": "AF AM AZ BH BD BT BN KH CN GE HK IN ID IR IQ IL JP JO KZ KW KG LA LB MO MY MV MN MM NP KP "
            "OM PK PS PH QA SA SG KR LK SY TW TJ TH TL TM AE UZ VN YE",
    "Europe": "AL AD AT BY BE BA BG HR CY CZ DK EE FI FR DE GR HU IS IE IT XK LV LI LT LU MT MD MC ME NL "
              "MK NO PL PT RO RU SM RS SK SI ES SE CH UA GB VA TR FO GI GG IM JE",
    "North America": "AG BS BB BZ CA CR CU DM DO SV GD GT HT HN JM MX NI PA KN LC VC TT US PR BM KY GL",
    "South America": "AR BO BR CL CO EC GY PY PE SR UY VE",
    "Oceania": "AU FJ KI MH FM NR NZ PW PG WS SB TO TV VU NC PF GU",
}
_REGION_OF = {code: region for region, codes in _CONTINENTS.items() for code in codes.split()}
REGIONS = list(_CONTINENTS)


_NAME_INDEX: dict[str, str] = {}
for _a2, (_a3, *_names) in COUNTRIES.items():
    for _n in _names:
        _NAME_INDEX[_n.lower()] = _a2
    _NAME_INDEX[_a3.lower()] = _a2


@lru_cache(maxsize=4096)
def country_code(value: str | None) -> str | None:
    """Resolve a country name / ISO code / common alias to ISO-3166 alpha-2."""
    if not value:
        return None
    text = re.sub(r"\s+", " ", value).strip().strip(".").strip()
    if not text:
        return None
    low = text.lower()
    if low in _COUNTRY_ALIASES:
        return _COUNTRY_ALIASES[low]
    if len(text) == 2 and text.isalpha():
        return text.upper() if text.upper() in COUNTRIES else None
    if low in _NAME_INDEX:
        return _NAME_INDEX[low]
    # "Republic of X" / "X (the)" style variants
    stripped = re.sub(r"^(the|republic of|kingdom of|state of)\s+|\s*\(.*\)$", "", low).strip()
    return _NAME_INDEX.get(stripped)


def country_name(code: str | None) -> str | None:
    if not code:
        return None
    if code in _DISPLAY_NAMES:
        return _DISPLAY_NAMES[code]
    entry = COUNTRIES.get(code)
    return entry[1] if entry else None


def resolve_place(raw: RawHackathon) -> tuple[str | None, str | None, str | None]:
    """Return (city, country_name, iso2) using explicit fields first, then the location string."""
    code = country_code(raw.country)
    city = raw.city
    parts = [p.strip() for p in (raw.location or "").split(",") if p.strip()]
    if raw.mode == "online" and not raw.country:
        return None, None, None
    if not code and parts:
        last = parts[-1]
        low = last.lower()
        if last.upper() in _US_STATES and len(last) == 2 and len(parts) >= 2:
            code = "US"
        elif last.upper() in _CA_PROVINCES and len(last) == 2 and len(parts) >= 2:
            code = "CA"
        elif low in _STATE_NAMES_US:
            code = "US"
        elif low in _STATE_NAMES_CA:
            code = "CA"
        elif low in _IN_STATES or low in _IN_CITIES:
            code = "IN"
        else:
            code = country_code(last)
            # "12345 Main St" or venue names resolve to nothing; postcodes like "MA 02139"
            if not code:
                m = re.match(r"([A-Z]{2})\s+\d{5}", last)
                if m and m.group(1) in _US_STATES:
                    code = "US"
    if not city and parts and raw.mode != "online":
        candidates = parts[:-1] if len(parts) >= 2 else parts
        # skip things that look like street addresses / venues
        for part in reversed(candidates):
            if re.search(r"\d", part) or part.upper() in _US_STATES or part.upper() in _CA_PROVINCES:
                continue
            if part.lower() in _IN_STATES and len(candidates) > 1:
                continue
            city = part
            break
        if city and country_code(city) == code:
            city = None
    return city, country_name(code), code


def region_of(code: str | None) -> str | None:
    return _REGION_OF.get(code or "")


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

# Fallback USD value of one unit of each currency. Live rates replace these
# when the refresher can reach the FX endpoint.
STATIC_USD_RATES: dict[str, float] = {
    "USD": 1.0, "INR": 0.0114, "EUR": 1.16, "GBP": 1.33, "CAD": 0.72, "AUD": 0.66, "SGD": 0.77,
    "CHF": 1.25, "AED": 0.272, "JPY": 0.0066, "CNY": 0.14, "HKD": 0.128, "NGN": 0.00065,
    "KES": 0.0077, "BRL": 0.18, "MXN": 0.054, "ZAR": 0.057, "PKR": 0.0035, "BDT": 0.0082,
    "LKR": 0.0033, "NPR": 0.0071, "IDR": 0.00006, "MYR": 0.237, "PHP": 0.017, "THB": 0.03,
    "VND": 0.000038, "KRW": 0.0007, "TRY": 0.024, "PLN": 0.27, "SEK": 0.105, "NOK": 0.099,
    "DKK": 0.155, "CZK": 0.047, "HUF": 0.0029, "ILS": 0.3, "SAR": 0.267, "QAR": 0.275,
    "EGP": 0.02, "NZD": 0.58, "TWD": 0.032, "UAH": 0.024, "RON": 0.23, "COP": 0.00025,
    "ARS": 0.00075, "CLP": 0.00105, "PEN": 0.29, "GHS": 0.08, "RWF": 0.0007,
}


def to_usd(amount: float | None, currency: str | None, rates: dict[str, float]) -> float | None:
    if not amount or not currency:
        return None
    rate = rates.get(currency.upper())
    if rate is None:
        return None
    return round(amount * rate, 2)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def _clean_title(title: str) -> str:
    title = re.sub(r"\s+", " ", title).strip()
    return title


_PLACEHOLDER_RE = re.compile(r"placeholder|/defaults?/|no[-_]?image|default[-_]?(logo|banner|image|cover)", re.I)


def _real_image(url: str | None) -> str | None:
    if not url or _PLACEHOLDER_RE.search(url) or not url.startswith(("http://", "https://")):
        return None
    return url


def normalize(
    raw: RawHackathon,
    rates: dict[str, float],
    first_seen_at: datetime | None = None,
    last_seen_at: datetime | None = None,
) -> Hackathon:
    city, country, code = resolve_place(raw)
    spot = locate(raw, city, code)
    duration = None
    if raw.starts_at and raw.ends_at and raw.ends_at > raw.starts_at:
        duration = round((raw.ends_at - raw.starts_at).total_seconds() / 3600, 1)
    data = raw.model_dump()
    data.update(
        id=make_uid(raw.source, raw.source_id),
        title=_clean_title(raw.title),
        kind=infer_kind(raw),
        city=spot.city,
        state=spot.state,
        lat=spot.lat,
        lng=spot.lng,
        country=country,
        region=region_of(code),
        themes=classify_themes(raw),
        audience=classify_audience(raw),
        beginner_friendly=infer_beginner(raw),
        hiring=infer_hiring(raw),
        prize_usd=to_usd(raw.prize_amount, raw.prize_currency, rates),
        image_url=_real_image(raw.image_url),
        logo_url=_real_image(raw.logo_url),
        duration_hours=duration,
        first_seen_at=first_seen_at,
        last_seen_at=last_seen_at,
    )
    if raw.mode == "online":
        data["location"] = "Online"
    return Hackathon.model_validate(data)
