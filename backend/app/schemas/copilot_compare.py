"""Explicit, read-only stock/ETF reduction assumptions and paired results."""

from typing import Literal
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


class HypothesisAssumption(BaseModel):
    """A research hypothesis carried in as the USER's price assumption.

    Only an id, the subject and a number the user typed travel here; the claim
    text never does. ``user_confirmed`` must be literally true: the typed confirm
    step, not the research card, turns it into a calculation input. It adds one
    deterministic row to this comparison and authorizes nothing else."""

    model_config = ConfigDict(extra="forbid")

    hypothesis_id: str = Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,11}:h[0-9]$")
    subject: str = Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,11}$")
    price_change_pct: FiniteFloat = Field(ge=-95, le=100, strict=True)
    basis: Literal["user_assumption"] = "user_assumption"
    user_confirmed: StrictBool

    @model_validator(mode="after")
    def scoped(self) -> "HypothesisAssumption":
        if self.user_confirmed is not True:
            raise ValueError("The price-change assumption must be explicitly confirmed")
        if self.price_change_pct == 0:
            raise ValueError("A price-change assumption must be non-zero")
        if not self.hypothesis_id.startswith(f"{self.subject}:"):
            raise ValueError("Hypothesis id does not match its subject")
        return self


class CompareChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_portfolio_id: UUID
    ticker: str = Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,11}$")
    amount: FiniteFloat = Field(gt=0, le=100_000_000, strict=True)
    proceeds: Literal["cash", "repay_margin"]
    hypothesis: HypothesisAssumption | None = None


class HypothesisScenario(BaseModel):
    """Isolated subject price move at the captured close, both sides. Not a forecast."""

    model_config = ConfigDict(extra="forbid")
    hypothesis_id: str
    subject: str
    price_change_pct: FiniteFloat
    basis: Literal["user_assumption"] = "user_assumption"
    status: Literal["computed", "not_computable"]
    reason: Literal["subject_not_held", "subject_has_options"] | None = None
    subject_value_baseline: FiniteFloat | None = None
    subject_value_candidate: FiniteFloat | None = None
    baseline_pnl: FiniteFloat | None = None
    candidate_pnl: FiniteFloat | None = None
    baseline_equity: FiniteFloat | None = None
    candidate_equity: FiniteFloat | None = None


class ComparisonSide(BaseModel):
    gross_assets: FiniteFloat
    net_equity: FiniteFloat
    cash: FiniteFloat
    margin: FiniteFloat
    leverage: FiniteFloat
    largest_position_weight: FiniteFloat
    annual_volatility: FiniteFloat | None
    var_1d_95_usd: FiniteFloat | None
    cvar_1d_95_usd: FiniteFloat | None
    option_assets: FiniteFloat = 0
    option_liabilities: FiniteFloat = 0


class ComparisonReceipt(BaseModel):
    """Opaque server-authenticated snapshot, not a save/order credential."""

    model_config = ConfigDict(extra="forbid")
    record: str = Field(max_length=512000)
    signature: str = Field(pattern=r"^[a-f0-9]{64}$")
    save_available: bool = False


class PairedStress(BaseModel):
    label: str
    shocks: dict[str, FiniteFloat]
    iv_shift: FiniteFloat
    horizon_days: int = 0
    baseline_pnl: FiniteFloat
    candidate_pnl: FiniteFloat
    baseline_equity: FiniteFloat
    candidate_equity: FiniteFloat


class UnchangedOptionGroup(BaseModel):
    underlying: str
    expiry: str
    name: str
    leg_count: int
    mark_basis_max_loss: FiniteFloat | None
    mark_basis_max_gain: FiniteFloat | None


class ChangeComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_id: UUID
    portfolio_id: UUID
    computed_at: AwareDatetime
    snapshot_digest: str
    methodology_version: str
    assumptions: CompareChange
    price_as_of: str
    history_start: str
    observations: int
    sources: dict[str, str]
    baseline: ComparisonSide
    candidate: ComparisonSide
    limitations: list[str]
    risk_method: Literal["historical_equity", "mixed_instant_stress"] = "historical_equity"
    scenarios: list[PairedStress] = Field(default_factory=list)
    option_groups: list[UnchangedOptionGroup] = Field(default_factory=list)
    option_quote_basis: str | None = None
    hypothesis_scenario: HypothesisScenario | None = None
    replay_receipt: ComparisonReceipt | None = None


class ReplayComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_portfolio_id: UUID
    receipt: ComparisonReceipt


class ConfirmComparison(ReplayComparison):
    confirmed: StrictBool


class SavedComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: UUID
    portfolio_id: UUID
    result_id: UUID
    confirmed_at: AwareDatetime
    result: ChangeComparison
    notice: str = (
        "Saved as a draft risk plan with the original signed calculation. "
        "No holdings changed. This is a historical assumption, not an order or current recommendation."
    )


class ComparisonVerification(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result: ChangeComparison
    verified_at: AwareDatetime
    inputs_match_now: bool
    snapshot_age_seconds: int = Field(ge=0)
    recent_capture: bool
    notice: str = (
        "Historical calculation reproduced without fetching market data. Not a saved plan or permission to trade."
    )
