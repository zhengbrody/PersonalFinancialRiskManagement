"""Schema for ``GET /api/v1/regime/summary`` — the composed, plain-language
market risk-state readout that powers the public /risk-today page and a
quotable social ``post_text``. Deterministic; no LLM. ``protected_namespaces=()``
keeps the natural ``model_version`` field name.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class RegimeDriverOut(BaseModel):
    label: str
    vs_normal: str


class RegimeVixOut(BaseModel):
    current: Optional[float] = None
    change: Optional[float] = None
    level: Optional[str] = None


class RegimeFearGreedOut(BaseModel):
    score: Optional[float] = None
    rating: Optional[str] = None


class RegimeCurveOut(BaseModel):
    status: Optional[str] = None
    spread_3m_10y: Optional[float] = None
    inverted: Optional[bool] = None


class RegimeSummaryOut(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    headline: str
    # PRIMARY (validated) signal: the elevated-risk probability = P(volatile) +
    # P(stress). Present ONLY when the model tier is active, data is fresh, and
    # drift monitoring is healthy — otherwise null (degraded → market context).
    elevated_risk_probability: Optional[float] = None
    probability_band: Optional[str] = None  # Low | Moderate | High | Very high
    # SECONDARY 4-class risk STATE (risk_on|neutral|volatile|stress) + its label.
    # Context only — NOT a validated conclusion; on 4-class accuracy the model
    # loses to a persistence baseline. Never advice, never part of the Health Score.
    regime_state: Optional[str] = None
    label: Optional[str] = None
    blurb: Optional[str] = None
    confidence: Optional[float] = None
    drivers: list[RegimeDriverOut] = Field(default_factory=list)
    vix: RegimeVixOut = Field(default_factory=RegimeVixOut)
    fear_greed: RegimeFearGreedOut = Field(default_factory=RegimeFearGreedOut)
    curve: RegimeCurveOut = Field(default_factory=RegimeCurveOut)
    as_of: Optional[str] = None  # data date (last observation the model saw)
    source: str  # model | heuristic_fallback | unavailable
    model_version: Optional[str] = None
    health_status: Optional[str] = None  # healthy | watch | drift (drift monitor)
    # When degraded we show deterministic market context (VIX/F&G/curve), NOT a
    # probability conclusion — `degraded_reason` says why.
    degraded: bool = False
    degraded_reason: Optional[str] = None  # model_unavailable | stale_data | model_drift | health_*
    caveat: str
    post_text: str  # deterministic ~250-char social string
