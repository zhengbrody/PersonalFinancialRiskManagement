"""Copilot 2.0 — intent-routed, evidence-grounded answers.

The router classifies the user's message into an intent, gathers *deterministic*
evidence for it from the platform's own engines/providers (never the LLM), then
composes ONE answer in a fixed six-section contract:

  1. direct_answer          — answers the question, directly
  2. portfolio_relevance    — why it matters for THIS portfolio (or an honest
                              "not personalized" when no portfolio data loaded)
  3. evidence               — the vetted facts, each traceable by id/source/tool
  4. data_confidence        — qualitative confidence + what's missing
  5. what_would_change      — observable changes that would alter the conclusion
  6. simulation             — at most ONE deterministic what-if (never executed),
                              or an explicit "cannot simulate reliably"

Sections 3/4/6 are ALWAYS deterministic; the LLM may only phrase 1/2/5 and each
phrased section must pass a grounding gate (every numeric claim traceable to the
evidence packet) or it falls back to deterministic text. ``answer_markdown`` is
COMPOSED from the sections, so the flat and structured views cannot drift.
"""

from __future__ import annotations

from typing import Literal, Optional

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

# The closed six-section contract, in render order. ``answer_markdown`` is built
# from these; adding a key here is a contract change (update the composer + tests).
SECTION_KEYS = (
    "direct_answer",
    "portfolio_relevance",
    "evidence",
    "data_confidence",
    "what_would_change",
    "simulation",
)

SectionKey = Literal[
    "direct_answer",
    "portfolio_relevance",
    "evidence",
    "data_confidence",
    "what_would_change",
    "simulation",
]

# Deterministic reply language ("zh" only when the message is clearly Chinese —
# see ``detect_reply_language``). Defaults to "en" for backward compatibility.
AnswerLanguage = Literal["en", "zh"]


class EvidenceItem(BaseModel):
    """One vetted fact the answer is allowed to use."""

    label: str
    value: str  # pre-formatted for display ("$1,234", "12.3%", "0.85")
    source: str  # "engine" | "fmp" | "yfinance" | "macro" | "derived" | "glossary"
    # primary / secondary / derived — so a DERIVED estimate is never shown as a
    # provider-reported fact (rule #3). Filled from the registry via _ev().
    source_type: Optional[str] = None
    # Traceability (PR2, additive): a stable per-answer id ("E1", "E2", …) the
    # sections cite, and the deterministic tool that computed the fact.
    id: Optional[str] = None
    tool: Optional[str] = None


class CopilotAnswerSection(BaseModel):
    """One of the six structured answer sections (closed key set, fixed order).

    ``ai_generated`` is True only for a narrative section whose prose the LLM
    wrote AND that passed the grounding gate; the deterministic sections
    (evidence / data_confidence / simulation) are always False.
    """

    key: SectionKey
    title: str  # localized display header
    markdown: str
    ai_generated: bool = False


class CopilotAskRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    # Page-awareness context (optional, additive). `route` is the app path the
    # user is on (e.g. "/research", "/risk"); `ticker` is the security currently
    # in view. Both only STEER intent + which deterministic tools run — they
    # never become evidence the answer can cite.
    route: Optional[str] = Field(default=None, max_length=120)
    ticker: Optional[str] = Field(default=None, max_length=20)


class CopilotAnswer(BaseModel):
    intent: str
    tickers: list[str] = Field(default_factory=list)
    answer_markdown: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    data_only: bool = False  # True when no LLM prose survived → deterministic answer
    model: Optional[str] = None
    # Conviction the evidence supports (rule #3). "none" → the data is too thin
    # for a directional conclusion; the answer says so plainly.
    conviction: str = "medium"
    data_confidence: Optional[DataConfidence] = None
    # PR2 (additive): the six-section structured contract. ``answer_markdown``
    # is composed FROM these sections (single source — flat and structured
    # cannot contradict). Defaults keep pre-PR2 payloads/clients valid.
    sections: list[CopilotAnswerSection] = Field(default_factory=list)
    language: AnswerLanguage = "en"
    disclaimer: Optional[str] = None
