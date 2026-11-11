"""Wire contract for ``POST /api/v1/risk/factor_stress``.

Every number is computed in ``services.factor_stress``; these models only
describe it. Optional fields are optional because the engine reports a gap
instead of filling it — ``None`` always means "not available", never zero.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

FactorId = Literal["equity", "rates", "credit", "usd", "oil", "vol", "gold"]


class FactorStressRequest(BaseModel):
    expected_portfolio_id: Optional[str] = Field(default=None, min_length=1, max_length=64)
    # Your own scenario: a shock per factor, in that factor's unit. Bounded so a
    # typo cannot ask for a 1000% move.
    custom_shocks: Optional[dict[FactorId, float]] = None
    fill_unspecified: bool = True
    horizon_weeks: Literal[1, 2, 4] = 2
    confidence: Literal[0.9, 0.95, 0.99] = 0.95
    risk_free_rate: float = Field(default=0.045, ge=0.0, le=0.20)

    @field_validator("custom_shocks")
    @classmethod
    def _bounded(cls, v):
        if v is None:
            return v
        for factor, shock in v.items():
            limit = 2.5 if factor == "vol" else 0.9
            if not (-limit <= float(shock) <= limit):
                raise ValueError(f"{factor} shock must be within ±{limit}")
        return v or None


class FactorOut(BaseModel):
    id: FactorId
    label: str
    proxy: str
    unit: str
    description: str
    available: bool
    weekly_vol: float
    crisis_weekly_vol: float
    portfolio_loading: float


class ExposureRow(BaseModel):
    ticker: str
    source: str  # "own" | "sector_proxy:<ETF>"
    betas: dict[str, float]
    t_stats: dict[str, Optional[float]]
    r2: float
    n_obs: int
    resid_vol_weekly: float
    unstable: bool
    weight: float
    value_usd: float


class UnmodelledRow(BaseModel):
    ticker: str
    weight: float
    reason: str


class SkippedLeg(BaseModel):
    contract: str
    reason: str


class CoverageOut(BaseModel):
    modelled_weight: float
    proxied: list[str]
    unmodelled: list[UnmodelledRow]
    unpriced: list[str]
    option_legs_repriced: int
    option_legs_skipped: list[SkippedLeg]


class AccountOut(BaseModel):
    gross_long: float
    option_value: Optional[float]
    cash: float
    margin_loan: float
    net_equity: float
    leverage: Optional[float]


class ConcentrationOut(BaseModel):
    top_weight: Optional[float]
    hhi: float
    effective_holdings: Optional[float]


class CorrelationOut(BaseModel):
    calm: list[list[float]]
    crisis: list[list[float]]
    calm_n_obs: int
    crisis_n_obs: int


class DecompositionOut(BaseModel):
    factor_share: dict[str, float]
    idio_share: float
    weekly_vol: float


class HistogramBin(BaseModel):
    lo: float
    hi: float
    p: float


class TailMetric(BaseModel):
    level: float
    var: float
    cvar: float
    var_se: Optional[float]
    cvar_se: Optional[float]


class DistributionOut(BaseModel):
    histogram: list[HistogramBin]
    tails: list[TailMetric]
    mean_pct: float
    worst_pct: float
    prob_margin_call: Optional[float]
    n_sims: int
    n_obs: int


class FactorPnl(BaseModel):
    factor: FactorId
    pnl_usd: float


class OptionPnl(BaseModel):
    pnl_usd: float
    delta_usd: float
    convexity_usd: float
    vega_usd: float


class HoldingPnl(BaseModel):
    ticker: str
    move_pct: float
    pnl_usd: float
    source: str


class MarginOut(BaseModel):
    equity_after: float
    requirement_after: float
    utilisation_before: Optional[float]
    utilisation_after: Optional[float]
    breach: bool
    breach_multiple: Optional[float]


class LadderPoint(BaseModel):
    multiple: float
    pnl_usd: float
    pnl_pct: float
    linear_pnl_usd: float
    margin_utilisation: Optional[float]
    breach: bool


class PathPoint(BaseModel):
    date: str
    equity: float
    drawdown: Optional[float]
    margin_utilisation: Optional[float]


class RealisedCheck(BaseModel):
    coverage: float
    return_pct: float
    model_return_pct: float


class StressScenarioOut(BaseModel):
    id: str
    label: str
    kind: Literal["hypothetical", "historical", "custom"]
    source: str
    shocks: dict[str, float]
    specified: list[str]
    filled: list[str]
    pnl_usd: float
    pnl_pct: float
    band_low_usd: float
    band_high_usd: float
    stock_pnl_usd: float
    by_factor: list[FactorPnl]
    options: OptionPnl
    by_holding: list[HoldingPnl]
    margin: MarginOut
    ladder: list[LadderPoint]
    path: Optional[list[PathPoint]]
    realised: Optional[RealisedCheck]


class FactorStressOut(BaseModel):
    model_version: str
    as_of: str
    horizon_weeks: int
    confidence: float
    maintenance_requirement: float
    account: AccountOut
    factors: list[FactorOut]
    exposures: list[ExposureRow]
    coverage: CoverageOut
    concentration: ConcentrationOut
    correlation: CorrelationOut
    decomposition: dict[str, DecompositionOut]
    distribution: dict[str, DistributionOut]
    scenarios: list[StressScenarioOut]
    assumptions: list[str]
    warnings: list[str]
