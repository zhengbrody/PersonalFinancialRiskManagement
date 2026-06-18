"""Earnings comparison contracts (Phase 3).

Deterministic: actual revenue/EPS vs prior-quarter / prior-year, and vs analyst
estimate ONLY when estimate data exists (beat/miss is never shown without an
estimate). Transcript metadata is surfaced with explicit availability; missing
estimates / transcript are explicit. No LLM produces any number here.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .research import DataProvenanceItem, MissingDataItem

_DISCLAIMER = (
    "Educational and research use only — not investment advice. Earnings figures "
    "and beat/miss are computed deterministically from provider data; missing "
    "estimates or transcripts are listed explicitly."
)


class EarningsPeriod(BaseModel):
    period: str  # "2024-Q2"
    fiscal_date: Optional[str] = None
    revenue: Optional[float] = None
    revenue_yoy: Optional[float] = None  # vs same quarter prior year
    revenue_qoq: Optional[float] = None  # vs previous quarter
    eps: Optional[float] = None
    eps_yoy: Optional[float] = None
    eps_qoq: Optional[float] = None
    # vs analyst estimate (None unless estimate data exists)
    revenue_estimate: Optional[float] = None
    eps_estimate: Optional[float] = None
    revenue_surprise_pct: Optional[float] = None  # actual/estimate − 1
    eps_surprise_pct: Optional[float] = None
    revenue_beat: Optional[bool] = None  # only set when an estimate exists
    eps_beat: Optional[bool] = None


class EarningsTranscriptMetadata(BaseModel):
    available: bool = False
    quarter: Optional[int] = None
    fiscal_year: Optional[int] = None
    date: Optional[str] = None
    source: Optional[str] = None  # "fmp"
    excerpt_length: int = 0  # chars of transcript captured (for the thesis LLM)


class EarningsThemeSummary(BaseModel):
    """Deterministic factual summary of the latest quarter. (The LLM narrative —
    management tone, guidance, themes — lives in the thesis, which consumes this
    + the transcript excerpt; this block never uses an LLM.)"""

    headline: Optional[str] = None
    points: list[str] = Field(default_factory=list)
    ai_generated: bool = False


class EarningsComparisonOutput(BaseModel):
    ticker: str
    as_of: Optional[str] = None
    generated_at: Optional[str] = None
    periods: list[EarningsPeriod] = Field(default_factory=list)  # newest first
    transcript: EarningsTranscriptMetadata = Field(default_factory=EarningsTranscriptMetadata)
    summary: EarningsThemeSummary = Field(default_factory=EarningsThemeSummary)
    provenance: list[DataProvenanceItem] = Field(default_factory=list)
    missing_data: list[MissingDataItem] = Field(default_factory=list)
    disclaimer: str = _DISCLAIMER
