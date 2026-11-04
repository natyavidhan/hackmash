"""Persistent state, kept as one JSON document so it can live anywhere.

The refresher reads the previous ``State``, merges in fresh adapter output and
writes back both the state and the public catalog snapshot. Storage backends
only need get/put of two blobs, which keeps deployment options open: a local
directory, Cloudflare KV, R2, S3...
"""

from __future__ import annotations

import gzip
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, Field

from .models import DeadlineChange, RawHackathon

DEFAULT_DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class ListingState(BaseModel):
    raw: RawHackathon
    first_seen_at: datetime
    last_seen_at: datetime
    changes: list[DeadlineChange] = Field(default_factory=list)


class RunInfo(BaseModel):
    started_at: datetime
    finished_at: datetime
    ok: bool
    count: int = 0
    error: str | None = None
    elapsed: float = 0.0


class SourceState(BaseModel):
    last_run: RunInfo | None = None
    last_ok: RunInfo | None = None


class State(BaseModel):
    version: int = 1
    updated_at: datetime | None = None
    listings: dict[str, ListingState] = Field(default_factory=dict)
    sources: dict[str, SourceState] = Field(default_factory=dict)
    fx_rates: dict[str, float] = Field(default_factory=dict)
    fx_updated_at: datetime | None = None


class Store(Protocol):
    async def load_state(self) -> State: ...

    async def save_state(self, state: State) -> None: ...

    async def load_catalog(self) -> bytes | None: ...

    async def save_catalog(self, data: bytes) -> None: ...


class FileStore:
    """Local directory: ``state.json.gz`` + ``catalog.json``."""

    def __init__(self, directory: str | Path | None = None) -> None:
        self.dir = Path(directory or os.environ.get("HACKMASH_DATA_DIR") or DEFAULT_DATA_DIR)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.dir / "state.json.gz"
        self.catalog_path = self.dir / "catalog.json"

    async def load_state(self) -> State:
        if not self.state_path.exists():
            return State()
        try:
            with gzip.open(self.state_path, "rt", encoding="utf-8") as fh:
                return State.model_validate_json(fh.read())
        except (OSError, ValueError):
            return State()

    async def save_state(self, state: State) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            fh.write(state.model_dump_json())
        tmp.replace(self.state_path)

    async def load_catalog(self) -> bytes | None:
        return self.catalog_path.read_bytes() if self.catalog_path.exists() else None

    async def save_catalog(self, data: bytes) -> None:
        tmp = self.catalog_path.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(self.catalog_path)


def dumps(obj: object) -> bytes:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")
