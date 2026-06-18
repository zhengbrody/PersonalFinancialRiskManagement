"""Deterministic valuation contracts (Phase 2) — DCF + peer comparison.

Every number in these models is computed in backend code (services/research_dcf
+ research_peers); the LLM may only EXPLAIN them later, never invent them. Each
DCF assumption carries an explicit `source_type` so the UI can show whether a
figure is reported, derived, a labeled default, a user override, or unavailable.
Educational/research only — outputs are not investment advice.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from .research import DataProvenanceItem, MissingDataItem

# How a single assumption was sourced. "default" is a clearly-labeled
# conservative fallback; "unavailable" means we couldn't source it at all.
SourceType = Literal["reported", "derived", "default", "user_override", "unavailable"]

_DISCLAIMER = (
    "Educational and research use only — not investment advice. All figures are "
    "computed deterministically from provider data and labeled assumptions; "
    "defaults are explicit and every input shows its source."
)


# ════════════════════════════ DCF ════════════════════════════════════


class DCFAssumption(BaseModel):
    name: str
    value: Optional[float] = None
    source_type: SourceType = "unavailable"
    source: Optional[str] = None  # "fmp" | "derived:revenue_cagr" | "default" | "user"
    note: Optional[str] = None


class DCFInput(BaseModel):
    ticker: str
    projection_years: int = 5
    base_revenue: DCFAssumption
    revenue_growth: list[DCFAssumption] = Field(default_factory=list)  # per projection year
    operating_margin: list[DCFAssumption] = Field(default_factory=list)  # per projection year
    tax_rate: DCFAssumption
    da_pct_revenue: DCFAssumption  # D&A as a % of revenue
    capex_pct_revenue: DCFAssumption  # capex as a % of revenue
    nwc_pct_revenue: DCFAssumption  # ΔNWC as a % of the revenue change
    wacc: DCFAssumption
    terminal_growth: DCFAssumption
    net_debt: DCFAssumption
    diluted_shares: DCFAssumption
    provenance: list[DataProvenanceItem] = Field(default_factory=list)
    missing_data: list[MissingDataItem] = Field(default_factory=list)


class DCFProjectionYear(BaseModel):
    year: int
    revenue: float
    revenue_growth: float
    operating_margin: float
    ebit: float
    nopat: float
    da: float
    capex: float
    change_nwc: float
    fcf: float
    discount_factor: float
    pv_fcf: float


class DCFScenario(BaseModel):
    name: str  # "bear" | "base" | "bull"
    implied_value_per_share: Optional[float] = None
    enterprise_value: Optional[float] = None
    equity_value: Optional[float] = None
    upside_pct: Optional[float] = None


class DCFSensitivityTable(BaseModel):
    """A grid of implied per-share values. `values[i][j]` corresponds to
    (rows[i], cols[j]); None marks an invalid cell (e.g. terminal g ≥ WACC)."""

    title: str
    row_label: str
    col_label: str
    rows: list[float]
    cols: list[float]
    values: list[list[Optional[float]]]


class DCFOverrides(BaseModel):
    """Optional user overrides. Any field set replaces the derived assumption and
    is re-labeled source_type='user_override'."""

    projection_years: Optional[int] = Field(default=None, ge=3, le=10)
    base_revenue: Optional[float] = Field(default=None, gt=0)
    revenue_growth: Optional[list[float]] = None  # per year; or a single value applied to all
    terminal_operating_margin: Optional[float] = None
    operating_margin: Optional[float] = None  # flat margin for all years
    tax_rate: Optional[float] = Field(default=None, ge=0, le=0.6)
    da_pct_revenue: Optional[float] = Field(default=None, ge=0, le=0.5)
    capex_pct_revenue: Optional[float] = Field(default=None, ge=0, le=0.5)
    nwc_pct_revenue: Optional[float] = Field(default=None, ge=-0.5, le=0.5)
    wacc: Optional[float] = Field(default=None, gt=0, le=0.5)
    terminal_growth: Optional[float] = Field(default=None, ge=-0.05, le=0.1)
    net_debt: Optional[float] = None
    diluted_shares: Optional[float] = Field(default=None, gt=0)


class DCFRequest(BaseModel):
    overrides: Optional[DCFOverrides] = None


class DCFValuationOutput(BaseModel):
    ticker: str
    currency: str = "USD"
    as_of: Optional[str] = None
    generated_at: Optional[str] = None

    inputs: DCFInput
    projections: list[DCFProjectionYear] = Field(default_factory=list)

    terminal_value: Optional[float] = None
    pv_terminal_value: Optional[float] = None
    enterprise_value: Optional[float] = None
    equity_value: Optional[float] = None
    implied_value_per_share: Optional[float] = None
    current_price: Optional[float] = None
    upside_pct: Optional[float] = None  # implied/current − 1

    scenarios: list[DCFScenario] = Field(default_factory=list)  # bear/base/bull
    sensitivity: list[DCFSensitivityTable] = Field(default_factory=list)

    valid: bool = True
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = _DISCLAIMER


# ════════════════════════════ Peers ══════════════════════════════════


class PeerMetricProvenance(BaseModel):
    metric: str
    source: str  # "fmp" | "derived" | "none"
    as_of: Optional[str] = None


class PeerComparisonRow(BaseModel):
    """One company's metrics. `is_subject` marks the ticker under research."""

    ticker: str
    name: Optional[str] = None
    is_subject: bool = False
    market_cap: Optional[float] = None
    revenue_growth: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    net_margin: Optional[float] = None
    fcf_margin: Optional[float] = None
    roe: Optional[float] = None
    roic: Optional[float] = None
    pe: Optional[float] = None
    forward_pe: Optional[float] = None
    ev_sales: Optional[float] = None
    ev_ebitda: Optional[float] = None
    ps: Optional[float] = None
    debt_to_equity: Optional[float] = None
    net_cash: Optional[float] = None  # cash − total debt (positive = net cash)
    return_1y: Optional[float] = None


class PeerPercentile(BaseModel):
    metric: str
    subject_value: Optional[float] = None
    peer_median: Optional[float] = None
    percentile: Optional[float] = None  # 0..1 rank of the subject among peers (incl. subject)
    n: int = 0  # how many non-null values backed the stat


class PeerComparisonOutput(BaseModel):
    ticker: str
    as_of: Optional[str] = None
    generated_at: Optional[str] = None
    peer_source: str  # "fmp" | "sector" | "curated" | "user"
    rows: list[PeerComparisonRow] = Field(default_factory=list)  # subject first
    percentiles: list[PeerPercentile] = Field(default_factory=list)
    provenance: list[PeerMetricProvenance] = Field(default_factory=list)
    missing_data: list[MissingDataItem] = Field(default_factory=list)
    disclaimer: str = _DISCLAIMER
