"""Explicit confirmation and immutable combined-funding plan responses."""

from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from .funding_scenarios import FundingScenarioResult
from .put_plan import ConfirmPutPlan, PutPlanReview, ReviewPutPlanRequest


class ConfirmFundingPlan(ConfirmPutPlan):
    pass


class ReviewFundingPlanRequest(ReviewPutPlanRequest):
    pass


class FundingPlanReview(PutPlanReview):
    pass


class SavedFundingPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: UUID
    portfolio_id: UUID
    confirmed_at: AwareDatetime
    result: FundingScenarioResult
