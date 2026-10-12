"""Explicit scenario prices and whole-account hypothetical outcomes.

v1 (``funding-common-expiry-v1``) records remain readable unchanged; every field
added for v2 (``funding-account-scenarios-v2``) has a default so a saved v1
record parses with its original meaning. See docs/copilot-account-scenarios-math.md.
"""

from datetime import date
from typing import Annotated, Literal, Self
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

Price = Annotated[float, Field(strict=True, allow_inf_nan=False)]


def _valid_price_map(prices: dict[str, float]) -> None:
    if any(price < 0 or price > 1000000 for price in prices.values()):
        raise ValueError("Scenario prices must be nonnegative and at most 1,000,000 USD")


class ExpiryPriceScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=80)
    prices: dict[str, Price] = Field(min_length=1, max_length=120)
    # Explicit underlying prices on the expiry date of existing legs that expire
    # BEFORE the scenario horizon. Missing ⇒ that leg is not computable.
    settlement_prices: dict[date, dict[str, Price]] = Field(default_factory=dict, max_length=12)

    @model_validator(mode="after")
    def valid_prices(self) -> Self:
        _valid_price_map(self.prices)
        for row in self.settlement_prices.values():
            if not row or len(row) > 120:
                raise ValueError("Settlement price rows need 1-120 underlyings")
            _valid_price_map(row)
        return self


Objective = Literal["preserve_terminal_equity", "minimize_funding_gap", "minimize_conditional_debt"]


class FundingRiskAssumptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenarios: list[ExpiryPriceScenario] = Field(min_length=1, max_length=3)
    annual_borrowing_rate: FiniteFloat | None = Field(default=None, strict=True, ge=0, le=1)
    # Residual (still-open at the horizon) leg valuation inputs. Never defaulted.
    residual_risk_free_rate: FiniteFloat | None = Field(default=None, strict=True, ge=0, le=0.2)
    residual_iv_overrides: dict[
        Annotated[str, Field(pattern=r"^[A-Z]{1,6}\d{6}[CP]\d{8}$")],
        Annotated[float, Field(strict=True, gt=0, le=5, allow_inf_nan=False)],
    ] = Field(default_factory=dict, max_length=20)
    residual_assumptions_confirmed: StrictBool = False
    objective: Objective | None = None
    objective_confirmed: StrictBool = False
    broker_rules_provider: Literal["unknown"] = "unknown"

    @model_validator(mode="after")
    def unique_labels(self) -> Self:
        if len({row.label for row in self.scenarios}) != len(self.scenarios):
            raise ValueError("Scenario labels must be unique")
        if self.residual_iv_overrides and not self.residual_assumptions_confirmed:
            raise ValueError("Confirm user-supplied residual volatility assumptions")
        if self.objective_confirmed and self.objective is None:
            raise ValueError("A confirmed objective must be named")
        return self


