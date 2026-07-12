"""Copilot 2.0 — intent-routed, evidence-grounded answers.

The router classifies the user's message into one of eight intents, gathers
*deterministic* evidence for that intent from the platform's own engines/
providers (never the LLM), then asks the LLM to synthesize one answer in a fixed
five-section format using ONLY that evidence. Every number the answer cites is an
``EvidenceItem`` the backend computed.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .confidence import DataConfidence

INTENTS = (
    "portfolio_diagnosis",
    "ticker_research",
    "compare_tickers",
    "scenario_simulation",
    "macro_rates",
    "tax_fee_review",
    "explain_metric",
    "action_plan",
)


class EvidenceItem(BaseModel):
    """One vetted fact the answer is allowed to use."""

    label: str
    value: str  # pre-formatted for display ("$1,234", "12.3%", "0.85")
    source: str  # "engine" | "fmp" | "yfinance" | "macro" | "derived" | "glossary"
    # primary / secondary / derived — so a DERIVED estimate is never shown as a
    # provider-reported fact (rule #3). Filled from the registry via _ev().
    source_type: Optional[str] = None


class CopilotAskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class CopilotAnswer(BaseModel):
    intent: str
    tickers: list[str] = Field(default_factory=list)
    answer_markdown: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    data_only: bool = False  # True when no LLM key → deterministic answer
    model: Optional[str] = None
    # Conviction the evidence supports (rule #3). "none" → the data is too thin
    # for a directional conclusion; the answer says so plainly.
    conviction: str = "medium"
    data_confidence: Optional[DataConfidence] = None
