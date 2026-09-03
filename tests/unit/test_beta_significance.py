"""
test_beta_significance.py
Tests for the multi-factor Beta statistical-significance functionality
"""

from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest

import risk_engine
from data_provider import DataProvider
from risk_engine import RiskEngine

# ══════════════════════════════════════════════════════════════
#  Tests for the _compute_beta_with_significance method
# ══════════════════════════════════════════════════════════════


def test_beta_significance_highly_correlated():
    """Test highly correlated data (beta should be significant)"""
    # Create perfectly correlated data (beta=1.5, low noise)
    np.random.seed(42)
    n_samples = 252
    X = np.random.randn(n_samples)
    y = 1.5 * X + np.random.randn(n_samples) * 0.05  # beta=1.5, low noise

    # Create a mock DataProvider and RiskEngine
    mock_dp = Mock(spec=DataProvider)
    engine = RiskEngine(mock_dp)

    # Call the significance method
    stats = engine._compute_beta_with_significance(y, X)

    # Verify results
    assert 1.4 < stats["beta"] < 1.6, f"Beta should be close to 1.5, actual: {stats['beta']}"
    assert (
        stats["p_value"] < 0.001
    ), f"p-value should be very small (highly significant), actual: {stats['p_value']}"
    assert stats["is_significant"] == True, "beta should be significant"
    assert stats["r_squared"] > 0.9, f"R² should be high, actual: {stats['r_squared']}"
    assert not np.isnan(stats["t_stat"]), "t-statistic should not be NaN"
    assert not np.isnan(stats["std_error"]), "standard error should not be NaN"


def test_beta_significance_no_correlation():
    """Test uncorrelated data (beta should be insignificant)"""
    # Create completely independent random data
    np.random.seed(42)
    n_samples = 252
    X = np.random.randn(n_samples)
    y = np.random.randn(n_samples)  # completely independent

    mock_dp = Mock(spec=DataProvider)
    engine = RiskEngine(mock_dp)

    stats = engine._compute_beta_with_significance(y, X)

    # Verify results
    assert (
        stats["p_value"] > 0.05
    ), f"p-value should be greater than 0.05 (insignificant), actual: {stats['p_value']}"
    assert stats["is_significant"] == False, "beta should not be significant"
    assert stats["r_squared"] < 0.1, f"R² should be low, actual: {stats['r_squared']}"


def test_beta_significance_small_sample():
    """Test small sample (may be insignificant, depending on noise)"""
    np.random.seed(42)
    n_samples = 30  # only 30 samples
    X = np.random.randn(n_samples)
    y = 0.8 * X + np.random.randn(n_samples) * 0.5  # beta=0.8, moderate noise

    mock_dp = Mock(spec=DataProvider)
    engine = RiskEngine(mock_dp)

    stats = engine._compute_beta_with_significance(y, X)

    # A small sample should still return reasonable results
    assert "beta" in stats
    assert "p_value" in stats
    assert "t_stat" in stats
    assert not np.isnan(stats["beta"])
    assert 0 <= stats["p_value"] <= 1 or np.isnan(stats["p_value"])


def test_beta_significance_negative_beta():
    """Test negative beta coefficient"""
    np.random.seed(42)
    n_samples = 252
    X = np.random.randn(n_samples)
    y = -1.2 * X + np.random.randn(n_samples) * 0.1  # negative beta, low noise

    mock_dp = Mock(spec=DataProvider)
    engine = RiskEngine(mock_dp)

    stats = engine._compute_beta_with_significance(y, X)

    # Verify results
    assert -1.3 < stats["beta"] < -1.1, f"Beta should be close to -1.2, actual: {stats['beta']}"
    assert stats["p_value"] < 0.001, "negative beta should also be significant"
    assert stats["is_significant"] == True
    assert stats["t_stat"] < 0, "t-statistic of a negative beta should be negative"


