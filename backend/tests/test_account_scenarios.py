"""v2 whole-account scenarios: shared snapshot, mixed expiries, coverage, ranking.

Oracles are independent: Black-Scholes is re-derived here with math.erf (the
service uses scipy via libs.mindmarket_core.black_scholes), ledgers are written
out by hand, and settlement conservation is checked against intrinsic value.
Captures go through the REAL option capture -> compare -> signed receipt path.
"""

import math
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from backend.app.core.responses import APIError
from backend.app.schemas.copilot_compare import CompareChange
from backend.app.schemas.copilot_put import CashSecuredPutRequest
from backend.app.schemas.funding_risk import FundingRiskAssumptions, FundingRiskResult
from backend.app.schemas.funding_scenarios import FundingScenarioAssumptions
from backend.app.services import (
    broker_rules,
    comparison_options,
    comparison_replay,
    copilot_compare,
    funding_risk,
    funding_scenarios,
    option_coverage,
)
from libs.auth.active_portfolio import ActivePortfolioContext

NOW = datetime(2026, 9, 16, tzinfo=timezone.utc)
T = "2026-10-16"  # new Put expiry = valuation date
LATER = "2026-11-20"  # 35 days after T
EARLIER = "2026-10-02"
BOOK = "11111111-1111-4111-8111-111111111111"
USER = "22222222-2222-4222-8222-222222222222"
SPOTS = {"A": 100, "B": 50, "X": 40, "Y": 25}


def erf_bs(spot, strike, tau, rate, sigma, kind):
    """Independent closed form (math.erf), not the service implementation."""
    if spot == 0:
        return 0.0 if kind == "call" else strike * math.exp(-rate * tau)
    cdf = lambda z: 0.5 * (1 + math.erf(z / math.sqrt(2)))  # noqa: E731
    d1 = (math.log(spot / strike) + (rate + sigma * sigma / 2) * tau) / (sigma * math.sqrt(tau))
    d2 = d1 - sigma * math.sqrt(tau)
    if kind == "call":
        return spot * cdf(d1) - strike * math.exp(-rate * tau) * cdf(d2)
    return strike * math.exp(-rate * tau) * cdf(-d2) - spot * cdf(-d1)


def option(underlying, strike, expiry, kind, quantity, side):
    symbol = option_coverage.contract_symbol(underlying, expiry, kind, strike)
    return symbol, {
        "shares": quantity,
        "asset_type": "option",
        "underlying": underlying,
        "strike": strike,
        "expiry": expiry,
        "option_type": kind,
        "option_side": side,
        "contract_multiplier": 100,
    }


def capture(
    monkeypatch, *, options=(), stocks=None, cash=20000, debt=0, sell="A", amount=500.0, put=None
):
    monkeypatch.setattr(
        comparison_replay,
        "get_settings",
        lambda: SimpleNamespace(
            copilot_comparison_replay_enabled=True,
            risk_run_signing_secret="account-scenarios-synthetic-key-0000000000000000",
        ),
    )
    holdings = {
        t: {"shares": q, "asset_type": "stock"}
        for t, q in (stocks or {"A": 10, "B": 20, "Y": 8}).items()
    }
    holdings.update(dict(options))
    context = ActivePortfolioContext(BOOK, holdings, cash, debt, 0)
    dates = pd.bdate_range(end=NOW.date(), periods=101)
    scale = np.exp(0.0001 * (np.arange(101) - 100))
    prices = pd.DataFrame({t: s * scale for t, s in SPOTS.items()}, index=dates)

    def chain(underlying, expiry, kind, strike):
        return {
            "contract_symbol": option_coverage.contract_symbol(underlying, expiry, kind, strike),
            "strike": strike,
            "bid": 1.9,
            "ask": 2.1,
        }

    rows = comparison_options.capture_options(
        comparison_options.option_specs(context.holdings, now=NOW),
        prices.iloc[-1].to_dict(),
        now=NOW,
        chain_fn=chain,
    )
    comparison = copilot_compare.compare_change(
        context,
        CompareChange(expected_portfolio_id=BOOK, ticker=sell, amount=amount, proceeds="cash"),
        prices,
        {},
        now=NOW,
        option_results=rows,
    )
    receipt = comparison_replay.issue_receipt(
        USER, context, prices, rows, {}, comparison, portfolio_revision=UUID(BOOK)
    )
    snapshot = comparison_replay.read_receipt(receipt, USER, BOOK, str(comparison.result_id))
    assumptions = FundingScenarioAssumptions(
        expected_portfolio_id=BOOK,
        source_result_id=comparison.result_id,
        protected_holdings=[],
        sale_fees=5.0,
        confirmed=True,
        put=CashSecuredPutRequest(
            **{
                "expected_portfolio_id": BOOK,
                "underlying": "B",
                "expiry": T,
                "strike": 40.0,
                "premium_per_share": 2.5,
                "assumed_spot": 50.0,
                "contracts": 1,
                "fees_total": 2.0,
                "other_reserved_cash": 0.0,
                "cash_buffer": 0.0,
                "confirmed": True,
                "gross_settled_usd_cash_confirmed": True,
                "standard_contract_confirmed": True,
                **(put or {}),
            }
        ),
    )
    return snapshot, assumptions


