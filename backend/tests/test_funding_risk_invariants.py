"""Independent terminal-book oracle, not a reimplementation of funding rows.

All quotes and spot prices are synthetic; the captured comparison is real.
The oracle marks every owned asset and liability at entry and at common expiry.
"""

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

import numpy as np
import pandas as pd
import pytest

from backend.app.core.responses import APIError
from backend.app.schemas.copilot_compare import CompareChange
from backend.app.schemas.copilot_put import CashSecuredPutRequest
from backend.app.schemas.funding_scenarios import FundingScenarioAssumptions
from backend.app.services import comparison_options, comparison_replay, copilot_compare
from libs.auth.active_portfolio import ActivePortfolioContext

NOW = datetime(2026, 9, 16, tzinfo=timezone.utc)
EXPIRY = "2026-10-16"
BOOK = "11111111-1111-4111-8111-111111111111"
USER = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def captured(monkeypatch):
    monkeypatch.setattr(
        comparison_replay,
        "get_settings",
        lambda: SimpleNamespace(
            copilot_comparison_replay_enabled=True,
            risk_run_signing_secret="funding-oracle-synthetic-key-000000000000000000",
        ),
    )
    option = "X261016P00030000"
    context = ActivePortfolioContext(
        BOOK,
        {
            "A": {"shares": 10, "asset_type": "stock"},
            "B": {"shares": 20, "asset_type": "etf"},
            option: {
                "shares": -1,
                "asset_type": "option",
                "underlying": "X",
                "strike": 30,
                "expiry": EXPIRY,
                "option_type": "put",
                "option_side": "sell",
                "contract_multiplier": 100,
            },
        },
        1000,
        300,
        0,
    )
    dates = pd.bdate_range(end=NOW.date(), periods=101)
    scale = np.exp(0.0001 * (np.arange(101) - 100))
    prices = pd.DataFrame(
        {ticker: spot * scale for ticker, spot in {"A": 100, "B": 50, "X": 40}.items()}, index=dates
    )
    rows = comparison_options.capture_options(
        comparison_options.option_specs(context.holdings, now=NOW),
        prices.iloc[-1].to_dict(),
        now=NOW,
        chain_fn=lambda *args: {"contract_symbol": option, "strike": 30, "bid": 1.9, "ask": 2.1},
    )
    comparison = copilot_compare.compare_change(
        context,
        CompareChange(expected_portfolio_id=BOOK, ticker="A", amount=500.0, proceeds="cash"),
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
        sale_fees=1.0,
        confirmed=True,
        put=CashSecuredPutRequest(
            expected_portfolio_id=BOOK,
            underlying="B",
            expiry=EXPIRY,
            strike=40.0,
            premium_per_share=2.0,
            assumed_spot=50.0,
            contracts=1,
            fees_total=1.0,
            other_reserved_cash=0.0,
            cash_buffer=0.0,
            confirmed=True,
            gross_settled_usd_cash_confirmed=True,
            standard_contract_confirmed=True,
        ),
    )
    return snapshot, assumptions


def terminal_oracle(prices, *, sell=False, apr=None, repay=False):
    # Equity now: 10 A + 20 B + cash - debt - marked existing put liability.
    entry = Decimal(10 * 100 + 20 * 50 + 1000 - 300 - 100 * 2)
    a, b, x = (Decimal(str(prices[t])) for t in ("A", "B", "X"))
    terminal = 10 * a + 20 * b + 1000 - 300 - 100 * max(Decimal(30) - x, Decimal(0))
    debt = Decimal(300)
    if sell:
        # Replacing five A shares with sale cash captures the opportunity cost.
        terminal += Decimal(500) - 5 * a - 1
        terminal += Decimal(200) - 1 - 100 * max(Decimal(40) - b, Decimal(0))
        if repay:
            debt = Decimal(0)  # Cash and debt both decrease by 300; equity is unchanged.
    interest = (
        None if apr is None and debt else debt * Decimal(str(apr or 0)) * Decimal(30) / Decimal(365)
    )
    return entry, terminal, None if interest is None else terminal - interest, interest


