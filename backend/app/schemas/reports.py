"""Exportable-report contracts.

The report endpoints are a pure PRESENTATION layer: the client passes back the
data it ALREADY fetched (the risk report, the research fact-pack/verdict, the
options analysis — exactly the ``/risk/explain`` pattern), so there is no
recompute and no second LLM call. We REUSE the existing response models as the
inputs (no duplicated field declarations); Pydantic ignores any extra keys the
frontend's loose schemas may carry.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel

from .options import OptionAnalyzeResponse
from .research import FactPack, ResearchVerdict
from .risk import RiskReportOut
from .risk_explain import RiskExplainOutput


class PortfolioReportInput(BaseModel):
    report: RiskReportOut
    diagnosis: Optional[RiskExplainOutput] = None  # the AI exec summary, if fetched


class TickerReportInput(BaseModel):
    fact_pack: FactPack
    verdict: Optional[ResearchVerdict] = None  # the AI analyst view, if fetched


class OptionsReportInput(BaseModel):
    analysis: OptionAnalyzeResponse


class ReportResponse(BaseModel):
    html: str  # a single self-contained document (inline CSS + print rules)
    input_hash: str  # stable id for the same inputs (audit / cache key)
    as_of: str
    kind: str  # "portfolio" | "ticker" | "options"
