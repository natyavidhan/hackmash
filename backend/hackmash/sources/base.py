"""Base class and shared helpers for source adapters.

A source adapter is a subclass of ``Source`` living in its own module inside
``hackmash/sources/``. Modules are discovered automatically (see
``sources/__init__.py``); no registry edits are needed.

Test one adapter with::

    uv run hackmash fetch <key>            # summary + quality report
    uv run hackmash fetch <key> --json     # dump normalised items
"""

from __future__ import annotations

import asyncio
import html as html_lib
import logging
import re
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Iterable
from datetime import datetime, timezone, tzinfo
from typing import Any, ClassVar, TypeVar
from urllib.parse import urljoin

import httpx
from dateutil import parser as date_parser
from dateutil import tz as date_tz

from ..models import RawHackathon

log = logging.getLogger("hackmash.sources")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36 Hackmash/0.1 (+https://github.com/hackmash)"
)

IST = date_tz.gettz("Asia/Kolkata")
UTC = timezone.utc

T = TypeVar("T")


class SourceError(RuntimeError):
    """Raised when a source cannot be fetched or parsed at all."""


class Source(ABC):
    """One hackathon platform."""

    key: ClassVar[str]  # short id, lowercase, e.g. "devpost"
    name: ClassVar[str]  # display name, e.g. "Devpost"
    homepage: ClassVar[str]  # e.g. "https://devpost.com/hackathons"
    region: ClassVar[str] = "global"  # "global" or "india"
    focus: ClassVar[str] = ""  # short phrase, e.g. "Student hackathons (MLH member events)"
    description: ClassVar[str] = ""  # one or two sentences shown on the Sources page
    enabled: ClassVar[bool] = True  # set False to keep an adapter in the tree but skip it

    @abstractmethod
    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        """Return every current (open, upcoming or live) listing on the platform."""


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def make_client(**kwargs: Any) -> httpx.AsyncClient:
    headers = {
        "User-Agent": USER_AGENT,
        # Several platforms' WAFs (e.g. Devpost) reject a browser-style Accept header
        # from a non-browser client, so keep it generic. Override per request if needed.
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }
    headers.update(kwargs.pop("headers", {}))
    return httpx.AsyncClient(
        headers=headers,
        timeout=httpx.Timeout(30.0, connect=15.0),
        follow_redirects=True,
        **kwargs,
    )


async def request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    retries: int = 3,
    **kwargs: Any,
) -> httpx.Response:
    """HTTP request with retry + backoff on network errors, 429 and 5xx."""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = await client.request(method, url, **kwargs)
            if resp.status_code == 429 or resp.status_code >= 500:
                raise httpx.HTTPStatusError(
                    f"HTTP {resp.status_code}", request=resp.request, response=resp
                )
            resp.raise_for_status()
            return resp
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            last_exc = exc
            status = exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            if status is not None and status < 500 and status != 429:
                break  # 4xx other than 429 will not get better
            await asyncio.sleep(1.5 * (attempt + 1))
    if isinstance(last_exc, httpx.HTTPStatusError):
        reason = f"HTTP {last_exc.response.status_code}"
    else:
        reason = type(last_exc).__name__ if last_exc else "unknown error"
    raise SourceError(f"{method} {url} failed: {reason}") from last_exc


async def get_json(client: httpx.AsyncClient, url: str, **kwargs: Any) -> Any:
    resp = await request(client, "GET", url, **kwargs)
    return resp.json()


async def post_json(client: httpx.AsyncClient, url: str, payload: Any, **kwargs: Any) -> Any:
    resp = await request(client, "POST", url, json=payload, **kwargs)
    return resp.json()


async def get_text(client: httpx.AsyncClient, url: str, **kwargs: Any) -> str:
    resp = await request(client, "GET", url, **kwargs)
    return resp.text


async def gather_limited(coros: Iterable[Awaitable[T]], limit: int = 6) -> list[T | BaseException]:
    """Run awaitables with bounded concurrency; exceptions are returned, not raised."""
    sem = asyncio.Semaphore(limit)

    async def run(coro: Awaitable[T]) -> T:
        async with sem:
            return await coro

    return await asyncio.gather(*(run(c) for c in coros), return_exceptions=True)


# ---------------------------------------------------------------------------
# Dates
# ---------------------------------------------------------------------------


def to_utc(value: Any, assume_tz: tzinfo | str | None = UTC) -> datetime | None:
    """Parse ISO strings, human dates, epoch seconds/millis or datetimes into aware UTC.

    ``assume_tz`` is applied when the input carries no offset (default UTC). Pass
    ``IST`` for Indian platforms that publish local times, or an IANA name.
    Returns None for empty / unparseable input.
    """
    if value is None or value == "":
        return None
    if isinstance(assume_tz, str):
        assume_tz = date_tz.gettz(assume_tz) or UTC
    try:
        if isinstance(value, datetime):
            dt = value
        elif isinstance(value, (int, float)):
            seconds = value / 1000 if value > 1e11 else value
            dt = datetime.fromtimestamp(seconds, tz=UTC)
        elif isinstance(value, str):
            text = value.strip()
            if re.fullmatch(r"\d{10}(\d{3})?", text):
                return to_utc(int(text), assume_tz)
            dt = date_parser.parse(text)
        else:
            return None
    except (ValueError, OverflowError, TypeError):
        return None
    if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
        dt = dt.replace(tzinfo=assume_tz or UTC)
    return dt.astimezone(UTC)


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")
_BLOCK_RE = re.compile(r"</?(p|div|br|li|ul|ol|h[1-6]|tr|section|article)[^>]*>", re.I)


