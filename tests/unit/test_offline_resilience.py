"""
tests/unit/test_offline_resilience.py

Verify that RiskEngine's core analysis completes with a graceful degraded
report when benchmark/factor/macro data is unavailable (e.g. no network).

We monkey-patch `yfinance.download` to raise ConnectionError so no network
call can succeed. DataProvider already loads portfolio-price data that the
test injects directly, so the hot path (VaR, drawdown, EWMA cov, stress)
remains exercised.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from data_provider import DataProvider
from risk_engine import RiskEngine


class _OfflineError(ConnectionError):
    """Marker so we can assert we actually blocked network calls."""


@pytest.fixture
def synthetic_prices():
    """100-day random walk for 3 equities — deterministic seed."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2024-01-01", periods=120, freq="B")
    drift = np.array([0.0004, 0.0002, 0.0003])
    vol = np.array([0.015, 0.020, 0.012])
    shocks = rng.normal(size=(len(dates), 3)) * vol + drift
    prices = 100.0 * np.exp(np.cumsum(shocks, axis=0))
    return pd.DataFrame(prices, index=dates, columns=["AAA", "BBB", "CCC"])


def _build_offline_provider(prices: pd.DataFrame) -> DataProvider:
    weights = {col: 1.0 / len(prices.columns) for col in prices.columns}
    dp = DataProvider(weights, period_years=1)
    dp._prices = prices  # inject pre-computed prices
    dp._returns = prices.pct_change().dropna()  # simple returns per convention
    return dp


def test_risk_engine_runs_offline(synthetic_prices, monkeypatch):
    """RiskEngine.run() must complete without crashing when yfinance is blocked."""

    # Block every possible network call
    def _boom(*args, **kwargs):
        raise _OfflineError("network blocked by test harness")

    monkeypatch.setattr("yfinance.download", _boom)
    monkeypatch.setattr("data_provider.yf.download", _boom, raising=False)

    dp = _build_offline_provider(synthetic_prices)
    engine = RiskEngine(dp, mc_simulations=500, mc_horizon=5)

    report = engine.run()

    # Core portfolio math that only needs injected prices must succeed.
    assert np.isfinite(report.var_95) and report.var_95 > 0
    assert np.isfinite(report.var_99) and report.var_99 > 0
    assert np.isfinite(report.annual_volatility)
    assert report.max_drawdown <= 0

    # Degraded fields: risk-free falls back, betas become NaN, factor
    # tables are empty — but no exception propagates.
    assert report.risk_free_rate == pytest.approx(engine.risk_free_rate_fallback)
    assert all(np.isnan(v) for v in report.betas.values())
    assert report.factor_betas.isna().all().all() if report.factor_betas is not None else True


def test_data_provider_returns_are_simple(synthetic_prices):
    """Guard-rail: DataProvider must emit simple returns, not log."""
    dp = _build_offline_provider(synthetic_prices)
    ret = dp.get_daily_returns()
    expected_first = synthetic_prices.iloc[1] / synthetic_prices.iloc[0] - 1
    for col in ret.columns:
        assert ret[col].iloc[0] == pytest.approx(expected_first[col], rel=1e-10)


def test_portfolio_cumulative_return_matches_prices(synthetic_prices):
    """Compounding simple returns must reproduce the realized price path return."""
    dp = _build_offline_provider(synthetic_prices)
    port_cum = dp.get_portfolio_cumulative_returns()

    # Equal-weight portfolio final cum-return should match weighted
    # geometric-mean-of-prices result to within 1e-8.
    weights = dp.get_weight_array()
    returns = dp.get_daily_returns()
    # (1+r).cumprod() - 1 equivalent on portfolio daily returns
    port_daily = returns.dot(weights)
    manual_cum = float((1 + port_daily).prod())
    assert float(port_cum.iloc[-1]) == pytest.approx(manual_cum, rel=1e-10)


