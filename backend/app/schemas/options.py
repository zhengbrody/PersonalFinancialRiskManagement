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
    break_even: Optional[float] = None
    moneyness: Optional[str] = None
    payoff: list[PayoffPointOut] = Field(default_factory=list)
    source: str = "yfinance"
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


class OptionAnalyzeResponse(BaseModel):
    results: list[OptionAnalyticsOut]
    totals: OptionTotalsOut
    as_of: str
    warnings: list[str] = Field(default_factory=list)
