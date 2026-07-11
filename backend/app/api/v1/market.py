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

from fastapi import APIRouter, Depends, Query, Request

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import ok, server_error, too_many_requests, unprocessable
from ...schemas.envelope import Envelope
from ...schemas.market import (
    PriceProvenance,
    PriceRow,
    PricesResponse,
    SentimentResponse,
    SentimentRow,
)
from ...services import market_data

router = APIRouter(prefix="/api/v1/market", tags=["market"])

_logger = logging.getLogger(__name__)

_SENTIMENT_MODEL = "claude-haiku-4-5-20251001"


def _record_sentiment_cost(user_id: str, sentiments: list) -> None:
    """Log the actual token cost of a sentiment scan (Haiku × N tickers).
    Never raises."""
    try:
        import json

        from libs.billing.costs import estimate_cost_usd, estimate_tokens
        from libs.billing.usage import record_event

        # Rough: a short prompt+verdict per scored ticker.
        scored = [s for s in sentiments if s.get("headline_count")]
        tokens_in = 300 * max(1, len(scored))
        tokens_out = estimate_tokens(json.dumps(sentiments, default=str))
        cost = estimate_cost_usd(
            "anthropic", _SENTIMENT_MODEL, tokens_in=tokens_in, tokens_out=tokens_out
        )
        record_event(
            user_id,
            "analysis",
            provider="anthropic",
            model=_SENTIMENT_MODEL,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
        )
    except Exception:  # noqa: BLE001
        _logger.warning("market.sentiment.cost_record_failed")


@router.get(
    "/prices", summary="Latest adjusted close per ticker", response_model=Envelope[PricesResponse]
)
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

    prov: dict = {}
    try:
        latest = market_data.get_latest_prices(normalised, provenance=prov)
    except Exception as exc:
        _logger.warning("market.prices.fetch_failed err=%s", exc)
        raise server_error("Market data fetch failed.", reason=type(exc).__name__) from exc

    by_ticker = prov.get("by_ticker", {})

    def _source_for(price_row) -> str:
        ticker = str(getattr(price_row, "ticker", "") or "").upper()
        return (
            getattr(price_row, "source", None)
            or by_ticker.get(ticker)
            or by_ticker.get(str(getattr(price_row, "ticker", "")))
            or "unknown"
        )

    payload = PricesResponse(
        prices=[
            PriceRow(
                ticker=p.ticker,
                price=p.price,
                as_of=p.as_of,
                source=_source_for(p),
            )
            for p in latest
        ],
        requested=normalised,
        provenance=PriceProvenance(
            by_ticker=by_ticker,
            yfinance_fallback_used=market_data.yfinance_fallback_tickers(by_ticker),
            massive_fallback_used=market_data.massive_fallback_tickers(by_ticker),
            missing=prov.get("missing", []),
        ),
    )
    return ok(payload.model_dump(), request=request, started_at=started)


@router.post(
    "/sentiment",
    summary="AI sentiment per holding (authed, credits)",
    response_model=Envelope[SentimentResponse],
)
def portfolio_sentiment(request: Request, user: AuthedUser = Depends(require_user)):
    """Per-holding AI sentiment over recent headlines for the caller's ACTIVE
    portfolio. Credit-gated (it's an LLM call per ticker); fail-open on a
    metering blip; degrades to neutral/data-only without an LLM key, so it never
    500s. Cached per ticker-set in the service."""
    started = time.perf_counter()

    # Active tickers (fail-soft — empty portfolio → no work, not a 422).
    from ...services._common import active_tickers

    tickers = active_tickers(user.access_token)
    if not tickers:
        return ok(
            SentimentResponse(sentiments=[], ai_generated=False).model_dump(),
            request=request,
            started_at=started,
        )

    # Credit gate (LLM). Out of credits → 429; metering blip → fail-open.
    from libs.billing.usage import ESTIMATED_COST_USD, QuotaExceeded, check_credits

    try:
        check_credits(user.id, email=user.email, estimated_cost_usd=ESTIMATED_COST_USD["analysis"])
    except QuotaExceeded as exc:
        raise too_many_requests(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        _logger.warning("market.sentiment.credit_check_failed reason=%s", type(exc).__name__)

    from ...services import market_sentiment
    from ...services.llm_client import get_llm_callable

    llm = get_llm_callable(with_tools=False)
    rows = market_sentiment.score_portfolio_sentiment(tickers, llm_callable=llm)
    if llm is not None:
        _record_sentiment_cost(user.id, rows)

    payload = SentimentResponse(
        sentiments=[SentimentRow(**r) for r in rows],
        ai_generated=llm is not None,
    )
    return ok(payload.model_dump(), request=request, started_at=started)
