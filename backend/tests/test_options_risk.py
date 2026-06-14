"""Unit tests for the deterministic option portfolio-risk services:
``options_exposure`` (aggregates + flags) and ``options_scenarios`` (BS reprice
grid). Pure math over synthetic per-contract result dicts — no network.
"""

from __future__ import annotations

from backend.app.services import options_exposure as oe
from backend.app.services import options_scenarios as osc


def _res(**over):
    """A repriceable per-contract analytics dict (long ATM call by default)."""
    base = dict(
        underlying="AAPL",
        option_type="call",
        strike=100.0,
        expiry="2027-06-18",
        quantity=1.0,
        contract_multiplier=100.0,
        days_to_expiry=365,
        spot=100.0,
        mark=10.0,
        iv=0.30,
        greeks={"delta": 0.6, "gamma": 0.02, "theta": -0.05, "vega": 0.15, "rho": 0.1},
        delta_notional=6000.0,
        market_value=1000.0,
        moneyness="ATM",
        warnings=[],
    )
    base.update(over)
    return base


# ── exposure aggregates ───────────────────────────────────────────────────────


def test_exposure_nets_long_and_short_greeks():
    exp = oe.build_exposure(
        [
            _res(quantity=2.0),
            _res(
                option_type="put",
                quantity=-1.0,
                greeks={"delta": -0.4, "gamma": 0.02, "theta": -0.03, "vega": 0.1, "rho": -0.1},
            ),
        ]
    )
    # net delta = 2·0.6·100 + (−1)·(−0.4)·100 = 120 + 40 = 160
    assert exp["net_delta"] == 160.0
    assert exp["gross_delta"] == 160.0  # |120| + |40|
    assert exp["contracts"] == 2 and exp["short_contracts"] == 1


def test_short_gamma_flag():
    # one big short call → net gamma negative
    exp = oe.build_exposure([_res(quantity=-5.0)])
    assert exp["net_gamma"] < 0
    assert any(f["code"] == "short_gamma" for f in exp["flags"])


def test_uncovered_short_call_flag_without_equity_context():
    exp = oe.build_exposure([_res(quantity=-1.0)])
    f = [x for x in exp["flags"] if x["code"] == "uncovered_short_call"]
    assert f and f[0]["severity"] == "watch"  # no equity context → verify


def test_covered_short_call_no_flag_with_equity():
    exp = oe.build_exposure([_res(quantity=-1.0)], equity_shares_by_underlying={"AAPL": 100})
    assert not any(f["code"] == "uncovered_short_call" for f in exp["flags"])


def test_uncovered_short_call_high_when_undercovered():
    exp = oe.build_exposure(
        [_res(quantity=-2.0)], equity_shares_by_underlying={"AAPL": 50}  # need 200
    )
    f = [x for x in exp["flags"] if x["code"] == "uncovered_short_call"]
    assert f and f[0]["severity"] == "high"


def test_short_put_collateral_and_flag():
    exp = oe.build_exposure(
        [
            _res(
                option_type="put",
                quantity=-1.0,
                strike=100.0,
                greeks={"delta": -0.5, "gamma": 0.02, "theta": -0.03, "vega": 0.1, "rho": -0.1},
            )
        ],
        net_equity=10_000.0,
    )
    # cash-secured put collateral = 100 × 1 × 100 = 10,000 > 50% of 10k net equity
    assert exp["short_collateral_estimate"] == 10_000.0
    assert any(f["code"] == "under_collateralized_short" for f in exp["flags"])


def test_expiry_ladder_and_underlying_exposure():
    exp = oe.build_exposure(
        [_res(expiry="2027-06-18"), _res(underlying="MSFT", expiry="2027-09-17")]
    )
    assert len(exp["expiry_ladder"]) == 2
    assert {u["underlying"] for u in exp["underlying_exposure"]} == {"AAPL", "MSFT"}


def test_missing_data_flag():
    exp = oe.build_exposure([_res(greeks=None, warnings=["option chain unavailable"])])
    assert any(f["code"] == "missing_option_data" for f in exp["flags"])


def test_empty_results_zeroed():
    exp = oe.build_exposure([])
    assert exp["net_delta"] == 0.0 and exp["contracts"] == 0 and exp["flags"] == []


# ── scenario grid ─────────────────────────────────────────────────────────────


def test_scenario_grid_long_call_signs():
    out = osc.scenario_grid([_res()])
    assert out["repriced"] == 1 and out["skipped"] == []
    cells = {
        (c["underlying_shock"], c["iv_shock"], c["horizon"]): c["total_pnl"] for c in out["grid"]
    }
    # long call: −30% underlying (iv flat, today) loses; +30% gains.
    assert cells[(-0.30, 0.0, 0)] < 0
    assert cells[(0.30, 0.0, 0)] > 0
    # IV crush (−20 vol pts) at flat spot hurts a long option.
    assert cells[(0.0, -0.20, 0)] < 0


def test_scenario_grid_axes_and_top_positions():
    out = osc.scenario_grid([_res(), _res(underlying="NVDA", quantity=3.0)])
    assert out["underlying_shocks"] == osc.DEFAULT_UNDERLYING_SHOCKS
    assert "expiry" in out["horizons"]
    # 9 × 5 × 4 = 180 cells
    assert len(out["grid"]) == 180
    assert len(out["top_positions"]) == 2
    # the 3-lot NVDA call should dominate the loss ranking at the stress cell
    assert out["top_positions"][0]["underlying"] == "NVDA"


def test_scenario_grid_skips_unrepriceable():
    out = osc.scenario_grid([_res(iv=None, greeks=None)])
    assert out["repriced"] == 0 and len(out["skipped"]) == 1


def test_scenario_short_call_loses_on_rally():
    # short call: +30% underlying → loss (negative pnl).
    out = osc.scenario_grid([_res(quantity=-1.0)])
    cells = {
        (c["underlying_shock"], c["iv_shock"], c["horizon"]): c["total_pnl"] for c in out["grid"]
    }
    assert cells[(0.30, 0.0, 0)] < 0
    assert cells[(-0.30, 0.0, 0)] > 0  # short call gains when underlying falls
