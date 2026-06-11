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
    # None = unknown cost basis (omit from P&L); distinct from a real 0.
    cost_basis: Optional[float] = Field(default=None, ge=0)
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


class ComponentReturnRow(BaseModel):
    """Per-holding contribution to annualized portfolio return
    (weight × annualized mean daily return) — the return-side mirror of
    component VaR, so the report can show 'who pays you' next to 'who
    risks you'."""

    ticker: str
    contribution: float


class LiquidityRow(BaseModel):
    ticker: str
    days_to_liquidate: Optional[float] = None
    adv_30d: Optional[float] = None
    market_value: Optional[float] = None


class PriceProvenanceOut(BaseModel):
    """Where the portfolio's price history came from + how deep it is. Surfaced
    in the Health Score / Risk Report 'data quality' area."""

    primary: str = "yfinance"
    fallback: str = "massive"
    massive_fallback_used: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    trading_days: Optional[int] = None


class SectorWeightOut(BaseModel):
    sector: str
    weight: float


class ConcentrationOut(BaseModel):
    """Deterministic concentration diagnostics over the invested book
    (cash excluded). HHI = sum of squared weights; effective_holdings =
    1/HHI is 'how many equally-weighted positions this behaves like'.
    Sectors come from the deterministic resolver (holding override →
    canonical SECTOR_MAP → asset-type default → Unclassified) — no
    network calls."""

    num_holdings: int
    top_holding_ticker: Optional[str] = None
    top_holding_weight: Optional[float] = None
    top5_weight: Optional[float] = None
    hhi: Optional[float] = None
    effective_holdings: Optional[float] = None
    sectors: list[SectorWeightOut] = Field(default_factory=list)
    top_sector: Optional[str] = None
    top_sector_weight: Optional[float] = None


class RiskReportOut(BaseModel):
    """JSON-safe projection of the engine's ``RiskReport`` dataclass.

    Large matrices (cov, corr, MC simulation paths) are intentionally
    NOT shipped over the wire — they'd add tens of MB and the dashboard
    doesn't render them anyway. If a chart needs them later, we add a
    targeted endpoint that returns just that slice."""

    # Price-data provenance for the report's 'data quality' area.
    price_provenance: Optional[PriceProvenanceOut] = None

    # KPIs — scalars, NaN-scrubbed at the envelope layer.
    annual_return: Optional[float] = None
    annual_volatility: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    var_95: Optional[float] = None
    var_99: Optional[float] = None
    cvar_95: Optional[float] = None
    risk_free_rate: Optional[float] = None

    # Account-value context. These are not model-estimated risk metrics; they are
    # deterministic account arithmetic from latest/previous closes + cash/margin.
    total_value: Optional[float] = None  # gross assets before margin loan
    net_equity: Optional[float] = None  # gross assets - margin loan
    cash_balance: Optional[float] = None
    margin_loan: Optional[float] = None
    contributed_capital: Optional[float] = None
    daily_pnl: Optional[float] = None
    daily_return: Optional[float] = None
    total_pnl: Optional[float] = None
    total_return: Optional[float] = None

    # Beta vs the configured benchmark (e.g. {"SPY": 1.02}).
    betas: dict[str, float] = Field(default_factory=dict)
    # Factor attribution table (SPY/QQQ/GLD/TLT/IWM/VTV).
    factor_betas: list[FactorBetaRow] = Field(default_factory=list)
    # Per-ticker share of total VaR.
    component_var_pct: list[ComponentVarRow] = Field(default_factory=list)
    # Per-ticker contribution to annualized return (decimal, sums to the
    # equity book's annual return before the cash/margin mix).
    component_return: list[ComponentReturnRow] = Field(default_factory=list)

    # Stress test summary.
    stress_loss: Optional[float] = None
    stress_market_shock: Optional[float] = None
    stress_asset_losses: list[StressAssetLoss] = Field(default_factory=list)

    # Macro betas (rates / USD / oil — engine returns a flat dict).
    macro_betas: dict[str, float] = Field(default_factory=dict)

    # Liquidity rows (one per ticker).
    liquidity: list[LiquidityRow] = Field(default_factory=list)

    # Concentration diagnostics (single-name risk), derived from market values.
    concentration: Optional[ConcentrationOut] = None

    # Drawdown stats. Engine returns a free-form dict; we pass through
    # only the keys frontends consume so a new field doesn't leak.
    drawdown_stats: Optional[dict[str, Any]] = None

    # Human-readable caveats about the inputs behind the numbers (e.g.
    # stress test fell back to market beta for tickers with too little
    # history). Rendered in the report's data-quality area.
    data_quality_notes: list[str] = Field(default_factory=list)