def run(snapshot, assumptions, **risk):
    assumptions.risk = FundingRiskAssumptions(**risk)
    return funding_scenarios.calculate(snapshot, assumptions, now=NOW)


def iv_of(snapshot, symbol):
    for row in snapshot.option_results:
        if row["contract_symbol"] == symbol:
            return row["iv"]
    raise AssertionError(symbol)


# ── 1. shared snapshot ───────────────────────────────────────────────────────


def test_every_alternative_and_outcome_carries_the_same_snapshot_id(monkeypatch):
    sym, leg = option("X", 25, LATER, "put", -1, "sell")
    snapshot, assumptions = capture(monkeypatch, options=[(sym, leg)], stocks={"A": 10, "B": 20})
    prices = {"A": 100, "B": 50, "X": 40}
    result = run(
        snapshot,
        assumptions,
        scenarios=[{"label": "flat", "prices": prices}, {"label": "down", "prices": prices}],
        residual_risk_free_rate=0.04,
    ).account_risk
    sid = result.market_snapshot.snapshot_id
    ids = {alt.snapshot_id for alt in result.alternatives} | {
        o.snapshot_id for s in result.scenarios for o in s.outcomes
    }
    assert ids == {sid} and len(result.alternatives) == 3
    # The snapshot records the captured inputs every alternative used.
    assert result.market_snapshot.prices["X"] == pytest.approx(40, rel=1e-3)
    assert {o.contract for o in result.market_snapshot.options} == {sym}
    assert all(
        o.initial_net_equity == result.scenarios[0].outcomes[0].initial_net_equity
        for s in result.scenarios
        for o in s.outcomes
    )
    # Sensitivity: a different captured quote is a different snapshot.
    changed = snapshot.model_copy(deep=True)
    changed.option_results[0]["mark"] = 2.5
    other = funding_risk._market_snapshot(
        changed,
        changed.prices.frame(),
        {"A", "B", "X"},
        funding_risk._legs(
            comparison_options.option_specs(changed.account.context().holdings, now=NOW), changed
        ),
    )
    assert other.snapshot_id != sid


# ── 2. mixed expiries: residual BS valuation at T ────────────────────────────


