"""Research context is separate from account evidence and execution receipts."""

from typing import Literal, Self

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat, model_validator

from .decision_support import MethodReference


class ResearchObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    ticker: str
    metric: str
    value: FiniteFloat | None
    unit: Literal["ratio", "fraction"]
    source: str
    source_as_of: AwareDatetime | None = None
    reporting_period: None = None
    provenance: Literal["block_only", "unavailable"]
    status: Literal["available", "missing", "stale", "undated"]
    basis: Literal["provider_projection", "computed_from_series"]
    scope: Literal["company_research"] = "company_research"


class ResearchQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method_id: str
    hypothesis: str
    observation_ids: list[str]
    counterpoint: str
    invalidation_check: str
    status: Literal["not_tested"] = "not_tested"


class ResearchLead(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    publisher: str | None = None
    author: None = None
    published_at: AwareDatetime | None = None
    url: str
    conflicts: Literal["not_disclosed_in_feed"] = "not_disclosed_in_feed"
    verification: Literal["metadata_only"] = "metadata_only"


class CopilotResearch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    ticker: str
    captured_at: AwareDatetime
    status: Literal["available", "partial", "unavailable"]
    observations: list[ResearchObservation] = Field(max_length=4)
    questions: list[ResearchQuestion] = Field(max_length=2)
    leads: list[ResearchLead] = Field(default_factory=list, max_length=3)
    methods: list[MethodReference]
    limitations: list[str]
    can_rank_candidates: Literal[False] = False

    @model_validator(mode="after")
    def bound_observations(self) -> Self:
        ids = {row.id for row in self.observations}
        if len(ids) != len(self.observations) or any(
            row.ticker != self.ticker or row.id != f"{row.ticker}:{row.metric}"
            for row in self.observations
        ):
            raise ValueError("Research observation scope mismatch")
        if any(id not in ids for question in self.questions for id in question.observation_ids):
            raise ValueError("Research question has an unknown observation")
        return self
