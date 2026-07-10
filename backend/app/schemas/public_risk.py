"""Schemas for the PUBLIC (no-signup) portfolio risk check.

Strictness is the point: this endpoint is anonymous, so the input contract is
the abuse surface. Tickers are a tight uppercase pattern (a formula-injection
string like "=HYPERLINK(...)" or an SQL fragment can never validate), shares
must be finite and positive with a sane cap, at most 10 holdings, no extra
fields anywhere, no duplicates. Nothing here is ever persisted.
"""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_HOLDINGS = 10

# Uppercase exchange-style symbols only (AAPL, BRK.B, BF-B). No leading
# punctuation → formula-injection strings can never validate as tickers.
_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")


class PublicHolding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, max_length=10)
    shares: float = Field(gt=0, le=1e9, allow_inf_nan=False)

    @field_validator("ticker")
    @classmethod
    def _ticker_shape(cls, v: str) -> str:
        v = v.strip().upper()
        if not _TICKER_RE.match(v):
            raise ValueError("ticker must look like an exchange symbol (e.g. AAPL, BRK.B)")
        return v


class PublicRiskCheckIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    holdings: list[PublicHolding] = Field(min_length=1, max_length=MAX_HOLDINGS)

    @model_validator(mode="after")
    def _no_duplicate_tickers(self):
        tickers = [h.ticker for h in self.holdings]
        if len(set(tickers)) != len(tickers):
            raise ValueError("duplicate tickers — merge the share counts first")
        return self


class ConcentrationOut(BaseModel):
    top_ticker: Optional[str] = None
    top_weight: Optional[float] = None
    hhi: Optional[float] = None
    effective_holdings: Optional[float] = None
    weights: dict[str, float] = Field(default_factory=dict)


class RiskMetricsOut(BaseModel):
    total_value: Optional[float] = None
    annual_volatility: Optional[float] = None
    # 1-day HISTORICAL (empirical) VaR/CVaR at 95% — losses as positive
    # fractions of portfolio value.
    var_95_1d: Optional[float] = None
    cvar_95_1d: Optional[float] = None
    beta_to_market: Optional[float] = None


class StressRowOut(BaseModel):
    market_shock_pct: float
    est_portfolio_impact_pct: Optional[float] = None
    est_portfolio_impact_usd: Optional[float] = None


class ProvenanceOut(BaseModel):
    as_of: Optional[str] = None
    observations: int = 0
    priced: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    sources: dict[str, str] = Field(default_factory=dict)
    # When the joint return window is thin, the shortest-history ticker that
    # truncated it (so a dashed metric reads as a data-window limit, not a bug).
    window_limited_by: Optional[str] = None


class PublicRiskCheckOut(BaseModel):
    concentration: ConcentrationOut
    metrics: RiskMetricsOut
    stress: list[StressRowOut] = Field(default_factory=list)
    provenance: ProvenanceOut
    disclaimer: str = (
        "Educational risk analytics over the holdings you entered — computed "
        "from public market data, nothing stored, not investment advice."
    )
