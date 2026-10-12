"""Version-two execution records in the existing copilot_runs table."""

from typing import Literal, Self
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from .copilot_candidates import CandidateBatch, CandidateRequest
from .copilot_runs import RunSnapshot


class SignedTaskToken(BaseModel):
    """Same wire shape as copilot_task_state.TaskStateToken (kept here to avoid
    an import cycle); verified server-side before use."""

    model_config = ConfigDict(extra="forbid")
    record: str = Field(min_length=2, max_length=8192)
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")


class StartCandidateRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    task: CandidateRequest
    # Optional (additive): when present, the run must be exactly the task's
    # current confirmed version — same run id and same confirmed parameters.
    task_state: SignedTaskToken | None = None


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
            "analysis_failed",
            "reauthentication_required",
            "execution_expired",
            "portfolio_changed",
            "execution_version_changed",
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
    implementation: str | None = None
    user_id: UUID
    snapshot: RunSnapshot
    portfolio_revision: UUID
    task: CandidateRequest
    # Optional (additive): the decision task + confirmed version this run was
    # started for. Lets the server refuse a superseded version (older token)
    # after a newer confirmed version has been started. Legacy records: None.
    task_id: UUID | None = None
    task_version: int | None = Field(default=None, ge=1)

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
