"""``GET /api/v1/macro/*`` — free macro data slice.

Public endpoints. Macro series + the Treasury yield curve are public
information; gating them adds friction without protecting anything.
The service module enforces an allow-list on FRED series so this
backend can never become an unwitting free FRED proxy.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Query, Request

from ...core.responses import ok, server_error, unprocessable
from ...schemas.macro import (
    MoverRowOut,
    MoversResponse,
    NewsItemOut,
    NewsResponse,
    RegimeDetailResponse,
    RegimeFearGreedOut,
    RegimeHistoryPointOut,
    RegimeResponse,
    RegimeVixOut,
    RegimeYieldCurveOut,
    SectorRowOut,
    SeriesBatchResponse,
    SeriesPointOut,
    SeriesResultOut,
    YieldCurvePointOut,
    YieldCurveResponse,
)
from ...services import macro_data, market_movers, market_news, market_regime, regime_detail

router = APIRouter(prefix="/api/v1/macro", tags=["macro"])

_logger = logging.getLogger(__name__)


@router.get("/series", summary="Last N days of one or more FRED series")
def get_series(
    request: Request,
    series: str = Query(
        ...,
        min_length=1,
        max_length=200,
        description=(
            "Comma-separated FRED series IDs. Only allow-listed series "
            "are returned — see ``services.macro_data.ALLOWED_FRED_SERIES``. "
            "Example: `?series=DFF,CPIAUCSL,UNRATE`."
        ),
    ),
    days: int = Query(
        365,
        ge=30,
        le=365 * 10,
        description="Trailing window in days. Min 30, max 10 years.",
    ),
):
    """Return latest-value + trailing window for each allow-listed series."""
    started = time.perf_counter()

    raw = [s for s in series.split(",") if s.strip()]
    try:
        # Validate first so a single bad ID rejects the whole call
        # before any HTTP work. _validate_series_id raises ValueError.
        for s in raw:
            macro_data._validate_series_id(s)
    except ValueError as exc:
        raise unprocessable(str(exc)) from exc

    try:
        results = macro_data.get_fred_series_batch(raw, days=days)
    except Exception as exc:
        _logger.warning("macro.series.fetch_failed err=%s", exc)
        raise server_error("FRED fetch failed.", reason=type(exc).__name__) from exc

    # Batch tolerates per-series failure (one delisted-or-broken series
    # shouldn't kill the dashboard). But when every requested series
    # fails, that's not a "success with empty data" — surface 500 so
    # the UI shows the right error state.
    if raw and not results:
        raise server_error("FRED fetch failed for every requested series.")

    payload = SeriesBatchResponse(
        series=[
            SeriesResultOut(
                series_id=r.series_id,
                label=r.label,
                latest_value=r.latest_value,
                latest_date=r.latest_date,
                points=[SeriesPointOut(date=p.date, value=p.value) for p in r.points],
            )
            for r in results
        ]
    )
    return ok(payload.model_dump(), request=request, started_at=started)


@router.get("/yield_curve", summary="Latest US Treasury daily yield curve")
def get_yield_curve(request: Request):
    """Return today's (or the most recent published) Treasury curve."""
    started = time.perf_counter()
    try:
        result = macro_data.get_yield_curve()
    except Exception as exc:
        _logger.warning("macro.yield_curve.fetch_failed err=%s", exc)
        raise server_error("Treasury fetch failed.", reason=type(exc).__name__) from exc

    payload = YieldCurveResponse(
        as_of=result.as_of,
        points=[YieldCurvePointOut(tenor=p.tenor, yield_pct=p.yield_pct) for p in result.points],
    )
    return ok(payload.model_dump(), request=request, started_at=started)


@router.get("/regime", summary="Market-regime snapshot: VIX, Fear & Greed, yield curve")
def get_regime(request: Request):
    """Return the current market regime. Public.

    Each leg (VIX / Fear & Greed / yield-curve status) is fetched
    independently and nulls itself on upstream failure — the panel
    renders partially rather than 500-ing on one dead source. Hence no
    error branch here: a well-formed (possibly partially-null) snapshot
    is always a 200.
    """
    started = time.perf_counter()
    snap = market_regime.get_market_regime()
    payload = RegimeResponse(
        vix=RegimeVixOut(current=snap.vix.current, change=snap.vix.change, level=snap.vix.level),
        fear_greed=RegimeFearGreedOut(score=snap.fear_greed.score, rating=snap.fear_greed.rating),
        yield_curve=RegimeYieldCurveOut(
            status=snap.yield_curve.status,
            spread_3m_10y=snap.yield_curve.spread_3m_10y,
            inverted=snap.yield_curve.inverted,
        ),
    )
    return ok(payload.model_dump(), request=request, started_at=started)


@router.get("/regime_detail", summary="Market-wide regime (bull/bear/transition) + history")
def get_regime_detail_endpoint(request: Request):
    """Return the composite market regime (bull / bear / transition) with a
    confidence, the sub-signals, and a ~1y history. Public. Fails soft to an
    empty snapshot — always a 200, never blocks the /markets page."""
    started = time.perf_counter()
    d = regime_detail.get_regime_detail()
    payload = RegimeDetailResponse(
        current_regime=d.current_regime,
        confidence=d.confidence,
        regime_since_date=d.regime_since_date,
        vix_regime=d.vix_regime,
        trend_regime=d.trend_regime,
        vol_regime=d.vol_regime,
        history=[RegimeHistoryPointOut(date=p.date, regime=p.regime) for p in d.history],
    )
    return ok(payload.model_dump(), request=request, started_at=started)


@router.get("/movers", summary="Sector performance + today's top gainers/losers")
def get_movers_endpoint(request: Request):
    """Sector ETF performance + S&P-500 top gainers/losers/unusual-volume.
    Public, free (yfinance). Fail-soft: any leg may be empty if its upstream is
    down — always a 200, never blocks the /markets page."""
    started = time.perf_counter()
    snap = market_movers.get_movers()

    def _movers(rows):
        return [
            MoverRowOut(
                ticker=m.ticker,
                name=m.name,
                change_pct=m.change_pct,
                close=m.close,
                avg_volume_ratio=m.avg_volume_ratio,
            )
            for m in rows
        ]

    payload = MoversResponse(
        scan_date=snap.scan_date,
        sectors=[
            SectorRowOut(
                sector=s.sector, ticker=s.ticker, change_pct=s.change_pct, ytd_return=s.ytd_return
            )
            for s in snap.sectors
        ],
        top_gainers=_movers(snap.top_gainers),
        top_losers=_movers(snap.top_losers),
        unusual_volume=_movers(snap.unusual_volume),
    )
    return ok(payload.model_dump(), request=request, started_at=started)


@router.get("/news", summary="Latest macro market news (free RSS + yfinance)")
def get_news_endpoint(request: Request):
    """Aggregated macro headlines. Public, free, fail-soft to an empty list."""
    started = time.perf_counter()
    items = market_news.get_macro_news()
    payload = NewsResponse(items=[NewsItemOut(**it) for it in items])
    return ok(payload.model_dump(), request=request, started_at=started)
