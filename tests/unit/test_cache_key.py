"""
tests/unit/test_cache_key.py

Verify the analysis-cache key in app.py invalidates correctly when ANY
risk parameter changes (not just weights). Previously only weights_json
was checked, which gave a misleading "using cache" banner when mc_sims,
market_shock, etc. actually changed.

We don't boot the full Streamlit runtime — we reconstruct the tuple the
app uses to identify a cache hit and assert its equality semantics.
"""
from __future__ import annotations

import json
import pytest


def _cache_key(weights, period_years, mc_sims, mc_horizon, rf, shock):
    """Replica of app.py's cache-key construction (kept in sync manually)."""
    weights_json = json.dumps(weights, sort_keys=True)
    return (
        weights_json,
        period_years,
        mc_sims,
        mc_horizon,
        round(float(rf), 6),
        round(float(shock), 6),
    )


@pytest.fixture
def baseline():
    return {
        "weights": {"AAPL": 0.5, "GOOGL": 0.5},
        "period_years": 2,
        "mc_sims": 10000,
        "mc_horizon": 21,
        "rf": 0.045,
        "shock": -0.10,
    }


def test_identical_params_produce_same_key(baseline):
    k1 = _cache_key(**baseline)
    k2 = _cache_key(**baseline)
    assert k1 == k2


def test_weight_change_invalidates(baseline):
    k1 = _cache_key(**baseline)
    new = dict(baseline, weights={"AAPL": 0.6, "GOOGL": 0.4})
    assert _cache_key(**new) != k1


def test_mc_sims_change_invalidates(baseline):
    k1 = _cache_key(**baseline)
    assert _cache_key(**dict(baseline, mc_sims=5000)) != k1


def test_mc_horizon_change_invalidates(baseline):
    k1 = _cache_key(**baseline)
    assert _cache_key(**dict(baseline, mc_horizon=10)) != k1


def test_period_years_change_invalidates(baseline):
    k1 = _cache_key(**baseline)
    assert _cache_key(**dict(baseline, period_years=5)) != k1


def test_market_shock_change_invalidates(baseline):
    """This was the specific bug: market_shock was NOT in the old cache key."""
    k1 = _cache_key(**baseline)
    assert _cache_key(**dict(baseline, shock=-0.20)) != k1


def test_risk_free_change_invalidates(baseline):
    k1 = _cache_key(**baseline)
    assert _cache_key(**dict(baseline, rf=0.050)) != k1


def test_weights_order_independent(baseline):
    """Same weights in different insertion order → same key (json sort_keys)."""
    k1 = _cache_key(**baseline)
    reordered = {"GOOGL": 0.5, "AAPL": 0.5}
    assert _cache_key(**dict(baseline, weights=reordered)) == k1


def test_tiny_float_noise_rounded_away(baseline):
    """1e-10 noise on rf/shock should NOT invalidate (rounding to 6 decimals)."""
    k1 = _cache_key(**baseline)
    k2 = _cache_key(**dict(baseline, rf=0.045 + 1e-10, shock=-0.10 + 1e-10))
    assert k1 == k2
