"""Normalized internal shapes for external market-data providers.

Every provider adapter (FMP today; yfinance/SEC as free fallback) returns its
data already normalized into these models, wrapped in a ``ProviderResult`` that
carries provenance: ``source``, ``as_of``, ``coverage`` (0..1 fraction of the
expected fields that were actually present), and ``warnings``. Downstream
(FactPack, Copilot) only ever sees these — never raw provider JSON — so an LLM
can't be handed an unbounded blob and the UI always has source + freshness.
"""

from __future__ import annotations

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

_Lax = ConfigDict(extra="ignore")

T = TypeVar("T")


class ProviderResult(BaseModel, Generic[T]):
    """A provider response + its provenance. ``data is None`` ⇒ unavailable
    (missing key / endpoint / fail-soft) — callers fall back to free data."""

    model_config = ConfigDict(arbitrary_types_allowed=True)
    data: Optional[T] = None
    source: str = "fmp"
    as_of: Optional[str] = None
    coverage: float = 0.0
    warnings: list[str] = Field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.data is not None


class CompanyProfile(BaseModel):
    model_config = _Lax
    ticker: str
    name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    exchange: Optional[str] = None
    currency: Optional[str] = None
    market_cap: Optional[float] = None
    price: Optional[float] = None
    beta: Optional[float] = None
    description: Optional[str] = None


class PriceBar(BaseModel):
    model_config = _Lax
    date: str
    close: float


class Ratios(BaseModel):
    """Compact valuation/quality/profitability ratios (latest TTM/annual)."""

    model_config = _Lax
    pe: Optional[float] = None
    forward_pe: Optional[float] = None
    pb: Optional[float] = None
    ps: Optional[float] = None
    ev_ebitda: Optional[float] = None
    dividend_yield: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    roic: Optional[float] = None
    current_ratio: Optional[float] = None
    debt_to_equity: Optional[float] = None
    interest_coverage: Optional[float] = None
    fcf_yield: Optional[float] = None


class GrowthRow(BaseModel):
    model_config = _Lax
    period: str
    revenue: Optional[float] = None
    net_income: Optional[float] = None
    eps: Optional[float] = None


class AnalystConsensus(BaseModel):
    model_config = _Lax
    target_low: Optional[float] = None
    target_high: Optional[float] = None
    target_consensus: Optional[float] = None
    target_median: Optional[float] = None
    num_analysts: Optional[int] = None
    rating: Optional[str] = None  # latest grade action, if available


class PeerRow(BaseModel):
    model_config = _Lax
    ticker: str
    name: Optional[str] = None
    market_cap: Optional[float] = None
    pe: Optional[float] = None
    ps: Optional[float] = None
    net_margin: Optional[float] = None
    roe: Optional[float] = None


class NewsItem(BaseModel):
    model_config = _Lax
    title: str
    site: Optional[str] = None
    published: Optional[str] = None
    url: Optional[str] = None
    snippet: Optional[str] = None


class InsiderSummary(BaseModel):
    model_config = _Lax
    buys_90d: int = 0
    sells_90d: int = 0
    net_shares_90d: Optional[float] = None
