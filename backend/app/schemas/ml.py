"""Schemas for the ML regime endpoint (/api/v1/ml/regime).

`protected_namespaces=()` lets us keep the natural field name `model_version`
(Pydantic v2 otherwise warns on the `model_` prefix).
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class FeatureDriver(BaseModel):
    feature: str
    label: str
    value: float
    vs_normal: str
    importance: Optional[float] = None


class MLRegimeOut(BaseModel):
    model_config = ConfigDict(extra="ignore", protected_namespaces=())
    # The 4-class risk STATE (risk_on|neutral|volatile|stress). Market CONTEXT
    # only — never investment advice, never feeds the deterministic Health Score.
    regime: Optional[str] = None
    confidence: Optional[float] = None
    class_probabilities: dict[str, float] = Field(default_factory=dict)
    top_drivers: list[FeatureDriver] = Field(default_factory=list)
    # Provenance.
    model_version: Optional[str] = None
    trained_at: Optional[str] = None
    training_window: Optional[dict] = None
    source: str  # model | heuristic_fallback | unavailable
    last_updated: Optional[str] = None
    data_coverage: dict = Field(default_factory=dict)
    current_realized_vol: Optional[float] = None
    note: Optional[str] = None
