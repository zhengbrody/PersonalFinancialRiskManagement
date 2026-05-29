"""``GET /api/v1/market/prices`` — public market-data slice.

Public because price quotes are not sensitive. Auth would only add
friction without protecting anything — a logged-out user reading
SPY's close is identical to a Yahoo Finance widget.

The underlying ``services.market_data`` module caches per-ticker at
the file system (24h TTL by default), so a hot endpoint returns
in <50ms even with no in-process cache. We'll layer Redis here if
we move to multi-instance backend in Phase 5+.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Query, Request

from ...core.responses import ok, server_error, unprocessable
from ...schemas.market import PriceRow, PricesResponse
from ...services import market_data

router = APIRouter(prefix="/api/v1/market", tags=["market"])

_logger = logging.getLogger(__name__)


@router.get("/prices", summary="Latest adjusted close per ticker")
def get_prices(
    request: Request,
    tickers: str = Query(
        ...,
        min_length=1,
        max_length=1024,
        description=(
            "Comma-separated ticker list. Case-insensitive, deduped "
            "server-side. Example: `?tickers=SPY,BND,AAPL`."
        ),
    ),
):
    """Return the most recent adjusted close + bar date per ticker.

    Tickers yfinance can't price (delisted, typo) are silently
    omitted from `prices`; compare against `requested` to find them.
    """
    started = time.perf_counter()

    raw = [t for t in tickers.split(",") if t.strip()]
    try:
        normalised = market_data._normalise_tickers(raw)
    except ValueError as exc:
        raise unprocessable(str(exc)) from exc

    try:
        latest = market_data.get_latest_prices(normalised)
    except Exception as exc:
        _logger.warning("market.prices.fetch_failed err=%s", exc)
        raise server_error("Market data fetch failed.", reason=type(exc).__name__) from exc

    payload = PricesResponse(
        prices=[PriceRow(ticker=p.ticker, price=p.price, as_of=p.as_of) for p in latest],
        requested=normalised,
    )
    return ok(payload.model_dump(), request=request, started_at=started)
