"""Bounded hypothetical sale, debt repayment and Put funding alternatives."""

from typing import Literal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat, StrictBool

from .copilot_compare import ComparisonReceipt
from .copilot_put import CashSecuredPutRequest, CashSecuredPutResult
from .funding_risk import FundingRiskAssumptions, FundingRiskResult


class FundingScenarioAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_portfolio_id: UUID
    source_result_id: UUID
    put: CashSecuredPutRequest
    protected_holdings: list[str] = Field(default_factory=list, max_length=100)
    sale_fees: FiniteFloat = Field(strict=True, ge=0, le=100000, multiple_of=0.01)
    confirmed: StrictBool
    risk: FundingRiskAssumptions | None = None


class FundingScenarioRequest(FundingScenarioAssumptions):
    receipt: ComparisonReceipt


class FundingExpiryFunding(BaseModel):
    model_config = ConfigDict(extra="forbid")
    underlying_price: FiniteFloat
    assignment_cash_shortfall: FiniteFloat
    hypothetical_debt_if_shortfall_financed: FiniteFloat
    interest_cost: None = None


class FundingAlternative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["no_action", "sale_keep_cash_and_put", "sale_repay_margin_and_put"]
    cash_before_put: FiniteFloat
    margin_remaining: FiniteFloat
    debt_repaid: FiniteFloat
    sale_proceeds_net: FiniteFloat
    shares_sold: FiniteFloat
    initial_incremental_equity: FiniteFloat
    assignment_cash_shortfall: FiniteFloat = 0
    hypothetical_debt_if_shortfall_financed: FiniteFloat | None = None
    status: Literal[
        "no_action", "covered_under_assumptions", "insufficient_cash", "financing_rules_required"
    ]
    put: CashSecuredPutResult | None = None
    pre_put_largest_position_weight: FiniteFloat
    pre_put_var_1d_95_usd: FiniteFloat | None
    expiry_funding: list[FundingExpiryFunding] = Field(default_factory=list, max_length=7)


class FundingScenarioResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result_id: UUID = Field(default_factory=uuid4)
    computed_at: AwareDatetime
    receipt: ComparisonReceipt | None = None
    methodology_version: Literal["funding-scenarios-v1"] = "funding-scenarios-v1"
    portfolio_id: UUID
    source_result_id: UUID
    snapshot_digest: str
    captured_at: AwareDatetime
    assumptions: FundingScenarioAssumptions
    sale_ticker: str
    sale_price: FiniteFloat
    alternatives: list[FundingAlternative] = Field(min_length=3, max_length=3)
    account_risk: FundingRiskResult | None = None
    broker_buying_power: None = None
    preferred_alternative: None = None
    limitations: list[str]
