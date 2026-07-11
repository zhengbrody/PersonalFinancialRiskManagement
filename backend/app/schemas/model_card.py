"""Public model-card contract for the risk-state classifier.

Every number is read from the committed ML artifacts (regime_meta.json +
validation_report.json) so the page can never drift from what actually validated
the model. Prose fields (intended use, limitations) are stable constants.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class CalibrationBinOut(BaseModel):
    bin: str
    n: int
    mean_predicted: Optional[float] = None
    observed_frequency: Optional[float] = None


class ModelFeatureOut(BaseModel):
    name: str
    importance: Optional[float] = None


class ClassDefinitionOut(BaseModel):
    label: str  # display label (e.g. "Elevated")
    key: str  # model class (risk_on | neutral | volatile | stress)
    definition: str  # plain-language threshold


class ModelCardOut(BaseModel):
    # keep the literal `model_*` field names (pydantic guards that namespace)
    model_config = ConfigDict(protected_namespaces=())

    available: bool = True
    model_version: Optional[str] = None
    trained_at: Optional[str] = None
    sklearn_version: Optional[str] = None
    estimator: Optional[str] = None

    # what it is / isn't
    headline: str = ""
    intended_use: str = ""
    not_for: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    excluded_signals: str = ""

    # structure
    classes: list[str] = Field(default_factory=list)
    class_definitions: list[ClassDefinitionOut] = Field(default_factory=list)
    features: list[ModelFeatureOut] = Field(default_factory=list)
    training_window: dict = Field(default_factory=dict)
    class_distribution: dict = Field(default_factory=dict)

    # honest metrics (the whole point of the page)
    cv_accuracy: Optional[float] = None  # mean walk-forward 4-class accuracy
    persistence_baseline_accuracy: Optional[float] = None  # the baseline it loses to
    majority_baseline_cv_accuracy: Optional[float] = None
    logistic_baseline_cv_accuracy: Optional[float] = None
    holdout_accuracy: Optional[float] = None
    holdout_majority_baseline_accuracy: Optional[float] = None
    elevated_risk_auc: Optional[float] = None  # the signal that survives validation
    brier: Optional[float] = None
    brier_base_rate: Optional[float] = None
    elevated_base_rate: Optional[float] = None
    holdout_size: Optional[int] = None
    calibration_bins: list[CalibrationBinOut] = Field(default_factory=list)
