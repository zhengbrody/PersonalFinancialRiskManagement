"""Explicit hypothetical standard USD equity-put assumptions."""

from datetime import date
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


class CashSecuredPutRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_portfolio_id: UUID
    underlying: str = Field(pattern=r"^[A-Z]{1,6}$")
    expiry: date
    strike: FiniteFloat = Field(strict=True, gt=0, lt=100000, multiple_of=0.01)
    premium_per_share: FiniteFloat = Field(strict=True, gt=0, multiple_of=0.01)
    assumed_spot: FiniteFloat = Field(strict=True, gt=0, lt=1000000)
    contracts: int = Field(ge=1, le=100, strict=True)
    fees_total: FiniteFloat = Field(strict=True, ge=0, le=100000, multiple_of=0.01)
    other_reserved_cash: FiniteFloat = Field(strict=True, ge=0, le=100000000, multiple_of=0.01)
    cash_buffer: FiniteFloat = Field(strict=True, ge=0, le=100000000, multiple_of=0.01)
    confirmed: StrictBool
    # The app cannot infer settled cash / open-order reservations from holdings.
    gross_settled_usd_cash_confirmed: StrictBool
    standard_contract_confirmed: StrictBool

    @model_validator(mode="after")
    def valid_economics(self) -> Self:
        if self.premium_per_share >= self.strike:
            raise ValueError("Premium must be less than the strike")
        if self.fees_total >= self.premium_per_share * self.contracts * 100:
            raise ValueError("This first model requires positive net premium after estimated fees")
        return self


class PutExpiryScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    underlying_price: FiniteFloat
    assumes_assignment: bool
    no_action_incremental_pnl: Literal[0] = 0
    candidate_incremental_pnl: FiniteFloat
    shares_acquired: int
    cash_after_settlement: FiniteFloat
    free_cash_after_reserves: FiniteFloat
    funding_gap_after_reserves: FiniteFloat


class CashSecuredPutResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    result_id: UUID
    portfolio_id: UUID
    computed_at: AwareDatetime
    snapshot_digest: str
    assumptions: CashSecuredPutRequest
    methodology_version: Literal["cash-secured-put-v1"] = "cash-secured-put-v1"
    input_basis: Literal["user_hypothesis_not_live_quote"] = "user_hypothesis_not_live_quote"
    recorded_cash: FiniteFloat
    existing_put_reserve: FiniteFloat
    no_action_free_cash: FiniteFloat
    assignment_notional: FiniteFloat
    gross_premium: FiniteFloat
    net_premium: FiniteFloat
    initial_incremental_equity: FiniteFloat
    pre_trade_funding_gap: FiniteFloat
    funding_status: Literal["covered_under_assumptions", "insufficient_cash"]
    best_expiry_pnl: FiniteFloat
    maximum_loss: FiniteFloat
    breakeven: FiniteFloat
    scenarios: list[PutExpiryScenario]
    limitations: list[str]
    source_url: Literal[
        "https://www.optionseducation.org/strategies/all-strategies/cash-secured-put"
    ] = "https://www.optionseducation.org/strategies/all-strategies/cash-secured-put"
    save_available: Literal[False] = False