@pytest.mark.parametrize("x_at_t", [0, 22, 40])
def test_mixed_expiry_residual_leg_matches_independent_black_scholes(monkeypatch, x_at_t):
    """Hand ledger: stocks A10 B20, cash 20000, debt 0; existing short X30P @T and
    short X25P @LATER (both marked 2.00). New 1x B40P @2.50 fee 2; sell $500 A fee 5."""
    short_t = option("X", 30, T, "put", -1, "sell")
    short_later = option("X", 25, LATER, "put", -1, "sell")
    snapshot, assumptions = capture(
        monkeypatch, options=[short_t, short_later], stocks={"A": 10, "B": 20}
    )
    rate = 0.04
    prices = {"A": 90, "B": 45, "X": x_at_t}
    result = run(
        snapshot,
        assumptions,
        scenarios=[{"label": "s", "prices": prices}],
        residual_risk_free_rate=rate,
    ).account_risk
    sigma = iv_of(snapshot, short_later[0])
    tau = 35 / 365.25
    residual = -100 * erf_bs(x_at_t, 25, tau, rate, sigma, "put")
    entry = 10 * 100 + 20 * 50 + 20000 - 200 - 200  # two marked short puts
    x_assigned = 100 if x_at_t < 30 else 0
    base = 10 * 90 + 20 * 45 + x_assigned * x_at_t + 20000 - 30 * x_assigned + residual
    # Candidate: 5 A sold for 495 net, +250-2 premium, B40P OTM at 45.
    cand = 5 * 90 + 20 * 45 + x_assigned * x_at_t + 20000 + 495 + 248 - 30 * x_assigned + residual
    no_action, keep, repay = result.scenarios[0].outcomes
    for row, equity in ((no_action, base), (keep, cand), (repay, cand)):
        assert row.initial_net_equity == pytest.approx(entry)
        assert row.residual_option_value == pytest.approx(residual, abs=0.0051)
        assert row.net_equity_after_interest == pytest.approx(equity, abs=0.011)
        assert row.total_pnl == pytest.approx(equity - entry, abs=0.011)
        (valuation,) = row.residual_valuations
        assert valuation.iv_source == "captured_quote_implied_vol"
        assert valuation.tau_years == pytest.approx(tau)
        assert valuation.rate == rate and not row.not_computable
    # The residual leg is NOT valued at its expiry payoff.
    payoff = -100 * max(25 - x_at_t, 0)
    assert abs(no_action.residual_option_value - payoff) > 1


def test_residual_leg_without_rate_is_not_computable_never_zero(monkeypatch):
    snapshot, assumptions = capture(
        monkeypatch,
        options=[option("X", 25, LATER, "put", -1, "sell")],
        stocks={"A": 10, "B": 20},
    )
    result = run(
        snapshot, assumptions, scenarios=[{"label": "s", "prices": {"A": 90, "B": 45, "X": 30}}]
    ).account_risk
    for row in result.scenarios[0].outcomes:
        assert row.residual_option_value is None
        assert row.net_equity_after_interest is None and row.total_pnl is None
        assert row.gross_leverage_if_gap_financed is None
        assert "residual_rate_missing" in {n.code for n in row.not_computable}
        assert row.residual_valuations[0].position_value is None
        # Cash is independent of the open leg and stays known.
        assert row.cash_after_interest is not None
    assert result.ranking.status == "not_requested"


def test_user_iv_override_is_labelled_and_used(monkeypatch):
    sym, leg = option("X", 25, LATER, "put", -1, "sell")
    snapshot, assumptions = capture(monkeypatch, options=[(sym, leg)], stocks={"A": 10, "B": 20})
    result = run(
        snapshot,
        assumptions,
        scenarios=[{"label": "s", "prices": {"A": 90, "B": 45, "X": 30}}],
        residual_risk_free_rate=0.03,
        residual_iv_overrides={sym: 0.6},
        residual_assumptions_confirmed=True,
    ).account_risk
    valuation = result.scenarios[0].outcomes[0].residual_valuations[0]
    assert valuation.iv_source == "user_assumption" and valuation.iv == 0.6
    assert valuation.position_value == pytest.approx(
        -100 * erf_bs(30, 25, 35 / 365.25, 0.03, 0.6, "put"), abs=0.0051
    )
    with pytest.raises(ValidationError):
        FundingRiskAssumptions(
            scenarios=[{"label": "s", "prices": {"X": 1}}], residual_iv_overrides={sym: 0.6}
        )


def test_earlier_expiring_leg_needs_an_explicit_settlement_price(monkeypatch):
    sym, leg = option("X", 30, EARLIER, "put", -1, "sell")
    snapshot, assumptions = capture(monkeypatch, options=[(sym, leg)], stocks={"A": 10, "B": 20})
    prices = {"A": 100, "B": 50, "X": 45}
    missing = run(snapshot, assumptions, scenarios=[{"label": "s", "prices": prices}])
    for row in missing.account_risk.scenarios[0].outcomes:
        assert row.cash_before_interest is None and row.positions is None
        assert row.total_pnl is None and row.funding_gap is None
        assert row.not_computable[0].code == "settlement_price_missing"
    # Assigned at 20 on the earlier date; held to T and valued at 45 there.
    given = run(
        snapshot,
        assumptions,
        scenarios=[{"label": "s", "prices": prices, "settlement_prices": {EARLIER: {"X": 20}}}],
    ).account_risk.scenarios[0]
    base = given.outcomes[0]
    assert base.positions["X"] == 100
    assert base.cash_before_interest == 20000 - 3000
    assert base.min_cash_through_horizon == 17000
    assert base.net_equity_after_interest == pytest.approx(1000 + 1000 + 17000 + 4500)
    with pytest.raises(APIError) as error:
        run(
            snapshot,
            assumptions,
            scenarios=[{"label": "s", "prices": prices, "settlement_prices": {T: {"X": 20}}}],
        )
    assert error.value.code == "unexpected_settlement_prices"


