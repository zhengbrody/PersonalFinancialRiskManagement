"""
tests/unit/test_options_pricing.py
Unit tests for options_engine.py
Covers: bs_price, bs_greeks, implied_volatility, build_strategy,
        compute_pnl_at_expiry, strategy_metrics, compute_portfolio_greeks
"""

import pytest
import numpy as np
from unittest.mock import patch
from datetime import datetime, timedelta

from options_engine import (
    bs_price,
    bs_greeks,
    implied_volatility,
    build_strategy,
    compute_pnl_at_expiry,
    strategy_metrics,
    compute_portfolio_greeks,
    compute_strategy_greeks,
    OptionLeg,
    OptionStrategy,
    StockLeg,
    StockPosition,
    OptionPosition,
    CONTRACT_MULTIPLIER,
)


# ══════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════

# Use a far-future expiry so _time_to_expiry_years returns a positive T
_FAR_EXPIRY = (datetime.now() + timedelta(days=365)).strftime("%Y-%m-%d")


# ══════════════════════════════════════════════════════════════
#  bs_price tests
# ══════════════════════════════════════════════════════════════

class TestBSPrice:
    """Black-Scholes pricing sanity checks."""

    def test_put_call_parity(self):
        """C - P = S - K * exp(-rT) (put-call parity)."""
        S, K, T, r, sigma = 100.0, 100.0, 1.0, 0.05, 0.20
        call = bs_price(S, K, T, r, sigma, "call")
        put = bs_price(S, K, T, r, sigma, "put")
        expected = S - K * np.exp(-r * T)
        assert abs((call - put) - expected) < 1e-8

    def test_put_call_parity_otm(self):
        """Put-call parity holds for OTM strikes as well."""
        S, K, T, r, sigma = 100.0, 120.0, 0.5, 0.03, 0.35
        call = bs_price(S, K, T, r, sigma, "call")
        put = bs_price(S, K, T, r, sigma, "put")
        expected = S - K * np.exp(-r * T)
        assert abs((call - put) - expected) < 1e-8

    def test_atm_call_positive(self):
        """ATM call with vol > 0 must have positive price."""
        price = bs_price(100.0, 100.0, 1.0, 0.05, 0.20, "call")
        assert price > 0.0

    def test_t_zero_intrinsic_call(self):
        """At T=0, call value equals intrinsic."""
        assert bs_price(110.0, 100.0, 0.0, 0.05, 0.30, "call") == pytest.approx(10.0)
        assert bs_price(90.0, 100.0, 0.0, 0.05, 0.30, "call") == 0.0

    def test_t_zero_intrinsic_put(self):
        """At T=0, put value equals intrinsic."""
        assert bs_price(90.0, 100.0, 0.0, 0.05, 0.30, "put") == pytest.approx(10.0)
        assert bs_price(110.0, 100.0, 0.0, 0.05, 0.30, "put") == 0.0

    def test_sigma_zero_call_itm(self):
        """sigma=0 for ITM call returns discounted intrinsic."""
        S, K, T, r = 110.0, 100.0, 1.0, 0.05
        forward = S * np.exp(r * T)
        expected = (forward - K) * np.exp(-r * T)
        assert bs_price(S, K, T, r, 0.0, "call") == pytest.approx(expected, rel=1e-6)

    def test_sigma_zero_otm_call(self):
        """sigma=0 for OTM call returns 0 (forward < K)."""
        assert bs_price(90.0, 100.0, 1.0, 0.0, 0.0, "call") == 0.0


# ══════════════════════════════════════════════════════════════
#  bs_greeks tests
# ══════════════════════════════════════════════════════════════

