"""Cloudflare Workers entry point for the Hackmash API.

The scrapers run elsewhere (GitHub Actions, see .github/workflows/refresh.yml)
and publish /data/catalog.json as a static asset of this Worker. Here we only
read that file through the ASSETS binding and serve the shared FastAPI routes.
`build.sh` copies the needed `hackmash` modules next to this file.
"""

import time

from workers import WorkerEntrypoint, asgi

from hackmash.api import create_app
from hackmash.query import LoadedCatalog

CATALOG_PATH = "/data/catalog.json"
CACHE_SECONDS = 300


class AssetsCatalog:
    """Loads the catalog from static assets, cached per isolate for a few minutes."""

    def __init__(self) -> None:
        self._catalog: LoadedCatalog | None = None
        self._loaded_at = 0.0

    async def get(self, request):
        now = time.monotonic()
        if self._catalog is not None and now - self._loaded_at < CACHE_SECONDS:
            return self._catalog
        env = request.scope["env"]
        resp = await env.ASSETS.fetch(f"https://assets.local{CATALOG_PATH}")
        if resp.ok:
            data = (await resp.text()).encode("utf-8")
            if self._catalog is None or self._catalog.data != data:
                self._catalog = LoadedCatalog(data)
            self._loaded_at = now
        return self._catalog


app = create_app(AssetsCatalog(), gzip=False)


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        return await asgi.fetch(app, request, self.env, self.ctx)
