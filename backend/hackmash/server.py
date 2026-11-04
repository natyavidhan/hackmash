"""Local / container server: the API over the file store, with the refresh loop in-process.

    uv run hackmash serve            # or: uvicorn hackmash.server:app
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, Request

from .api import create_app
from .query import LoadedCatalog
from .state import FileStore

log = logging.getLogger("hackmash.server")


# ---------------------------------------------------------------------------


class LocalRuntime:
    """Reads the catalog the refresher writes and re-fetches on a schedule."""

    def __init__(self) -> None:
        self.store = FileStore()
        self.catalog: LoadedCatalog | None = None
        self.lock = asyncio.Lock()
        self.refreshing = False
        self.interval = timedelta(hours=float(os.environ.get("HACKMASH_REFRESH_HOURS", "4")))

    async def get(self, request: Request) -> LoadedCatalog | None:
        return self.catalog

    async def reload(self) -> None:
        data = await self.store.load_catalog()
        if data:
            self.catalog = LoadedCatalog(data)

    async def _refresh(self, keys: list[str] | None = None) -> None:
        from .pipeline import refresh_all  # lazy: adapters pull in scraping deps

        async with self.lock:
            self.refreshing = True
            try:
                results = await refresh_all(keys, self.store)
                failed = [r.source for r in results if not r.ok]
                log.info("refresh done: %d sources, failed: %s", len(results), failed or "none")
                await self.reload()
            finally:
                self.refreshing = False

    async def trigger(self, keys: list[str] | None = None) -> bool:
        if self.refreshing:
            return False
        asyncio.create_task(self._refresh(keys))
        return True

    async def loop(self) -> None:
        while True:
            try:
                if self.catalog is None or self.catalog.is_stale(self.interval):
                    await self._refresh()
            except Exception:  # noqa: BLE001 - keep the loop alive
                log.exception("scheduled refresh failed")
            await asyncio.sleep(600)


def _local_app() -> FastAPI:
    runtime = LocalRuntime()
    auto = os.environ.get("HACKMASH_AUTO_REFRESH", "1") not in ("0", "false", "no")
    static = Path(os.environ.get("HACKMASH_STATIC_DIR") or Path(__file__).resolve().parents[2] / "frontend" / "dist")

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await runtime.reload()
        task = asyncio.create_task(runtime.loop()) if auto else None
        yield
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = create_app(runtime, lifespan=lifespan, static_dir=static, refresh=runtime.trigger)
    app.state.runtime = runtime
    return app


app = _local_app()
