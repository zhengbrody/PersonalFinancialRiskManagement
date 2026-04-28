"""Unit tests for libs.mindmarket_core.black_scholes.

Strategy: textbook reference values + edge cases + IV roundtrip
+ put-call parity. No fixtures, no I/O.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from libs.mindmarket_core import black_scholes as bs


# ── Textbook reference: Hull 9th ed., Table 17.4 region ──────────


def test_atm_1y_call_matches_textbook():
    """S=100 K=100 T=1 r=5% sigma=20% → call ≈ 10.4506 (Hull eq. 17.5)."""
    price = bs.bs_price(S=100, K=100, T=1.0, r=0.05, sigma=0.20, option_type="call")
    assert price == pytest.approx(10.4506, abs=1e-3)


def test_atm_1y_put_matches_textbook():
    """Same params, put ≈ 5.5735."""
    price = bs.bs_price(S=100, K=100, T=1.0, r=0.05, sigma=0.20, option_type="put")
    assert price == pytest.approx(5.5735, abs=1e-3)


def test_put_call_parity():
    """C - P = S - K * exp(-rT) for European options on non-dividend stock."""
    S, K, T, r, sigma = 105, 100, 0.5, 0.04, 0.25
    c = bs.bs_price(S, K, T, r, sigma, "call")
    p = bs.bs_price(S, K, T, r, sigma, "put")
    parity_lhs = c - p
    parity_rhs = S - K * math.exp(-r * T)
    assert parity_lhs == pytest.approx(parity_rhs, abs=1e-6)


# ── Edge cases ────────────────────────────────────────────────


def test_at_expiry_returns_intrinsic_value():
    assert bs.bs_price(S=110, K=100, T=0, r=0.05, sigma=0.2, option_type="call") == 10.0
    assert bs.bs_price(S=90, K=100, T=0, r=0.05, sigma=0.2, option_type="put") == 10.0
    assert bs.bs_price(S=90, K=100, T=0, r=0.05, sigma=0.2, option_type="call") == 0.0


def test_zero_vol_returns_discounted_intrinsic():
    """Zero vol = deterministic forward."""
    S, K, T, r = 100, 100, 1.0, 0.05
    forward = S * math.exp(r * T)
    df = math.exp(-r * T)
    expected = max(forward - K, 0.0) * df
    actual = bs.bs_price(S, K, T, r, sigma=0.0, option_type="call")
    assert actual == pytest.approx(expected, abs=1e-10)


def test_invalid_inputs_raise():
    with pytest.raises(ValueError, match="option_type"):
        bs.bs_price(100, 100, 1, 0.05, 0.2, option_type="garbage")
    with pytest.raises(ValueError, match="positive"):
        bs.bs_price(0, 100, 1, 0.05, 0.2)
    with pytest.raises(ValueError, match="negative"):
        bs.bs_price(100, 100, -1, 0.05, 0.2)


# ── Greeks ────────────────────────────────────────────────────


def test_atm_call_delta_above_half():
    """ATM call delta is slightly > 0.5 because of the (r + σ²/2)T drift in d1."""
    g = bs.bs_greeks(S=100, K=100, T=1.0, r=0.05, sigma=0.20, option_type="call")
    assert 0.5 < g["delta"] < 0.7


def test_put_delta_negative():
    g = bs.bs_greeks(S=100, K=100, T=1.0, r=0.05, sigma=0.20, option_type="put")
    assert -1.0 < g["delta"] < 0.0


def test_gamma_same_for_call_and_put():
    """Gamma should be identical for matched call/put (put-call parity on Γ)."""
    gc = bs.bs_greeks(S=100, K=100, T=1.0, r=0.05, sigma=0.2, option_type="call")
    gp = bs.bs_greeks(S=100, K=100, T=1.0, r=0.05, sigma=0.2, option_type="put")
    assert gc["gamma"] == pytest.approx(gp["gamma"], abs=1e-10)


def test_greeks_at_expiry_have_zero_gamma_theta_vega():
    g = bs.bs_greeks(S=100, K=100, T=0.0, r=0.05, sigma=0.2, option_type="call")
    assert g["gamma"] == 0.0
    assert g["theta"] == 0.0
    assert g["vega"] == 0.0


# ── Implied volatility ────────────────────────────────────────


def test_iv_roundtrip_recovers_input_sigma():
    for sigma_in in [0.10, 0.20, 0.35, 0.60]:
        S, K, T, r = 100, 100, 0.5, 0.03
        market = bs.bs_price(S, K, T, r, sigma_in, "call")
        iv = bs.implied_volatility(market, S, K, T, r, "call")
        assert iv == pytest.approx(sigma_in, abs=1e-5)


def test_iv_returns_none_for_impossible_price():
    # Below intrinsic
    assert bs.implied_volatility(market_price=0.01, S=110, K=100, T=1.0, r=0.05, option_type="call") is None
    # Above max for call (≥ S)
    assert bs.implied_volatility(market_price=200, S=100, K=100, T=1.0, r=0.05, option_type="call") is None
    # Negative price
    assert bs.implied_volatility(market_price=-1, S=100, K=100, T=1.0, r=0.05, option_type="call") is None
