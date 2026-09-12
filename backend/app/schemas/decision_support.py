"""Additive task contract. Requests and external prose never become account facts."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

TaskKind = Literal["explanation", "clarification", "specified_comparison", "candidate_request"]


class DecisionTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: TaskKind
    goal: str | None = None
    missing_inputs: list[str] = Field(default_factory=list)
    # Only a separately confirmed, validated request may populate constraints.
    confirmed_constraints: dict[str, str] = Field(default_factory=dict)


class MethodReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    author: str
    url: str
    reviewed_at: str
    version: str
    summary: str
    checks: list[str]
    counterpoint: str
    applicability: str


class DecisionSupport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    task: DecisionTask
    coverage: Literal["unsupported", "insufficient_data", "explained", "evaluated"]
    methods: list[MethodReference] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    # This envelope describes the task, not a signed calculation/save receipt.
    save_available: Literal[False] = False
    candidate_comparison_available: bool = False
    cash_secured_put_available: bool = False
