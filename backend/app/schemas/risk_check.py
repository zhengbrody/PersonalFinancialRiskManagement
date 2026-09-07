"""Small, typed Copilot view of the existing risk report, not another engine."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, FiniteFloat

from .confidence import DataConfidence


class CheckMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    label: str
    value: FiniteFloat | None = None
    unit: Literal["usd", "fraction", "multiple", "days"]
    horizon: str
    basis: str
    explanation: str
    source_field: str


class CheckFinding(BaseModel):
    key: str
    title: str
    severity: Literal["high", "elevated", "info"]
    explanation: str


class CheckStrategy(BaseModel):
    underlying: str
    expiry: str
    name: str
    leg_count: int
    premium_basis: Literal["entry", "current_mark", "mixed", "unavailable"]
    max_loss: FiniteFloat | None = None
    max_gain: FiniteFloat | None = None
    loss_status: Literal["bounded", "unbounded", "unavailable"]
    gain_status: Literal["bounded", "unbounded", "unavailable"]


class RiskCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    portfolio_id: str
    result_id: str
    methodology_version: Literal["risk-check-v1"] = "risk-check-v1"
    computed_at: str
    price_history_as_of: str | None = None
    status: Literal["ready", "limited"]
    summary: str
    metrics: list[CheckMetric] = Field(default_factory=list)
    strategies: list[CheckStrategy] = Field(default_factory=list)
    findings: list[CheckFinding] = Field(default_factory=list, max_length=3)
    limitations: list[str] = Field(default_factory=list)
    data_confidence: DataConfidence | None = None
