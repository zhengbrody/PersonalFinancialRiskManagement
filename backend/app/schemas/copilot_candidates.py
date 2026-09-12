"""User-confirmed constraints and a bounded, single-capture comparison batch."""

from typing import Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    StrictBool,
    model_validator,
)

from .copilot_compare import ChangeComparison, ComparisonSide


class CandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_portfolio_id: UUID
    goal: Literal["increase_cash", "reduce_margin"]
    amount: FiniteFloat = Field(gt=0, le=100_000_000, strict=True)
    protected_holdings: list[str] = Field(default_factory=list, max_length=100)
    confirmed: StrictBool


class CandidateBatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: UUID
    portfolio_id: UUID
    computed_at: AwareDatetime
    task: CandidateRequest
    baseline: ComparisonSide | None = None
    candidates: list[ChangeComparison] = Field(default_factory=list, max_length=2)
    preferred_result_id: UUID | None = None
    coverage: Literal["evaluated", "insufficient_data", "unsupported"]
    judgment: str
    excluded: dict[str, str] = Field(default_factory=dict)
    limitations: list[str]

    @model_validator(mode="after")
    def bound_comparisons(self) -> Self:
        if self.task.expected_portfolio_id != self.portfolio_id or not self.task.confirmed:
            raise ValueError("Batch must bind confirmed constraints to its portfolio")
        ids = [candidate.result_id for candidate in self.candidates]
        if len(set(ids)) != len(ids):
            raise ValueError("Candidate identifiers must be unique")
        if self.preferred_result_id is not None and self.preferred_result_id not in ids:
            raise ValueError("Preferred result must be an evaluated candidate")
        expected_proceeds = "cash" if self.task.goal == "increase_cash" else "repay_margin"
        for candidate in self.candidates:
            if (
                candidate.portfolio_id != self.portfolio_id
                or candidate.computed_at != self.computed_at
                or candidate.baseline != self.baseline
                or candidate.assumptions.amount != self.task.amount
                or candidate.assumptions.proceeds != expected_proceeds
                or candidate.assumptions.ticker in self.task.protected_holdings
            ):
                raise ValueError("Candidate does not match the captured task and baseline")
        if self.candidates and self.coverage != "evaluated":
            raise ValueError("Calculated candidates require evaluated coverage")
        if not self.candidates and self.coverage == "evaluated":
            raise ValueError("Empty comparisons cannot claim evaluated coverage")
        return self
