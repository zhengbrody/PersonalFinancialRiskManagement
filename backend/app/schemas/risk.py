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

from .confidence import DataConfidence

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
    in the Health Score / Risk Report 'data quality' area.

    NOTE ``trading_days`` reflects the ENDPOINT price window (``history_days``,
    ~1y default) used for weights/P&L/DR/rolling vol; the engine's beta/factor/
    correlation regressions run on the DataProvider's own ~2-year window."""

    primary: str = "massive"
    fallback: str = "yfinance"
    by_ticker: dict[str, str] = Field(default_factory=dict)
    yfinance_fallback_used: list[str] = Field(default_factory=list)
    # Deprecated compatibility field. Historically meant "Massive fallback";
    # now means "Massive-sourced tickers" because Massive is primary.
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


class CorrTopPair(BaseModel):
    a: str
    b: str
    rho: float


class BestDiversifier(BaseModel):
    ticker: str
    avg_rho: float


class CorrelationOut(BaseModel):
    """Pairwise correlation of holdings' daily returns (the engine's plain
    Pearson ``corr_matrix``, estimated on the engine DataProvider's ~2-year
    window) plus deterministic diversification insights. Insights are
    computed over the FULL matrix; ``tickers``/``matrix`` are capped at the
    top 30 by portfolio weight (``truncated`` flags the cut).
    ``diversification_ratio`` = Σŵᵢσᵢ / σₚ — computed on the ENDPOINT's
    price window (``history_days``, default ~1y), a different window than
    the matrix; numerator and denominator share one frame and ddof, so
    DR ≥ 1 holds by construction regardless. The UI labels both windows."""

    tickers: list[str]
    matrix: list[list[Optional[float]]]
    avg_pairwise: Optional[float] = None
    top_pair: Optional[CorrTopPair] = None
    best_diversifier: Optional[BestDiversifier] = None
    diversification_ratio: Optional[float] = None
    truncated: bool = False
    total_tickers: int = 0


class RollingVolPoint(BaseModel):
    date: str
    portfolio: float
    benchmark: Optional[float] = None


class RollingVolatilityOut(BaseModel):
    """21-day rolling annualized volatility of portfolio daily returns
    (equal-weight window, sample std, ×√252, ×risk_scale so the level
    matches the levered book). NOTE: the headline ``annual_volatility``
    is EWMA-based — a faster-reacting estimator; the UI labels both.
    ``benchmark`` is the same computation on SPY, UNscaled (an index has
    no leverage)."""

    window_days: int = 21
    series: list[RollingVolPoint] = Field(default_factory=list)
    current: Optional[float] = None
    median: Optional[float] = None
    state: Literal["calm", "normal", "elevated"] = "normal"
    benchmark_ticker: Optional[str] = None


DimensionKey = Literal[
    "concentration",
    "volatility",
    "drawdown",
    "beta",
    "correlation",
    "liquidity",
    "leverage",
    "options",
]
DimensionStatus = Literal["calm", "normal", "elevated", "high", "n/a"]


class RiskDimension(BaseModel):
    """One risk dimension in the explainable cockpit. Every field is ASSEMBLED
    from numbers the report/score already computed — no new risk math. A
    dimension the book can't measure (no options, no liquidity data) ships
    ``measurable=False`` + ``status='n/a'`` rather than a fake zero."""

    model_config = ConfigDict(extra="allow")

    key: DimensionKey
    name: str
    value: Optional[float] = None
    display: Optional[str] = None  # formatted value, e.g. "32%" / "1.18×"
    unit: Optional[str] = None  # pct | ratio | x | usd | days | count
    status: DimensionStatus = "n/a"
    # Percentile of the current value vs the user's OWN snapshot history
    # (0..1; 0.9 = higher than 90% of their past readings). None until enough
    # history has accrued (< _MIN_HISTORY snapshots).
    percentile: Optional[float] = None
    percentile_n: Optional[int] = None  # observations behind the percentile
    # Share of the portfolio's current risk ATTENTION (severity-normalised
    # across the measurable dimensions, sums to ~1). NOT a variance
    # decomposition — the dimensions overlap; this ranks "what to look at
    # first", labelled as such in the UI.
    contribution: Optional[float] = None
    confidence: Optional[str] = None  # high | medium | low (per-dimension)
    explanation: str = ""  # plain-English, deterministic
    action: Optional[str] = None  # a Copilot ?q= prompt or lever key
    measurable: bool = True