class NotComputable(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: Literal[
        "settlement_price_missing",
        "residual_iv_missing",
        "residual_rate_missing",
        "interest_rate_unknown",
        "broker_collateral_unknown",
        "nonpositive_equity",
    ]
    contract: str | None = None
    message: str


class ResidualValuation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract: str
    expiry: date
    contracts_signed: int
    tau_years: FiniteFloat
    underlying_price: FiniteFloat
    iv: FiniteFloat | None
    iv_source: Literal["captured_quote_implied_vol", "user_assumption", "missing"]
    rate: FiniteFloat | None
    rate_source: Literal["user_assumption", "missing"]
    value_per_share: FiniteFloat | None
    position_value: FiniteFloat | None


class SettlementEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract: str
    expiry: date
    underlying_price: FiniteFloat
    action: Literal["assigned", "exercised", "expired"]
    shares_delta: FiniteFloat
    cash_delta: FiniteFloat


class CoverageRelation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract: str
    underlying: str
    option_type: Literal["call", "put"]
    side: Literal["long", "short"]
    expiry: date
    strike: FiniteFloat
    contracts: int
    coverage: Literal[
        "stock",
        "long_call_spread",
        "uncovered",
        "long_put_spread",
        "cash_secured",
        "protective",
        "unpaired_no_stock",
        "long_call",
    ]
    covered_by: str | None = None
    max_loss_excl_premium: FiniteFloat | None
    collateral: Literal["shares", "long_option", "cash", "broker_rule_unknown", "none"]


class CoverageChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract: str
    before: str
    after: str
    reason: str


class BrokerRequirementOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requirement: Literal[
        "buying_power_impact", "maintenance_requirement", "uncovered_call_collateral"
    ]
    status: Literal["unknown"]
    value: None = None
    reason: str


class BrokerRulesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider_id: Literal["unknown"]
    rule_version: str
    source: str


class OptionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract: str
    mark: FiniteFloat
    iv: FiniteFloat | None
    spot: FiniteFloat | None
    basis: Literal["captured_two_sided_quote_midpoint"] = "captured_two_sided_quote_midpoint"


class MarketSnapshotOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    snapshot_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    captured_at: AwareDatetime
    price_as_of: date
    prices: dict[str, FiniteFloat]
    options: list[OptionInput]
    quote_time_note: str


class AccountAlternative(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["no_action", "sale_keep_cash_and_put", "sale_repay_margin_and_put"]
    snapshot_id: str
    coverage_at_capture: list[CoverageRelation]
    coverage_changes: list[CoverageChange]
    unbounded_loss: bool
    buying_power: BrokerRequirementOut


class RankingOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal[
        "not_requested",
        "objective_not_confirmed",
        "not_computable",
        "no_dominant_alternative",
        "preferred",
    ]
    objective: Objective | None = None
    preferred_kind: (
        Literal["no_action", "sale_keep_cash_and_put", "sale_repay_margin_and_put"] | None
    ) = None
    reasons: list[str]


class ExpiryAccountOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["no_action", "sale_keep_cash_and_put", "sale_repay_margin_and_put"]
    # Optional in v2: an unknown settlement price makes positions/cash unknown.
    positions: dict[str, FiniteFloat] | None
    position_values: dict[str, FiniteFloat] | None
    stock_assets: FiniteFloat | None
    initial_net_equity: FiniteFloat
    cash_before_interest: FiniteFloat | None
    cash_after_interest: FiniteFloat | None
    principal_debt: FiniteFloat
    interest_cost: FiniteFloat | None
    net_equity_before_interest: FiniteFloat | None
    net_equity_after_interest: FiniteFloat | None
    total_pnl_before_interest: FiniteFloat | None
    total_pnl: FiniteFloat | None
    incremental_pnl_vs_no_action: FiniteFloat | None
    assignment_shares: dict[str, FiniteFloat] | None
    assignment_cash_paid: FiniteFloat | None
    funding_gap_before_interest: FiniteFloat | None
    funding_gap: FiniteFloat | None
    conditional_debt_if_gap_financed: FiniteFloat | None
    largest_position_weight: FiniteFloat | None
    gross_leverage_if_gap_financed: FiniteFloat | None
    # v2 additions (defaults keep v1 records valid).
    snapshot_id: str | None = None
    short_stock_value: FiniteFloat | None = None
    residual_option_value: FiniteFloat | None = None
    residual_valuations: list[ResidualValuation] = Field(default_factory=list)
    settlement_events: list[SettlementEvent] = Field(default_factory=list)
    min_cash_through_horizon: FiniteFloat | None = None
    sold_stock_opportunity_cost: FiniteFloat | None = None
    fees_total: FiniteFloat | None = None
    open_leg_coverage: list[CoverageRelation] = Field(default_factory=list)
    not_computable: list[NotComputable] = Field(default_factory=list)


class ExpiryAccountScenario(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    prices: dict[str, FiniteFloat]
    outcomes: list[ExpiryAccountOutcome] = Field(min_length=3, max_length=3)


class FundingRiskResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    methodology_version: Literal["funding-common-expiry-v1", "funding-account-scenarios-v2"] = (
        "funding-account-scenarios-v2"
    )
    portfolio_id: UUID
    source_result_id: UUID
    captured_at: AwareDatetime
    assumptions: FundingRiskAssumptions
    days_of_interest: int = Field(ge=0)
    scenarios: list[ExpiryAccountScenario]
    preferred_alternative: None = None
    limitations: list[str]
    valuation_date: date | None = None
    market_snapshot: MarketSnapshotOut | None = None
    alternatives: list[AccountAlternative] = Field(default_factory=list, max_length=3)
    broker_rules: BrokerRulesOut | None = None
    ranking: RankingOut | None = None