def clean_text(value: Any) -> str | None:
    """Collapse whitespace and unescape entities. Returns None for empty input."""
    if value is None:
        return None
    text = html_lib.unescape(str(value)).replace("\xa0", " ")
    text = _WS_RE.sub(" ", text)
    text = re.sub(r"\s*\n\s*", "\n", text).strip()
    return text or None


def html_to_text(value: Any, max_len: int = 1500) -> str | None:
    """Strip HTML to readable plain text, keeping paragraph breaks."""
    if not value:
        return None
    text = str(value)
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = _BLOCK_RE.sub("\n", text)
    text = _TAG_RE.sub(" ", text)
    text = clean_text(text) or ""
    text = re.sub(r"\n{3,}", "\n\n", text)
    if len(text) > max_len:
        cut = text[:max_len].rsplit(" ", 1)[0]
        text = cut.rstrip(" ,.;:") + "…"
    return text or None


def abs_url(base: str, url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    return urljoin(base, url)


# ---------------------------------------------------------------------------
# Money
# ---------------------------------------------------------------------------

_CURRENCY_SYMBOLS = {
    "$": "USD",
    "us$": "USD",
    "usd": "USD",
    "₹": "INR",
    "rs": "INR",
    "rs.": "INR",
    "inr": "INR",
    "€": "EUR",
    "eur": "EUR",
    "£": "GBP",
    "gbp": "GBP",
    "¥": "JPY",
    "jpy": "JPY",
    "cad": "CAD",
    "c$": "CAD",
    "aud": "AUD",
    "a$": "AUD",
    "sgd": "SGD",
    "s$": "SGD",
    "chf": "CHF",
    "aed": "AED",
    "usdc": "USD",
    "usdt": "USD",
}

_MULTIPLIERS = {
    "k": 1e3,
    "thousand": 1e3,
    "m": 1e6,
    "mn": 1e6,
    "million": 1e6,
    "lakh": 1e5,
    "lakhs": 1e5,
    "lac": 1e5,
    "lacs": 1e5,
    "l": 1e5,
    "crore": 1e7,
    "crores": 1e7,
    "cr": 1e7,
}

_MONEY_RE = re.compile(
    r"(?P<cur1>us\$|c\$|a\$|s\$|\$|₹|€|£|¥|rs\.?|inr|usd|eur|gbp|cad|aud|sgd|chf|aed|jpy)?\s*"
    r"(?P<num>\d[\d,]*(?:\.\d+)?)\s*"
    r"(?P<mult>k|thousand|mn|million|m|lakhs?|lacs?|l|crores?|cr)?\b\s*"
    r"(?P<cur2>usdc|usdt|usd|inr|eur|gbp|cad|aud|sgd|chf|aed|jpy)?",
    re.I,
)


def parse_money(text: Any, default_currency: str | None = None) -> tuple[float | None, str | None]:
    """Extract the largest money amount from text like "$10,000", "₹1.5 Lakh", "INR 50K".

    Returns (amount, currency). Plain numbers without a currency marker only
    count when ``default_currency`` is given.
    """
    if text is None:
        return None, None
    if isinstance(text, (int, float)):
        return (float(text), default_currency) if text > 0 else (None, None)
    best: tuple[float, str] | None = None
    for m in _MONEY_RE.finditer(html_lib.unescape(str(text))):
        cur_raw = (m.group("cur1") or m.group("cur2") or "").lower()
        currency = _CURRENCY_SYMBOLS.get(cur_raw) or (default_currency if not cur_raw else None)
        if not currency:
            continue
        try:
            amount = float(m.group("num").replace(",", ""))
        except ValueError:
            continue
        mult = (m.group("mult") or "").lower()
        if mult == "m" and not cur_raw:
            continue  # "5m" without currency is more likely minutes/metres
        amount *= _MULTIPLIERS.get(mult, 1)
        if amount <= 0:
            continue
        if best is None or amount > best[0]:
            best = (amount, currency)
    return best if best else (None, None)


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def first(*values: Any) -> Any:
    """First value that is not None / empty."""
    for v in values:
        if v not in (None, "", [], {}):
            return v
    return None


def as_int(value: Any) -> int | None:
    try:
        if value in (None, ""):
            return None
        return int(float(str(value).replace(",", "")))
    except (TypeError, ValueError):
        return None


def mode_from(text: Any) -> str | None:
    """Map free-text like "Online", "offline", "In-person", "Hybrid" to a Mode."""
    if text is None:
        return None
    t = str(text).strip().lower()
    if not t:
        return None
    if "hybrid" in t:
        return "hybrid"
    if any(w in t for w in ("online", "virtual", "remote", "digital")):
        return "online"
    if any(w in t for w in ("offline", "in-person", "in person", "inperson", "on-site", "onsite", "venue")):
        return "in_person"
    return None
