"""Compose captured reduction and Put arithmetic without mutating an account.

The original comparison is authenticated and replayed by the API. Financing
balances remain explicit; a zero-debt copy is used ONLY for gross Put funding
arithmetic, never to claim margin eligibility or broker buying power.
"""

from copy import deepcopy
from dataclasses import asdict, replace
from decimal import Decimal

from ..core.responses import APIError
from ..schemas.funding_scenarios import (
    FundingAlternative,
    FundingExpiryFunding,
    FundingScenarioAssumptions,
    FundingScenarioResult,
)
from . import comparison_options, comparison_replay, copilot_put, copilot_scope


def calculate(snapshot, body, *, now):
    if not body.confirmed or not body.put.confirmed:
        raise APIError(422, "confirmation_required", "Confirm all hypothetical assumptions.")
    expected = body.expected_portfolio_id
    if expected != body.put.expected_portfolio_id or expected != snapshot.account.portfolio_id:
        raise APIError(409, "portfolio_changed", "Scenario inputs must belong to one portfolio.")
    if body.source_result_id != snapshot.result.result_id:
        raise APIError(409, "untrusted_comparison", "The source calculation does not match.")
    age = (now - snapshot.captured_at).total_seconds()
    if age < 0 or age > 900:
        raise APIError(
            409, "comparison_expired", "Capture a new comparison before composing a scenario."
        )
    comparison_replay.replay(snapshot)
    change = snapshot.result.assumptions
    if change.ticker in {ticker.strip().upper() for ticker in body.protected_holdings}:
        raise APIError(422, "protected_holding", "The proposed reduction is protected.")
    net = Decimal(str(change.amount)) - Decimal(str(body.sale_fees))
    if net <= 0:
        raise APIError(422, "invalid_sale_fees", "Sale fees must be less than gross proceeds.")
    context = snapshot.account.context()
    if change.ticker in {
        spec.underlying for spec in comparison_options.option_specs(context.holdings, now=now)
    }:
        raise APIError(
            422,
            "protected_option_underlying",
            "Do not sell an existing option underlying in this funding model.",
        )
    price = Decimal(str(snapshot.prices.frame().iloc[-1][change.ticker]))
    sold = Decimal(str(change.amount)) / price
    rows = [
        FundingAlternative(
            kind="no_action",
            cash_before_put=context.cash_balance,
            margin_remaining=context.margin_loan,
            debt_repaid=0,
            sale_proceeds_net=0,
            shares_sold=0,
            initial_incremental_equity=0,
            status="no_action",
            pre_put_largest_position_weight=snapshot.result.baseline.largest_position_weight,
            pre_put_var_1d_95_usd=snapshot.result.baseline.var_1d_95_usd,
        )
    ]
    for repay in (False, True):
        adjusted = deepcopy(context)
        adjusted.holdings[change.ticker]["shares"] = float(
            Decimal(str(adjusted.holdings[change.ticker]["shares"])) - sold
        )
        debt = Decimal(str(context.margin_loan))
        repayment = min(net, debt) if repay else Decimal(0)
        remaining_debt = debt - repayment
        adjusted = replace(
            adjusted,
            cash_balance=float(Decimal(str(context.cash_balance)) + net - repayment),
            margin_loan=0.0,
        )
        arithmetic_digest = copilot_scope.context_digest(asdict(adjusted))
        put = copilot_put.calculate(adjusted, body.put, arithmetic_digest, now=now)
        rows.append(
            FundingAlternative(
                kind="sale_repay_margin_and_put" if repay else "sale_keep_cash_and_put",
                cash_before_put=adjusted.cash_balance,
                margin_remaining=float(remaining_debt),
                debt_repaid=float(repayment),
                sale_proceeds_net=float(net),
                shares_sold=float(sold),
                initial_incremental_equity=-body.sale_fees - body.put.fees_total,
                assignment_cash_shortfall=max(
                    row.funding_gap_after_reserves for row in put.scenarios
                ),
                hypothetical_debt_if_shortfall_financed=float(remaining_debt)
                + max(row.funding_gap_after_reserves for row in put.scenarios),
                status="financing_rules_required" if remaining_debt else put.funding_status,
                put=put,
                pre_put_largest_position_weight=snapshot.result.candidate.largest_position_weight,
                pre_put_var_1d_95_usd=snapshot.result.candidate.var_1d_95_usd,
                expiry_funding=[
                    FundingExpiryFunding(
                        underlying_price=row.underlying_price,
                        assignment_cash_shortfall=row.funding_gap_after_reserves,
                        hypothetical_debt_if_shortfall_financed=float(remaining_debt)
                        + row.funding_gap_after_reserves,
                    )
                    for row in put.scenarios
                ],
            )
        )
    result = FundingScenarioResult(
        computed_at=now,
        portfolio_id=expected,
        source_result_id=body.source_result_id,
        snapshot_digest=snapshot.result.snapshot_digest,
        captured_at=snapshot.captured_at,
        assumptions=FundingScenarioAssumptions.model_validate(body.model_dump(exclude={"receipt"})),
        sale_ticker=change.ticker,
        sale_price=float(price),
        alternatives=rows,
        limitations=[
            "All alternatives use the same authenticated account and captured closing sale price. No trade or account update occurred.",
            "Sale proceeds are hypothetical settled USD cash; actual execution, settlement timing, taxes and slippage are not verified.",
            "Put rows reuse gross cash collateral arithmetic. Remaining debt is shown separately and is not erased: financing rules are required before treating such a row as eligible.",
            "Pre-Put concentration and dollar VaR reuse the signed reduction at its captured valuation; they exclude the new Put and sale fees. Whole-account expiry outcomes, when requested, are reported separately; no risk ranking is inferred.",
            "Standalone Put expiry debt figures exclude interest. Optional whole-account scenarios apply only an explicitly supplied borrowing APR over the captured-date-to-expiry horizon. They are conditional funding arithmetic, not financing approval. Instantaneous source-comparison stress and terminal Put payoff are not added across different horizons.",
            "Existing short-Put reserves remain full gross strike collateral, including same-underlying contracts; no netting or hedge benefit is assumed.",
            "No broker buying power, maintenance requirement or conditional ranking is provided without verified broker rules. User-supplied interest assumptions are not verified broker terms.",
            "The no-action row makes no sale and writes no new Put. Standalone Put payoff rows exclude sold-stock opportunity cost and existing portfolio P&L. Optional whole-account expiry outcomes include both under explicit terminal prices.",
            "Existing option obligations are validated by the Put engine; unsupported combinations stop calculation. Protection underlyings cannot be sold.",
            "Saving a signed combined scenario records hypothetical assumptions only; it does not settle sale proceeds, repay debt, approve financing or execute a Put.",
        ],
    )

    if body.risk is not None:
        from . import funding_risk

        result.account_risk = funding_risk.calculate(
            snapshot, result.assumptions, body.risk, now=now, funding_result=result
        )
    return result
