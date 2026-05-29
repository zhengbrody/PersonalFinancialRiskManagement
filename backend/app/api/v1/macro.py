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
    SeriesBatchResponse,
    SeriesPointOut,
    SeriesResultOut,
    YieldCurvePointOut,
    YieldCurveResponse,
)
from ...services import macro_data

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
