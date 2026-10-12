"""Cross-device saved-plan history and the versioned review-metric contract.

See docs/plan-history-review-2026-10.md. Every figure is deterministic; a
component that cannot be computed is ``None`` with a stated reason.
"""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat

from .copilot_compare import SavedComparison
from .funding_plan import SavedFundingPlan
from .put_plan import SavedPutPlan

PlanKind = Literal["comparison", "cash_secured_put", "funding_scenarios"]


class SavedPlanItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: PlanKind
    plan_id: UUID
    portfolio_id: UUID
    confirmed_at: AwareDatetime
    captured_at: AwareDatetime
    methodology_version: str
    summary: str
    evidence_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    signature_verified: Literal[True] = True


class SavedPlanPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plans: list[SavedPlanItem]
    next_cursor: str | None = None
    unverified_records: int = 0
    order: Literal["stable_plan_id"] = "stable_plan_id"


class SavedPlanDetail(BaseModel):
    """Exactly one of comparison / put / funding is set, matching ``item.kind``."""

    model_config = ConfigDict(extra="forbid")
    item: SavedPlanItem
    comparison: SavedComparison | None = None
    put: SavedPutPlan | None = None
    funding: SavedFundingPlan | None = None


class MetricReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_portfolio_id: UUID


class DataWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    price_as_of: str
    history_start: str
    observations: int = Field(ge=0)


class ReviewMetric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric_id: Literal[
        "net_equity",
        "leverage",
        "largest_position_weight",
        "annual_volatility",
        "var_1d_95_usd",
        "cvar_1d_95_usd",
    ]
    label: str
    unit: Literal["usd", "ratio", "fraction", "fraction_per_year"]
    horizon: str
    original: FiniteFloat | None
    original_inputs_current_method: FiniteFloat | None
    original_holdings_current_prices: FiniteFloat | None
    current: FiniteFloat | None
    method_change: FiniteFloat | None
    market_change: FiniteFloat | None
    account_change: FiniteFloat | None
    total_change: FiniteFloat | None
    not_computable_reason: str | None = None


class MethodComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract_version: Literal["plan-review-metrics-v1"] = "plan-review-metrics-v1"
    original_method_version: str
    current_method_version: str
    same_method: bool
    reproduced: bool | None


class PlanMetricReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: UUID
    portfolio_id: UUID
    kind: PlanKind
    reviewed_at: AwareDatetime
    status: Literal["comparable", "method_changed", "not_computable"]
    status_reason: str | None = None
    method: MethodComparison | None = None
    original_window: DataWindow | None = None
    market_window: DataWindow | None = None
    account_window: DataWindow | None = None
    account_changes: list[str] = Field(default_factory=list)
    metrics: list[ReviewMetric] = Field(default_factory=list)
    decomposition: Literal["sequential_market_then_account"] = "sequential_market_then_account"
    notes: list[str] = Field(default_factory=list)
    realised_return_attribution: Literal[False] = False
    holdings_changed_by_review: Literal[False] = False
    live_quote_checked: Literal[False] = False
