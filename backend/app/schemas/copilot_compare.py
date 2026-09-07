"""Explicit, read-only stock/ETF reduction assumptions and paired results."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat, StrictBool


class CompareChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_portfolio_id: UUID
    ticker: str = Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,11}$")
    amount: FiniteFloat = Field(gt=0, le=100_000_000, strict=True)
    proceeds: Literal["cash", "repay_margin"]


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