@pytest.mark.parametrize("apr", [None, 0.0, 0.12])
@pytest.mark.parametrize(
    "prices",
    [
        {"A": 0, "B": 0, "X": 0},
        {"A": 130, "B": 35, "X": 20},
        {"A": 100, "B": 40, "X": 30},
        {"A": 80, "B": 60, "X": 50},
    ],
)
def test_terminal_account_against_independent_oracle(captured, prices, apr):
    from backend.app.schemas.funding_risk import FundingRiskAssumptions
    from backend.app.services import funding_risk, funding_scenarios

    snapshot, assumptions = captured
    funding = funding_scenarios.calculate(snapshot, assumptions, now=NOW)
    result = funding_risk.calculate(
        snapshot,
        assumptions,
        FundingRiskAssumptions(
            scenarios=[{"label": "explicit", "prices": prices}], annual_borrowing_rate=apr
        ),
        now=NOW,
        funding_result=funding,
    )
    baseline = None
    for index, outcome in enumerate(result.scenarios[0].outcomes):
        entry, terminal, after, interest = terminal_oracle(
            prices, sell=index > 0, repay=index == 2, apr=apr
        )
        assert outcome.initial_net_equity == float(entry)
        assert outcome.net_equity_before_interest == pytest.approx(float(terminal))
        assert outcome.total_pnl_before_interest == pytest.approx(float(terminal - entry))
        assert outcome.net_equity_after_interest == (
            None if after is None else pytest.approx(float(after), abs=0.0051)
        )
        assert outcome.interest_cost == (
            None if interest is None else pytest.approx(float(interest), abs=0.0051)
        )
        assert outcome.assignment_shares.get("X", 0) == (100 if prices["X"] < 30 else 0)
        assert outcome.assignment_shares.get("B", 0) == (100 if index and prices["B"] < 40 else 0)
        if after is None or after <= 0:
            assert outcome.gross_leverage_if_gap_financed is None
            assert outcome.largest_position_weight is None
        if after is None:
            assert outcome.funding_gap is None
            assert outcome.conditional_debt_if_gap_financed is None
        else:
            assert outcome.total_pnl == pytest.approx(float(after - entry), abs=0.0051)
            assert outcome.funding_gap == pytest.approx(max(0, -outcome.cash_after_interest))
            assert outcome.conditional_debt_if_gap_financed == pytest.approx(
                outcome.principal_debt + outcome.funding_gap
            )
        if index == 0:
            baseline = outcome.total_pnl
        assert outcome.incremental_pnl_vs_no_action == (
            None
            if baseline is None or outcome.total_pnl is None
            else pytest.approx(outcome.total_pnl - baseline, abs=0.0051)
        )
    assert result.preferred_alternative is None
    assert any("does not imply broker approval" in line for line in result.limitations)


def test_missing_prices_stop_instead_of_inferred_prices(captured):
    from backend.app.schemas.funding_risk import FundingRiskAssumptions
    from backend.app.services import funding_risk, funding_scenarios

    snapshot, assumptions = captured
    with pytest.raises(APIError) as error:
        funding_risk.calculate(
            snapshot,
            assumptions,
            FundingRiskAssumptions(
                scenarios=[{"label": "missing X", "prices": {"A": 100, "B": 50}}]
            ),
            now=NOW,
            funding_result=funding_scenarios.calculate(snapshot, assumptions, now=NOW),
        )
    assert error.value.code == "incomplete_expiry_prices"