class TestBSGreeks:
    """Greeks analytical tests."""

    def test_call_delta_range(self):
        """Call delta in [0, 1]."""
        g = bs_greeks(100.0, 100.0, 1.0, 0.05, 0.20, "call")
        assert 0.0 <= g["delta"] <= 1.0

    def test_put_delta_range(self):
        """Put delta in [-1, 0]."""
        g = bs_greeks(100.0, 100.0, 1.0, 0.05, 0.20, "put")
        assert -1.0 <= g["delta"] <= 0.0

    def test_call_put_delta_sum(self):
        """call delta + |put delta| = 1 (approximately, via N(d1))."""
        gc = bs_greeks(100.0, 100.0, 1.0, 0.05, 0.20, "call")
        gp = bs_greeks(100.0, 100.0, 1.0, 0.05, 0.20, "put")
        # call_delta - put_delta = 1
        assert gc["delta"] - gp["delta"] == pytest.approx(1.0, abs=1e-8)

    def test_gamma_positive(self):
        """Gamma is always positive for both calls and puts."""
        gc = bs_greeks(100.0, 100.0, 1.0, 0.05, 0.30, "call")
        gp = bs_greeks(100.0, 100.0, 1.0, 0.05, 0.30, "put")
        assert gc["gamma"] > 0.0
        assert gp["gamma"] > 0.0

    def test_gamma_same_for_call_put(self):
        """Gamma is the same for call and put at same strike."""
        gc = bs_greeks(100.0, 100.0, 1.0, 0.05, 0.30, "call")
        gp = bs_greeks(100.0, 100.0, 1.0, 0.05, 0.30, "put")
        assert gc["gamma"] == pytest.approx(gp["gamma"], rel=1e-8)

    def test_vega_positive(self):
        """Vega is positive (options value increases with vol)."""
        g = bs_greeks(100.0, 100.0, 1.0, 0.05, 0.20, "call")
        assert g["vega"] > 0.0


# ══════════════════════════════════════════════════════════════
#  implied_volatility tests
# ══════════════════════════════════════════════════════════════

class TestImpliedVolatility:
    """IV round-trip and edge-case tests."""

    def test_round_trip_call(self):
        """price -> IV -> price should recover original IV."""
        S, K, T, r, sigma = 100.0, 105.0, 0.5, 0.05, 0.25
        price = bs_price(S, K, T, r, sigma, "call")
        iv = implied_volatility(price, S, K, T, r, "call")
        assert iv is not None
        assert iv == pytest.approx(sigma, abs=1e-6)

    def test_round_trip_put(self):
        """Round-trip IV recovery for puts."""
        S, K, T, r, sigma = 100.0, 95.0, 1.0, 0.03, 0.40
        price = bs_price(S, K, T, r, sigma, "put")
        iv = implied_volatility(price, S, K, T, r, "put")
        assert iv is not None
        assert iv == pytest.approx(sigma, abs=1e-6)

    def test_zero_price_returns_none(self):
        """market_price <= 0 should return None."""
        assert implied_volatility(0.0, 100.0, 100.0, 1.0, 0.05, "call") is None
        assert implied_volatility(-1.0, 100.0, 100.0, 1.0, 0.05, "call") is None

    def test_expired_option_returns_none(self):
        """T <= 0 should return None."""
        assert implied_volatility(5.0, 100.0, 100.0, 0.0, 0.05, "call") is None


# ══════════════════════════════════════════════════════════════
#  build_strategy tests
# ══════════════════════════════════════════════════════════════

class TestBuildStrategy:
    """Ensure all 10 strategies construct without error."""

    STRATEGIES = [
        "long_call",
        "long_put",
        "covered_call",
        "protective_put",
        "bull_call_spread",
        "bear_put_spread",
        "iron_condor",
        "straddle",
        "strangle",
        "wheel",
    ]

    @pytest.mark.parametrize("name", STRATEGIES)
    @patch("options_engine._time_to_expiry_years", return_value=1.0)
    def test_build_all_strategies(self, mock_tte, name):
        """Each strategy name constructs an OptionStrategy successfully."""
        strat = build_strategy(name, "AAPL", S=150.0, expiry=_FAR_EXPIRY)
        assert isinstance(strat, OptionStrategy)
        assert strat.ticker == "AAPL"
        assert strat.spot == 150.0
        assert len(strat.option_legs) >= 1 or len(strat.stock_legs) >= 1

    @patch("options_engine._time_to_expiry_years", return_value=1.0)
    def test_unknown_strategy_raises(self, mock_tte):
        """Unknown strategy name should raise ValueError."""
        with pytest.raises(ValueError, match="Unknown strategy"):
            build_strategy("flying_butterfly_of_doom", "AAPL", S=150.0, expiry=_FAR_EXPIRY)


# ══════════════════════════════════════════════════════════════
#  compute_pnl_at_expiry tests
# ══════════════════════════════════════════════════════════════

