"""Proactive Copilot insights (PR4) — deterministic, change-aware, no advice.

Insights are computed server-side from data the platform ALREADY records
(portfolio snapshots, the live score, the cached market/ML regime, data
confidence). They report MATERIAL changes only (thresholds + one-per-kind
dedup + stable episode ids so a persisting condition keeps the same id and a
client-side dismissal survives). No BUY/SELL, no price targets, no trade
instructions — each insight ends in a non-transactional next ANALYSIS step.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .copilot2 import EvidenceItem

InsightKind = (
    str  # score_move | dimension_drag | concentration | leverage | market_regime | data_quality
)


class InsightNextAnalysis(BaseModel):
    """A non-transactional next step — always an ANALYSIS surface, never a trade."""

    label: str
    href: str  # internal app route ("/score", "/risk", "/scenarios", "/markets")


class InsightOut(BaseModel):
    # Stable across calls while the same episode persists (dedup/cooldown key
    # for clients); one insight per kind per response.
    id: str
    kind: InsightKind
    severity: str = "info"  # info | watch | high
    what_changed: str
    why_it_matters: str
    evidence: list[EvidenceItem] = Field(default_factory=list)
    confidence: Optional[str] = None  # high | medium | low (the score's own read)
    as_of: Optional[str] = None
    missing_data: list[str] = Field(default_factory=list)
    suggested_next_analysis: Optional[InsightNextAnalysis] = None


class InsightsOut(BaseModel):
    insights: list[InsightOut] = Field(default_factory=list)
    as_of: Optional[str] = None
    portfolio_available: bool = False
    missing_data: list[str] = Field(default_factory=list)
