"""Unit tests for libs.mindmarket_core.portfolio_math."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from libs.mindmarket_core import portfolio_math as pm


# ── Sharpe ─────────────────────────────────────────────────


def test_sharpe_basic():
    assert pm.sharpe_ratio(0.10, 0.15, 0.04) == pytest.approx(0.4, abs=1e-9)


def test_sharpe_zero_vol_returns_zero():
    assert pm.sharpe_ratio(0.10, 0.0, 0.04) == 0.0
    assert pm.sharpe_ratio(0.10, -0.01, 0.04) == 0.0  # defensive negative


# ── Margin call ────────────────────────────────────────────


def test_no_margin_loan():
    out = pm.margin_call_distance(100_000, 0)
    assert out["has_margin"] is False
    assert out["leverage"] == 1.0
    assert out["distance_to_call_pct"] == float("inf")


def test_with_margin_normal():
    out = pm.margin_call_distance(total_long=100_000, margin_loan=40_000, maintenance_ratio=0.25)
    assert out["has_margin"] is True
    # net = 60k, leverage = 100/60
    assert out["leverage"] == pytest.approx(100_000 / 60_000, rel=1e-9)
    # call value = 40_000 / (1 - 0.25) = 53_333.33
    assert out["margin_call_portfolio_value"] == pytest.approx(53_333.33, abs=0.01)
    assert 0 < out["distance_to_call_pct"] < 1


# ── Compliance ─────────────────────────────────────────────


def test_no_violations():
    weights = {"A": 0.10, "B": 0.10, "C": 0.10}
    sectors = {"A": "Tech", "B": "Energy", "C": "Health"}
    assert pm.check_compliance(weights, sectors) == []


def test_single_stock_violation():
    weights = {"A": 0.30}
    sectors = {"A": "Tech"}
    v = pm.check_compliance(weights, sectors)
    assert any(x["rule"] == "max_single_stock_weight" for x in v)


def test_sector_violation():
    weights = {"A": 0.10, "B": 0.10, "C": 0.15, "D": 0.10}
    sectors = {"A": "Tech", "B": "Tech", "C": "Tech", "D": "Energy"}
    v = pm.check_compliance(weights, sectors)
    sector_v = [x for x in v if x["rule"] == "max_sector_weight"]
    assert len(sector_v) == 1
    assert sector_v[0]["sector"] == "Tech"


def test_floating_point_tolerance_no_false_violations():
    """0.15 + epsilon should NOT trip the 0.15 limit."""
    weights = {"A": 0.15 + 1e-10}
    sectors = {"A": "Tech"}
    assert pm.check_compliance(weights, sectors) == []


# ── Adjust for compliance ──────────────────────────────────


def test_adjust_caps_overweight_position():
    weights = {"A": 0.50, "B": 0.30, "C": 0.20}
    sectors = {"A": "Tech", "B": "Energy", "C": "Health"}
    out = pm.adjust_for_compliance(weights, sectors)
    assert all(w <= 0.15 + 1e-9 for w in out.values())
    assert out["A"] < 0.50


def test_adjust_does_not_renormalize_to_one():
    """Per ADR-0001 docstring: do NOT renormalize. Residual is implicit cash."""
    weights = {"A": 0.50, "B": 0.30, "C": 0.20}
    sectors = {"A": "Tech", "B": "Energy", "C": "Health"}
    out = pm.adjust_for_compliance(weights, sectors)
    assert sum(out.values()) <= 1.0 + 1e-9
    # In this scenario all 3 hit the per-stock cap; sum = 0.45
    assert sum(out.values()) == pytest.approx(0.45, abs=1e-6)


def test_adjust_at_cap_already_unchanged():
    """Inputs exactly at the cap stay; the algorithm only kicks in when
    something exceeds the cap. (Sub-cap inputs *do* get pushed up via
    slack redistribution — that's by design — see test_adjust_caps_overweight_position.)"""
    weights = {"A": 0.15, "B": 0.15, "C": 0.15}
    sectors = {"A": "Tech", "B": "Energy", "C": "Health"}
    out = pm.adjust_for_compliance(weights, sectors)
    for k, v in weights.items():
        assert out[k] == pytest.approx(v, abs=1e-9)


# ── Efficient frontier ─────────────────────────────────────


def test_frontier_returns_expected_keys():
    rng = np.random.default_rng(0)
    rets = pd.DataFrame(rng.normal(0, 0.01, (252, 4)), columns=["A", "B", "C", "D"])
    out = pm.efficient_frontier(rets, risk_free=0.04, n_points=10)
    for key in ("frontier_vols", "frontier_rets", "frontier_weights",
                "max_sharpe_weights", "min_var_weights", "tickers"):
        assert key in out
    assert len(out["tickers"]) == 4
    # Min-var and max-sharpe weights sum to 1
    assert sum(out["min_var_weights"].values()) == pytest.approx(1.0, abs=1e-4)
    assert sum(out["max_sharpe_weights"].values()) == pytest.approx(1.0, abs=1e-4)


# ── Drawdown ───────────────────────────────────────────────


def test_drawdown_no_episodes():
    flat = pd.Series([0.0] * 100)
    out = pm.drawdown_statistics(flat)
    assert out["num_episodes"] == 0
    assert out["pct_time_underwater"] == 0.0


def test_drawdown_one_episode():
    # 10 below, 10 above, 10 below
    s = pd.Series([-0.05] * 10 + [-0.001] * 10 + [-0.05] * 10)
    out = pm.drawdown_statistics(s)
    assert out["num_episodes"] >= 1
    assert out["pct_time_underwater"] > 0


def test_drawdown_currently_underwater():
    s = pd.Series([-0.001] * 10 + [-0.05] * 10)
    out = pm.drawdown_statistics(s)
    assert out["is_currently_underwater"] is True
    assert out["current_episode_days"] == 10