@pytest.mark.parametrize(
    "mutation", ["order", "call", "long", "fractional", "multiplier", "expiry"]
)
def test_expiry_guards(captured, monkeypatch, mutation):
    """v2 values calls, long legs and mixed expiries, but a leg that does not
    match a captured, signed quote row is still refused (never priced ad hoc)."""
    from backend.app.schemas.funding_risk import FundingRiskAssumptions
    from backend.app.services import funding_risk, funding_scenarios

    snapshot, assumptions = captured
    funding = funding_scenarios.calculate(snapshot, assumptions, now=NOW)
    specs = comparison_options.option_specs(snapshot.account.context().holdings, now=NOW)
    if mutation == "order":
        funding.alternatives.reverse()
    else:
        kwargs = {
            "call": {"option_type": "call"},
            "long": {"quantity": 1},
            "fractional": {"quantity": -0.5},
            "multiplier": {"contract_multiplier": 10},
            "expiry": {"expiry": "2026-11-20"},
        }[mutation]
        specs = [SimpleNamespace(**(vars(specs[0]) | kwargs))]
        monkeypatch.setattr(funding_risk.comparison_options, "option_specs", lambda *a, **kw: specs)
        monkeypatch.setattr(funding_risk.comparison_replay, "replay", lambda *a: None)
    with pytest.raises(APIError) as error:
        funding_risk.calculate(
            snapshot,
            assumptions,
            FundingRiskAssumptions(
                scenarios=[{"label": "explicit", "prices": {"A": 100, "B": 50, "X": 40}}]
            ),
            now=NOW,
            funding_result=funding,
        )
    assert error.value.code == "risk_source_mismatch"


def test_reserves_affect_funding_not_equity(captured):
    from backend.app.schemas.funding_risk import FundingRiskAssumptions
    from backend.app.services import funding_risk, funding_scenarios

    snapshot, assumptions = captured
    risk = FundingRiskAssumptions(
        scenarios=[{"label": "up", "prices": {"A": 120, "B": 60, "X": 50}}],
        annual_borrowing_rate=0.12,
    )
    before = funding_risk.calculate(
        snapshot,
        assumptions,
        risk,
        now=NOW,
        funding_result=funding_scenarios.calculate(snapshot, assumptions, now=NOW),
    )
    reserved = assumptions.model_copy(deep=True)
    reserved.put.other_reserved_cash = 1500.0
    reserved.put.cash_buffer = 250.0
    after = funding_risk.calculate(
        snapshot,
        reserved,
        risk,
        now=NOW,
        funding_result=funding_scenarios.calculate(snapshot, reserved, now=NOW),
    )
    for a, b in zip(before.scenarios[0].outcomes, after.scenarios[0].outcomes):
        assert a.total_pnl == b.total_pnl
        assert a.net_equity_after_interest == b.net_equity_after_interest
        assert b.funding_gap == pytest.approx(max(0, 1750 - b.cash_after_interest), abs=0.0051)
        assert b.conditional_debt_if_gap_financed == pytest.approx(b.principal_debt + b.funding_gap)


@pytest.mark.parametrize("price", [False, True, "100", None])
def test_expiry_prices_reject_coercion(price):
    from pydantic import ValidationError

    from backend.app.schemas.funding_risk import FundingRiskAssumptions

    with pytest.raises(ValidationError):
        FundingRiskAssumptions.model_validate(
            {"scenarios": [{"label": "explicit", "prices": {"A": price}}]}
        )


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1, 1000001])
def test_expiry_prices_require_explicit_finite_numbers(invalid):
    from pydantic import ValidationError

    from backend.app.schemas.funding_risk import ExpiryPriceScenario

    with pytest.raises(ValidationError):
        ExpiryPriceScenario(label="invalid", prices={"SPY": invalid})


def _option(underlying, strike, expiry, kind, quantity, side):
    date = datetime.strptime(expiry, "%Y-%m-%d")
    symbol = f"{underlying}{date:%y%m%d}{kind[0].upper()}{round(strike * 1000):08d}"
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


