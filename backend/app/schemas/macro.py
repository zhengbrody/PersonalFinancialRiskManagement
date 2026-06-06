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
    source: str = "FRED"
    cache_ttl_seconds: int = 3600
    refresh_policy: str = (
        "Auto-refreshes after cache expiry; FRED publication cadence controls when new observations appear."
    )


class YieldCurvePointOut(BaseModel):
    tenor: str
    yield_pct: float


class YieldCurveResponse(BaseModel):
    """Payload for ``GET /api/v1/macro/yield_curve``."""

    as_of: str
    points: list[YieldCurvePointOut]
    source: str = "US Treasury"
    cache_ttl_seconds: int = 3600
    refresh_policy: str = (
        "Auto-refreshes after cache expiry; Treasury publication cadence controls when the latest curve appears."
    )


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


# ── /api/v1/macro/regime_detail (bull/bear/transition "market season") ──


class RegimeHistoryPointOut(BaseModel):
    date: str
    regime: str


class RegimeDetailResponse(BaseModel):
    """Payload for ``GET /api/v1/macro/regime_detail``. Every scalar is
    nullable (fail-soft); ``history`` may be empty."""

    current_regime: Optional[str] = None
    confidence: Optional[float] = None
    regime_since_date: Optional[str] = None
    vix_regime: Optional[str] = None
    trend_regime: Optional[str] = None
    vol_regime: Optional[str] = None
    history: list[RegimeHistoryPointOut] = Field(default_factory=list)


# ── /api/v1/macro/movers (sector performance + top gainers/losers) ──


class SectorRowOut(BaseModel):
    sector: str
    ticker: str
    change_pct: Optional[float] = None
    ytd_return: Optional[float] = None


class MoverRowOut(BaseModel):
    ticker: str
    name: str = ""
    change_pct: Optional[float] = None
    close: Optional[float] = None
    avg_volume_ratio: Optional[float] = None


class MoversResponse(BaseModel):
    """Payload for ``GET /api/v1/macro/movers``. Public, fail-soft — any leg
    may be empty if its upstream is down."""

    scan_date: Optional[str] = None
    sectors: list[SectorRowOut] = Field(default_factory=list)
    top_gainers: list[MoverRowOut] = Field(default_factory=list)
    top_losers: list[MoverRowOut] = Field(default_factory=list)
    unusual_volume: list[MoverRowOut] = Field(default_factory=list)


# ── /api/v1/macro/news (free macro headlines) ──


class NewsItemOut(BaseModel):
    source: Optional[str] = None
    title: str
    link: Optional[str] = None
    published: Optional[str] = None
    summary: Optional[str] = None


class NewsResponse(BaseModel):
    items: list[NewsItemOut] = Field(default_factory=list)
