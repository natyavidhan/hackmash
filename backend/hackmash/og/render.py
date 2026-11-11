"""Draw hackathon posters with headless Chromium and send them to the site.

The browser never touches the network. Logos are downloaded here (https only,
public addresses only, size-capped, cached on disk) and handed to the page as
data: URIs; the page's Content-Security-Policy and a request filter block
everything else. Scraped text reaches the page only as JSON and is escaped there.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import ipaddress
import logging
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from ..share import Card, ShareContext, card_for
from ..sync import IngestClient

log = logging.getLogger("hackmash.og")

TEMPLATE = Path(__file__).parent / "poster.html"
JPEG_QUALITY = 84
LOGO_MAX_BYTES = 1_500_000
LOGO_RETRY_AFTER = 7 * 86_400  # a logo that failed is tried again a week later
_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


def sniff(data: bytes) -> str | None:
    """The image type from the file's first bytes (servers often say octet-stream)."""
    for magic, kind in _SIGNATURES:
        if data.startswith(magic):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        return "image/avif"
    head = data[:512].lstrip().lower()
    if head.startswith(b"<svg") or (head.startswith(b"<?xml") and b"<svg" in head):
        return "image/svg+xml"
    return None


async def _public_host(host: str) -> bool:
    """Does `host` resolve only to public addresses? (No fetching from the home network.)"""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError:
        return False
    return bool(infos) and all(ipaddress.ip_address(info[4][0]).is_global for info in infos)


class LogoCache:
    """Event logos as data: URIs, kept on disk by URL."""

    def __init__(self, directory: Path) -> None:
        self.dir = directory
        self.dir.mkdir(parents=True, exist_ok=True)

    async def data_uri(self, http: httpx.AsyncClient, url: str | None) -> str | None:
        if not url or not url.startswith("https://"):
            return None
        key = hashlib.sha1(url.encode()).hexdigest()
        path, bad = self.dir / key, self.dir / f"{key}.bad"
        if not path.exists():
            if bad.exists() and time.time() - bad.stat().st_mtime < LOGO_RETRY_AFTER:
                return None
            data = await self._download(http, url)
            if data is None:
                bad.touch()
                return None
            path.write_bytes(data)
            bad.unlink(missing_ok=True)
        data = path.read_bytes()
        kind = sniff(data)
        return f"data:{kind};base64,{base64.b64encode(data).decode()}" if kind else None

    async def _download(self, http: httpx.AsyncClient, url: str) -> bytes | None:
        for _ in range(4):  # follow redirects ourselves, checking every host
            host = urlparse(url).hostname or ""
            if not url.startswith("https://") or not await _public_host(host):
                return None
            try:
                async with http.stream("GET", url) as res:
                    if res.is_redirect and res.headers.get("location"):
                        url = urljoin(url, res.headers["location"])
                        continue
                    if res.status_code != 200:
                        return None
                    chunks, size = [], 0
                    async for chunk in res.aiter_bytes():
                        size += len(chunk)
                        if size > LOGO_MAX_BYTES:
                            return None
                        chunks.append(chunk)
            except httpx.HTTPError:
                return None
            data = b"".join(chunks)
            return data if sniff(data) else None
        return None


class Renderer:
    """A headless Chromium with a few pages, each holding the poster template."""

    def __init__(self, pages: int = 3) -> None:
        self.pages = pages

    async def __aenter__(self) -> Renderer:
        from playwright.async_api import async_playwright  # the `og` extra

        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch()
        self._pool: asyncio.Queue = asyncio.Queue()
        for _ in range(self.pages):
            page = await self._browser.new_page(viewport={"width": 1200, "height": 630}, device_scale_factor=1)
            await page.route("**/*", _only_local)
            await page.goto(TEMPLATE.as_uri())
            await self._pool.put(page)
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._browser.close()
        await self._pw.stop()

    async def render(self, card: dict[str, Any]) -> bytes:
        page = await self._pool.get()
        try:
            await page.evaluate("card => window.render(card)", card)
            return await page.screenshot(type="jpeg", quality=JPEG_QUALITY)
        finally:
            await self._pool.put(page)


async def _only_local(route: Any) -> None:
    if route.request.url.startswith(("file:", "data:")):
        await route.continue_()
    else:
        await route.abort()


@dataclass
class PosterReport:
    total: int
    drawn: int
    failed: int
    elapsed: float
    errors: list[str]

    def summary(self) -> str:
        failed = f", {self.failed} failed" if self.failed else ""
        return f"drew {self.drawn} link-preview posters ({self.total - self.drawn - self.failed} unchanged{failed}) in {self.elapsed:.0f}s"


async def publish_posters(
    doc: dict[str, Any],
    client: IngestClient | None,
    data_dir: Path,
    *,
    force: bool = False,
    only: set[str] | None = None,
    out_dir: Path | None = None,
    pages: int = 3,
) -> PosterReport:
    """Draw every poster whose content changed and send it (or write it to `out_dir`)."""
    started = time.monotonic()
    ctx = ShareContext.from_catalog(doc)
    cards: list[Card] = [card_for(item, ctx) for item in doc.get("items", []) if not only or item["id"] in only]
    have: dict[str, str] = {}
    if client is not None and out_dir is None and not force:
        have = (await asyncio.to_thread(client.og_state)).get("hashes") or {}
    todo = [c for c in cards if force or have.get(c.id) != c.hash]
    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)

    errors: list[str] = []
    drawn = 0
    if todo:
        logos = LogoCache(data_dir / "logos")
        headers = {"User-Agent": "hackmash/0.2 (+https://hackmash.xyz) link-preview posters", "Accept": "image/*,*/*;q=0.5"}
        async with httpx.AsyncClient(timeout=10.0, headers=headers, follow_redirects=False) as http, Renderer(pages) as renderer:
            gate = asyncio.Semaphore(pages * 2)

            async def one(card: Card) -> None:
                nonlocal drawn
                async with gate:
                    logo = await logos.data_uri(http, card.logo_url)
                    jpeg = await renderer.render({**card.to_dict(), "logo": logo})
                    if out_dir:
                        (out_dir / f"{card.id}.jpg").write_bytes(jpeg)
                    elif client is not None:
                        await asyncio.to_thread(client.put_og, card.id, card.hash, jpeg)
                    drawn += 1

            results = await asyncio.gather(*(one(c) for c in todo), return_exceptions=True)
            for card, res in zip(todo, results, strict=True):
                if isinstance(res, BaseException):
                    errors.append(f"{card.id}: {type(res).__name__}: {res}"[:300])
    report = PosterReport(total=len(cards), drawn=drawn, failed=len(errors), elapsed=time.monotonic() - started, errors=errors)
    for err in errors[:5]:
        log.warning("poster failed: %s", err)
    return report
