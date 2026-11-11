"""HTTP API (FastAPI) + static hosting for the built React app, for running Hackmash
locally or on your own server. In production the same routes are served by the
Cloudflare Worker in ``worker/src`` from D1, which ``hackmash sync`` fills.

    GET  /api/catalog                      the catalog the web app filters locally (ETag-cached)
    GET  /api/hackathons                   server-side search/filter/sort (public API)
    GET  /api/hackathons/{id}              one listing (also resolves ids of merged duplicates)
    GET  /api/hackathons/{id}/calendar.ics calendar file: event + deadline reminders
    GET  /api/calendar.ics?ids=a,b         subscribable calendar for a personal tracker
    GET  /api/sources                      platforms and their fetch health
    GET  /api/health                       liveness + data freshness
    POST /api/admin/refresh                re-fetch now (local server only; needs HACKMASH_ADMIN_TOKEN)

``hackmash.server:app`` reads the store the refresher writes and runs the
refresh loop in-process. The catalog comes through a ``CatalogSource``, so other
storage can be plugged in.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Annotated, Any, Protocol

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response

from . import __version__
from .ics import calendar
from .query import LoadedCatalog
from .query import Query as SearchQuery

log = logging.getLogger("hackmash.api")


class CatalogSource(Protocol):
    async def get(self, request: Request) -> LoadedCatalog | None: ...


def _split(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for v in values or []:
        out.extend(p.strip() for p in v.split(",") if p.strip())
    return out


def _ics_response(body: str, filename: str) -> Response:
    return Response(
        body,
        media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{filename}"', "Cache-Control": "public, max-age=1800"},
    )


def create_app(
    source: CatalogSource,
    *,
    lifespan: Any = None,
    static_dir: Path | None = None,
    refresh: Any = None,
    gzip: bool = True,
) -> FastAPI:
    """Build the API around a catalog source.

    ``refresh`` is an optional ``async (keys) -> None`` callable that powers the
    admin endpoint; ``static_dir`` serves a built frontend with SPA fallback.
    """
    app = FastAPI(
        title="Hackmash API",
        version=__version__,
        description="Every hackathon from every platform, in one feed. Data: public listings, refreshed every few hours.",
        lifespan=lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    if gzip:  # off on Cloudflare, whose edge compresses responses itself
        app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"], allow_headers=["*"])

    async def catalog(request: Request) -> LoadedCatalog:
        cat = await source.get(request)
        if cat is None:
            raise HTTPException(503, "Catalog not built yet. The first refresh is still running; try again shortly.")
        return cat

    @app.get("/api/health")
    async def health(request: Request) -> dict[str, Any]:
        cat = await source.get(request)
        return {
            "ok": cat is not None,
            "version": __version__,
            "generated_at": cat.doc.get("generated_at") if cat else None,
            "count": len(cat.items) if cat else 0,
        }

    @app.get("/api/catalog")
    @app.get("/data/catalog.json", include_in_schema=False)
    async def get_catalog(request: Request, if_none_match: Annotated[str | None, Header()] = None) -> Response:
        cat = await catalog(request)
        headers = {"ETag": cat.etag, "Cache-Control": "public, max-age=300, stale-while-revalidate=3600"}
        if if_none_match == cat.etag:
            return Response(status_code=304, headers=headers)
        return Response(cat.data, media_type="application/json", headers=headers)

    @app.get("/api/hackathons")
    async def search(
        request: Request,
        q: str | None = None,
        source_: Annotated[list[str] | None, Query(alias="source")] = None,
        mode: Annotated[list[str] | None, Query()] = None,
        kind: Annotated[list[str] | None, Query()] = None,
        theme: Annotated[list[str] | None, Query()] = None,
        audience: Annotated[list[str] | None, Query()] = None,
        country: Annotated[list[str] | None, Query()] = None,
        region: Annotated[list[str] | None, Query()] = None,
        status: Annotated[list[str] | None, Query(description="open | live | upcoming | ended")] = None,
        min_prize_usd: float | None = None,
        beginner: bool | None = None,
        free: bool | None = None,
        ids: Annotated[list[str] | None, Query()] = None,
        sort: str = "deadline",
        page: int = 1,
        page_size: int = 30,
    ) -> dict[str, Any]:
        cat = await catalog(request)
        query = SearchQuery(
            q=q,
            source=_split(source_),
            mode=_split(mode),
            kind=_split(kind),
            theme=_split(theme),
            audience=_split(audience),
            country=_split(country),
            region=_split(region),
            status=_split(status),
            min_prize_usd=min_prize_usd,
            beginner=beginner,
            free=free,
            ids=_split(ids),
            sort=sort,
            page=page,
            page_size=page_size,
        )
        total, items = cat.search(query)
        return {
            "total": total,
            "page": query.page,
            "page_size": query.page_size,
            "generated_at": cat.doc.get("generated_at"),
            "items": items,
        }

    @app.get("/api/hackathons/{hid}")
    async def get_one(request: Request, hid: str) -> dict[str, Any]:
        cat = await catalog(request)
        item = cat.by_id.get(hid)
        if not item:
            raise HTTPException(404, "No such hackathon (it may have ended more than 30 days ago).")
        return cat.enrich(item)

    @app.get("/api/hackathons/{hid}/calendar.ics")
    async def one_calendar(request: Request, hid: str) -> Response:
        cat = await catalog(request)
        item = cat.by_id.get(hid)
        if not item:
            raise HTTPException(404, "No such hackathon")
        return _ics_response(calendar([item], name=item.get("title", "Hackathon")), f"{item['id']}.ics")

    @app.get("/api/calendar.ics")
    async def tracker_calendar(
        request: Request,
        ids: Annotated[list[str] | None, Query()] = None,
        name: str = "My hackathons",
    ) -> Response:
        cat = await catalog(request)
        items, seen = [], set()
        for i in _split(ids)[:300]:
            it = cat.by_id.get(i)
            if it and it["id"] not in seen:
                seen.add(it["id"])
                items.append(it)
        return _ics_response(calendar(items, name=f"Hackmash: {name}"[:80]), "hackmash.ics")

    @app.get("/api/sources")
    async def sources(request: Request) -> dict[str, Any]:
        cat = await catalog(request)
        return {"generated_at": cat.doc.get("generated_at"), "sources": cat.sources}

    if refresh is not None:
        admin_token = os.environ.get("HACKMASH_ADMIN_TOKEN")

        @app.post("/api/admin/refresh")
        async def admin_refresh(
            authorization: Annotated[str | None, Header()] = None,
            source_: Annotated[list[str] | None, Query(alias="source")] = None,
        ) -> JSONResponse:
            if not admin_token or authorization != f"Bearer {admin_token}":
                raise HTTPException(403, "Refresh requires HACKMASH_ADMIN_TOKEN")
            started = await refresh(_split(source_) or None)
            if not started:
                return JSONResponse({"started": False, "reason": "a refresh is already running"}, status_code=409)
            return JSONResponse({"started": True}, status_code=202)

    if static_dir and static_dir.is_dir():
        root = static_dir.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> Response:
            if path.startswith(("api/", "data/")):
                raise HTTPException(404)
            candidate = (root / path).resolve()
            if path and candidate.is_file() and root in candidate.parents:
                cache = "public, max-age=31536000, immutable" if path.startswith("assets/") else "public, max-age=300"
                return FileResponse(candidate, headers={"Cache-Control": cache})
            return FileResponse(root / "index.html", headers={"Cache-Control": "no-cache"})

    return app