# ── 3. coverage / protection dependencies ────────────────────────────────────


def test_covered_call_broken_by_sale_is_flagged_and_settles_short(monkeypatch):
    """Y: 100 shares cover 1 short Y30C @T. Selling $2,500 of Y (100 sh) leaves the
    call naked. At T with Y=35 the call is assigned: no-action delivers its shares,
    the candidate ends short 100 Y valued at 35 (a 3,500 liability)."""
    sym, leg = option("Y", 30, T, "call", -1, "sell")
    snapshot, assumptions = capture(
        monkeypatch,
        options=[(sym, leg)],
        stocks={"A": 10, "B": 20, "Y": 100},
        sell="Y",
        amount=2500.0,
    )
    funding = run(
        snapshot,
        assumptions,
        scenarios=[{"label": "s", "prices": {"A": 100, "B": 50, "Y": 35}}],
        objective="preserve_terminal_equity",
        objective_confirmed=True,
    )
    risk = funding.account_risk
    base, keep, repay = risk.alternatives
    assert [(r.coverage, r.contracts) for r in base.coverage_at_capture] == [("stock", 1)]
    assert not base.unbounded_loss
    assert keep.unbounded_loss and repay.unbounded_loss
    (change,) = keep.coverage_changes
    assert (change.contract, change.before, change.after) == (sym, "stock×1", "uncovered×1")
    naked = [r for r in keep.coverage_at_capture if r.contract == sym][0]
    assert naked.max_loss_excl_premium is None and naked.collateral == "broker_rule_unknown"
    assert [a.status for a in funding.alternatives][1:] == ["financing_rules_required"] * 2
    no_action, sold, _ = risk.scenarios[0].outcomes
    entry = 1000 + 1000 + 2500 + 20000 - 200
    assert no_action.positions["Y"] == 0
    assert no_action.net_equity_after_interest == pytest.approx(1000 + 1000 + 20000 + 3000)
    assert sold.positions["Y"] == -100 and sold.short_stock_value == 3500
    # 22000 stock+cash, +2495 sale, +248 premium, +3000 strike, -3500 short Y.
    assert sold.net_equity_after_interest == pytest.approx(
        1000 + 1000 + 20000 + 2495 + 248 + 3000 - 3500
    )
    assert sold.total_pnl == pytest.approx(sold.net_equity_after_interest - entry)
    assert sold.sold_stock_opportunity_cost == pytest.approx(100 * (35 - 25), rel=1e-3)
    # Unbounded loss forbids a ranking even with a confirmed objective.
    assert risk.ranking.status == "not_computable"
    assert any("unbounded" in reason for reason in risk.ranking.reasons)


def test_protective_put_loses_its_stock_when_sold(monkeypatch):
    sym, leg = option("Y", 20, T, "put", 1, "buy")
    snapshot, assumptions = capture(
        monkeypatch,
        options=[(sym, leg)],
        stocks={"A": 10, "B": 20, "Y": 100},
        sell="Y",
        amount=2500.0,
    )
    risk = run(
        snapshot, assumptions, scenarios=[{"label": "s", "prices": {"A": 100, "B": 50, "Y": 15}}]
    ).account_risk
    (change,) = risk.alternatives[1].coverage_changes
    assert (change.before, change.after) == ("protective×1", "unpaired_no_stock×1")
    no_action, sold, _ = risk.scenarios[0].outcomes
    # Exercised at 15<20: deliver 100 Y for 2000 cash. Candidate ends short 100 Y.
    assert no_action.positions["Y"] == 0 and sold.positions["Y"] == -100
    assert no_action.settlement_events[0].action == "exercised"
    assert sold.short_stock_value == 1500