class FrontierPoint(BaseModel):
    """One point on the risk/return plane (annualized)."""

    vol: float
    ret: float


class EfficientFrontierOut(BaseModel):
    """Payload for ``POST /api/v1/risk/efficient_frontier``."""

    frontier: list[FrontierPoint] = Field(default_factory=list)
    current: FrontierPoint
    risk_free_rate: float
    # Provenance: last price date + daily return observations behind the curve.
    as_of: Optional[str] = None
    observations: Optional[int] = None


class ScenarioPoint(BaseModel):
    """Projected portfolio outcome under a broad market move."""

    shock_pct: float  # e.g. -0.30 = market −30%
    pnl_pct: float  # signed portfolio P&L fraction (leverage-scaled)
    portfolio_value: float  # projected $ value after the move
    # Per-holding signed return under this shock (βᵢ·shock), most-impacted
    # first, top-N kept. Lets the Scenario Explorer show "top impacted
    # holdings" for the selected shock with no recompute. Optional → older
    # clients ignore it.
    asset_losses: list[StressAssetLoss] = Field(default_factory=list)


class ScenariosOut(BaseModel):
    """Payload for ``POST /api/v1/risk/scenarios``."""

    total_value: float
    scenarios: list[ScenarioPoint] = Field(default_factory=list)
    # Provenance: last price date + daily return observations behind the betas.
    as_of: Optional[str] = None
    observations: Optional[int] = None


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
    # Aligned with ScoreFromActiveRequest (365) so the Health Score and Risk
    # Report read the SAME 1-year window — the only avoidable source of
    # divergence between them. (Any residual difference is methodological: the
    # report uses EWMA covariance + Monte-Carlo VaR, the score simple std +
    # historical VaR — two intentional lenses on the same data.) 252 trading
    # days is ample for the 6-factor regression + stress.
    history_days: int = Field(default=365, ge=180, le=2520)
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
    net_equity: Optional[float] = None
    cash_balance: Optional[float] = None
    margin_loan: Optional[float] = None
    contributed_capital: Optional[float] = None
    daily_pnl: Optional[float] = None
    daily_return: Optional[float] = None
    total_pnl: Optional[float] = None
    total_return: Optional[float] = None
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
    price_provenance: Optional[PriceProvenanceOut] = None


# ── /api/v1/risk/benchmarks (public reference context) ──────────────


class BenchmarkRow(BaseModel):
    name: str
    annual_return: Optional[float] = None
    annual_volatility: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None


class BenchmarksOut(BaseModel):
    as_of: Optional[str] = None
    benchmarks: list[BenchmarkRow] = Field(default_factory=list)


# ── /api/v1/risk/historical_scenarios ──────────────────────────────


class HistoricalScenarioRow(BaseModel):
    label: str
    start: str
    end: str
    portfolio_return: Optional[float] = None
    market_return: Optional[float] = None
    max_drawdown: Optional[float] = None
    coverage: Optional[float] = None  # share of weight with data in the window
    recovery_days: Optional[int] = None  # trading days to claw back; None = not yet


class HistoricalScenariosOut(BaseModel):
    scenarios: list[HistoricalScenarioRow] = Field(default_factory=list)


# ── /api/v1/risk/var_backtest ──────────────────────────────────────


class HistogramBin(BaseModel):
    x: Optional[float] = None  # bin midpoint (daily return fraction)
    count: int = 0


class VarBacktestOut(BaseModel):
    n_days: int = 0
    mean_daily: Optional[float] = None
    vol_daily: Optional[float] = None
    var_95: Optional[float] = None  # Gaussian 1-day VaR (positive loss fraction)
    var_99: Optional[float] = None
    hist_var_95: Optional[float] = None  # empirical, for comparison
    hist_var_99: Optional[float] = None
    breaches_95: int = 0
    expected_95: Optional[float] = None
    breaches_99: int = 0
    expected_99: Optional[float] = None
    worst_day: Optional[float] = None
    histogram: list[HistogramBin] = Field(default_factory=list)
