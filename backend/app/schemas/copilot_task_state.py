"""Multi-turn decision task state: assumptions, confirmed parameters, account data.

Three things are kept strictly apart:

* ``assumptions`` — values the user *stated* in chat. They only prefill the
  typed form; nothing downstream reads them as facts or as consent.
* ``confirmed`` — parameters the user confirmed in the typed form. Versioned;
  a new version supersedes (invalidates) the previous version's run.
* account data — never here. It is captured server-side from the
  authenticated active portfolio when a run is reserved (``RunSnapshot``).

The record travels as an HMAC-signed token held in the client's session
partition (no new table). The server is the only issuer and verifies the
signature, owner, portfolio and expiry on every use.
"""

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

from .copilot_jobs import CandidateRunOut

Slot = Literal["goal", "amount", "protected_holdings"]
Goal = Literal["increase_cash", "reduce_margin"]
TaskStatus = Literal["needs_input", "ready_to_confirm", "confirmed", "closed"]
FollowUpOutcome = Literal[
    "started",  # a new task opened with this message
    "continued",  # the message supplied a pending input (as an assumption)
    "ambiguous",  # could be an answer, but unclear — asked instead of guessing
    "unrelated",  # an ordinary question; the open task is kept unchanged
    "turn_limit",  # clarification budget spent; use the typed form
    "closed",  # the user cancelled the task
    "expired",  # the task passed its expiry
    "discarded",  # an untrusted / foreign / other-portfolio token was ignored
]
Ambiguity = Literal[
    "amount_multiple",
    "amount_percent",
    "amount_unanchored",
    "amount_out_of_range",
    "goal_conflict",
    "goal_unsupported",
    "goal_negated",
    "protected_without_ticker",
    "ticker_without_instruction",
]


class TaskAssumptions(BaseModel):
    """What the user said. ``None`` = not stated; ``[]`` = stated 'none'."""

    model_config = ConfigDict(extra="forbid")
    goal: Goal | None = None
    amount: FiniteFloat | None = Field(default=None, gt=0, le=100_000_000)
    protected_holdings: list[str] | None = Field(default=None, max_length=100)
    stated_at_turn: dict[Slot, int] = Field(default_factory=dict)


class ConfirmedParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1, le=1000)
    goal: Goal
    amount: FiniteFloat = Field(gt=0, le=100_000_000)
    protected_holdings: list[str] = Field(default_factory=list, max_length=100)
    confirmed_at: AwareDatetime
    # The run calculated for exactly this version (idempotency key).
    run_id: UUID
    # Set when a resume found the account changed after this version's run was
    # reserved. A stale version can only be replaced by an explicit re-confirm.
    stale: bool = False


class TaskStateView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    task_id: UUID
    portfolio_id: UUID
    kind: Literal["candidate_request", "clarification"]
    status: TaskStatus
    missing_inputs: list[Slot] = Field(default_factory=list)
    pending_question: Slot | None = None
    ambiguities: list[Ambiguity] = Field(default_factory=list)
    clarification_turns: int = Field(default=0, ge=0)
    max_clarification_turns: int = Field(ge=1)
    assumptions: TaskAssumptions = Field(default_factory=TaskAssumptions)
    confirmed: ConfirmedParameters | None = None
    superseded_run_ids: list[UUID] = Field(default_factory=list, max_length=5)
    created_at: AwareDatetime
    updated_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.clarification_turns > self.max_clarification_turns:
            raise ValueError("Clarification turns exceed the bound")
        if self.status == "confirmed" and self.confirmed is None:
            raise ValueError("Confirmed status requires confirmed parameters")
        if self.confirmed is not None and self.status not in ("confirmed", "closed"):
            raise ValueError("Confirmed parameters require confirmed or closed status")
        if self.confirmed and self.confirmed.run_id in self.superseded_run_ids:
            raise ValueError("A current run cannot also be superseded")
        if self.expires_at <= self.created_at:
            raise ValueError("Expiry must follow creation")
        return self


class TaskStateRecord(TaskStateView):
    user_id: UUID

    def view(self) -> TaskStateView:
        return TaskStateView.model_validate(self.model_dump(exclude={"user_id"}))


class TaskStateToken(BaseModel):
    """Opaque to the client: echoed back verbatim; only the server can mint it."""

    model_config = ConfigDict(extra="forbid")
    record: str = Field(min_length=2, max_length=8192)
    signature: str = Field(pattern=r"^[0-9a-f]{64}$")


class TaskStateEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: FollowUpOutcome
    state: TaskStateView | None = None
    token: TaskStateToken | None = None


class ConfirmTaskParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_state: TaskStateToken
    expected_portfolio_id: UUID
    goal: Goal
    amount: FiniteFloat = Field(gt=0, le=100_000_000, strict=True)
    protected_holdings: list[str] = Field(default_factory=list, max_length=100)
    run_id: UUID
    confirmed: StrictBool


class ResumeTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_state: TaskStateToken
    expected_portfolio_id: UUID


ResumeOutcome = Literal[
    "needs_input",
    "ready_to_confirm",
    "continuing",
    "completed",
    "stale_account_changed",
    "run_missing",
    "run_failed",
    "expired",
    "closed",
    # A newer confirmed version of this task has been started: the older
    # version's run is never presented or continued.
    "superseded",
]


class TaskResumeOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: ResumeOutcome
    state: TaskStateView
    token: TaskStateToken
    run: CandidateRunOut | None = None
    dispatched: bool = False