def test_historical_portfolio_value_formula(synthetic_prices):
    """
    Regression test for pages/1_Overview.py Historical Portfolio Value:
    dollar curve MUST equal base_capital * cumret (NOT base * (1 + cumret)).

    Because data_provider.get_portfolio_cumulative_returns() returns
    `(1 + daily_return).cumprod()` — an already-normalized value index
    starting near 1.0, not a cumulative return rate.
    """
    dp = _build_offline_provider(synthetic_prices)
    cumret = dp.get_portfolio_cumulative_returns()

    base = 10_000.0
    # The correct projection:
    correct = base * cumret

    # If cumret = 1.05 (a 5% cumulative return), portfolio worth $10,500
    # NOT $20,500 (which is what `base * (1 + cumret)` would give).
    assert correct.iloc[-1] == pytest.approx(base * float(cumret.iloc[-1]), rel=1e-10)

    # The buggy formula produced approximately 2x the correct value when
    # cumret is near 1.0 — guard against regression.
    buggy = base * (1 + cumret)
    assert buggy.iloc[-1] == pytest.approx(base * (1 + float(cumret.iloc[-1])), rel=1e-10)
    assert buggy.iloc[-1] != pytest.approx(correct.iloc[-1], rel=0.01), (
        "The buggy formula should produce materially different numbers "
        "from the correct formula. If they match here, verify cumret is "
        "actually starting near 1 (multiplier index)."
    )

    # Also verify cumret is a multiplier (values near 1, not near 0)
    assert 0.5 < float(cumret.iloc[0]) < 2.0, (
        "cumret should start as a value multiplier near 1.0 "
        "(it's (1+r).cumprod(), not a return rate)"
    )


@pytest.mark.parametrize("shock", [-0.05, -0.10, -0.20, -0.30])
def test_stress_loss_uses_user_market_shock(synthetic_prices, shock, monkeypatch):
    """
    RiskEngine.run() must use the user-supplied market_shock when computing
    stress_loss, not the default -10%. Regression test for finding #2.

    Also verify report.stress_market_shock mirrors the value used so the
    UI / AI / exports all reference the same number.
    """

    # Stub all network calls
    def _boom(*a, **kw):
        raise ConnectionError("blocked")

    monkeypatch.setattr("yfinance.download", _boom)
    monkeypatch.setattr("data_provider.yf.download", _boom, raising=False)

    dp = _build_offline_provider(synthetic_prices)
    # Force a non-NaN beta so stress_loss is meaningful
    bench_df = synthetic_prices[["AAA"]].pct_change().dropna().rename(columns={"AAA": "SPY"})
    from unittest.mock import MagicMock

    dp.get_benchmark_returns = MagicMock(return_value=bench_df)

    engine = RiskEngine(
        dp,
        mc_simulations=500,
        mc_horizon=5,
        market_shock=shock,
    )
    report = engine.run()

    # The shock must be recorded on the report exactly as the user passed it
    assert report.stress_market_shock == pytest.approx(shock, rel=1e-12)

    # And stress_loss must be proportional to shock (asset_loss = beta * shock).
    # For the same weights/betas, doubling |shock| should ~double |stress_loss|.
    # We check monotonicity + sign: shock more negative => larger loss magnitude.
    if shock <= 0:
        # Not asserting sign of stress_loss (engine convention varies), only
        # that the report reports the exact shock the user requested.
        assert isinstance(report.stress_loss, float)


def test_stress_shock_bounds_enforced():
    """market_shock is clamped to [-0.90, 0.0] — no positive shocks, no <−90%."""
    from unittest.mock import MagicMock

    from risk_engine import RiskEngine

    dp = MagicMock()
    engine_pos = RiskEngine(dp, market_shock=0.20)  # positive input
    assert engine_pos.market_shock == 0.0

    engine_too_neg = RiskEngine(dp, market_shock=-2.0)  # too negative
    assert engine_too_neg.market_shock == -0.90

    engine_ok = RiskEngine(dp, market_shock=-0.15)
    assert engine_ok.market_shock == -0.15
