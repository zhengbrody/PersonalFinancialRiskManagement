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
