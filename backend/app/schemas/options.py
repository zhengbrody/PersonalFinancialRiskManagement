"""Request + response shapes for ``POST /api/v1/options/analyze``.

The client sends the option contracts it already knows about (from the active
portfolio's holdings); the backend prices them off free yfinance chains and
returns Greeks / IV / mark / payoff. Deterministic + credit-free — see
``services.options_analytics``.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class OptionContractIn(BaseModel):
    """One option contract to analyze."""

    model_config = ConfigDict(str_strip_whitespace=True)

    underlying: str = Field(..., min_length=1, max_length=12)
    option_type: Literal["call", "put"]
    strike: float = Field(..., gt=0)
    expiry: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")  # ISO date
    quantity: float = Field(default=1.0)  # contracts; negative = short
    avg_premium: Optional[float] = Field(default=None, ge=0)  # per share
    contract_multiplier: float = Field(default=100.0, gt=0)
    # Optional caller-supplied market inputs — used when the live chain is
    # unavailable so the contract can still be modelled (theoretical_fallback).
    market_price: Optional[float] = Field(default=None, ge=0)  # per-share mark override
    implied_vol: Optional[float] = Field(default=None, gt=0)  # decimal, e.g. 0.35


class OptionAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contracts: list[OptionContractIn] = Field(..., min_length=1, max_length=50)
    risk_free_rate: float = Field(default=0.045, ge=0.0, le=0.20)


class GreeksOut(BaseModel):
    delta: float
    gamma: float
    theta: float
    vega: float
    rho: float


class PayoffPointOut(BaseModel):
    price: float
    pnl: float


class OptionAnalyticsOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    contract_symbol: Optional[str] = None
    underlying: str
    option_type: str
    strike: float
    expiry: str
    quantity: float
    contract_multiplier: float
    days_to_expiry: int
    spot: Optional[float] = None
    mark: Optional[float] = None
    iv: Optional[float] = None
    greeks: Optional[GreeksOut] = None
    delta_notional: Optional[float] = None
    market_value: Optional[float] = None
    cost_basis: Optional[float] = None
    unrealized_pnl: Optional[float] = None
    intrinsic_value: Optional[float] = None
    time_value: Optional[float] = None
    max_loss: Optional[float] = None  # None = unbounded (e.g. naked short call)
    max_gain: Optional[float] = None  # None = unbounded (e.g. long call)
    assignment_risk: Optional[str] = None  # None | "watch" | "high"
    break_even: Optional[float] = None
    moneyness: Optional[str] = None
    payoff: list[PayoffPointOut] = Field(default_factory=list)
    # Price-quality state: "market" (live) | "stale_eod" (delayed/EOD chain) |
    # "manual" (user override) | "theoretical_fallback" (Black-Scholes, no quote).
    source: str = "market"
    warnings: list[str] = Field(default_factory=list)


class OptionTotalsOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    net_delta: float = 0.0
    net_gamma: float = 0.0
    net_theta: float = 0.0
    net_vega: float = 0.0
    delta_notional: float = 0.0
    market_value: float = 0.0
    unrealized_pnl: Optional[float] = None
    contracts: int = 0


class OptionFlagOut(BaseModel):
    code: str
    severity: str  # info | watch | high
    detail: str


class ExpiryBucketOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    expiry: str
    days_to_expiry: int
    contracts: int
    net_delta: float
    net_notional: float


class UnderlyingExposureOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    underlying: str
    contracts: int
    net_delta: float
    net_notional: float
    equity_shares: Optional[float] = None


class OptionExposureOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    net_delta: float
    gross_delta: float
    net_gamma: float
    net_theta: float
    net_vega: float
    option_market_value: Optional[float] = None
    option_notional: float
    short_collateral_estimate: float
    contracts: int
    short_contracts: int
    expiry_ladder: list[ExpiryBucketOut] = Field(default_factory=list)
    underlying_exposure: list[UnderlyingExposureOut] = Field(default_factory=list)
    flags: list[OptionFlagOut] = Field(default_factory=list)


# ── Black-Scholes stress grid (nested in the analyze response) ─────────────────


class ScenarioCellOut(BaseModel):
    underlying_shock: float
    iv_shock: float
    horizon: int | str  # days forward, or "expiry"
    total_pnl: float


class ScenarioPositionOut(BaseModel):
    model_config = ConfigDict(extra="allow")

    underlying: Optional[str] = None
    option_type: Optional[str] = None
    strike: Optional[float] = None
    expiry: Optional[str] = None
    quantity: Optional[float] = None
    pnl: float


class OptionScenarioGrid(BaseModel):
    model_config = ConfigDict(extra="allow")

    grid: list[ScenarioCellOut]
    top_positions: list[ScenarioPositionOut]
    stress_cell: dict[str, float]
    underlying_shocks: list[float]
    iv_shocks: list[float]
    horizons: list[int | str]
    repriced: int
    skipped: list[dict] = Field(default_factory=list)
    as_of: Optional[str] = None


class OptionStrategyOut(BaseModel):
    """A recognized multi-leg (or single-leg) strategy with NET, bounded
    economics — the netted view that stops a spread's short leg showing an
    unreal unbounded loss."""

    model_config = ConfigDict(extra="allow")

    underlying: str
    expiry: str
    name: str  # "Bull call spread" | "Long straddle" | "Custom (N legs)" | …
    leg_count: int
    net_debit: float  # >0 = net debit paid, <0 = net credit received
    net_pnl: Optional[float] = None
    max_loss: Optional[float] = None  # None = unbounded
    max_gain: Optional[float] = None  # None = unbounded
    break_evens: list[float] = Field(default_factory=list)
    net_greeks: dict[str, float] = Field(default_factory=dict)
    payoff: list[PayoffPointOut] = Field(default_factory=list)
    legs: list[OptionAnalyticsOut] = Field(default_factory=list)


class OptionAnalyzeResponse(BaseModel):
    results: list[OptionAnalyticsOut]
    totals: OptionTotalsOut
    exposure: OptionExposureOut
    scenarios: OptionScenarioGrid
    strategies: list[OptionStrategyOut] = Field(default_factory=list)
    as_of: str
    warnings: list[str] = Field(default_factory=list)


# ── AI explanation (deterministic skeleton → optional LLM rephrase) ────────────


class OptionExplainInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    exposure: OptionExposureOut


class OptionExplainAction(BaseModel):
    title: str
    reason: str
    next_step: str


class OptionExplainOutput(BaseModel):
    severity: str  # low | moderate | elevated | high
    headline: str
    summary_bullets: list[str] = Field(default_factory=list)
    suggested_actions: list[OptionExplainAction] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    ai_generated: bool = False
