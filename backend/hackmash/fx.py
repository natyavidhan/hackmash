"""Currency conversion rates (USD value of one unit), refreshed daily."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx

from .normalize import STATIC_USD_RATES
from .state import State

log = logging.getLogger(__name__)

FX_URL = "https://open.er-api.com/v6/latest/USD"  # free, no key, daily updates
MAX_AGE = timedelta(hours=20)


async def update_rates(state: State, client: httpx.AsyncClient) -> dict[str, float]:
    """Return USD-per-unit rates, fetching fresh ones when the cached set is stale."""
    now = datetime.now(timezone.utc)
    fresh = state.fx_updated_at and now - state.fx_updated_at < MAX_AGE and state.fx_rates
    if not fresh:
        try:
            resp = await client.get(FX_URL, timeout=15)
            resp.raise_for_status()
            per_usd = resp.json().get("rates") or {}
            rates = {code: round(1 / value, 8) for code, value in per_usd.items() if value}
            if rates.get("INR"):
                state.fx_rates = rates
                state.fx_updated_at = now
        except Exception as exc:  # noqa: BLE001 - static rates are a fine fallback
            log.warning("fx: could not fetch live rates (%s); using cached/static rates", exc)
    return {**STATIC_USD_RATES, **state.fx_rates, "USD": 1.0}
