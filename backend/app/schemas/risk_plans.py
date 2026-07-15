"""Risk PLANS — a saved ANALYSIS the user can review later (PR2).

A plan captures a hypothesis + a baseline snapshot + a proposed (simulated)
change + its expected impact + the data confidence at save time. It is NEVER an
order: the app has no path that writes a plan back to holdings or executes a
trade. The JSON blobs are opaque client-computed snapshots, but we bound their
size and reject non-finite numbers at the trust boundary so a client can't park
NaN/Inf or oversized payloads in our storage.
"""

from __future__ import annotations

import json
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

PlanStatus = Literal["draft", "active", "resolved", "archived"]
PlanSource = Literal["score", "risk", "scenario", "research", "copilot"]

# Per-blob byte cap (bounds arrays/objects too) — a plan is a compact snapshot,
# not a data lake. Reject NaN/Inf via json.dumps(allow_nan=False).
_BLOB_MAX_BYTES = 16384
_UUID_RE = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"


def _bounded_finite(v: Any, name: str) -> Any:
    """A JSON blob must be finite (no NaN/Inf) and within the byte cap."""
    try:
        encoded = json.dumps(v, ensure_ascii=False, allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ValueError(f"{name} must be finite JSON (no NaN/Inf): {exc}") from exc
    if len(encoded.encode("utf-8")) > _BLOB_MAX_BYTES:
        raise ValueError(f"{name} exceeds {_BLOB_MAX_BYTES} bytes")
    return v


class RiskPlanCreate(BaseModel):
    """Create a plan against a portfolio the caller owns (RLS enforces the
    ownership on write; this only shape-checks the payload)."""

    model_config = {"extra": "forbid"}

    portfolio_id: str = Field(..., pattern=_UUID_RE)
    title: str = Field(..., min_length=1, max_length=200)
    source: PlanSource
    status: PlanStatus = "draft"
    hypothesis: Optional[str] = Field(default=None, max_length=2000)
    baseline: dict[str, Any] = Field(default_factory=dict)
    proposed_changes: dict[str, Any] = Field(default_factory=dict)
    expected_impact: dict[str, Any] = Field(default_factory=dict)
    data_confidence: dict[str, Any] = Field(default_factory=dict)
    review_at: Optional[str] = Field(default=None, max_length=40)

    @field_validator("baseline", "proposed_changes", "expected_impact", "data_confidence")
    @classmethod
    def _blobs(cls, v: dict[str, Any], info: Any) -> dict[str, Any]:
        return _bounded_finite(v, info.field_name)


class RiskPlanPatch(BaseModel):
    """Partial update. Only status transitions + review/outcome bookkeeping and
    the editable text/plan blobs — never portfolio_id or source (a plan's
    provenance is immutable)."""

    model_config = {"extra": "forbid"}

    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    status: Optional[PlanStatus] = None
    hypothesis: Optional[str] = Field(default=None, max_length=2000)
    proposed_changes: Optional[dict[str, Any]] = None
    expected_impact: Optional[dict[str, Any]] = None
    review_at: Optional[str] = Field(default=None, max_length=40)
    outcome: Optional[dict[str, Any]] = None

    @field_validator("proposed_changes", "expected_impact", "outcome")
    @classmethod
    def _blobs(cls, v: Optional[dict[str, Any]], info: Any) -> Optional[dict[str, Any]]:
        return None if v is None else _bounded_finite(v, info.field_name)


class RiskPlanOut(BaseModel):
    """A stored plan (the DB row, ISO timestamps as strings)."""

    model_config = {"extra": "ignore"}

    id: str
    portfolio_id: str
    title: str
    status: PlanStatus
    source: PlanSource
    hypothesis: Optional[str] = None
    baseline: dict[str, Any] = Field(default_factory=dict)
    proposed_changes: dict[str, Any] = Field(default_factory=dict)
    expected_impact: dict[str, Any] = Field(default_factory=dict)
    data_confidence: dict[str, Any] = Field(default_factory=dict)
    review_at: Optional[str] = None
    reviewed_at: Optional[str] = None
    resolved_at: Optional[str] = None
    outcome: Optional[dict[str, Any]] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class RiskPlanList(BaseModel):
    plans: list[RiskPlanOut] = Field(default_factory=list)


class RiskPlanReviewRequest(BaseModel):
    """The caller passes the CURRENT metrics it already fetched (same pattern as
    /risk/explain, /risk/alerts) — the review compares them to the plan's stored
    baseline. No recompute, no holdings mutation."""

    model_config = {"extra": "forbid"}

    current: dict[str, Any] = Field(default_factory=dict)

    @field_validator("current")
    @classmethod
    def _finite(cls, v: dict[str, Any]) -> dict[str, Any]:
        return _bounded_finite(v, "current")


class RiskPlanMetricDelta(BaseModel):
    metric: str
    baseline: Optional[float] = None
    current: Optional[float] = None
    delta: Optional[float] = None
    improved: Optional[bool] = None  # by the metric's intrinsic better-direction


class RiskPlanReviewOut(BaseModel):
    """A deterministic, advice-free comparison of the plan's baseline vs the
    current metrics: which moved which way, and an overall verdict."""

    verdict: Literal["improved", "worsened", "inconclusive"]
    confidence: Literal["high", "medium", "low"]
    metrics: list[RiskPlanMetricDelta] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    disclaimer: str = "Educational comparison of your own saved numbers — not financial advice."