def test_beta_significance_edge_cases():
    """Test edge cases"""
    mock_dp = Mock(spec=DataProvider)
    engine = RiskEngine(mock_dp)

    # Test 1: constant array (no variation)
    X_const = np.ones(100)
    y_const = np.random.randn(100)

    stats_const = engine._compute_beta_with_significance(y_const, X_const)

    # Should return NaN or near zero (X has no variation, so the X'X matrix is singular)
    # In practice lstsq will attempt to handle it and may return a very small value or NaN
    assert np.isnan(stats_const["beta"]) or abs(stats_const["beta"]) < 1.0

    # Test 2: data containing NaN
    X_nan = np.array([1, 2, np.nan, 4, 5])
    y_nan = np.array([2, 4, 6, 8, 10])

    # This should be handled or return a reasonable error
    try:
        stats_nan = engine._compute_beta_with_significance(y_nan, X_nan)
        # If no error is raised, check the result
        assert "beta" in stats_nan
    except (ValueError, np.linalg.LinAlgError):
        # Raising an exception is allowed
        pass


# ══════════════════════════════════════════════════════════════
#  Tests for the _compute_multi_factor_betas method (integration test)
# ══════════════════════════════════════════════════════════════


@pytest.mark.integration
def test_multi_factor_betas_with_significance():
    """Integration test: multi-factor beta calculation and significance test.
    Benchmark data now flows through DataProvider.get_benchmark_returns,
    not yfinance directly, so we stub the provider method."""
    # Create mock data
    dates = pd.date_range("2023-01-01", periods=252, freq="D")

    # Mock asset returns
    np.random.seed(42)
    asset_returns = pd.DataFrame(
        {
            "AAPL": np.random.randn(252) * 0.02,
            "TSLA": np.random.randn(252) * 0.03,
        },
        index=dates,
    )

    # Mock factor returns (SPY, QQQ, etc.) — provided directly at the simple-return level
    np.random.seed(7)
    factor_ret = pd.DataFrame(
        {
            "SPY": np.random.randn(252) * 0.01,
            "QQQ": np.random.randn(252) * 0.015,
            "GLD": np.random.randn(252) * 0.008,
            "TLT": np.random.randn(252) * 0.01,
            "IWM": np.random.randn(252) * 0.012,
            "VTV": np.random.randn(252) * 0.009,
        },
        index=dates,
    )

    # Mock DataProvider: benchmark returns are now provider-sourced
    mock_dp = Mock(spec=DataProvider)
    mock_dp.start_date = dates[0]
    mock_dp.end_date = dates[-1]
    mock_dp.get_benchmark_returns.return_value = factor_ret
    mock_dp.get_risk_free_rate.return_value = 0.045

    engine = RiskEngine(mock_dp)

    # Call the multi-factor beta calculation
    result = engine._compute_multi_factor_betas(asset_returns)

    # Verify the return structure
    assert "betas" in result, "should return betas"
    assert "significance" in result, "should return significance"

    betas_df = result["betas"]
    sig_df = result["significance"]

    # Verify the betas DataFrame
    assert isinstance(betas_df, pd.DataFrame)
    assert not betas_df.empty
    assert "AAPL" in betas_df.index
    assert "TSLA" in betas_df.index

    # Verify the significance DataFrame
    assert isinstance(sig_df, pd.DataFrame)
    assert not sig_df.empty
    assert "Ticker" in sig_df.columns
    assert "Factor" in sig_df.columns
    assert "Beta" in sig_df.columns
    assert "t_stat" in sig_df.columns
    assert "p_value" in sig_df.columns
    assert "is_significant" in sig_df.columns
    assert "r_squared" in sig_df.columns

    # Check that each asset has statistics for all 6 factors
    for ticker in ["AAPL", "TSLA"]:
        ticker_data = sig_df[sig_df["Ticker"] == ticker]
        assert len(ticker_data) == 6, f"{ticker} should have 6 factors"

        # Check that all required fields exist and are correctly formatted
        for _, row in ticker_data.iterrows():
            assert "Beta" in row
            assert "t_stat" in row
            assert "p_value" in row
            assert isinstance(row["is_significant"], (bool, np.bool_))


