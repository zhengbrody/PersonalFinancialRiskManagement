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

from .confidence import DataConfidence


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
    fcf_cagr: Optional[float] = None  # free-cash-flow CAGR (cash-flow statement)
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
    realized_vol_20d: Optional[float] = None  # annualized, from daily returns
    realized_vol_60d: Optional[float] = None
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


class CacheProvenance(BaseModel):
    """Whether a payload was served from cache and its freshness window. Lets the
    UI show a "cached · as of … · stale" badge and trust the recency."""

    cache_hit: bool = False
    fetched_at: Optional[str] = None  # ISO8601 — when the underlying data was fetched
    expires_at: Optional[str] = None  # ISO8601 — when the cached copy goes stale
    stale: bool = False  # served past expiry because a refresh failed


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
    # Set when the FactPack was served via the shared cache (build_fact_pack_cached).
    cache: Optional[CacheProvenance] = None


# ── Verdict (LLM over the FactPack) ─────────────────────────────────


class DimensionScore(BaseModel):
    name: str  # valuation | growth | quality | momentum | risk
    score: int = Field(ge=0, le=100)
    note: str = ""


class ResearchVerdict(BaseModel):
    """The LLM's ranked judgment over the FactPack. The model phrases + ranks;
    every number it cites already lives in the FactPack."""

    rating: str  # data screen: "Strong"|"Favorable"|"Mixed"|"Weak"|"Very Weak" (never buy/sell)
    conviction: str = "medium"  # low | medium | high
    summary: str
    dimensions: list[DimensionScore] = Field(default_factory=list)
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    what_would_change_my_mind: list[str] = Field(default_factory=list)
    data_only: bool = False  # True when no LLM key → deterministic placeholder
    # Unified data-confidence block. When ``data_confidence.directional_allowed``
    # is False (critical coverage < 40%) the rating is "Insufficient data" and
    # conviction is "none" — no directional verdict on thin data (rule #3).
    data_confidence: Optional[DataConfidence] = None


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


# ════════════════════════════════════════════════════════════════════
# Institutional Research FactPack (Phase 1) — financial statements +
# deterministic trend engine. ADDITIVE: this is a separate, richer contract
# from the compact FactPack above (which the verdict LLM consumes). Every
# number below is computed in backend code; the LLM never produces any of them.
# Missing data is explicit (never hidden); provenance is per-dataset.
# ════════════════════════════════════════════════════════════════════


class DataProvenanceItem(BaseModel):
    """Where one dataset came from and when — provenance is per-dataset, always
    present so the UI can show source + freshness + coverage."""

    dataset: str  # "profile" | "income_quarterly" | "balance_quarterly" | "cashflow_annual" | ...
    source: str  # "fmp" | "yfinance" | "derived" | "none"
    as_of: Optional[str] = None  # latest fiscal date represented in the data
    fetched_at: Optional[str] = None  # ISO timestamp of the fetch
    coverage: float = 0.0  # 0..1 fraction of expected fields present
    note: Optional[str] = None


class MissingDataItem(BaseModel):
    """A dataset/field that is explicitly absent — surfaced, never silently
    dropped (product principle 3)."""

    dataset: str
    reason: str  # "provider_error" | "no_key" | "empty" | "insufficient_history" | "unsupported"


class CompanySnapshot(BaseModel):
    ticker: str
    name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    exchange: Optional[str] = None
    currency: str = "USD"
    price: Optional[float] = None
    market_cap: Optional[float] = None
    beta: Optional[float] = None
    shares_outstanding: Optional[float] = None


class _FinancialFigures(BaseModel):
    """Shared per-period figures (raw, where available) + deterministically
    computed margins. Subclassed by FinancialQuarter / FinancialAnnual so the
    field set + margin semantics are identical across cadences (DRY)."""

    # raw line items (None = the provider didn't supply it)
    revenue: Optional[float] = None
    gross_profit: Optional[float] = None
    operating_income: Optional[float] = None
    net_income: Optional[float] = None
    eps: Optional[float] = None
    eps_diluted: Optional[float] = None
    free_cash_flow: Optional[float] = None
    capex: Optional[float] = None
    cash: Optional[float] = None
    debt: Optional[float] = None
    shares_outstanding: Optional[float] = None
    diluted_shares: Optional[float] = None
    ebitda: Optional[float] = None
    # deterministic margins (ratios; None when revenue or the numerator is missing)
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    fcf_margin: Optional[float] = None


class FinancialQuarter(_FinancialFigures):
    period: str  # human label, e.g. "2024-Q2"
    fiscal_date: Optional[str] = None  # statement date, e.g. "2024-06-29"


class FinancialAnnual(_FinancialFigures):
    fiscal_year: str  # e.g. "2024"
    fiscal_date: Optional[str] = None


class FinancialTrendSummary(BaseModel):
    """Deterministic trend read across the quarterly (and annual) series. All
    growth is fractional (0.12 = +12%); margin deltas are in ratio points."""

    # Trailing-twelve-month aggregates (sum of the latest 4 quarters; None if <4)
    ttm_revenue: Optional[float] = None
    ttm_ebitda: Optional[float] = None
    ttm_fcf: Optional[float] = None
    ttm_eps: Optional[float] = None
    ttm_net_income: Optional[float] = None

    # Latest-quarter growth
    revenue_yoy: Optional[float] = None  # latest Q vs same Q one year prior
    revenue_qoq: Optional[float] = None  # latest Q vs the previous quarter
    eps_yoy: Optional[float] = None
    net_income_yoy: Optional[float] = None
    prior_revenue_yoy: Optional[float] = None  # the YoY one quarter earlier (for acceleration)

    # Margin deltas: latest Q margin minus the same-quarter-prior-year margin
    gross_margin_delta_yoy: Optional[float] = None
    operating_margin_delta_yoy: Optional[float] = None
    net_margin_delta_yoy: Optional[float] = None

    # Deterministic flags
    revenue_trend: Optional[str] = None  # "accelerating" | "decelerating" | "stable"
    flags: list[str] = Field(default_factory=list)
    quarters_used: int = 0
    annuals_used: int = 0


class ResearchFactPack(BaseModel):
    """Institutional research fact pack: company snapshot + up to 8 quarters and
    5 fiscal years of financials + a deterministic trend summary, with explicit
    provenance, missing-data, and a confidence score. Quarters/annuals are
    ordered NEWEST FIRST (index 0 = most recent)."""

    ticker: str
    as_of: Optional[str] = None  # latest fiscal date across datasets
    generated_at: Optional[str] = None  # ISO timestamp the pack was built
    snapshot: CompanySnapshot
    quarters: list[FinancialQuarter] = Field(default_factory=list)
    annuals: list[FinancialAnnual] = Field(default_factory=list)
    trend: FinancialTrendSummary = Field(default_factory=FinancialTrendSummary)
    provenance: list[DataProvenanceItem] = Field(default_factory=list)
    missing_data: list[MissingDataItem] = Field(default_factory=list)
    data_confidence: float = 0.0  # 0..1, deterministic
    confidence_label: str = "low"  # "high" | "medium" | "low"
    disclaimer: str = (
        "Educational and research use only — not investment advice. All figures "
        "are computed deterministically from provider data; missing data is listed "
        "explicitly and never inferred by an AI model."
    )
