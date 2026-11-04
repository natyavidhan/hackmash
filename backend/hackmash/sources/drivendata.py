"""DrivenData: social-impact machine-learning prize competitions.

No public API; the server-rendered list ``https://www.drivendata.org/competitions/``
has one card per competition with data attributes (start date, joined count,
total prize purse, categories, difficulty) plus the exact deadline in the
end-date tooltip ("Dec. 3, 2026, 11:59 p.m. UTC").

Only cards in the live "Prize competitions" section (``#active_competitions``)
and any upcoming section are emitted; open-ended practice competitions and
benchmarks (no prize, rolling one-year windows) are skipped.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup, Tag

from ..models import RawHackathon
from .base import Source, abs_url, as_int, clean_text, get_text, parse_money, to_utc

log = logging.getLogger(__name__)

SITE = "https://www.drivendata.org"
LIST_URL = f"{SITE}/competitions/"

_SECTION_IDS = ("active_competitions", "upcoming_competitions")
_BG_RE = re.compile(r"background-image:\s*url\(\s*['\"]?([^'\")]+?)['\"]?\s*\)")


def parse_deadline(text: str | None) -> datetime | None:
    """'Dec. 3, 2026, 11:59 p.m. UTC' -> aware datetime."""
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"\bnoon\b", "12:00 p.m.", t, flags=re.I)
    t = re.sub(r"\bmidnight\b", "12:00 a.m.", t, flags=re.I)
    t = re.sub(r"\b([ap])\.m\.", lambda m: m.group(1).upper() + "M", t, flags=re.I)
    t = re.sub(r"\b(\d{1,2}) ([AP]M)\b", r"\1:00 \2", t)  # "11 PM" -> "11:00 PM"
    t = re.sub(r"\b(Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)\.", lambda m: m.group(1)[:3], t)
    return to_utc(t)


class DrivenData(Source):
    key = "drivendata"
    name = "DrivenData"
    homepage = "https://www.drivendata.org/competitions/"
    region = "global"
    focus = "Social-impact machine-learning prize competitions"
    description = (
        "Data-science competitions with social impact, run with partners such as NASA, the U.S. "
        "Department of Energy and the World Bank, with large cash prize pools."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        soup = BeautifulSoup(await get_text(client, LIST_URL), "lxml")
        cards: list[Tag] = []
        for section_id in _SECTION_IDS:
            section = soup.find(id=section_id)
            if isinstance(section, Tag):
                cards.extend(c for c in section.select("div.panel-container") if isinstance(c, Tag))

        now = datetime.now(timezone.utc)
        items: list[RawHackathon] = []
        seen: set[str] = set()
        for card in cards:
            try:
                item = self._build(card)
            except Exception:  # noqa: BLE001 - skip one bad card, keep the rest
                log.exception("drivendata: could not parse a competition card")
                continue
            if item is None or item.source_id in seen:
                continue
            seen.add(item.source_id)
            end = item.ends_at
            if end is None or end >= now - timedelta(hours=1):
                items.append(item)
        return items

    def _build(self, card: Tag) -> RawHackathon | None:
        title_link = card.select_one(".panel-competition-title a") or card.select_one("h3 a")
        if title_link is None or not title_link.get("href"):
            return None
        href = str(title_link["href"])
        m = re.search(r"/competitions/(\d+)/", href)
        source_id = m.group(1) if m else href.strip("/").split("/")[-1]
        title = clean_text(title_link.get_text(" ", strip=True))

        tags = [
            clean_text(a.get_text(strip=True).lstrip("#"))
            for a in [*card.select("a.text-category"), *card.select(".row-description .d-none a")]
        ]
        tags = list(dict.fromkeys(t.lower() for t in tags if t))
        description_el = card.select_one(".row-description p")
        tagline = None
        if description_el is not None:
            for hidden in description_el.select(".d-none"):
                hidden.decompose()
            tagline = clean_text(description_el.get_text(" ", strip=True))

        image = None
        image_el = card.select_one("a.image")
        if image_el is not None and (bg := _BG_RE.search(str(image_el.get("style") or ""))):
            image = bg.group(1).strip()
        logo_el = card.select_one(".panel-logo img")
        logo = abs_url(SITE, str(logo_el.get("src"))) if logo_el is not None and logo_el.get("src") else None
        organizer = None
        if logo_el is not None and logo_el.get("alt"):
            organizer = clean_text(re.sub(r"^Hosted by\s+", "", str(logo_el.get("alt")), flags=re.I))

        attrs: dict[str, Any] = dict(card.attrs)
        start = None
        start_raw = str(attrs.get("data-start_date") or "")
        if re.fullmatch(r"\d{8}", start_raw):
            start = to_utc(f"{start_raw[:4]}-{start_raw[4:6]}-{start_raw[6:]}T00:00:00Z")
        end_el = card.select_one(".end-date")
        end = parse_deadline(str(end_el.get("title"))) if end_el is not None and end_el.get("title") else None

        prize_el = card.select_one(".prize")
        prize_text = None
        if prize_el is not None:
            prize_text = clean_text(prize_el.parent.get_text(" ", strip=True)) if prize_el.parent else None
        amount, currency = parse_money(prize_text) if prize_text else (None, None)
        purse = attrs.get("data-total_prize_purse")
        try:
            purse_amount = float(str(purse)) if purse not in (None, "") else None
        except ValueError:
            purse_amount = None
        if purse_amount and currency:
            amount = purse_amount
        if not amount:
            amount = currency = None
            if prize_text and not re.search(r"\d", prize_text):
                prize_text = None

        difficulty = next(
            (k.removeprefix("data-difficulty_") for k in attrs if k.startswith("data-difficulty_")), None
        )
        return RawHackathon(
            source=self.key,
            source_id=source_id,
            title=title or source_id,
            url=abs_url(SITE, href) or LIST_URL,
            kind="data_science",
            organizer=organizer,
            tagline=tagline,
            image_url=image,
            logo_url=logo,
            mode="online",
            location="Online",
            starts_at=start,
            ends_at=end,
            submission_deadline=end,
            timezone="UTC",
            prize_text=prize_text,
            prize_amount=amount,
            prize_currency=currency,
            tags=tags,
            participants=as_int(attrs.get("data-joined")),
            beginner_friendly=True if difficulty == "beginner" else None,
            extra={"difficulty": difficulty},
        )