class LossFigure(BaseModel):
    """A downside number shown in BOTH a loss fraction and dollars (over the
    net-equity basis). ``pct`` and ``usd`` are positive magnitudes."""

    label: str = ""
    horizon: Optional[str] = None  # "1d" | "21d" | "scenario" | "current"
    pct: Optional[float] = None
    usd: Optional[float] = None


class MarginBuffer(BaseModel):
    """How much equity cushion sits above the maintenance-margin line.
    ``maintenance_requirement`` uses a conservative 25% of gross assets (Reg-T
    style); a real broker requirement varies by security. ``status`` is a
    deterministic band, not a margin call prediction."""

    net_equity: Optional[float] = None
    margin_loan: Optional[float] = None
    gross_assets: Optional[float] = None
    maintenance_requirement: Optional[float] = None
    buffer_usd: Optional[float] = None
    buffer_pct: Optional[float] = None  # buffer / gross assets
    status: Literal["none", "comfortable", "tight", "call_risk", "n/a"] = "n/a"


class LossBreakdown(BaseModel):
    """Downside in % AND $ — the losses view of the cockpit. 1-day VaR/CVaR are
    a genuine 1-day historical estimate from the report's price window (the
    report's headline ``var_95`` is a 21-day Monte-Carlo number, surfaced here
    correctly labelled as ``var_21d_95``). All $ figures are on
    ``basis_value`` (net equity)."""

    basis_value: Optional[float] = None  # net equity the $ figures are computed on
    var_1d_95: Optional[LossFigure] = None
    cvar_1d_95: Optional[LossFigure] = None
    var_21d_95: Optional[LossFigure] = None  # the existing MC number, correctly labelled
    stress: Optional[LossFigure] = None
    current_drawdown: Optional[LossFigure] = None
    margin_buffer: Optional[MarginBuffer] = None


class RiskReportOut(BaseModel):
    """JSON-safe projection of the engine's ``RiskReport`` dataclass.

    Large matrices (cov, EWMA corr, MC simulation paths) are intentionally
    NOT shipped over the wire — they'd add tens of MB and the dashboard
    doesn't render them anyway. (The plain corr matrix IS shipped since the
    Risk Desk round, as the capped 2-dp ``correlation`` summary below.)"""

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

    # Desk analytics (Risk Desk round) — additive, fail-soft to None.
    correlation: Optional[CorrelationOut] = None
    rolling_volatility: Optional[RollingVolatilityOut] = None

    # Human-readable caveats about the inputs behind the numbers (e.g.
    # stress test fell back to market beta for tickers with too little
    # history). Rendered in the report's data-quality area.
    data_quality_notes: list[str] = Field(default_factory=list)
    # Unified data-confidence + provenance block (same contract as the score).
    data_confidence: Optional[DataConfidence] = None

    # ── Explainable risk cockpit (additive; assembled from the fields above,
    # no new risk math). ``dimensions`` is the per-dimension model (value /
    # status / percentile / contribution / confidence / explanation / action);
    # ``losses`` shows downside in BOTH % and $. ──
    dimensions: list[RiskDimension] = Field(default_factory=list)
    losses: Optional[LossBreakdown] = None


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
    # Margin/cash transparency. `sharpe_ratio` above is the leverage-invariant
    # ASSET-MIX Sharpe; these expose the leverage cost separately so it isn't
    # hidden. Present (>1 / non-zero) only for margin books.
    leverage: Optional[float] = None
    gross_annual_return: Optional[float] = None  # unlevered asset-mix return
    margin_cost_annual: Optional[float] = None  # annualized borrow drag
    # Deterministic input-health. `data_quality` ∈ [0,1] is the worst-link of
    # coverage / observations / dropped holdings; `confidence` is its label
    # (high|medium|low). When confidence is not high the score is stabilized
    # toward neutral instead of collapsing — see ScoreResponse.base_overall.
    data_quality: Optional[float] = None
    confidence: Optional[str] = None
    dropped_tickers: list[str] = Field(default_factory=list)
    # Drawdown from peak RIGHT NOW (0 = at a fresh high) — non-scoring context so
    # the UI can flag whether the worst drawdown is stale (recovered) or active.
    current_drawdown: Optional[float] = None


