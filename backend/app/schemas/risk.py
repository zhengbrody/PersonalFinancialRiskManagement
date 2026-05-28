"""Request / response schemas for the risk-scoring endpoint.

Holdings come in as a list of plain Pydantic rows. The endpoint
converts them into the existing ``domain.models.PortfolioInput`` so
the engine's input contract is the only audited surface — we don't
duplicate validation rules here.

Returns are the deterministic engine output as JSON. The frontend
never sees the dataclass; we serialise once at the boundary.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

AssetType = Literal["public_security", "cash", "crypto", "real_estate"]


class HoldingIn(BaseModel):
    """One row in the request body. Maps 1:1 to
    ``domain.models.AssetPositionInput`` minus a couple of nullable
    quality-of-life fields. Same validation rules apply once we
    rebuild the engine's model — keeping the schema deliberately
    permissive here lets the engine emit the precise error code."""

    model_config = ConfigDict(str_strip_whitespace=True)

    ticker: str = Field(..., min_length=1, max_length=20)
    name: str = Field(default="", max_length=120)
    asset_type: AssetType = "public_security"
    market_value: float = Field(..., ge=0)
    cost_basis: float = Field(default=0.0, ge=0)
    expense_ratio: float = Field(default=0.0, ge=0, le=0.10)
    source: str = Field(default="api", max_length=40)
    proxy_ticker: Optional[str] = None
    enabled: bool = True


class ScoreRequest(BaseModel):
    """Body for ``POST /api/v1/risk/score``.

    ``returns`` is an optional inline daily-returns matrix as a
    ``{ticker: [r1, r2, …]}`` dict. When omitted the endpoint synthesises
    a deterministic-but-realistic return stream so the API is testable
    without a market-data fetcher. Production callers should always pass
    real returns; the synthetic fallback is documented as a dev aid.
    """

    holdings: list[HoldingIn] = Field(..., min_length=1)
    risk_preference: int = Field(default=3, ge=1, le=5)
    risk_free_rate: float = Field(default=0.045, ge=0.0, le=0.20)
    returns: Optional[dict[str, list[float]]] = None
    benchmark_returns: Optional[list[float]] = None


class DimensionScoreOut(BaseModel):
    name: str
    score: float
    status: str
    detail: str


class PortfolioMetricsOut(BaseModel):
    annual_return: Optional[float] = None
    annual_volatility: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    var_95_daily: Optional[float] = None
    cvar_95_daily: Optional[float] = None
    beta_to_benchmark: Optional[float] = None
    total_value: Optional[float] = None
    cash_weight: Optional[float] = None
    data_coverage: Optional[float] = None
    observations: Optional[int] = None
    data_quality_notes: list[str] = Field(default_factory=list)


class ScoreResponse(BaseModel):
    overall_score: int
    risk_preference: int
    risk_target: dict
    metrics: PortfolioMetricsOut
    dimensions: dict[str, DimensionScoreOut]
