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


class FeatureDriftOut(BaseModel):
    """One feature's drift verdict. ``psi`` is judged against the feature's OWN
    calibrated null (psi_p90/psi_p99 = percentiles of historical same-length
    window PSIs baked into the reference). ``ks_stat`` is descriptive only —
    no p-value is published because live windows are autocorrelated and an
    i.i.d. p would be invalid."""

    psi: Optional[float] = None
    psi_p90: Optional[float] = None
    psi_p99: Optional[float] = None
    ks_stat: Optional[float] = None
    # Fraction of live points outside the training [min, max]; > 0.25 forces
    # drift (PSI saturates and can't see beyond the support).
    oob_frac: Optional[float] = None
    n: int = 0
    status: str = "insufficient"
    calibrated: bool = False


class PredictionDriftOut(BaseModel):
    psi: Optional[float] = None
    status: str = "healthy"
    calibrated: bool = False
    n: int = 0
    live_fractions: dict[str, float] = Field(default_factory=dict)


class ReferenceSummary(BaseModel):
    """Identity of the committed drift reference the live window is scored
    against (a 3-field summary, not the full quantile grids)."""

    model_version: Optional[str] = None
    rows: Optional[int] = None
    features: int = 0


class ModelFreshnessOut(BaseModel):
    """Model age vs the staleness threshold (MINDMARKET_ML_STALE_DAYS).
    fresh | stale | unknown — an axis SEPARATE from the drift verdict."""

    status: str = "unknown"
    age_days: Optional[float] = None
    threshold_days: float = 21.0
    trained_at: Optional[str] = None


class ArtifactProvenanceOut(BaseModel):
    """What the delivery pipeline recorded about the run that produced the
    committed artifact. NOT the latest pipeline result — that is not knowable
    from the serving box."""

    source_commit: Optional[str] = None
    run_id: Optional[str] = None
    run_url: Optional[str] = None
    recorded_at: Optional[str] = None
    gates_passed: Optional[bool] = None
    gates: dict[str, bool] = Field(default_factory=dict)
    matches_meta: Optional[bool] = None


class ApprovedArtifactOut(BaseModel):
    """sha256 of the bytes the serving model was loaded from vs the approved
    hash. ``match`` is None when no approved hash was recorded (unknown)."""

    loaded_sha256: Optional[str] = None
    approved_sha256: Optional[str] = None
    approved_source: Optional[str] = None  # provenance | meta | None
    match: Optional[bool] = None
    provenance: Optional[ArtifactProvenanceOut] = None


class MLHealthOut(BaseModel):
    """GET /api/v1/ml/health — model/artifact identity + drift status.

    ``status``: ok | not_ready | unavailable (service tiers).
    ``overall_status``: healthy | watch | drift — worst feature/prediction
    verdict, each judged against its own calibrated null (live-window PSI vs
    the distribution of historical same-length training windows) — null unless
    status == ok. Read-only context; never advice."""

    model_config = ConfigDict(extra="ignore", protected_namespaces=())

    status: str
    model_version: Optional[str] = None
    trained_at: Optional[str] = None
    artifact_loaded: bool = False
    sklearn_runtime: Optional[str] = None
    sklearn_trained: Optional[str] = None
    sklearn_match: Optional[bool] = None
    reference: Optional[ReferenceSummary] = None
    features: dict[str, FeatureDriftOut] = Field(default_factory=dict)
    prediction: Optional[PredictionDriftOut] = None
    overall_status: Optional[str] = None
    data_as_of: Optional[str] = None
    live_window_days: int = 0
    note: Optional[str] = None
    last_updated: Optional[str] = None
    # Additive, independent of `status`/`overall_status`.
    freshness: Optional[ModelFreshnessOut] = None
    approved_artifact: Optional[ApprovedArtifactOut] = None
