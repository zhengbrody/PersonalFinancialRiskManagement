"""AI thesis + analyst-report contracts (Phase 3).

The thesis LLM may only EXPLAIN/compare/write prose from the deterministic
evidence (FactPack + DCF + peers + earnings + news/technicals). It must not
output a buy/sell/hold call, a fabricated target price, or any number absent
from the evidence — `research_thesis` validates and flags unsupported numbers,
and falls back to a deterministic thesis on any LLM failure.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .research import DataProvenanceItem, MissingDataItem

_DISCLAIMER = (
    "Educational and research use only — not investment advice. The thesis is an "
    "AI explanation of deterministic figures; it makes no buy/sell/hold "
    "recommendation and invents no numbers. Verify against primary sources."
)


class ThesisOutput(BaseModel):
    ticker: str
    generated_at: Optional[str] = None
    bull_case: list[str] = Field(default_factory=list)
    bear_case: list[str] = Field(default_factory=list)
    key_debate: Optional[str] = None
    what_would_change_view: list[str] = Field(default_factory=list)
    monitor_next_quarter: list[str] = Field(default_factory=list)
    questions_for_management: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    ai_generated: bool = False  # False = deterministic fallback (no/failed LLM)
    # Numbers in the LLM prose NOT found in the deterministic evidence (validation).
    flagged_numbers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = _DISCLAIMER


# ── Analyst HTML report (Part C) ─────────────────────────────────────


class AnalystReportSection(BaseModel):
    key: str  # "cover" | "snapshot" | "exec_summary" | "financials" | ...
    title: str
    included: bool = True
    note: Optional[str] = None  # e.g. why a section is empty/partial


class AnalystReportProvenanceAppendix(BaseModel):
    items: list[DataProvenanceItem] = Field(default_factory=list)
    missing_data: list[MissingDataItem] = Field(default_factory=list)


class AnalystReportOutput(BaseModel):
    ticker: str
    title: str
    generated_at: Optional[str] = None
    as_of: Optional[str] = None
    html: str  # full self-contained HTML document (PDF-ready)
    sections: list[AnalystReportSection] = Field(default_factory=list)
    provenance: AnalystReportProvenanceAppendix = Field(
        default_factory=AnalystReportProvenanceAppendix
    )
    disclaimer: str = _DISCLAIMER
