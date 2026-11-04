"""TAIKAI: hackathon platform used by companies, EU programmes and Web3 ecosystems.

Public GraphQL API (the one taikai.network itself calls; introspection is off,
field names come from the site's bundled queries):

    POST https://api.taikai.network/api/graphql
    challenges(where: {publishInfo: ACTIVE, steps: {some: {startDate >= now}}}, page: N)

A challenge is a list of named timeline "steps" that only carry a start date;
the last step marks the end (TAIKAI's own JSON-LD uses first/last step as
start/end). Registration window, team size, tracks and the markdown tabs
(overview / rules / prizes / faqs) come back in the same query, so no per-item
requests are needed.

TAIKAI has no attendance-mode or venue field (its JSON-LD hard-codes "online"
for every event), so ``mode`` is only set when the description says so in
plain words.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

import httpx
import pycountry

from ..models import RawHackathon
from .base import Source, as_int, clean_text, html_to_text, post_json, to_utc

log = logging.getLogger(__name__)

API = "https://api.taikai.network/api/graphql"
SITE = "https://taikai.network"
MAX_PAGES = 20

QUERY = """
query HackmashChallenges($page: Int, $since: DateTime) {
  challenges(
    where: {
      publishInfo: { state: { equals: ACTIVE } }
      steps: { some: { startDate: { gte: $since } } }
    }
    page: $page
    orderBy: { order: desc }
  ) {
    id name slug isClosed isPublic shortDescription keywords
    prize prizeDecimals prizeCurrency { name }
    organization { name slug city country }
    startParticipantRegistrationDate endParticipantRegistrationDate
    maxMembersPerProject allowedParticipants participantsCount registrationDomainsWhiteList
    logoImageFile { url } cardImageFile { url } coverImageFile { url }
    industries { title } tags { title } categories { name }
    customLinks
    steps(orderBy: { startDate: asc }) { name startDate }
    tabs { title isEnabled content }
  }
  challengesPageInfo(
    where: {
      publishInfo: { state: { equals: ACTIVE } }
      steps: { some: { startDate: { gte: $since } } }
    }
    orderBy: { order: desc }
  ) { pageCount recordCount }
}
"""

# step names (EN / PT / ES / FR) that mark the start of building
_START_RE = re.compile(
    r"kick[\s-]?off|hackathon\s+(?:weekend\s+)?(?:start|begin)|hacking\s+(?:start|begin)|"
    r"start\s+of\s+(?:the\s+)?(?:hackathon|hacking|challenge)|(?:hackathon|challenge)\s+(?:starts|begins)|"
    r"opening(?:\s+ceremony)?|arranque|in[ií]cio\s+d[oa]|abertura|comienzo|inicio\s+del|d[ée]but\s+du",
    re.I,
)
_SUBMIT_RE = re.compile(r"submission|submit|entrega|submiss|soumission|deadline\s+for\s+projects", re.I)
_EVAL_RE = re.compile(r"evaluat|judg|avalia|evalua|jury|j[uú]ri|pitch|demo\s*day|presenta", re.I)
_REG_RE = re.compile(r"regist|inscri", re.I)

_ONLINE_RE = re.compile(
    r"\b(?:online|virtual|remote)\s+(?:hackathon|event|competition|challenge|format|edition)\b|"
    r"\b(?:100\s*%|fully|entirely|completely)\s+(?:online|virtual|remote)\b|"
    r"\btakes?\s+place\s+(?:fully\s+|entirely\s+)?online\b",
    re.I,
)
_ONSITE_RE = re.compile(
    r"\b(?:in[\s-]person|on[\s-]?site|physical|presencial)\s+(?:hackathon|event|edition|competition)\b", re.I
)
_HYBRID_RE = re.compile(r"\bhybrid\s+(?:hackathon|event|format|edition)\b|\bh[íi]brid[oa]\b", re.I)

_SYMBOLS = {"USD": "$", "EUR": "€", "GBP": "£", "BRL": "R$"}
_STABLE = {"USDC": "USD", "USDT": "USD"}


def md_to_text(value: Any, max_len: int = 1500) -> str | None:
    """TAIKAI tab content is markdown with occasional inline HTML."""
    if not value:
        return None
    text = str(value)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s*", "", text)
    text = re.sub(r"(?m)^\s*(?:[-*+]|\d+\.)\s+", "• ", text)
    text = re.sub(r"(?m)^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", "", text)
    text = re.sub(r"(?m)^\s*\|?[\s:|-]+\|[\s:|-]*$", "", text)  # table separators
    text = text.replace("|", " ")
    text = re.sub(r"(\*\*|__|~~|`)", "", text)
    text = text.replace("\\", "")
    return html_to_text(text.replace("\n", "<br>"), max_len=max_len)


def _currencies_in(text: str) -> set[str]:
    found: set[str] = set()
    if re.search(r"R\$|\bBRL\b|\breais\b", text):
        found.add("BRL")
        text = re.sub(r"R\$", " ", text)
    if re.search(r"\$|\bUSD\b|\bUSDC\b|\bUSDT\b|\bdollars?\b", text, re.I):
        found.add("USD")
    if re.search(r"€|\bEUR\b|\beuros?\b", text, re.I):
        found.add("EUR")
    if re.search(r"£|\bGBP\b|\bpounds?\b", text, re.I):
        found.add("GBP")
    return found


def _is_fiat(code: str) -> bool:
    return bool(code) and code not in ("XAU", "XAG") and pycountry.currencies.get(alpha_3=code) is not None


def _safe_url(url: Any) -> str | None:
    if not url:
        return None
    return quote(str(url).strip(), safe=":/?&=%#+@,;~")


class Taikai(Source):
    key = "taikai"
    name = "TAIKAI"
    homepage = "https://taikai.network/hackathons"
    region = "global"
    focus = "Corporate, EU-programme and Web3 ecosystem hackathons"
    description = (
        "Hackathon platform used by companies, European space and innovation programmes and Web3 "
        "ecosystems, with multi-stage challenges, team matchmaking and prize tracks."
    )

    async def fetch(self, client: httpx.AsyncClient) -> list[RawHackathon]:
        since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        rows: list[dict[str, Any]] = []
        for page in range(MAX_PAGES):
            data = await post_json(client, API, {"query": QUERY, "variables": {"page": page, "since": since}})
            if data.get("errors") and not data.get("data"):
                raise RuntimeError(f"taikai graphql error: {data['errors'][0].get('message')}")
            payload = data.get("data") or {}
            batch = payload.get("challenges") or []
            rows.extend(batch)
            pages = (payload.get("challengesPageInfo") or {}).get("pageCount") or 0
            if not batch or page + 1 >= pages:
                break

        now = datetime.now(timezone.utc)
        items: list[RawHackathon] = []
        seen: set[str] = set()
        for row in rows:
            if not isinstance(row, dict) or row.get("id") in seen or row.get("isPublic") is False:
                continue
            seen.add(row.get("id"))
            try:
                item = self._build(row)
            except Exception:  # noqa: BLE001 - skip one bad row, keep the rest
                log.exception("taikai: could not parse challenge %s", row.get("slug"))
                continue
            end = item.ends_at or item.submission_deadline
            if end is None or end >= now - timedelta(hours=1):
                items.append(item)
        return items

    def _build(self, row: dict[str, Any]) -> RawHackathon:
        org = row.get("organization") or {}
        steps = [
            (to_utc(s.get("startDate")), clean_text(s.get("name")) or "")
            for s in row.get("steps") or []
            if isinstance(s, dict) and to_utc(s.get("startDate"))
        ]
        steps.sort(key=lambda s: s[0])
        reg_open = to_utc(row.get("startParticipantRegistrationDate"))
        reg_close = to_utc(row.get("endParticipantRegistrationDate"))

        start = next((at for at, name in steps if _START_RE.search(name)), None)
        if start is None and steps:
            after_reg = [
                at for at, name in steps if reg_close and at > reg_close and not _REG_RE.search(name)
            ]
            start = after_reg[0] if after_reg else steps[0][0]
        submission = next(
            (
                at
                for at, name in steps
                if _SUBMIT_RE.search(name) and not _REG_RE.search(name) and (start is None or at > start)
            ),
            None,
        )
        if submission is None and start is not None:
            submission = next((at for at, name in steps if at > start and _EVAL_RE.search(name)), None)
        end = steps[-1][0] if steps else None
        if start and end and end < start:
            start = None

        tabs = {
            str(t.get("title") or "").lower(): str(t.get("content") or "")
            for t in row.get("tabs") or []
            if isinstance(t, dict) and t.get("isEnabled", True) is not False and t.get("content")
        }
        overview = tabs.get("overview") or ""
        text_blob = " ".join(tabs.get(k, "") for k in ("overview", "rules", "faqs", "prizes"))
        if _HYBRID_RE.search(text_blob) or (_ONLINE_RE.search(text_blob) and _ONSITE_RE.search(text_blob)):
            mode = "hybrid"
        elif _ONLINE_RE.search(text_blob):
            mode = "online"
        elif _ONSITE_RE.search(text_blob):
            mode = "in_person"
        else:
            mode = None

        prize_amount = prize_currency = prize_text = None
        raw_prize = row.get("prize")
        if isinstance(raw_prize, (int, float)) and raw_prize > 0:
            amount = raw_prize / (10 ** (as_int(row.get("prizeDecimals")) or 0))
            currency = str((row.get("prizeCurrency") or {}).get("name") or "").upper()
            currency = _STABLE.get(currency, currency)
            # the challenge-level currency defaults to EUR; trust the prizes tab when it clearly disagrees
            hinted = _currencies_in(tabs.get("prizes", "") or text_blob)
            if currency and currency not in hinted and len(hinted) == 1:
                currency = next(iter(hinted))
            if _is_fiat(currency):
                prize_amount, prize_currency = float(amount), currency
                symbol = _SYMBOLS.get(currency)
                prize_text = f"{symbol}{amount:,.0f}" if symbol else f"{amount:,.0f} {currency}"
            elif currency:
                prize_text = f"{amount:,.0f} {currency}"

        tags: list[str] = []
        for value in [
            *(i.get("title") for i in row.get("industries") or [] if isinstance(i, dict)),
            *(t.get("title") for t in row.get("tags") or [] if isinstance(t, dict)),
            *str(row.get("keywords") or "").split(","),
        ]:
            tag = clean_text(value)
            if tag and tag.lower() not in {t.lower() for t in tags}:
                tags.append(tag)

        eligibility = []
        domains = [d for d in row.get("registrationDomainsWhiteList") or [] if d]
        if domains:
            eligibility.append("Registration limited to emails from: " + ", ".join(domains))

        team_max = as_int(row.get("maxMembersPerProject"))
        image = _safe_url(
            ((row.get("coverImageFile") or {}).get("url")) or (row.get("cardImageFile") or {}).get("url")
        )
        org_slug = org.get("slug") or ""
        return RawHackathon(
            source=self.key,
            source_id=str(row["id"]),
            title=clean_text(row.get("name")) or row["slug"],
            url=f"{SITE}/{org_slug}/hackathons/{row['slug']}",
            organizer=clean_text(org.get("name")),
            tagline=clean_text(row.get("shortDescription")),
            description=md_to_text(overview),
            image_url=image,
            logo_url=_safe_url((row.get("logoImageFile") or {}).get("url")),
            mode=mode,
            location="Online" if mode == "online" else None,
            starts_at=start,
            ends_at=end,
            registration_opens_at=reg_open,
            registration_deadline=reg_close,
            submission_deadline=submission,
            prize_text=prize_text,
            prize_amount=prize_amount,
            prize_currency=prize_currency,
            tags=tags,
            participants=as_int(row.get("participantsCount")),
            team_size_max=team_max if team_max and team_max > 0 else None,
            eligibility=eligibility,
            invite_only=True if domains else None,
            extra={
                "tracks": [clean_text(c.get("name")) for c in row.get("categories") or [] if c.get("name")],
                "timeline": [{"name": name, "starts_at": at.isoformat()} for at, name in steps],
                "participant_selection": "selected"
                if row.get("allowedParticipants") == "SELECTED"
                else "open",
                "is_closed": bool(row.get("isClosed")),
                "links": [
                    link.get("url")
                    for link in row.get("customLinks") or []
                    if isinstance(link, dict) and link.get("url")
                ],
            },
        )