@pytest.mark.integration
def test_portfolio_factor_betas_shape_is_factor_indexed():
    """Portfolio-level factor regression: ONE row per factor, indexed by
    factor ticker, with columns beta/r_squared/t_stat/p_value. This is the
    shape the report API serialises — distinct from the per-asset matrix
    `_compute_multi_factor_betas` returns. Guards the serializer contract
    (a mismatch here silently blanked the report's Factor-betas table)."""
    dates = pd.date_range("2023-01-01", periods=252, freq="D")
    np.random.seed(42)
    asset_returns = pd.DataFrame(
        {"AAPL": np.random.randn(252) * 0.02, "TSLA": np.random.randn(252) * 0.03},
        index=dates,
    )
    np.random.seed(7)
    factor_ret = pd.DataFrame(
        {tk: np.random.randn(252) * 0.01 for tk in ["SPY", "QQQ", "GLD", "TLT", "IWM", "VTV"]},
        index=dates,
    )
    mock_dp = Mock(spec=DataProvider)
    mock_dp.get_benchmark_returns.return_value = factor_ret

    engine = RiskEngine(mock_dp)
    weights = np.array([0.6, 0.4])
    fb = engine._compute_portfolio_factor_betas(asset_returns, weights)

    assert isinstance(fb, pd.DataFrame)
    # Indexed by factor ticker, NOT by holding ticker.
    assert set(fb.index) == {"SPY", "QQQ", "GLD", "TLT", "IWM", "VTV"}
    assert "AAPL" not in fb.index
    # Exactly the columns the serializer reads.
    assert set(fb.columns) == {"beta", "r_squared", "t_stat", "p_value"}


# ══════════════════════════════════════════════════════════════
#  Regression: holding a ticker that is ALSO a factor ETF
#  (duplicate column labels in the aligned frame)
# ══════════════════════════════════════════════════════════════

FACTOR_TICKERS_ORDER = ["SPY", "QQQ", "GLD", "TLT", "IWM", "VTV"]
FACTOR_NAMES = [
    "S&P 500",
    "NASDAQ 100",
    "Gold",
    "US Treasury 20Y+",
    "Small Cap (Size)",
    "Value (Style)",
]


def _factor_frame(dates, seed=5):
    """Deterministic, network-free factor return frame (all 6 factors)."""
    np.random.seed(seed)
    return pd.DataFrame(
        {tk: np.random.randn(len(dates)) * 0.01 for tk in FACTOR_TICKERS_ORDER},
        index=dates,
    )


def _engine_with_factors(factor_ret):
    mock_dp = Mock(spec=DataProvider)
    mock_dp.get_benchmark_returns.return_value = factor_ret
    return RiskEngine(mock_dp)


def test_factor_betas_when_portfolio_holds_a_factor_etf():
    """A holding that is ALSO a factor ETF must still get real factor betas.

    Regression for the production defect: `pd.concat([returns, factor_ret])`
    produced DUPLICATE column labels when a user held SPY/QQQ/GLD/..., so
    `aligned[ticker]` returned a (T, 2) DataFrame. `y` was then 2-D and
    `np.column_stack([ones, factor])` raised
    `ValueError: setting an array element with a sequence`, which the
    per-factor try/except swallowed into a warning — leaving that holding's
    whole factor-beta row NaN in the Risk Report (HTTP 200, silently wrong).
    A real session holding SPY + QQQ + GLD logged exactly 18 such warnings
    (3 tickers x 6 factors).
    """
    dates = pd.date_range("2023-01-03", periods=252, freq="B")
    factor_ret = _factor_frame(dates)
    np.random.seed(11)
    # AAPL is a plain holding; SPY is held AND is a factor.
    asset_returns = pd.DataFrame(
        {"AAPL": np.random.randn(252) * 0.02, "SPY": factor_ret["SPY"]},
        index=dates,
    )
    engine = _engine_with_factors(factor_ret)

    with patch.object(risk_engine.logger, "warning") as mock_warn:
        result = engine._compute_multi_factor_betas(asset_returns)

    betas = result["betas"]
    sig = result["significance"]

    # Every ticker x factor cell is a real number — no NaN row for SPY.
    assert set(betas.index) == {"AAPL", "SPY"}
    assert set(betas.columns) == set(FACTOR_NAMES)
    assert not betas.isna().any().any(), f"NaN betas present:\n{betas}"
    assert np.isfinite(betas.to_numpy()).all()

    # Full significance table: 2 tickers x 6 factors, all finite.
    assert len(sig) == 12
    assert not sig["Beta"].isna().any()
    assert not sig["t_stat"].isna().any()

    # And the failure path never fired.
    failures = [
        c
        for c in mock_warn.call_args_list
        if "Beta calculation failed" in str(c.args[0] if c.args else "")
    ]
    assert failures == [], f"unexpected beta-failure warnings: {failures}"

    # Sanity: SPY regressed on the S&P 500 factor (its own series) is ~1.0.
    assert betas.loc["SPY", "S&P 500"] == pytest.approx(1.0, abs=1e-9)