def _capture(monkeypatch, *, options, cash, debt, sell="A", amount=500.0, put=None):
    """Real capture/replay path with synthetic quotes; no monkeypatched specs."""
    monkeypatch.setattr(
        comparison_replay,
        "get_settings",
        lambda: SimpleNamespace(
            copilot_comparison_replay_enabled=True,
            risk_run_signing_secret="funding-oracle-synthetic-key-000000000000000000",
        ),
    )
    holdings = {
        "A": {"shares": 10, "asset_type": "stock"},
        "B": {"shares": 20, "asset_type": "etf"},
        "Y": {"shares": 8, "asset_type": "stock"},
    }
    holdings.update(dict(options))
    context = ActivePortfolioContext(BOOK, holdings, cash, debt, 0)
    dates = pd.bdate_range(end=NOW.date(), periods=101)
    scale = np.exp(0.0001 * (np.arange(101) - 100))
    spots = {"A": 100, "B": 50, "X": 40, "Y": 25}
    prices = pd.DataFrame({t: s * scale for t, s in spots.items()}, index=dates)

    def chain(underlying, expiry, kind, strike):
        date = datetime.strptime(expiry, "%Y-%m-%d")
        symbol = f"{underlying}{date:%y%m%d}{kind[0].upper()}{round(strike * 1000):08d}"
        return {"contract_symbol": symbol, "strike": strike, "bid": 1.9, "ask": 2.1}

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
        sale_fees=7.5,
        confirmed=True,
        put=CashSecuredPutRequest(
            **{
                "expected_portfolio_id": BOOK,
                "underlying": "B",
                "expiry": EXPIRY,
                "strike": 40.0,
                "premium_per_share": 2.5,
                "assumed_spot": 50.0,
                "contracts": 2,
                "fees_total": 3.0,
                "other_reserved_cash": 100.0,
                "cash_buffer": 50.0,
                "confirmed": True,
                "gross_settled_usd_cash_confirmed": True,
                "standard_contract_confirmed": True,
                **(put or {}),
            }
        ),
    )
    return snapshot, assumptions


@pytest.mark.parametrize("debt", [300, 1000])
def test_partial_repayment_two_contracts_and_reserves_against_closed_form(monkeypatch, debt):
    """Hand ledger: C=1000, D=debt, sell $500 of A (5 sh) fee 7.5, existing 2x X30P
    marked 2.00, new 2x B40P at 2.50 fee 3.0, reserve 150, APR 9%, T=30d, all assigned."""
    from backend.app.schemas.funding_risk import FundingRiskAssumptions
    from backend.app.services import funding_risk, funding_scenarios

    snapshot, assumptions = _capture(
        monkeypatch, options=[_option("X", 30, EXPIRY, "put", -2, "sell")], cash=1000, debt=debt
    )
    funding = funding_scenarios.calculate(snapshot, assumptions, now=NOW)
    result = funding_risk.calculate(
        snapshot,
        assumptions,
        FundingRiskAssumptions(
            scenarios=[{"label": "down", "prices": {"A": 90, "B": 35, "X": 25, "Y": 25}}],
            annual_borrowing_rate=0.09,
        ),
        now=NOW,
        funding_result=funding,
    )
    D = Decimal(debt)
    net = Decimal("492.5")  # 500 - 7.5
    repaid = min(net, D)
    # Initial equity: 1000 + 1000 + 200 stock, +1000 cash, -400 put mark, -debt.
    initial = Decimal(2200 + 1000 - 400) - D
    # Terminal stock book: A 90, B 35, Y 25, X 25 (200 X delivered at 30 in every row).
    base_assets = Decimal(10 * 90 + 20 * 35 + 8 * 25 + 200 * 25)  # 6800
    cand_assets = Decimal(5 * 90 + 220 * 35 + 8 * 25 + 200 * 25)  # 13350
    base_cash = Decimal(1000 - 6000)
    keep_cash = Decimal(1000) + net + Decimal(497) - Decimal(6000 + 8000)
    repay_cash = keep_cash - repaid

    def interest(principal):
        return principal * Decimal("0.09") * 30 / 365

    expected = {
        "no_action": (base_assets, base_cash, D),
        "sale_keep_cash_and_put": (cand_assets, keep_cash, D),
        "sale_repay_margin_and_put": (cand_assets, repay_cash, D - repaid),
    }
    outcomes = {row.kind: row for row in result.scenarios[0].outcomes}
    for kind, (assets, cash, principal) in expected.items():
        row = outcomes[kind]
        cost = Decimal(0) if principal == 0 else interest(principal)
        equity = assets + cash - principal - cost
        assert row.initial_net_equity == float(initial)
        assert row.stock_assets == float(assets)
        assert row.cash_before_interest == float(cash)
        assert row.principal_debt == float(principal)
        assert row.interest_cost == float(cost.quantize(Decimal("0.01")))
        assert row.total_pnl == pytest.approx(float(equity - initial), abs=0.0051)
        assert row.assignment_cash_paid == (6000.0 if kind == "no_action" else 14000.0)
        gap = Decimal(150) - (cash - cost)
        assert row.funding_gap == pytest.approx(float(gap), abs=0.0051)
        assert row.gross_leverage_if_gap_financed == pytest.approx(
            float((assets + cash - cost + gap) / equity), rel=1e-9
        )
        assert row.largest_position_weight == pytest.approx(
            float((Decimal(5000) if kind == "no_action" else Decimal(7700)) / assets), rel=1e-9
        )
    # Sold-stock opportunity cost (+50 on 5 shares of A falling 100->90), sale
    # fee (-7.5), and the new Put's net premium minus intrinsic (497 - 1000)
    # are the ONLY differences between keeping cash and no action.
    keep, base = outcomes["sale_keep_cash_and_put"], outcomes["no_action"]
    assert keep.total_pnl_before_interest - base.total_pnl_before_interest == pytest.approx(
        50 - 7.5 - 503
    )
    assert keep.incremental_pnl_vs_no_action == pytest.approx(
        keep.total_pnl - base.total_pnl, abs=0.0051
    )


