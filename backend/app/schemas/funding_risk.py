"""Explicit common-expiry prices and whole-account hypothetical outcomes."""

from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    model_validator,
)


class ExpiryPriceScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=80)
    prices: dict[str, Annotated[float, Field(strict=True, allow_inf_nan=False)]] = Field(
        min_length=1, max_length=120
    )

    @model_validator(mode="after")
    def valid_prices(self) -> Self:
        if any(price < 0 or price > 1000000 for price in self.prices.values()):
            raise ValueError("Scenario prices must be nonnegative and at most 1,000,000 USD")
        return self


class FundingRiskAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenarios: list[ExpiryPriceScenario] = Field(min_length=1, max_length=3)
    annual_borrowing_rate: FiniteFloat | None = Field(default=None, strict=True, ge=0, le=1)

    @model_validator(mode="after")
    def unique_labels(self) -> Self:
        if len({row.label for row in self.scenarios}) != len(self.scenarios):
            raise ValueError("Scenario labels must be unique")
        return self


class ExpiryAccountOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["no_action", "sale_keep_cash_and_put", "sale_repay_margin_and_put"]
    positions: dict[str, FiniteFloat]
    position_values: dict[str, FiniteFloat]
    stock_assets: FiniteFloat
    initial_net_equity: FiniteFloat
    cash_before_interest: FiniteFloat
    cash_after_interest: FiniteFloat | None
    principal_debt: FiniteFloat
    interest_cost: FiniteFloat | None
    net_equity_before_interest: FiniteFloat
    net_equity_after_interest: FiniteFloat | None
    total_pnl_before_interest: FiniteFloat
    total_pnl: FiniteFloat | None
    incremental_pnl_vs_no_action: FiniteFloat | None
    assignment_shares: dict[str, FiniteFloat]
    assignment_cash_paid: FiniteFloat
    funding_gap_before_interest: FiniteFloat
    funding_gap: FiniteFloat | None
    conditional_debt_if_gap_financed: FiniteFloat | None
    largest_position_weight: FiniteFloat | None
    gross_leverage_if_gap_financed: FiniteFloat | None


class ExpiryAccountScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    prices: dict[str, FiniteFloat]
    outcomes: list[ExpiryAccountOutcome] = Field(min_length=3, max_length=3)


class FundingRiskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    methodology_version: Literal["funding-common-expiry-v1"] = "funding-common-expiry-v1"
    portfolio_id: UUID
    source_result_id: UUID
    captured_at: AwareDatetime
    assumptions: FundingRiskAssumptions
    days_of_interest: int = Field(ge=0)
    scenarios: list[ExpiryAccountScenario]
    preferred_alternative: None = None
    limitations: list[str]