def test_held_factor_etf_does_not_corrupt_other_holdings_betas():
    """The duplicate column ALSO silently corrupted every OTHER holding.

    With two identical (collinear) SPY columns, the intended univariate
    regression became bivariate and `lstsq`'s minimum-norm solution split the
    coefficient evenly across them — so every other holding's S&P 500 beta
    came out at exactly HALF its true value, with no exception and no
    warning. This asserts a holding's betas are unaffected by whether a
    factor ETF happens to also be in the book.
    """
    dates = pd.date_range("2023-01-03", periods=252, freq="B")
    factor_ret = _factor_frame(dates)
    np.random.seed(11)
    aapl = pd.Series(np.random.randn(252) * 0.02, index=dates)

    engine = _engine_with_factors(factor_ret)
    without_spy = engine._compute_multi_factor_betas(pd.DataFrame({"AAPL": aapl}))["betas"]
    with_spy = engine._compute_multi_factor_betas(
        pd.DataFrame({"AAPL": aapl, "SPY": factor_ret["SPY"]})
    )["betas"]

    for factor_name in FACTOR_NAMES:
        assert with_spy.loc["AAPL", factor_name] == pytest.approx(
            without_spy.loc["AAPL", factor_name], rel=1e-12, abs=1e-15
        ), f"AAPL's {factor_name} beta changed just because SPY is held"


def test_factor_betas_unchanged_for_non_overlapping_holdings():
    """No-overlap book: betas are numerically IDENTICAL to the pre-fix values.

    Values pinned from the pre-fix implementation (captured by stashing the
    fix and re-running), so this fails if the namespacing change ever alters
    the regression itself. The fix only relabels columns.
    """
    dates = pd.date_range("2023-01-03", periods=252, freq="B")
    factor_ret = _factor_frame(dates)
    np.random.seed(11)
    asset_returns = pd.DataFrame(
        {"AAPL": np.random.randn(252) * 0.02, "MSFT": np.random.randn(252) * 0.017},
        index=dates,
    )
    engine = _engine_with_factors(factor_ret)
    result = engine._compute_multi_factor_betas(asset_returns)
    betas = result["betas"]

    expected = {
        "AAPL": {
            "S&P 500": 0.13303900643282837,
            "NASDAQ 100": 0.03847059801466438,
            "Gold": -0.2318530573180178,
            "US Treasury 20Y+": 0.15434122278049053,
            "Small Cap (Size)": 0.14318065463545648,
            "Value (Style)": -0.13871995449485316,
        },
        "MSFT": {
            "S&P 500": -0.08078502279706481,
            "NASDAQ 100": -0.017231905282481516,
            "Gold": 0.011695063154347598,
            "US Treasury 20Y+": -0.13289643756804664,
            "Small Cap (Size)": 0.09977597017402275,
            "Value (Style)": 0.11657520833234543,
        },
    }
    for ticker, row in expected.items():
        for factor_name, value in row.items():
            assert betas.loc[ticker, factor_name] == pytest.approx(
                value, rel=1e-12, abs=1e-15
            ), f"{ticker}/{factor_name} drifted"

    # The significance statistics are equally untouched.
    sig = result["significance"]
    r = sig[(sig["Ticker"] == "AAPL") & (sig["Factor"] == "S&P 500")].iloc[0]
    assert r["Beta"] == pytest.approx(0.13303900643282837, rel=1e-12)
    assert r["t_stat"] == pytest.approx(1.0574209077296437, rel=1e-12)
    assert r["p_value"] == pytest.approx(0.29134021890567774, rel=1e-12)
    assert r["r_squared"] == pytest.approx(0.004452641217646769, rel=1e-12)
    assert r["std_error"] == pytest.approx(0.12581461692342777, rel=1e-12)