def test_negative_equity_with_positive_assets_has_no_ratios(monkeypatch):
    from backend.app.schemas.funding_risk import FundingRiskAssumptions
    from backend.app.services import funding_risk, funding_scenarios

    snapshot, assumptions = _capture(
        monkeypatch, options=[_option("X", 30, EXPIRY, "put", -2, "sell")], cash=1000, debt=300
    )
    result = funding_risk.calculate(
        snapshot,
        assumptions,
        FundingRiskAssumptions(
            scenarios=[{"label": "crash", "prices": {"A": 90, "B": 5, "X": 5, "Y": 25}}],
            annual_borrowing_rate=0.09,
        ),
        now=NOW,
        funding_result=funding_scenarios.calculate(snapshot, assumptions, now=NOW),
    )
    for row in result.scenarios[0].outcomes:
        assert row.stock_assets > 0
        assert row.net_equity_after_interest < 0
        assert row.largest_position_weight is None
        assert row.gross_leverage_if_gap_financed is None
        # Unknown ratios do not erase the known dollar figures.
        assert row.total_pnl is not None and row.funding_gap is not None


@pytest.mark.parametrize(
    "options",
    [
        [
            _option("X", 30, EXPIRY, "put", -1, "sell"),
            _option("X", 25, "2026-11-20", "put", -1, "sell"),
        ],
        [_option("X", 30, EXPIRY, "put", 1, "buy")],
        [_option("Y", 30, EXPIRY, "call", -1, "sell")],
        [_option("X", 30, EXPIRY, "put", -1, "sell"), _option("X", 25, EXPIRY, "put", 1, "buy")],
    ],
    ids=["mixed-expiry-short-puts", "protective-long-put", "covered-call", "vertical-put-spread"],
)
def test_formerly_unsupported_books_are_valued_without_dropping_legs(monkeypatch, options):
    """Real holdings through capture -> replay -> composition. Every leg appears in
    the coverage relations; a missing residual rate is NOT COMPUTABLE, not zero."""
    from backend.app.schemas.funding_risk import FundingRiskAssumptions
    from backend.app.services import funding_scenarios

    snapshot, assumptions = _capture(monkeypatch, options=options, cash=20000, debt=300)
    assumptions.risk = FundingRiskAssumptions(
        scenarios=[
            {
                "label": "flat",
                "prices": {"A": 100, "B": 50, "Y": 25}
                | ({"X": 40} if any(leg["underlying"] == "X" for _, leg in options) else {}),
            }
        ],
        annual_borrowing_rate=0.05,
    )
    risk = funding_scenarios.calculate(snapshot, assumptions, now=NOW).account_risk
    symbols = {symbol for symbol, _ in options}
    relations = risk.alternatives[0].coverage_at_capture
    assert {r.contract for r in relations} | {r.covered_by for r in relations} >= symbols
    residual = any(leg["expiry"] > EXPIRY for _, leg in options)
    for row in risk.scenarios[0].outcomes:
        assert (row.total_pnl is None) == residual
        assert ("residual_rate_missing" in {n.code for n in row.not_computable}) == residual
