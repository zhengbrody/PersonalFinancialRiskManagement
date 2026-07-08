"""Schemas for the ML regime endpoint (/api/v1/ml/regime).

`protected_namespaces=()` lets us keep the natural field name `model_version`
(Pydantic v2 otherwise warns on the `model_` prefix).
"""

from __future__ import annotations

from typing import Any, Optional

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


class FeatureDriftOut(BaseModel):
    psi: Optional[float] = None
    ks_stat: Optional[float] = None
    ks_p: Optional[float] = None
    n: int = 0
    status: str = "insufficient"


class PredictionDriftOut(BaseModel):
    psi: Optional[float] = None
    status: str = "healthy"
    n: int = 0
    live_fractions: dict[str, float] = Field(default_factory=dict)


class MLHealthOut(BaseModel):
    """GET /api/v1/ml/health — model/artifact identity + drift status.

    ``status``: ok | not_ready | unavailable (service tiers).
    ``overall_status``: healthy | watch | drift (worst feature/prediction PSI
    band) — null unless status == ok. Read-only context; never advice."""

    model_config = ConfigDict(extra="ignore", protected_namespaces=())

    status: str
    model_version: Optional[str] = None
    trained_at: Optional[str] = None
    artifact_loaded: bool = False
    sklearn_runtime: Optional[str] = None
    sklearn_trained: Optional[str] = None
    sklearn_match: Optional[bool] = None
    reference: Optional[dict[str, Any]] = None
    features: dict[str, FeatureDriftOut] = Field(default_factory=dict)
    prediction: Optional[PredictionDriftOut] = None
    overall_status: Optional[str] = None
    data_as_of: Optional[str] = None
    live_window_days: int = 0
    note: Optional[str] = None
    last_updated: Optional[str] = None
