"""Ticker Research 2.0 — the compact **FactPack** + LLM **Verdict** contracts.

The FactPack is the deterministic, source-attributed projection of all the
provider/free data for one ticker. It is intentionally SMALL: top-K drivers,
key ratios, a peer-relative valuation band, risk flags, analyst implied upside,
and per-source provenance. This — never raw provider JSON — is what the verdict
LLM receives, so the model explains/ranks/concludes over vetted numbers and
cannot invent them.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class SourceRef(BaseModel):
    """Where one slice of the FactPack came from + how complete it was."""

    field: str
    source: str  # "fmp" | "yfinance" | "derived"
    as_of: Optional[str] = None
    coverage: float = 0.0


class ValuationBlock(BaseModel):
    pe: Optional[float] = None
    forward_pe: Optional[float] = None
    ps: Optional[float] = None
    pb: Optional[float] = None
    ev_ebitda: Optional[float] = None
    fcf_yield: Optional[float] = None
    dividend_yield: Optional[float] = None
    # Peer-relative verdict, computed deterministically (never by the LLM).
    band: Optional[str] = None  # "cheap" | "in-line" | "rich"
    peer_median_pe: Optional[float] = None


class QualityBlock(BaseModel):
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    roic: Optional[float] = None
    current_ratio: Optional[float] = None
    debt_to_equity: Optional[float] = None
    interest_coverage: Optional[float] = None


class GrowthBlock(BaseModel):
    revenue_cagr: Optional[float] = None  # derived from the income-statement series
    eps_cagr: Optional[float] = None
    revenue_growth_yoy: Optional[float] = None
    earnings_growth_yoy: Optional[float] = None
    periods: int = 0  # how many annual rows backed the CAGR


class AnalystBlock(BaseModel):
    rating: Optional[str] = None
    num_analysts: Optional[int] = None
    target_low: Optional[float] = None
    target_consensus: Optional[float] = None
    target_high: Optional[float] = None
    implied_upside_pct: Optional[float] = None  # derived vs current price


class MomentumBlock(BaseModel):
    """Price-trend technicals — all deterministic, from free yfinance scalars /
    price history. No signal here is advice; it only says where price sits."""

    rsi_14: Optional[float] = None
    sma_50: Optional[float] = None
    sma_200: Optional[float] = None
    price_vs_sma50_pct: Optional[float] = None  # derived: price/sma50 - 1
    price_vs_sma200_pct: Optional[float] = None
    fifty_two_week_high: Optional[float] = None
    fifty_two_week_low: Optional[float] = None
    pct_from_52w_high: Optional[float] = None  # derived: price/high - 1 (≤0)
    pct_off_52w_low: Optional[float] = None  # derived: price/low - 1 (≥0)
    trend: Optional[str] = None  # "uptrend" | "downtrend" | "mixed" (vs both SMAs)


class OwnershipBlock(BaseModel):
    institutional_pct: Optional[float] = None  # fraction held by institutions


class InsiderBlock(BaseModel):
    """Form-4 insider activity over the trailing ~90 days (FMP)."""

    buys_90d: int = 0
    sells_90d: int = 0
    net_shares_90d: Optional[float] = None
    signal: Optional[str] = None  # "net buying" | "net selling" | "balanced"


class PeerCompareRow(BaseModel):
    ticker: str
    name: str = ""
    market_cap: Optional[float] = None
    pe: Optional[float] = None
    ps: Optional[float] = None
    net_margin: Optional[float] = None
    roe: Optional[float] = None


class NewsHeadline(BaseModel):
    """Metadata ONLY — title/site/published/url. No article body is ever
    forwarded to the LLM (principle: no raw blobs)."""

    title: str
    site: Optional[str] = None
    published: Optional[str] = None
    url: Optional[str] = None


class DataQuality(BaseModel):
    coverage: float = 0.0  # 0..1 overall
    sources: list[SourceRef] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class FactPack(BaseModel):
    """The compact, source-attributed fact sheet for one ticker."""

    ticker: str
    name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    currency: str = "USD"
    as_of: Optional[str] = None

    price: Optional[float] = None
    market_cap: Optional[float] = None
    beta: Optional[float] = None

    valuation: ValuationBlock = Field(default_factory=ValuationBlock)
    quality: QualityBlock = Field(default_factory=QualityBlock)
    growth: GrowthBlock = Field(default_factory=GrowthBlock)
    analyst: AnalystBlock = Field(default_factory=AnalystBlock)
    momentum: MomentumBlock = Field(default_factory=MomentumBlock)
    ownership: OwnershipBlock = Field(default_factory=OwnershipBlock)
    insider: InsiderBlock = Field(default_factory=InsiderBlock)
    peers: list[PeerCompareRow] = Field(default_factory=list)
    news: list[NewsHeadline] = Field(default_factory=list)

    # Deterministic, plain-language synthesis — the K things that matter.
    drivers: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)

    data_quality: DataQuality = Field(default_factory=DataQuality)


# ── Verdict (LLM over the FactPack) ─────────────────────────────────


class DimensionScore(BaseModel):
    name: str  # valuation | growth | quality | momentum | risk
    score: int = Field(ge=0, le=100)
    note: str = ""


class ResearchVerdict(BaseModel):
    """The LLM's ranked judgment over the FactPack. The model phrases + ranks;
    every number it cites already lives in the FactPack."""

    rating: str  # "Strong Buy" | "Buy" | "Hold" | "Sell" | "Strong Sell"
    conviction: str = "medium"  # low | medium | high
    summary: str
    dimensions: list[DimensionScore] = Field(default_factory=list)
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    what_would_change_my_mind: list[str] = Field(default_factory=list)
    data_only: bool = False  # True when no LLM key → deterministic placeholder


# ── request/response envelopes ──────────────────────────────────────


class VerdictRequest(BaseModel):
    ticker: Optional[str] = Field(default=None, min_length=1, max_length=20)
    fact_pack: Optional[FactPack] = Field(
        default=None,
        description=(
            "The FactPack already fetched from GET /research/fact_pack/{ticker}. "
            "When supplied the verdict REUSES it (no second network fetch)."
        ),
    )
