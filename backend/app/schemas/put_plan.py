"""Signed original Put calculation and read-only assumption review."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, StrictBool

from .copilot_compare import ComparisonReceipt
from .copilot_put import CashSecuredPutResult


class ConfirmPutPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_portfolio_id: UUID
    confirmed: StrictBool
    receipt: ComparisonReceipt


class SavedPutPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: UUID
    portfolio_id: UUID
    confirmed_at: AwareDatetime
    result: CashSecuredPutResult


class ReviewPutPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_portfolio_id: UUID


class PutPlanReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: UUID
    portfolio_id: UUID
    reviewed_at: AwareDatetime
    verdict: Literal["requires_recalculation", "assumptions_need_confirmation"]
    changed_fields: list[str]
    reasons: list[str]
    live_quote_checked: Literal[False] = False
    holdings_changed_by_review: Literal[False] = False
