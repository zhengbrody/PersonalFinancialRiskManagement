"""Alert lifecycle state + per-user journey milestones (PR2).

Neither carries investment content: alert states key a deterministic alert's
STABLE episode id to a lifecycle state; journey stores only milestone
timestamps. Both are RLS-scoped to the caller.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

_UUID_RE = r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"

AlertState = Literal["new", "seen", "snoozed", "resolved"]


class AlertStateUpsert(BaseModel):
    """Set the lifecycle state for one alert episode on one portfolio."""

    model_config = {"extra": "forbid"}

    portfolio_id: str = Field(..., pattern=_UUID_RE)
    alert_key: str = Field(..., min_length=1, max_length=200)
    state: AlertState
    # Only meaningful for `snoozed`; ISO timestamp (validated as a bounded string).
    snooze_until: Optional[str] = Field(default=None, max_length=40)


class AlertStateOut(BaseModel):
    model_config = {"extra": "ignore"}

    portfolio_id: str
    alert_key: str
    state: AlertState
    snooze_until: Optional[str] = None
    updated_at: Optional[str] = None


class AlertStateList(BaseModel):
    states: list[AlertStateOut] = Field(default_factory=list)


# ── journey ───────────────────────────────────────────────────────────

JourneyMilestone = Literal[
    # Product events with authoritative backend handlers (portfolio created,
    # score/report completed, plan saved/reviewed) are stamped by those handlers
    # and cannot be claimed through this generic client endpoint.
    "first_score_at",
    "first_stress_test_at",
    "last_workspace_view",
]


class JourneyRecordRequest(BaseModel):
    """Record the two client-originated events.

    ``first_score_at`` is sent only after the active-book Overview renders;
    ``first_stress_test_at`` only after an explicit sandbox run succeeds;
    ``last_workspace_view`` is navigation telemetry. Other milestones are
    stamped by their authoritative backend product endpoint.
    """

    model_config = {"extra": "forbid"}

    milestone: JourneyMilestone


class JourneyOut(BaseModel):
    model_config = {"extra": "ignore"}

    first_portfolio_at: Optional[str] = None
    first_score_at: Optional[str] = None
    first_driver_viewed_at: Optional[str] = None
    first_stress_test_at: Optional[str] = None
    first_plan_at: Optional[str] = None
    first_plan_reviewed_at: Optional[str] = None
    last_workspace_view: Optional[str] = None
