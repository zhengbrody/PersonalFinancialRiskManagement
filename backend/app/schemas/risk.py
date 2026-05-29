"""Request / response schemas for the risk-scoring endpoint.

Holdings come in as a list of plain Pydantic rows. The endpoint
converts them into the existing ``domain.models.PortfolioInput`` so
the engine's input contract is the only audited surface — we don't
duplicate validation rules here.

Returns are the deterministic engine output as JSON. The frontend
never sees the dataclass; we serialise once at the boundary.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

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


# ── /risk/report_from_active ───────────────────────────────────────


class FactorBetaRow(BaseModel):
    """One row of the factor-attribution table."""

    factor: str
    beta: Optional[float] = None
    r_squared: Optional[float] = None
    t_stat: Optional[float] = None
    p_value: Optional[float] = None


class ComponentVarRow(BaseModel):
    """One ticker's share of total portfolio VaR."""

    ticker: str
    pct: float


class StressAssetLoss(BaseModel):
    ticker: str
    loss_pct: float


class LiquidityRow(BaseModel):
    ticker: str
    days_to_liquidate: Optional[float] = None
    adv_30d: Optional[float] = None
    market_value: Optional[float] = None


class RiskReportOut(BaseModel):
    """JSON-safe projection of the engine's ``RiskReport`` dataclass.

    Large matrices (cov, corr, MC simulation paths) are intentionally
    NOT shipped over the wire — they'd add tens of MB and the dashboard
    doesn't render them anyway. If a chart needs them later, we add a
    targeted endpoint that returns just that slice."""

    # KPIs — scalars, NaN-scrubbed at the envelope layer.
    annual_return: Optional[float] = None
    annual_volatility: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    var_95: Optional[float] = None
    var_99: Optional[float] = None
    cvar_95: Optional[float] = None
    risk_free_rate: Optional[float] = None

    # Beta vs the configured benchmark (e.g. {"SPY": 1.02}).
    betas: dict[str, float] = Field(default_factory=dict)
    # Factor attribution table (SPY/QQQ/GLD/TLT/IWM/VTV).
    factor_betas: list[FactorBetaRow] = Field(default_factory=list)
    # Per-ticker share of total VaR.
    component_var_pct: list[ComponentVarRow] = Field(default_factory=list)

    # Stress test summary.
    stress_loss: Optional[float] = None
    stress_market_shock: Optional[float] = None
    stress_asset_losses: list[StressAssetLoss] = Field(default_factory=list)

    # Macro betas (rates / USD / oil — engine returns a flat dict).
    macro_betas: dict[str, float] = Field(default_factory=dict)

    # Liquidity rows (one per ticker).
    liquidity: list[LiquidityRow] = Field(default_factory=list)

    # Drawdown stats. Engine returns a free-form dict; we pass through
    # only the keys frontends consume so a new field doesn't leak.
    drawdown_stats: Optional[dict[str, Any]] = None


class ReportFromActiveRequest(BaseModel):
    """Body for ``POST /api/v1/risk/report_from_active``.

    Matches ScoreFromActiveRequest — both endpoints resolve the active
    portfolio from JWT. We keep them as separate routes (rather than a
    single 'report' that also returns the score) because the score
    endpoint is fast and the report endpoint is slow; users can poll
    the score frequently while the report takes seconds.
    """

    risk_preference: int = Field(default=3, ge=1, le=5)
    risk_free_rate: float = Field(default=0.045, ge=0.0, le=0.20)
    history_days: int = Field(default=730, ge=180, le=2520)
    market_shock: float = Field(
        default=-0.10,
        ge=-0.50,
        le=0.0,
        description="Stress-test market move applied to the portfolio.",
    )


class ScoreFromActiveRequest(BaseModel):
    """Body for ``POST /api/v1/risk/score_from_active``.

    All fields optional — the endpoint resolves the active portfolio
    from the caller's JWT. ``risk_preference`` and ``risk_free_rate``
    override the defaults baked into the score for that one call.
    """

    risk_preference: int = Field(default=3, ge=1, le=5)
    risk_free_rate: float = Field(default=0.045, ge=0.0, le=0.20)
    history_days: int = Field(
        default=365,
        ge=60,
        le=2520,
        description=(
            "Trailing window of daily history used to build the returns "
            "matrix. 365 ≈ 252 trading days, the engine's preferred "
            "minimum. Cap at 10 years."
        ),
    )


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
