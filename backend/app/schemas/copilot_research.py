"""Research context is separate from account evidence and execution receipts."""

from typing import Literal, Self

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    model_validator,
)

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


Comparator = Literal["gt", "ge", "lt", "le"]
HypothesisStatus = Literal["unverified", "supported_by_evidence", "contradicted", "stale"]
MissingReason = Literal[
    "no_authorized_source",
    "reporting_period_unavailable",
    "observation_missing",
    "observation_stale",
    "observation_undated",
    "no_testable_predicate",
    "cited_source_not_retrieved",
]


class HypothesisSource(BaseModel):
    """Where a claim or its evidence came from. Never an authorization."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(max_length=120)
    source_type: Literal["user_statement", "provider_snapshot", "method_card"]
    author: str | None = Field(default=None, max_length=120)
    publisher: str | None = Field(default=None, max_length=120)
    url: str | None = Field(default=None, max_length=500)
    published_at: AwareDatetime | None = None
    retrieved_at: AwareDatetime | None = None
    usage_basis: Literal["user_provided", "provider_api", "public_page_paraphrase"]
    # A direct quote must say where it is; otherwise the text is a paraphrase.
    quote_locator: str | None = Field(default=None, max_length=200)
    paraphrase: bool = True
    verification: Literal["not_verified", "provider_snapshot", "reviewed_method"]

    @model_validator(mode="after")
    def quote_needs_locator(self) -> Self:
        if not self.paraphrase and not self.quote_locator:
            raise ValueError("A quotation needs a locator")
        if self.source_type == "user_statement" and self.verification != "not_verified":
            raise ValueError("A user statement cannot be marked verified")
        return self


class HypothesisTest(BaseModel):
    """One observable predicate. The threshold is ALWAYS the user's number."""

    model_config = ConfigDict(extra="forbid")
    observation_id: str
    comparator: Comparator
    threshold: FiniteFloat
    unit: Literal["ratio", "fraction"]
    threshold_basis: Literal["user_assumption"] = "user_assumption"


class InvalidationCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["observable_test", "qualitative_check", "not_defined"]
    description: str = Field(max_length=400)
    observation_id: str | None = None


class HypothesisMissing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    item: str = Field(max_length=120)
    reason: MissingReason


def evaluate_test(test: HypothesisTest | None, observation: "ResearchObservation | None") -> str:
    """The ONLY rule that may assign a status. Pure; a method card cannot reach it."""
    if test is None or observation is None:
        return "unverified"
    if observation.status == "stale":
        return "stale"
    if observation.status != "available" or observation.value is None:
        return "unverified"
    if observation.unit != test.unit:
        return "unverified"
    value, limit = observation.value, test.threshold
    held = {
        "gt": value > limit,
        "ge": value >= limit,
        "lt": value < limit,
        "le": value <= limit,
    }[test.comparator]
    return "supported_by_evidence" if held else "contradicted"


class ResearchHypothesis(BaseModel):
    """A checkable research view. Evidence, model inference and user assumption
    are separate fields; none of them can authorize a tool, rank a candidate
    or become a confirmed comparison parameter."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,11}:h[0-9]$")
    origin: Literal["user_view", "method_question"]
    claim: str = Field(min_length=1, max_length=300)
    claim_basis: Literal["user_assumption", "model_inference"]
    subject: str
    scope: Literal["company"] = "company"
    as_of: AwareDatetime
    sources: list[HypothesisSource] = Field(max_length=6)
    evidence_observation_ids: list[str] = Field(default_factory=list, max_length=4)
    inference: list[str] = Field(default_factory=list, max_length=4)
    test: HypothesisTest | None = None
    counter_arguments: list[str] = Field(min_length=1, max_length=4)
    invalidation_conditions: list[InvalidationCondition] = Field(min_length=1, max_length=4)
    status: HypothesisStatus
    missing: list[HypothesisMissing] = Field(default_factory=list, max_length=8)
    can_authorize_tools: Literal[False] = False
    comparison_input: Literal["user_entered_price_change_only"] = "user_entered_price_change_only"

    @model_validator(mode="after")
    def separated(self) -> Self:
        expected = "user_assumption" if self.origin == "user_view" else "model_inference"
        if self.claim_basis != expected:
            raise ValueError("Hypothesis claim basis does not match its origin")
        if self.test is not None and self.test.observation_id not in self.evidence_observation_ids:
            raise ValueError("A hypothesis test must reference linked research evidence")
        if self.test is not None and self.origin != "user_view":
            raise ValueError("Only a user's own stated threshold can be tested")
        if self.status in ("supported_by_evidence", "contradicted") and self.test is None:
            raise ValueError("A decided status needs an observable test")
        return self


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
    hypotheses: list[ResearchHypothesis] = Field(default_factory=list, max_length=4)

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
        method_ids = {method.id for method in self.methods}
        if any(question.method_id not in method_ids for question in self.questions):
            raise ValueError("Research question has an unavailable method")
        by_id = {row.id: row for row in self.observations}
        for hypothesis in self.hypotheses:
            if hypothesis.subject != self.ticker or not hypothesis.id.startswith(f"{self.ticker}:"):
                raise ValueError("Research hypothesis scope mismatch")
            # Evidence is research observations only: a method id, lead URL or
            # free text can never be cited as evidence for a hypothesis.
            if any(id not in by_id for id in hypothesis.evidence_observation_ids):
                raise ValueError("Research hypothesis cites unknown evidence")
            observation = by_id.get(hypothesis.test.observation_id) if hypothesis.test else None
            if hypothesis.test is not None and observation is not None:
                if observation.unit != hypothesis.test.unit:
                    raise ValueError("Research hypothesis test unit mismatch")
            # Status is recomputed, never trusted from the producer.
            if hypothesis.status != evaluate_test(hypothesis.test, observation) and not (
                hypothesis.test is None and hypothesis.status == "stale"
            ):
                raise ValueError("Research hypothesis status is not supported by its evidence")
        if len({h.id for h in self.hypotheses}) != len(self.hypotheses):
            raise ValueError("Duplicate research hypothesis")
        return self
