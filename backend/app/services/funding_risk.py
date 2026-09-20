"""Whole-account expiry ledger with explicit prices, assignments and debt.

Only standard short puts expiring together are admitted. No broker financing is
inferred. Interest is simple actual/365 on pre-expiry principal, not on a
hypothetical deficit loan drawn at expiry. All branches use one initial equity.
"""

from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from ..core.responses import APIError
from ..schemas.funding_risk import ExpiryAccountOutcome, ExpiryAccountScenario, FundingRiskResult
from . import comparison_options, comparison_replay
from .options_analytics import _intrinsic_value


def money(value):
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def calculate(snapshot, funding_assumptions, risk_assumptions, *, now, funding_result):
    if not funding_assumptions.confirmed:
        raise APIError(
            422,
            "risk_scenarios_unconfirmed",
            "Confirm the common-expiry price and financing assumptions.",
        )
    comparison_replay.replay(snapshot)
    if (
        funding_result.source_result_id != snapshot.result.result_id
        or funding_result.portfolio_id != snapshot.account.portfolio_id
        or funding_result.assumptions != funding_assumptions
    ):
        raise APIError(
            409,
            "risk_source_mismatch",
            "The funding ledger must match the captured source and assumptions.",
        )
    funding = funding_result
    context = snapshot.account.context()
    specs = comparison_options.option_specs(context.holdings, now=now)
    if any(
        spec.option_type != "put"
        or spec.quantity >= 0
        or spec.contract_multiplier != 100
        or abs(spec.quantity) != int(abs(spec.quantity))
        for spec in specs
    ):
        raise APIError(
            422,
            "unsupported_expiry_legs",
            "Only whole standard short Put contracts are supported in this expiry ledger.",
        )
    if [row.kind for row in funding.alternatives] != [
        "no_action",
        "sale_keep_cash_and_put",
        "sale_repay_margin_and_put",
    ]:
        raise APIError(
            409,
            "risk_source_mismatch",
            "Funding alternatives must include the original ordered baseline.",
        )
    expiry = funding_assumptions.put.expiry
    if any(spec.expiry != expiry.isoformat() for spec in specs):
        raise APIError(
            422,
            "mixed_expiry_unsupported",
            "All existing puts must share the new Put expiry for a whole-account expiry comparison.",
        )
    quantities = {
        ticker: Decimal(str(holding["shares"]))
        for ticker, holding in context.holdings.items()
        if str(holding.get("asset_type") or "public_security").lower() != "option"
    }
    required = (
        set(quantities) | {spec.underlying for spec in specs} | {funding_assumptions.put.underlying}
    )
    if any(set(scenario.prices) != required for scenario in risk_assumptions.scenarios):
        raise APIError(
            422,
            "incomplete_expiry_prices",
            "Provide exactly one expiry price for every held stock and existing/new option underlying; no price is inferred.",
        )
    frame = snapshot.prices.frame()
    initial_assets = sum(
        (qty * Decimal(str(frame.iloc[-1][ticker])) for ticker, qty in quantities.items()),
        Decimal(0),
    )
    existing_options = sum(
        (
            Decimal(str(row["mark"]))
            * Decimal(str(row["quantity"]))
            * Decimal(str(row["contract_multiplier"]))
            for row in snapshot.option_results
        ),
        Decimal(0),
    )
    initial_equity = (
        initial_assets
        + Decimal(str(context.cash_balance))
        + existing_options
        - Decimal(str(context.margin_loan))
    )
    days = (expiry - snapshot.captured_at.date()).days
    if days <= 0:
        raise APIError(
            422, "invalid_expiry_horizon", "Expiry must follow the captured account date."
        )
    rate = risk_assumptions.annual_borrowing_rate
    reserve = Decimal(str(funding_assumptions.put.other_reserved_cash)) + Decimal(
        str(funding_assumptions.put.cash_buffer)
    )
    sold_ticker = snapshot.result.assumptions.ticker
    sold = Decimal(str(snapshot.result.assumptions.amount)) / Decimal(
        str(frame.iloc[-1][sold_ticker])
    )
    output = []
    for scenario in risk_assumptions.scenarios:
        outcomes = []
        for alternative in funding.alternatives:
            no_action = alternative.kind == "no_action"
            shares = dict(quantities)
            if not no_action:
                shares[sold_ticker] -= sold
            cash = Decimal(str(alternative.cash_before_put))
            debt = Decimal(str(alternative.margin_remaining))
            assigned = defaultdict(Decimal)
            paid = Decimal(0)
            legs = [
                (spec.underlying, Decimal(str(spec.strike)), Decimal(str(abs(spec.quantity))) * 100)
                for spec in specs
            ]
            if not no_action:
                put = funding_assumptions.put
                cash += Decimal(str(put.premium_per_share)) * put.contracts * 100 - Decimal(
                    str(put.fees_total)
                )
                legs.append(
                    (put.underlying, Decimal(str(put.strike)), Decimal(put.contracts * 100))
                )
            for underlying, strike, count in legs:
                price = scenario.prices[underlying]
                if _intrinsic_value("put", float(price), float(strike)) > 0:
                    assigned[underlying] += count
                    shares[underlying] = shares.get(underlying, Decimal(0)) + count
                    cash -= strike * count
                    paid += strike * count
            values = {
                ticker: qty * Decimal(str(scenario.prices[ticker]))
                for ticker, qty in shares.items()
            }
            assets = sum(values.values(), Decimal(0))
            before = assets + cash - debt
            interest = (
                Decimal(0)
                if debt == 0
                else (None if rate is None else debt * Decimal(str(rate)) * days / 365)
            )
            after_cash = None if interest is None else cash - interest
            equity = None if interest is None else before - interest
            gap = None if after_cash is None else max(Decimal(0), reserve - after_cash)
            financed_debt = None if gap is None else debt + gap
            # Conditional borrowing adds equal cash and debt; it cannot improve equity.
            leverage = (
                None if equity is None or equity <= 0 else (assets + after_cash + gap) / equity
            )
            concentration = (
                None
                if equity is None or equity <= 0 or assets <= 0
                else max(values.values(), default=Decimal(0)) / assets
            )
            outcomes.append(
                ExpiryAccountOutcome(
                    kind=alternative.kind,
                    positions={ticker: float(qty) for ticker, qty in shares.items()},
                    position_values={ticker: money(value) for ticker, value in values.items()},
                    stock_assets=money(assets),
                    initial_net_equity=money(initial_equity),
                    cash_before_interest=money(cash),
                    cash_after_interest=None if after_cash is None else money(after_cash),
                    principal_debt=money(debt),
                    interest_cost=None if interest is None else money(interest),
                    net_equity_before_interest=money(before),
                    net_equity_after_interest=None if equity is None else money(equity),
                    total_pnl_before_interest=money(before - initial_equity),
                    total_pnl=None if equity is None else money(equity - initial_equity),
                    incremental_pnl_vs_no_action=None,
                    assignment_shares={ticker: float(qty) for ticker, qty in assigned.items()},
                    assignment_cash_paid=money(paid),
                    funding_gap_before_interest=money(max(Decimal(0), reserve - cash)),
                    funding_gap=None if gap is None else money(gap),
                    conditional_debt_if_gap_financed=(
                        None if financed_debt is None else money(financed_debt)
                    ),
                    largest_position_weight=None if concentration is None else float(concentration),
                    gross_leverage_if_gap_financed=None if leverage is None else float(leverage),
                )
            )
        baseline = outcomes[0].total_pnl
        for outcome in outcomes:
            if baseline is not None and outcome.total_pnl is not None:
                outcome.incremental_pnl_vs_no_action = money(
                    Decimal(str(outcome.total_pnl)) - Decimal(str(baseline))
                )
        output.append(
            ExpiryAccountScenario(label=scenario.label, prices=scenario.prices, outcomes=outcomes)
        )
    return FundingRiskResult(
        portfolio_id=snapshot.account.portfolio_id,
        source_result_id=snapshot.result.result_id,
        captured_at=snapshot.captured_at,
        assumptions=risk_assumptions,
        days_of_interest=days,
        scenarios=output,
        limitations=[
            "All assets are valued at the same explicitly assumed expiry prices. These scenarios have no probabilities and are not forecasts.",
            "Only standard USD long stocks/ETFs and physically settled short Puts sharing one expiry are supported. No protection leg is removed.",
            "Every below-strike Put, including existing positions in the no-action baseline, is assumed assigned. At-the-money and out-of-the-money Puts expire without exercise; early or discretionary assignment is not modeled.",
            "Existing Put collateral is released or paid at the common expiry. Other cash holds and the chosen cash buffer remain reserved in every alternative.",
            "Total P&L uses the original captured equity including existing option marks. New premium is not instant profit; full terminal obligations and both fee types are included.",
            "Interest is simple actual/365 on each branch's initial debt from capture date to expiry. Unknown rates leave debt-bearing net equity, net P&L and exact funding gaps unknown. Zero-debt branches incur no interest.",
            "Conditional borrowing covers cash and reserve deficits at expiry only; it adds matching cash and debt, has no retroactive interest, and does not imply broker approval or available credit.",
            "Largest-position weight uses total stock value after assignment, excluding cash. Leverage assumes deficit financing; ratios are unavailable when net equity is unknown or nonpositive.",
            "Taxes, dividends, changes in reserved cash, intraperiod price paths, margin calls and execution/settlement uncertainty are excluded. Financing feasibility remains unverified and no alternative is ranked.",
        ],
    )