class OptionScorePenaltyRow(BaseModel):
    code: str
    severity: str
    points: int


class OptionScoreImpactOut(BaseModel):
    """How option holdings affect the Health Score — surfaced so the deduction
    is transparent (base_score − penalty, with the per-flag breakdown)."""

    model_config = ConfigDict(extra="allow")

    contracts: int
    net_delta: float
    net_gamma: float
    net_theta: float
    net_vega: float
    option_notional: float
    short_collateral_estimate: float
    base_score: int
    penalty: int
    flags: list[dict] = Field(default_factory=list)  # {code, severity, detail}
    penalty_breakdown: list[OptionScorePenaltyRow] = Field(default_factory=list)


class ScoreDriverOut(BaseModel):
    """One dimension's deterministic contribution to the overall score —
    the points it COSTS vs a perfect 10 (biggest drag first)."""

    key: str
    name: str
    score: float
    weight: float
    points_below_max: int
    detail: str = ""


class ReasonCodeOut(BaseModel):
    """A structured, machine-readable penalty behind the score (the LLM may
    phrase these, never invent). Extra keys (dimension / tickers /
    stabilized_from) ride along per code."""

    model_config = ConfigDict(extra="allow")
    code: str
    severity: str
    detail: str = ""


class ScoreResponse(BaseModel):
    overall_score: int
    risk_preference: int
    risk_target: dict
    metrics: PortfolioMetricsOut
    dimensions: dict[str, DimensionScoreOut]
    price_provenance: Optional[PriceProvenanceOut] = None
    # Present only when the active book contains option contracts.
    options: Optional[OptionScoreImpactOut] = None
    # Concentration over the invested equity book (top name / top-5 / HHI /
    # sectors). Cheap (weights + sector resolver, no Monte-Carlo); lets /score
    # show "what's dragging it" without the full risk report. None for an
    # empty/uncomputable book.
    concentration: Optional[ConcentrationOut] = None
    # Deterministic explainability + stabilization (additive). `base_overall` is
    # the score BEFORE confidence dampening (== overall_score at full data);
    # `drivers` ranks the dimensions by points-cost; `reason_codes` are the
    # structured penalties incl. low-data-confidence + missing prices.
    base_overall: Optional[int] = None
    drivers: list[ScoreDriverOut] = Field(default_factory=list)
    reason_codes: list[ReasonCodeOut] = Field(default_factory=list)
    # The methodology version that produced this score (single source:
    # libs/mindmarket_core/score_version.py). Auditable + used to gate
    # cross-version trend comparison.
    score_version: Optional[str] = None
    # Unified data-confidence + provenance (coverage, source types, freshness,
    # missing datasets, conviction cap). Additive; the shared <DataConfidence>
    # UI renders it. None only on the degenerate no-metrics path.
    data_confidence: Optional[DataConfidence] = None


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


class CoverageTestOut(BaseModel):
    """Kupiec POF + Christoffersen independence + joint conditional-coverage
    verdict for one confidence level. ``passed`` = joint p ≥ 0.05 (the VaR
    model is NOT rejected at the conventional test size)."""

    n: int = 0
    breaches: int = 0
    expected: Optional[float] = None
    alpha: Optional[float] = None
    lr_uc: Optional[float] = None
    p_uc: Optional[float] = None
    lr_ind: Optional[float] = None
    p_ind: Optional[float] = None
    lr_cc: Optional[float] = None
    p_cc: Optional[float] = None
    passed: Optional[bool] = None


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
    # Statistical coverage verdicts (Risk Desk ML-lifecycle Phase 3).
    coverage_95: Optional[CoverageTestOut] = None
    coverage_99: Optional[CoverageTestOut] = None
