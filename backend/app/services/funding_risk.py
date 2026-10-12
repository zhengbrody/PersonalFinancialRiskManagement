"""Whole-account scenario ledger at one valuation date (v2).

Specification: docs/copilot-account-scenarios-math.md. Every alternative —
including no action — is evaluated from ONE captured account and ONE captured
market snapshot; each outcome carries that snapshot's id. Legs expiring at or
before the horizon settle physically at explicit prices; legs still open are
valued by Black-Scholes at the horizon with a captured-quote or explicitly
confirmed IV and an explicit rate, or are reported NOT COMPUTABLE — never zero,
never their expiry payoff. No broker rule is assumed (only the ``unknown``
provider exists), and no alternative is ranked without a confirmed objective
and complete, bounded metrics.
"""

import hashlib
import json
import math
from collections import defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from libs.mindmarket_core.black_scholes import bs_price

from ..core.responses import APIError
from ..schemas.funding_risk import (
    AccountAlternative,
    BrokerRequirementOut,
    BrokerRulesOut,
    CoverageChange,
    CoverageRelation,
    ExpiryAccountOutcome,
    ExpiryAccountScenario,
    FundingRiskResult,
    MarketSnapshotOut,
    NotComputable,
    OptionInput,
    RankingOut,
    ResidualValuation,
    SettlementEvent,
)
from . import broker_rules, comparison_options, comparison_replay, option_coverage
from .copilot_candidates import dominates_all

MULT = Decimal(100)
YEAR_BASIS = Decimal("365.25")  # the capture engine's IV-calibration basis
KINDS = ["no_action", "sale_keep_cash_and_put", "sale_repay_margin_and_put"]


def money(value):
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def residual_value_per_share(spot, strike, tau, rate, iv, option_type) -> Decimal:
    """Black-Scholes value at the horizon; S=0 uses the analytic limit."""
    spot, strike, tau, rate, iv = (float(v) for v in (spot, strike, tau, rate, iv))
    if spot == 0:
        if option_type == "call":
            return Decimal(0)
        return Decimal(repr(strike * math.exp(-rate * tau)))
    return Decimal(repr(float(bs_price(spot, strike, tau, rate, iv, option_type))))


def settle(leg, price):
    """Physical settlement at expiry; ITM long legs exercise, ITM short legs are
    assigned, ATM/OTM legs expire. Returns (action, shares_delta, cash_delta)."""
    count = Decimal(abs(leg["quantity"])) * MULT
    strike = leg["strike"]
    itm = price < strike if leg["option_type"] == "put" else price > strike
    if not itm:
        return "expired", Decimal(0), Decimal(0)
    receives_shares = (leg["option_type"] == "put") == (leg["quantity"] < 0)
    shares = count if receives_shares else -count
    return ("assigned" if leg["quantity"] < 0 else "exercised"), shares, -strike * shares


def _legs(specs, snapshot):
    rows = {
        (r["underlying"], r["expiry"], r["option_type"], Decimal(str(r["strike"]))): r
        for r in snapshot.option_results
    }
    legs = []
    for spec in specs:
        key = (spec.underlying, spec.expiry, spec.option_type, Decimal(str(spec.strike)))
        row = rows.get(key)
        if (
            row is None
            or Decimal(str(row["quantity"])) != Decimal(str(spec.quantity))
            or Decimal(str(spec.quantity)) != int(spec.quantity)
            or spec.contract_multiplier != 100
            or Decimal(str(row.get("contract_multiplier"))) != MULT
        ):
            raise APIError(
                409,
                "risk_source_mismatch",
                "Every option leg must match a captured quote row in the signed snapshot.",
            )
        legs.append(
            {
                "symbol": option_coverage.contract_symbol(
                    spec.underlying, spec.expiry, spec.option_type, spec.strike
                ),
                "underlying": spec.underlying,
                "option_type": spec.option_type,
                "quantity": int(spec.quantity),
                "strike": Decimal(str(spec.strike)),
                "expiry": spec.expiry,
                "mark": Decimal(str(row["mark"])),
                "iv": None if row.get("iv") is None else Decimal(str(row["iv"])),
                "spot": row.get("spot"),
            }
        )
    return legs


