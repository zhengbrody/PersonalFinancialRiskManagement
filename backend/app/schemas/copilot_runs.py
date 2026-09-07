"""Durable foreground-check records. No prompts, credentials or orders."""

from typing import Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    JsonValue,
    model_validator,
)

from .risk_check import RiskCheck

RunState = Literal["running", "completed", "failed", "cancelled", "interrupted"]


class StartRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    expected_portfolio_id: UUID


class RunSnapshot(BaseModel):
    """Server-resolved account inputs; not a replayable market-data snapshot."""

    model_config = ConfigDict(extra="forbid")
    portfolio_id: UUID
    holdings: dict[str, dict[str, JsonValue]]
    cash_balance: FiniteFloat
    margin_loan: FiniteFloat
    contributed_capital: FiniteFloat
    risk_preference: int = Field(ge=1, le=5)
    preference_source: Literal["confirmed", "neutral_baseline", "request_override"]
    preference_confirmed_at: str | None = None
    history_days: int = Field(default=365, ge=180, le=2520)
    risk_free_rate: FiniteFloat = Field(default=0.045, ge=0, le=0.20)
    market_shock: FiniteFloat = Field(default=-0.10, ge=-0.50, le=0)


class RunOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    portfolio_id: UUID
    state: RunState
    created_at: AwareDatetime
    expires_at: AwareDatetime
    updated_at: AwareDatetime
    result: RiskCheck | None = None
    error_code: Literal["analysis_failed", "run_expired"] | None = None

    @model_validator(mode="after")
    def consistent_result(self) -> Self:
        if (self.state == "completed") != (self.result is not None):
            raise ValueError("Only completed runs carry a result")
        if self.result and self.result.portfolio_id != str(self.portfolio_id):
            raise ValueError("Result portfolio mismatch")
        return self


class RunRecord(RunOut):
    version: Literal[1] = 1
    user_id: UUID
    snapshot: RunSnapshot

    @model_validator(mode="after")
    def consistent_snapshot(self) -> Self:
        if self.snapshot.portfolio_id != self.portfolio_id:
            raise ValueError("Snapshot portfolio mismatch")
        return self

    def public(self) -> RunOut:
        return RunOut.model_validate(self.model_dump(include=set(RunOut.model_fields)))
