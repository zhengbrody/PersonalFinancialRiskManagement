"""Version-two execution records in the existing copilot_runs table."""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .copilot_candidates import CandidateBatch, CandidateRequest
from .copilot_runs import RunSnapshot


class StartCandidateRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    task: CandidateRequest


class CandidateRunOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    portfolio_id: UUID
    state: Literal["queued", "running", "completed", "failed", "cancelled", "interrupted"]
    created_at: AwareDatetime
    updated_at: AwareDatetime
    expires_at: AwareDatetime
    lease_until: AwareDatetime | None = None
    execution_deadline: AwareDatetime | None = None
    revision: int = Field(default=0, ge=0)
    attempts: int = Field(default=0, ge=0, le=2)
    step: Literal["queued", "capturing", "evaluating", "done"] = "queued"
    result: CandidateBatch | None = None
    error_code: (
        Literal[
            "analysis_failed", "reauthentication_required", "execution_expired", "portfolio_changed"
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if (self.state == "completed") != (self.result is not None):
            raise ValueError("Only complete runs carry results")
        if self.result and self.result.portfolio_id != self.portfolio_id:
            raise ValueError("Result portfolio mismatch")
        if self.state == "running" and self.lease_until is None:
            raise ValueError("Running requires a lease")
        if (
            self.execution_deadline
            and self.lease_until
            and self.lease_until > self.execution_deadline
        ):
            raise ValueError("Lease cannot outlive the execution deadline")
        if self.state == "completed" and self.step != "done":
            raise ValueError("Complete requires a terminal step")
        return self


class CandidateRunRecord(CandidateRunOut):
    version: Literal[2] = 2
    user_id: UUID
    snapshot: RunSnapshot
    portfolio_revision: UUID
    task: CandidateRequest

    @model_validator(mode="after")
    def scope_matches(self) -> Self:
        if (
            self.snapshot.portfolio_id != self.portfolio_id
            or self.task.expected_portfolio_id != self.portfolio_id
        ):
            raise ValueError("Snapshot and task must match the portfolio")
        return self

    def public(self) -> CandidateRunOut:
        return CandidateRunOut.model_validate(
            self.model_dump(include=set(CandidateRunOut.model_fields))
        )


class RecoverCandidateRuns(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_portfolio_id: UUID


class CandidateRunList(BaseModel):
    model_config = ConfigDict(extra="forbid")
    runs: list[CandidateRunOut] = Field(default_factory=list, max_length=20)
    untrusted_records: int = Field(default=0, ge=0)
    dispatched: int = Field(default=0, ge=0, le=4)
    removed: int = Field(default=0, ge=0, le=100)