def _market_snapshot(snapshot, frame, tickers, legs) -> MarketSnapshotOut:
    prices = {t: float(frame.iloc[-1][t]) for t in sorted(tickers)}
    options = [
        OptionInput(
            contract=leg["symbol"],
            mark=float(leg["mark"]),
            iv=None if leg["iv"] is None else float(leg["iv"]),
            spot=None if leg["spot"] is None else float(leg["spot"]),
        )
        for leg in sorted(legs, key=lambda leg: leg["symbol"])
    ]
    canonical = json.dumps(
        {
            "captured_at": snapshot.captured_at.isoformat(),
            "account": snapshot.account.model_dump(mode="json"),
            "price_as_of": frame.index[-1].date().isoformat(),
            "prices": prices,
            "options": [row.model_dump(mode="json") for row in options],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return MarketSnapshotOut(
        snapshot_id=hashlib.sha256(canonical.encode()).hexdigest(),
        captured_at=snapshot.captured_at,
        price_as_of=frame.index[-1].date(),
        prices=prices,
        options=options,
        quote_time_note=(
            "Option quotes and stock closes were captured together with the signed comparison; "
            "exchange quote timestamps are not available from the provider."
        ),
    )


def _not(code, message, contract=None):
    return NotComputable(code=code, message=message, contract=contract)


def _evaluate(start, scenario, risk, *, horizon, days, reserve_base, initial_equity, market):
    legs = start["legs"]
    shares = dict(start["shares"])
    cash = start["cash"]
    debt = start["debt"]
    missing: list[NotComputable] = []
    events: list[SettlementEvent] = []
    settled_delta: dict[str, Decimal] = defaultdict(Decimal)
    paid = Decimal(0)
    unknown_state = False
    min_cash = cash
    by_date: dict[str, list] = defaultdict(list)
    for leg in legs:
        if leg["expiry"] <= horizon.isoformat():
            by_date[leg["expiry"]].append(leg)
    for expiry in sorted(by_date):
        when = date.fromisoformat(expiry)
        for leg in by_date[expiry]:
            raw = (
                scenario.prices.get(leg["underlying"])
                if when == horizon
                else scenario.settlement_prices.get(when, {}).get(leg["underlying"])
            )
            if raw is None:
                unknown_state = True
                missing.append(
                    _not(
                        "settlement_price_missing",
                        f"No explicit {leg['underlying']} price on {expiry}; this leg's "
                        "settlement and every cash/equity figure after it are not computable.",
                        leg["symbol"],
                    )
                )
                continue
            price = Decimal(str(raw))
            action, delta_shares, delta_cash = settle(leg, price)
            shares[leg["underlying"]] = shares.get(leg["underlying"], Decimal(0)) + delta_shares
            cash += delta_cash
            if delta_shares:
                settled_delta[leg["underlying"]] += delta_shares
            if delta_cash < 0:
                paid -= delta_cash
            events.append(
                SettlementEvent(
                    contract=leg["symbol"],
                    expiry=when,
                    underlying_price=float(price),
                    action=action,
                    shares_delta=float(delta_shares),
                    cash_delta=money(delta_cash),
                )
            )
        if not unknown_state:
            min_cash = min(min_cash, cash)

    residual_total: Decimal | None = Decimal(0)
    long_option_value = Decimal(0)
    valuations = []
    open_legs = [leg for leg in legs if leg["expiry"] > horizon.isoformat()]
    for leg in open_legs:
        expiry = date.fromisoformat(leg["expiry"])
        tau = Decimal((expiry - horizon).days) / YEAR_BASIS
        spot = Decimal(str(scenario.prices[leg["underlying"]]))
        override = risk.residual_iv_overrides.get(leg["symbol"])
        iv = Decimal(str(override)) if override is not None else leg["iv"]
        iv_source = (
            "user_assumption"
            if override is not None
            else ("captured_quote_implied_vol" if iv is not None else "missing")
        )
        rate = risk.residual_risk_free_rate
        value = per_share = None
        if iv is None:
            missing.append(
                _not(
                    "residual_iv_missing",
                    "No captured or confirmed implied volatility for a leg still open "
                    "at the valuation date.",
                    leg["symbol"],
                )
            )
        if rate is None:
            missing.append(
                _not(
                    "residual_rate_missing",
                    "A residual-valuation risk-free rate must be supplied explicitly; "
                    "none is assumed.",
                    leg["symbol"],
                )
            )
        if iv is not None and rate is not None:
            per_share = residual_value_per_share(
                spot, leg["strike"], tau, rate, iv, leg["option_type"]
            )
            value = per_share * leg["quantity"] * MULT
            if leg["quantity"] > 0:
                long_option_value += value
        if value is None:
            residual_total = None
        elif residual_total is not None:
            residual_total += value
        valuations.append(
            ResidualValuation(
                contract=leg["symbol"],
                expiry=expiry,
                contracts_signed=leg["quantity"],
                tau_years=float(tau),
                underlying_price=float(spot),
                iv=None if iv is None else float(iv),
                iv_source=iv_source,
                rate=rate,
                rate_source="missing" if rate is None else "user_assumption",
                value_per_share=None if per_share is None else float(per_share),
                position_value=None if value is None else money(value),
            )
        )

    interest = None
    if debt == 0:
        interest = Decimal(0)
    elif risk.annual_borrowing_rate is not None:
        interest = debt * Decimal(str(risk.annual_borrowing_rate)) * days / 365
    else:
        missing.append(
            _not(
                "interest_rate_unknown",
                "Debt remains but no borrowing APR was supplied; interest and every "
                "figure after it are unknown.",
            )
        )

    open_coverage = []
    gap_blocked = False
    short_tickers = sorted(t for t, q in shares.items() if q < 0)
    if not unknown_state and short_tickers:
        # Exercise/assignment left a short stock position: loss is unbounded as
        # the price rises and its collateral needs a broker rule.
        gap_blocked = True
        missing.append(
            _not(
                "short_stock_unbounded",
                f"A short stock position ({', '.join(short_tickers)}) remains at the valuation "
                "date; its loss is unbounded as the price rises and its collateral needs a "
                "broker rule, so the funding gap is unknown and no alternative is ranked.",
            )
        )
    if not unknown_state:
        open_coverage = option_coverage.relations(shares, open_legs)
        if option_coverage.has_unbounded(open_coverage):
            gap_blocked = True
            missing.append(
                _not(
                    "broker_collateral_unknown",
                    "An uncovered short call is open at the valuation date; its collateral "
                    "needs a broker rule, so the funding gap is unknown.",
                )
            )
    reserve = reserve_base + sum(
        (
            leg["strike"] * abs(leg["quantity"]) * MULT
            for leg in open_legs
            if leg["option_type"] == "put" and leg["quantity"] < 0
        ),
        Decimal(0),
    )

    values = long_stock = short_stock = before = None
    if not unknown_state:
        values = {t: q * Decimal(str(scenario.prices[t])) for t, q in shares.items()}
        long_stock = sum((v for v in values.values() if v > 0), Decimal(0))
        short_stock = -sum((v for v in values.values() if v < 0), Decimal(0))
        if residual_total is not None:
            before = long_stock - short_stock + residual_total + cash - debt
    after_cash = None if unknown_state or interest is None else cash - interest
    equity = None if before is None or interest is None else before - interest
    gap = None if after_cash is None or gap_blocked else max(Decimal(0), reserve - after_cash)
    leverage = concentration = None
    if equity is not None and equity <= 0:
        missing.append(
            _not("nonpositive_equity", "Net equity is not positive; ratios are undefined.")
        )
    if equity is not None and equity > 0:
        if gap is not None:
            leverage = (long_stock + long_option_value + after_cash + gap) / equity
        if long_stock > 0:
            concentration = max(values.values()) / long_stock
    sold = start["sold"]
    opportunity = (
        Decimal(0)
        if sold == 0
        else sold * (Decimal(str(scenario.prices[start["sold_ticker"]])) - start["sale_price"])
    )
    return ExpiryAccountOutcome(
        kind=start["kind"],
        snapshot_id=market.snapshot_id,
        positions=None if unknown_state else {t: float(q) for t, q in shares.items()},
        position_values=None if values is None else {t: money(v) for t, v in values.items()},
        stock_assets=None if long_stock is None else money(long_stock),
        short_stock_value=None if short_stock is None else money(short_stock),
        residual_option_value=None if residual_total is None else money(residual_total),
        residual_valuations=valuations,
        settlement_events=events,
        initial_net_equity=money(initial_equity),
        cash_before_interest=None if unknown_state else money(cash),
        cash_after_interest=None if after_cash is None else money(after_cash),
        min_cash_through_horizon=None if unknown_state else money(min_cash),
        principal_debt=money(debt),
        interest_cost=None if interest is None else money(interest),
        net_equity_before_interest=None if before is None else money(before),
        net_equity_after_interest=None if equity is None else money(equity),
        total_pnl_before_interest=None if before is None else money(before - initial_equity),
        total_pnl=None if equity is None else money(equity - initial_equity),
        incremental_pnl_vs_no_action=None,
        assignment_shares=(
            None if unknown_state else {t: float(q) for t, q in settled_delta.items() if q}
        ),
        assignment_cash_paid=None if unknown_state else money(paid),
        funding_gap_before_interest=(
            None if unknown_state or gap_blocked else money(max(Decimal(0), reserve - cash))
        ),
        funding_gap=None if gap is None else money(gap),
        conditional_debt_if_gap_financed=None if gap is None else money(debt + gap),
        largest_position_weight=None if concentration is None else float(concentration),
        gross_leverage_if_gap_financed=None if leverage is None else float(leverage),
        sold_stock_opportunity_cost=money(opportunity),
        fees_total=money(start["fees"]),
        open_leg_coverage=[CoverageRelation(**row) for row in open_coverage],
        not_computable=missing,
    )


OBJECTIVE_METRIC = {
    "preserve_terminal_equity": ("net_equity_after_interest", -1),
    "minimize_funding_gap": ("funding_gap", 1),
    "minimize_conditional_debt": ("conditional_debt_if_gap_financed", 1),
}


def rank(risk, scenarios, alternatives) -> RankingOut:
    """Conditional preference ONLY under a confirmed objective with every
    compared metric known and bounded for EVERY alternative."""
    if risk.objective is None:
        return RankingOut(status="not_requested", reasons=["No objective was requested."])
    if not risk.objective_confirmed:
        return RankingOut(
            status="objective_not_confirmed",
            objective=risk.objective,
            reasons=["Confirm the objective before alternatives are compared."],
        )
    field, sign = OBJECTIVE_METRIC[risk.objective]
    reasons = []
    vectors: dict[str, list] = {kind: [] for kind in KINDS}
    for scenario in scenarios:
        for outcome in scenario.outcomes:
            value = getattr(outcome, field)
            if value is None:
                reasons.append(
                    f"{field} is not computable for {outcome.kind} in '{scenario.label}'."
                )
            vectors[outcome.kind].append(None if value is None else sign * Decimal(str(value)))
    for alternative in alternatives:
        unbounded = alternative.unbounded_loss or any(
            relation.coverage == "uncovered"
            for scenario in scenarios
            for outcome in scenario.outcomes
            if outcome.kind == alternative.kind
            for relation in outcome.open_leg_coverage
        )
        if unbounded:
            reasons.append(
                f"{alternative.kind} carries an uncovered short call whose loss is "
                "unbounded beyond these scenarios."
            )
        if any(
            item.code == "short_stock_unbounded"
            for scenario in scenarios
            for outcome in scenario.outcomes
            if outcome.kind == alternative.kind
            for item in outcome.not_computable
        ):
            reasons.append(
                f"{alternative.kind} leaves a short stock position whose loss is unbounded "
                "beyond these scenarios."
            )
    if reasons:
        return RankingOut(status="not_computable", objective=risk.objective, reasons=reasons)
    for kind in KINDS:
        others = [vectors[other] for other in KINDS if other != kind]
        if dominates_all(vectors[kind], others):
            return RankingOut(
                status="preferred",
                objective=risk.objective,
                preferred_kind=kind,
                reasons=[
                    "Under the confirmed objective and these explicit price scenarios this "
                    "alternative is no worse in every scenario and better in at least one "
                    "versus each other alternative. Conditional arithmetic, not a forecast "
                    "or a trade instruction."
                ],
            )
    return RankingOut(
        status="no_dominant_alternative",
        objective=risk.objective,
        reasons=["No alternative is at least as good in every scenario; inspect the tradeoffs."],
    )


def calculate(snapshot, funding_assumptions, risk_assumptions, *, now, funding_result):
    if not funding_assumptions.confirmed:
        raise APIError(
            422,
            "risk_scenarios_unconfirmed",
            "Confirm the scenario price and financing assumptions.",
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
    if [row.kind for row in funding.alternatives] != KINDS:
        raise APIError(
            409,
            "risk_source_mismatch",
            "Funding alternatives must include the original ordered baseline.",
        )
    rules = broker_rules.provider(risk_assumptions.broker_rules_provider)
    context = snapshot.account.context()
    specs = comparison_options.option_specs(context.holdings, now=now)
    legs = _legs(specs, snapshot)
    put = funding_assumptions.put
    horizon = put.expiry
    days = (horizon - snapshot.captured_at.date()).days
    if days <= 0:
        raise APIError(
            422, "invalid_expiry_horizon", "Expiry must follow the captured account date."
        )
    quantities = {
        ticker: Decimal(str(holding["shares"]))
        for ticker, holding in context.holdings.items()
        if str(holding.get("asset_type") or "public_security").lower() != "option"
    }
    required = set(quantities) | {leg["underlying"] for leg in legs} | {put.underlying}
    if any(set(scenario.prices) != required for scenario in risk_assumptions.scenarios):
        raise APIError(
            422,
            "incomplete_expiry_prices",
            "Provide exactly one valuation-date price for every held stock and existing/new "
            "option underlying; no price is inferred.",
        )
    early = defaultdict(set)
    for leg in legs:
        if leg["expiry"] < horizon.isoformat():
            early[date.fromisoformat(leg["expiry"])].add(leg["underlying"])
    for scenario in risk_assumptions.scenarios:
        for when, row in scenario.settlement_prices.items():
            if when not in early or not set(row) <= early[when]:
                raise APIError(
                    422,
                    "unexpected_settlement_prices",
                    "Settlement prices are accepted only for underlyings of legs expiring "
                    "on that earlier date.",
                )
    open_symbols = {leg["symbol"] for leg in legs if leg["expiry"] > horizon.isoformat()}
    if set(risk_assumptions.residual_iv_overrides) - open_symbols:
        raise APIError(
            422,
            "unexpected_residual_iv",
            "Volatility overrides are accepted only for legs still open at the valuation date.",
        )
    frame = snapshot.prices.frame()
    sold_ticker = snapshot.result.assumptions.ticker
    if (required | {sold_ticker}) - set(frame.columns):
        raise APIError(
            409, "risk_source_mismatch", "A captured price is missing from the snapshot."
        )
    market = _market_snapshot(snapshot, frame, required | {sold_ticker}, legs)
    initial_assets = sum(
        (qty * Decimal(str(frame.iloc[-1][ticker])) for ticker, qty in quantities.items()),
        Decimal(0),
    )
    existing_options = sum((leg["mark"] * leg["quantity"] * MULT for leg in legs), Decimal(0))
    initial_equity = (
        initial_assets
        + Decimal(str(context.cash_balance))
        + existing_options
        - Decimal(str(context.margin_loan))
    )
    reserve_base = Decimal(str(put.other_reserved_cash)) + Decimal(str(put.cash_buffer))
    sale_price = Decimal(str(frame.iloc[-1][sold_ticker]))
    sold = Decimal(str(snapshot.result.assumptions.amount)) / sale_price
    new_put = {
        "symbol": option_coverage.contract_symbol(
            put.underlying, horizon.isoformat(), "put", put.strike
        )
        + "-new",
        "underlying": put.underlying,
        "option_type": "put",
        "quantity": -put.contracts,
        "strike": Decimal(str(put.strike)),
        "expiry": horizon.isoformat(),
    }
    starts = []
    for alternative in funding.alternatives:
        no_action = alternative.kind == "no_action"
        shares = dict(quantities)
        cash = Decimal(str(alternative.cash_before_put))
        fees = Decimal(0)
        if not no_action:
            shares[sold_ticker] -= sold
            cash += Decimal(str(put.premium_per_share)) * put.contracts * MULT - Decimal(
                str(put.fees_total)
            )
            fees = Decimal(str(funding_assumptions.sale_fees)) + Decimal(str(put.fees_total))
        starts.append(
            {
                "kind": alternative.kind,
                "shares": shares,
                "cash": cash,
                "debt": Decimal(str(alternative.margin_remaining)),
                "fees": fees,
                "sold": Decimal(0) if no_action else sold,
                "sold_ticker": sold_ticker,
                "sale_price": sale_price,
                "legs": legs if no_action else [*legs, new_put],
            }
        )
    base_relations = option_coverage.relations(starts[0]["shares"], legs)
    summaries = []
    for start in starts:
        rows = option_coverage.relations(start["shares"], start["legs"])
        changes = (
            []
            if start["kind"] == "no_action"
            else option_coverage.changes(
                base_relations,
                rows,
                reason=f"Hypothetical sale of {money(start['sold'])} {sold_ticker} shares "
                "changes the stock available to this leg.",
            )
        )
        answer = rules.evaluate("buying_power_impact")
        summaries.append(
            AccountAlternative(
                kind=start["kind"],
                snapshot_id=market.snapshot_id,
                coverage_at_capture=[CoverageRelation(**row) for row in rows],
                coverage_changes=[CoverageChange(**row) for row in changes],
                unbounded_loss=option_coverage.has_unbounded(rows),
                buying_power=BrokerRequirementOut(
                    requirement=answer.requirement, status=answer.status, reason=answer.reason
                ),
            )
        )
    output = []
    for scenario in risk_assumptions.scenarios:
        outcomes = [
            _evaluate(
                start,
                scenario,
                risk_assumptions,
                horizon=horizon,
                days=days,
                reserve_base=reserve_base,
                initial_equity=initial_equity,
                market=market,
            )
            for start in starts
        ]
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
        valuation_date=horizon,
        market_snapshot=market,
        alternatives=summaries,
        broker_rules=BrokerRulesOut(
            provider_id=rules.provider_id, rule_version=rules.rule_version, source=rules.source
        ),
        ranking=rank(risk_assumptions, output, summaries),
        limitations=LIMITATIONS,
    )


LIMITATIONS = [
    "Every alternative, including no action, is evaluated from the same captured account and the same captured prices and option quotes (one snapshot id). Scenario prices are explicit assumptions with no probabilities; they are not forecasts.",
    "Valuation date is the new Put's expiry. Legs expiring at or before it settle physically at the explicit price on their own expiry date: in-the-money short legs are assigned and in-the-money long legs are assumed exercised; at- or out-of-the-money legs expire. Early exercise and early assignment are not modelled.",
    "Legs still open at the valuation date are valued by Black-Scholes using the captured quote's implied volatility (or your confirmed override) and your explicit risk-free rate, with constant volatility to the horizon. Without those inputs the leg and every total that includes it are reported as not computable, never as zero or as an expiry payoff.",
    "Selling stock that covers a short call, or that a long put protects, recomputes the relationship; an uncovered short call has unbounded loss and a broker-defined collateral requirement. Likewise a long put exercised without the shares (or any settlement that leaves negative shares) creates a short stock position: its loss is unbounded, its funding gap is reported as not computable, and no alternative is ranked.",
    "Total P&L uses the original captured equity including existing option marks. New premium is not instant profit; terminal obligations and both fee types are included once. Sold-stock opportunity cost is a decomposition already inside total P&L, never subtracted twice.",
    "Interest is simple actual/365 on each branch's initial debt from capture to the valuation date. A cash deficit created by an assignment or exercise on an earlier expiry date accrues NO interest between that settlement date and the valuation date: interest there is understated (its financing appears only as the funding gap at the valuation date). An unknown APR leaves debt-bearing equity, P&L and funding gaps unknown; zero-debt branches incur none. Cash earns no yield here.",
    "Open short Puts at the valuation date reserve gross strike cash without spread netting. Conditional deficit borrowing adds equal cash and debt and does not imply broker approval or available credit.",
    "Broker buying power, maintenance requirements and uncovered-call collateral are unknown: no verified broker rule set is connected (provider 'unknown'). Actual fills, early exercise, margin calls and liquidation paths are not modelled.",
    "A preferred alternative is shown only under your confirmed objective when every compared figure is computable and bounded for every alternative; otherwise no ranking is given. It is conditional arithmetic, not a recommendation.",
    "Taxes, dividends, changes in reserved cash, intraperiod price paths and execution/settlement uncertainty are excluded.",
]
