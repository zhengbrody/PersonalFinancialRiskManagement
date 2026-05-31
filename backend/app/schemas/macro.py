"""Response shapes for the macro endpoints."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class SeriesPointOut(BaseModel):
    date: str
    value: float


class SeriesResultOut(BaseModel):
    series_id: str
    label: str
    latest_value: Optional[float] = None
    latest_date: Optional[str] = None
    points: list[SeriesPointOut] = Field(default_factory=list)


class SeriesBatchResponse(BaseModel):
    """Payload for ``GET /api/v1/macro/series``."""

    series: list[SeriesResultOut]


class YieldCurvePointOut(BaseModel):
    tenor: str
    yield_pct: float


class YieldCurveResponse(BaseModel):
    """Payload for ``GET /api/v1/macro/yield_curve``."""

    as_of: str
    points: list[YieldCurvePointOut]


# ── /api/v1/macro/regime ───────────────────────────────────────────


class RegimeVixOut(BaseModel):
    current: Optional[float] = None
    change: Optional[float] = None
    level: Optional[str] = None


class RegimeFearGreedOut(BaseModel):
    score: Optional[float] = None
    rating: Optional[str] = None


class RegimeYieldCurveOut(BaseModel):
    status: Optional[str] = None
    spread_3m_10y: Optional[float] = None
    inverted: Optional[bool] = None


class RegimeResponse(BaseModel):
    """Payload for ``GET /api/v1/macro/regime``.

    Every leg is independently nullable — a dead upstream nulls only its
    own block, never the whole response.
    """

    vix: RegimeVixOut
    fear_greed: RegimeFearGreedOut
    yield_curve: RegimeYieldCurveOut
