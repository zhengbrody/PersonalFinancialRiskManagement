"""Schemas for ``POST /api/v1/risk/explain``.

The explain endpoint turns ALREADY-COMPUTED portfolio numbers into a
structured, plain-English diagnosis. The client passes back the metrics it
already fetched from the score / report endpoints (so there is no recompute
and the LLM literally cannot see anything beyond these numbers).

Hard invariant: the LLM never invents a number. ``severity`` and
``primary_driver`` are computed deterministically in Python
(``services.risk_explain``); the LLM only rephrases the rest, and on any
failure the whole output falls back to a deterministic template.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .confidence import DataConfidence

Severity = Literal["low", "moderate", "elevated", "high"]


# ── input (client-supplied, already-computed numbers) ──────────────────


class ExplainDimension(BaseModel):
    name: str = ""
    score: Optional[float] = None
    status: str = ""


class ExplainMetrics(BaseModel):
    model_config = ConfigDict(extra="ignore")

    annual_return: Optional[float] = None
    annual_volatility: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    var_95_daily: Optional[float] = None
    cvar_95_daily: Optional[float] = None
    beta_to_benchmark: Optional[float] = None
    total_value: Optional[float] = None
    cash_weight: Optional[float] = None


class ExplainContributor(BaseModel):
    ticker: str
    pct: float  # share of total portfolio VaR (0..1)


class ExplainLiquidity(BaseModel):
    ticker: str
    days_to_liquidate: Optional[float] = None


class ExplainSnapshotDelta(BaseModel):
    as_of: Optional[str] = None
    prev_overall_score: Optional[int] = None
    prev_annual_volatility: Optional[float] = None
    prev_sharpe_ratio: Optional[float] = None


class RiskExplainInput(BaseModel):
    """Compact deterministic summary the page already has. Every field is
    optional so the one endpoint serves both the Health Score page (score
    side) and the Risk Report page (report side)."""

    model_config = ConfigDict(extra="ignore")

    source: Literal["score", "risk"] = "score"
    overall_score: Optional[int] = Field(default=None, ge=0, le=1000)
    dimensions: dict[str, ExplainDimension] = Field(default_factory=dict)
    metrics: ExplainMetrics = Field(default_factory=ExplainMetrics)

    # Risk-report-only context (left empty on the score page).
    top_component_var: list[ExplainContributor] = Field(default_factory=list)
    factor_betas: dict[str, float] = Field(default_factory=dict)
    stress_loss: Optional[float] = None
    stress_market_shock: Optional[float] = None
    liquidity_outliers: list[ExplainLiquidity] = Field(default_factory=list)

    snapshot_delta: Optional[ExplainSnapshotDelta] = None

    # The unified data-confidence block the page already fetched (from the score
    # / risk-report response). Passing it back lets the diagnosis gate its
    # conviction on data quality — the AI never asserts a confident read on thin
    # data (enforcement rule #3).
    data_confidence: Optional[DataConfidence] = None


# ── output (structured diagnosis) ──────────────────────────────────────


class SuggestedAction(BaseModel):
    reason: str
    evidence: str  # the metric(s) that justify the action — numbers from input
    next_step: str
    disclaimer: str = "Educational, not financial advice."


class RiskExplainOutput(BaseModel):
    severity: Severity
    headline: str
    summary_bullets: list[str] = Field(default_factory=list)
    primary_driver: str
    watch_items: list[str] = Field(default_factory=list)
    suggested_actions: list[SuggestedAction] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    # True when LLM phrasing was used; False when the deterministic template
    # produced the prose (no key / quota / parse failure).
    ai_generated: bool = False
    # Data-confidence gate (rule #3). ``directional_allowed=False`` when critical
    # coverage < 40% — the diagnosis is provisional, not a confident read.
    # Always derived deterministically (never from the LLM).
    confidence_label: Optional[str] = None
    directional_allowed: bool = True