class TestPnlAtExpiry:
    """P&L at expiration for simple strategies."""

    def test_long_call_profit_high_price(self):
        """Long call is profitable when underlying is well above strike + premium."""
        K, premium = 100.0, 5.0
        strat = OptionStrategy(
            name="Long Call",
            ticker="TEST",
            spot=100.0,
            option_legs=[
                OptionLeg(K, _FAR_EXPIRY, "call", 1, "buy", premium, 0.30),
            ],
        )
        prices = np.array([150.0])
        _, pnl = compute_pnl_at_expiry(strat, price_range=prices)
        # At S_T=150: intrinsic=50, pnl = (50-5)*1*100 = 4500
        assert pnl[0] == pytest.approx((50.0 - premium) * CONTRACT_MULTIPLIER)

    def test_long_call_loss_low_price(self):
        """Long call loses exactly the premium when OTM."""
        K, premium = 100.0, 5.0
        strat = OptionStrategy(
            name="Long Call",
            ticker="TEST",
            spot=100.0,
            option_legs=[
                OptionLeg(K, _FAR_EXPIRY, "call", 1, "buy", premium, 0.30),
            ],
        )
        prices = np.array([80.0])
        _, pnl = compute_pnl_at_expiry(strat, price_range=prices)
        # OTM: pnl = (0-5)*1*100 = -500
        assert pnl[0] == pytest.approx(-premium * CONTRACT_MULTIPLIER)


# ══════════════════════════════════════════════════════════════
#  strategy_metrics tests
# ══════════════════════════════════════════════════════════════

class TestStrategyMetrics:
    """Max profit, max loss, breakevens for known strategies."""

    def test_long_call_max_loss_is_premium(self):
        """Long call max loss = premium paid * qty * 100."""
        premium = 5.0
        strat = OptionStrategy(
            name="Long Call",
            ticker="TEST",
            spot=100.0,
            option_legs=[
                OptionLeg(100.0, _FAR_EXPIRY, "call", 1, "buy", premium, 0.30),
            ],
        )
        m = strategy_metrics(strat)
        # Max loss should be approximately -premium * 100
        assert m["max_loss"] == pytest.approx(-premium * CONTRACT_MULTIPLIER, rel=0.05)
        # Max profit should be unlimited (inf)
        assert m["max_profit"] == float("inf")

    def test_short_put_max_profit_is_premium(self):
        """Short (naked) put max profit is the premium received."""
        premium = 4.0
        strat = OptionStrategy(
            name="Short Put",
            ticker="TEST",
            spot=100.0,
            option_legs=[
                OptionLeg(100.0, _FAR_EXPIRY, "put", 1, "sell", premium, 0.30),
            ],
        )
        m = strategy_metrics(strat)
        # Max profit = premium * 100
        assert m["max_profit"] == pytest.approx(premium * CONTRACT_MULTIPLIER, rel=0.05)


# ══════════════════════════════════════════════════════════════
#  compute_portfolio_greeks tests
# ══════════════════════════════════════════════════════════════

class TestPortfolioGreeks:
    """Portfolio-level Greeks aggregation."""

    def test_stock_only_delta(self):
        """Stocks have delta = shares, gamma = 0."""
        stocks = [
            StockPosition("AAPL", 500, 150.0),
            StockPosition("MSFT", 300, 300.0),
        ]
        greeks = compute_portfolio_greeks(stocks, [])
        assert greeks["delta"] == pytest.approx(800.0)
        assert greeks["gamma"] == 0.0
        assert greeks["theta"] == 0.0
        assert greeks["vega"] == 0.0

    @patch("options_engine._time_to_expiry_years", return_value=0.5)
    def test_option_contributes_greeks(self, mock_tte):
        """An option position contributes non-zero delta and gamma."""
        options = [
            OptionPosition(
                ticker="AAPL",
                strike=150.0,
                expiry=_FAR_EXPIRY,
                option_type="call",
                contracts=10,
                sigma=0.30,
                spot=150.0,
            ),
        ]
        greeks = compute_portfolio_greeks([], options)
        # Call delta > 0, gamma > 0
        assert greeks["delta"] > 0.0
        assert greeks["gamma"] > 0.0

    @patch("options_engine._time_to_expiry_years", return_value=0.5)
    def test_mixed_portfolio_delta(self, mock_tte):
        """Stock + option portfolio has delta = shares + option_delta."""
        stocks = [StockPosition("AAPL", 100, 150.0)]
        options = [
            OptionPosition(
                ticker="AAPL",
                strike=150.0,
                expiry=_FAR_EXPIRY,
                option_type="call",
                contracts=1,
                sigma=0.30,
                spot=150.0,
            ),
        ]
        greeks = compute_portfolio_greeks(stocks, options)
        # Total delta should be > 100 (stock) because call adds positive delta
        assert greeks["delta"] > 100.0