def test_call_spread_relation_bounds_the_short_leg():
    legs = [
        {
            "symbol": "S",
            "underlying": "Y",
            "option_type": "call",
            "quantity": -2,
            "strike": 30,
            "expiry": T,
        },
        {
            "symbol": "L",
            "underlying": "Y",
            "option_type": "call",
            "quantity": 1,
            "strike": 35,
            "expiry": LATER,
        },
        {
            "symbol": "P",
            "underlying": "Y",
            "option_type": "put",
            "quantity": -1,
            "strike": 20,
            "expiry": T,
        },
        {
            "symbol": "Q",
            "underlying": "Y",
            "option_type": "put",
            "quantity": 1,
            "strike": 18,
            "expiry": T,
        },
    ]
    rows = option_coverage.relations({"Y": Decimal(150)}, legs)
    got = {
        (r["contract"], r["coverage"]): (r["contracts"], r["max_loss_excl_premium"]) for r in rows
    }
    assert got[("S", "stock")] == (1, 0)
    assert got[("S", "long_call_spread")] == (1, 500)
    assert got[("P", "long_put_spread")] == (1, 200)
    assert ("S", "uncovered") not in got
    # The long call expiring BEFORE the short cannot cover it.
    legs[1]["expiry"] = EARLIER
    rows = option_coverage.relations({"Y": Decimal(150)}, legs)
    assert any(r["contract"] == "S" and r["coverage"] == "uncovered" for r in rows)


# ── 4. settlement conservation ───────────────────────────────────────────────


@pytest.mark.parametrize("kind", ["put", "call"])
@pytest.mark.parametrize("quantity", [-2, 3])
@pytest.mark.parametrize("price", [0, 17, 30, 44])
def test_settlement_conserves_value_against_intrinsic(kind, quantity, price):
    leg = {"option_type": kind, "quantity": quantity, "strike": Decimal(30)}
    action, shares, cash = funding_risk.settle(leg, Decimal(price))
    intrinsic = max(price - 30, 0) if kind == "call" else max(30 - price, 0)
    # Cash moves exactly against the shares at the strike...
    assert cash == -30 * shares
    # ...and the net value delivered equals the signed intrinsic payoff.
    assert shares * price + cash == quantity * 100 * intrinsic
    assert (action == "expired") == (intrinsic == 0)
    if intrinsic:
        assert action == ("assigned" if quantity < 0 else "exercised")


def test_keep_and_repay_conserve_cash_minus_debt(monkeypatch):
    snapshot, assumptions = capture(monkeypatch, stocks={"A": 10, "B": 20}, cash=1000, debt=300)
    risk = run(
        snapshot,
        assumptions,
        scenarios=[{"label": "s", "prices": {"A": 80, "B": 30}}],
        annual_borrowing_rate=0.0,
    ).account_risk
    _, keep, repay = risk.scenarios[0].outcomes
    assert keep.cash_before_interest - keep.principal_debt == pytest.approx(
        repay.cash_before_interest - repay.principal_debt
    )
    assert keep.net_equity_after_interest == repay.net_equity_after_interest
    # Decomposition: ΔPnL = -opportunity - fees + new put payoff (B40P at 30).
    put_payoff = 250 - 100 * 10
    assert keep.incremental_pnl_vs_no_action == pytest.approx(
        -keep.sold_stock_opportunity_cost - 5 + put_payoff - 2, abs=0.011
    )
    assert keep.fees_total == 7


# ── 5. broker rules ──────────────────────────────────────────────────────────


def test_only_unknown_broker_rules_exist(monkeypatch):
    snapshot, assumptions = capture(monkeypatch, stocks={"A": 10, "B": 20})
    risk = run(
        snapshot, assumptions, scenarios=[{"label": "s", "prices": {"A": 1, "B": 1}}]
    ).account_risk
    assert risk.broker_rules.provider_id == "unknown"
    assert all(
        a.buying_power.status == "unknown" and a.buying_power.value is None
        for a in risk.alternatives
    )
    assert any("liquidation paths are not modelled" in line for line in risk.limitations)
    with pytest.raises(APIError):
        broker_rules.provider("reg_t")
    with pytest.raises(ValidationError):
        FundingRiskAssumptions(
            scenarios=[{"label": "s", "prices": {"A": 1}}], broker_rules_provider="reg_t"
        )


# ── 6. conditional ranking ───────────────────────────────────────────────────