def test_portfolio_factor_betas_with_held_factor_etf():
    """The portfolio-level regression has no duplicate-label hazard.

    `_compute_portfolio_factor_betas` concats only the renamed portfolio
    series (`__port__`) with the factor frame — the holdings frame never
    enters the concat — so holding SPY/QQQ/GLD cannot duplicate a label.
    Guards that this stays true.
    """
    dates = pd.date_range("2023-01-03", periods=252, freq="B")
    factor_ret = _factor_frame(dates)
    np.random.seed(11)
    asset_returns = pd.DataFrame(
        {
            "AAPL": np.random.randn(252) * 0.02,
            "SPY": factor_ret["SPY"],
            "QQQ": factor_ret["QQQ"],
            "GLD": factor_ret["GLD"],
        },
        index=dates,
    )
    engine = _engine_with_factors(factor_ret)

    with patch.object(risk_engine.logger, "warning") as mock_warn:
        fb = engine._compute_portfolio_factor_betas(asset_returns, np.array([0.4, 0.2, 0.2, 0.2]))

    assert fb is not None
    assert set(fb.index) == set(FACTOR_TICKERS_ORDER)
    assert not fb["beta"].isna().any()
    assert mock_warn.call_args_list == []


# ══════════════════════════════════════════════════════════════
#  Performance test
# ══════════════════════════════════════════════════════════════


def test_beta_significance_performance():
    """Test the performance of the significance test (should be fast)"""
    import time

    np.random.seed(42)
    n_samples = 252
    X = np.random.randn(n_samples)
    y = 1.5 * X + np.random.randn(n_samples) * 0.1

    mock_dp = Mock(spec=DataProvider)
    engine = RiskEngine(mock_dp)

    # Run 100 times and measure the elapsed time
    start = time.time()
    for _ in range(100):
        stats = engine._compute_beta_with_significance(y, X)
    elapsed = time.time() - start

    # 100 runs should complete within 1 second
    assert elapsed < 1.0, f"100 beta computations took {elapsed:.2f}s, too slow"


# ══════════════════════════════════════════════════════════════
#  Documentation test (ensure the return structure matches the docs)
# ══════════════════════════════════════════════════════════════


def test_beta_significance_return_structure():
    """Test that the structure of the returned dict matches the documentation"""
    np.random.seed(42)
    n_samples = 252
    X = np.random.randn(n_samples)
    y = 1.5 * X + np.random.randn(n_samples) * 0.1

    mock_dp = Mock(spec=DataProvider)
    engine = RiskEngine(mock_dp)

    stats = engine._compute_beta_with_significance(y, X)

    # Verify all required fields exist
    required_fields = [
        "beta",
        "intercept",
        "t_stat",
        "p_value",
        "is_significant",
        "r_squared",
        "std_error",
    ]

    for field in required_fields:
        assert field in stats, f"missing required field: {field}"

    # Verify types
    assert isinstance(stats["beta"], (float, np.floating))
    assert isinstance(stats["intercept"], (float, np.floating))
    assert isinstance(stats["t_stat"], (float, np.floating))
    assert isinstance(stats["p_value"], (float, np.floating))
    assert isinstance(stats["is_significant"], (bool, np.bool_))
    assert isinstance(stats["r_squared"], (float, np.floating))
    assert isinstance(stats["std_error"], (float, np.floating))

    # Verify reasonable ranges
    assert 0 <= stats["r_squared"] <= 1, f"R² should be in [0,1], actual: {stats['r_squared']}"
    assert 0 <= stats["p_value"] <= 1 or np.isnan(
        stats["p_value"]
    ), f"p-value should be in [0,1], actual: {stats['p_value']}"
    assert stats["std_error"] >= 0 or np.isnan(
        stats["std_error"]
    ), f"standard error should be non-negative, actual: {stats['std_error']}"


if __name__ == "__main__":
    # Run basic tests
    print("Running basic beta significance tests...")

    print("\n1. Testing highly correlated data...")
    test_beta_significance_highly_correlated()
    print("✓ Passed")

    print("\n2. Testing no correlation...")
    test_beta_significance_no_correlation()
    print("✓ Passed")

    print("\n3. Testing negative beta...")
    test_beta_significance_negative_beta()
    print("✓ Passed")

    print("\n4. Testing return structure...")
    test_beta_significance_return_structure()
    print("✓ Passed")

    print("\n5. Testing performance...")
    test_beta_significance_performance()
    print("✓ Passed")

    print("\n✅ All basic tests passed!")
