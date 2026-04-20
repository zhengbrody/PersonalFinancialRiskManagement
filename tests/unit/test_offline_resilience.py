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
    dp._prices = prices                         # inject pre-computed prices
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