def _ranked(monkeypatch, scenarios, **kw):
    snapshot, assumptions = capture(monkeypatch, stocks={"A": 10, "B": 20}, cash=20000, debt=0)
    return run(snapshot, assumptions, scenarios=scenarios, **kw).account_risk.ranking


def test_ranking_requires_a_confirmed_objective(monkeypatch):
    crash = [{"label": "crash", "prices": {"A": 100, "B": 20}}]
    assert _ranked(monkeypatch, crash).status == "not_requested"
    assert _ranked(monkeypatch, crash, objective="preserve_terminal_equity").status == (
        "objective_not_confirmed"
    )


def test_ranking_prefers_only_a_hand_verified_dominant_alternative(monkeypatch):
    # B crashes to 20: each candidate pays 100*(40-20)=2000 on the new Put and
    # gains 248 premium net, -5 fee, 0 opportunity (A flat): equity 2,243 below
    # no action; keep == repay (no debt). No action is strictly better than both.
    crash = [{"label": "crash", "prices": {"A": 100, "B": 20}}]
    ranking = _ranked(
        monkeypatch, crash, objective="preserve_terminal_equity", objective_confirmed=True
    )
    assert (ranking.status, ranking.preferred_kind) == ("preferred", "no_action")
    # Adding a rally where the Put expires worthless flips the order: no dominance.
    both = crash + [{"label": "rally", "prices": {"A": 100, "B": 60}}]
    ranking = _ranked(
        monkeypatch, both, objective="preserve_terminal_equity", objective_confirmed=True
    )
    assert ranking.status == "no_dominant_alternative" and ranking.preferred_kind is None


def test_ranking_refuses_when_any_metric_is_unknown(monkeypatch):
    snapshot, assumptions = capture(monkeypatch, stocks={"A": 10, "B": 20}, cash=20000, debt=300)
    ranking = run(
        snapshot,
        assumptions,
        scenarios=[{"label": "crash", "prices": {"A": 100, "B": 20}}],
        objective="preserve_terminal_equity",
        objective_confirmed=True,
    ).account_risk.ranking
    assert ranking.status == "not_computable" and ranking.preferred_kind is None


# ── 7. guards and compatibility ──────────────────────────────────────────────


def test_sale_of_option_underlying_still_refused_without_the_ledger(monkeypatch):
    snapshot, assumptions = capture(
        monkeypatch,
        options=[option("Y", 30, T, "call", -1, "sell")],
        stocks={"A": 10, "B": 20, "Y": 100},
        sell="Y",
        amount=2500.0,
    )
    with pytest.raises(APIError) as error:
        funding_scenarios.calculate(snapshot, assumptions, now=NOW)
    assert error.value.code == "protected_option_underlying"


def test_unexpected_iv_override_is_refused(monkeypatch):
    sym, leg = option("X", 30, T, "put", -1, "sell")
    snapshot, assumptions = capture(monkeypatch, options=[(sym, leg)], stocks={"A": 10, "B": 20})
    with pytest.raises(APIError) as error:
        run(
            snapshot,
            assumptions,
            scenarios=[{"label": "s", "prices": {"A": 1, "B": 1, "X": 1}}],
            residual_iv_overrides={sym: 0.5},
            residual_assumptions_confirmed=True,
        )
    assert error.value.code == "unexpected_residual_iv"


def test_saved_v1_record_still_parses_with_original_meaning():
    import json
    from pathlib import Path

    fixture = json.loads(
        (
            Path(__file__).parents[2] / "frontend/src/test-fixtures/copilot-funding-risk.json"
        ).read_text()
    )
    legacy = FundingRiskResult.model_validate(fixture["result"]["account_risk"])
    assert legacy.methodology_version == "funding-common-expiry-v1"
    assert legacy.market_snapshot is None and legacy.ranking is None
    assert legacy.scenarios[0].outcomes[0].snapshot_id is None


def test_residual_value_limit_at_zero_price():
    assert funding_risk.residual_value_per_share(0, 25, 0.1, 0.04, 0.3, "call") == 0
    assert float(funding_risk.residual_value_per_share(0, 25, 0.1, 0.04, 0.3, "put")) == (
        pytest.approx(25 * math.exp(-0.004))
    )
    assert date.fromisoformat(LATER) > date.fromisoformat(T)
