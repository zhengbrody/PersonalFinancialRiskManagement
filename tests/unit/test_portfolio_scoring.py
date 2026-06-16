from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from libs.mindmarket_core.portfolio_scoring import (
    AssetPosition,
    compute_portfolio_metrics,
    create_draft_positions,
    demo_asset_positions,
    positions_to_frame,
    score_portfolio,
)


def _sample_returns(periods: int = 252) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    index = pd.bdate_range("2024-01-01", periods=periods)
    market = rng.normal(0.00035, 0.010, periods)
    return pd.DataFrame(
        {
            "SPY": market,
            "QQQ": market * 1.25 + rng.normal(0.00010, 0.006, periods),
            "VXUS": market * 0.85 + rng.normal(0.00005, 0.007, periods),
            "BND": rng.normal(0.00010, 0.003, periods),
        },
        index=index,
    )


def test_score_portfolio_returns_bounded_score_and_exact_metrics():
    positions = demo_asset_positions(100_000)
    returns = _sample_returns()

    score = score_portfolio(
        positions,
        returns,
        benchmark_returns=returns["SPY"],
        risk_preference=3,
        risk_free_rate=0.04,
    )

    assert 0 <= score.overall_score <= 1000
    assert score.metrics.total_value == pytest.approx(100_000)
    assert score.metrics.observations == len(returns)
    assert score.metrics.annual_volatility > 0
    assert score.metrics.max_drawdown >= 0
    assert set(score.dimensions) == {
        "risk_match",
        "risk_adjusted_return",
        "downside_protection",
    }


def test_leverage_amplifies_volatility_and_var():
    """leverage L scales the equity return series by L (net of borrow
    carry), so annualised vol and daily VaR scale ~linearly by L while
    the unlevered run is unchanged (default L=1.0)."""
    positions = demo_asset_positions(100_000)
    returns = _sample_returns()

    base = compute_portfolio_metrics(positions, returns, risk_free_rate=0.04)
    levered = compute_portfolio_metrics(positions, returns, risk_free_rate=0.04, leverage=2.0)

    # Vol scales exactly by L (scaling a series scales its std exactly).
    assert levered.annual_volatility == pytest.approx(2.0 * base.annual_volatility, rel=1e-6)
    # VaR scales by L too (quantile of a scaled series), modulo the tiny
    # borrow-carry shift — so clearly larger, ~2×.
    assert levered.var_95_daily > 1.7 * base.var_95_daily
    # The leverage is disclosed in the notes for auditability.
    assert any("everage" in n for n in levered.data_quality_notes)
    # Default path is untouched.
    assert not any("everage" in n for n in base.data_quality_notes)


def test_sharpe_is_leverage_invariant_and_margin_cost_disclosed():
    """The headline Sharpe is the ASSET-MIX Sharpe — leverage must NOT change it
    (the old bug applied borrow drag to the Sharpe basis, turning it negative for
    margin books). Leverage instead surfaces a separate, positive margin cost."""
    positions = demo_asset_positions(100_000)
    returns = _sample_returns()

    base = compute_portfolio_metrics(positions, returns, risk_free_rate=0.04)
    levered = compute_portfolio_metrics(positions, returns, risk_free_rate=0.04, leverage=2.5)

    # Sharpe is identical regardless of leverage (asset-mix quality).
    assert levered.sharpe_ratio == pytest.approx(base.sharpe_ratio, rel=1e-9)
    # Margin cost is exposed separately: (L-1)*rf = 1.5 * 0.04 = 0.06.
    assert levered.margin_cost_annual == pytest.approx(1.5 * 0.04, rel=1e-9)
    assert levered.leverage == pytest.approx(2.5)
    # The unlevered asset-mix return is reported and matches the base book.
    assert levered.gross_annual_return == pytest.approx(base.annual_return, rel=1e-9)
    # Unlevered book: no margin cost, gross == levered return.
    assert base.margin_cost_annual == 0.0
    assert base.leverage == pytest.approx(1.0)


def test_levered_sharpe_stays_positive_when_asset_mix_is_sound():
    """Regression for the reported bug: a sound (positive-Sharpe) asset mix held
    on margin must NOT show a negative Sharpe on the score path."""
    positions = demo_asset_positions(100_000)
    returns = _sample_returns()
    levered = compute_portfolio_metrics(positions, returns, risk_free_rate=0.04, leverage=3.0)
    base = compute_portfolio_metrics(positions, returns, risk_free_rate=0.04)
    if base.sharpe_ratio > 0:
        assert levered.sharpe_ratio > 0


def test_leverage_is_clamped_and_defaults_noop():
    positions = demo_asset_positions(100_000)
    returns = _sample_returns()

    base = compute_portfolio_metrics(positions, returns, risk_free_rate=0.04)
    # leverage=1.0 (and non-finite) must be a no-op.
    same = compute_portfolio_metrics(positions, returns, risk_free_rate=0.04, leverage=1.0)
    assert same.annual_volatility == pytest.approx(base.annual_volatility, rel=1e-9)


def test_unknown_cost_basis_excludes_from_pnl():
    """cost_basis=None means UNKNOWN, not 0 — P&L must be None (excluded),
    never the full market value booked as profit."""
    unknown = AssetPosition(
        ticker="AAPL",
        name="Apple",
        asset_type="public_security",
        market_value=10_000.0,
        cost_basis=None,
    )
    assert unknown.unrealized_pnl is None
    assert unknown.unrealized_pnl_pct is None

    known = AssetPosition(
        ticker="MSFT",
        name="Microsoft",
        asset_type="public_security",
        market_value=10_000.0,
        cost_basis=8_000.0,
    )
    assert known.unrealized_pnl == pytest.approx(2_000.0)
    assert known.unrealized_pnl_pct == pytest.approx(0.25)


def test_draft_positions_propagate_unknown_cost_basis():
    """Rebalancing an unknown-cost position must keep it unknown, not
    invent a basis (which would manufacture P&L out of thin air)."""
    base = [
        AssetPosition("AAPL", "Apple", "public_security", 10_000.0, cost_basis=None),
        AssetPosition("BND", "Bonds", "public_security", 10_000.0, cost_basis=9_000.0),
    ]
    drafted = create_draft_positions(base, {"AAPL": 0.5, "BND": 0.5})
    by_ticker = {p.ticker: p for p in drafted}
    assert by_ticker["AAPL"].cost_basis is None
    assert by_ticker["BND"].cost_basis is not None


def test_risk_preference_changes_risk_match_score():
    positions = demo_asset_positions(100_000)
    returns = _sample_returns()

    conservative = score_portfolio(
        positions,
        returns,
        benchmark_returns=returns["SPY"],
        risk_preference=1,
    )
    growth = score_portfolio(
        positions,
        returns,
        benchmark_returns=returns["SPY"],
        risk_preference=4,
    )

    assert conservative.dimensions["risk_match"].score != growth.dimensions["risk_match"].score


def test_create_draft_positions_normalizes_weights_without_changing_total_value():
    positions = demo_asset_positions(100_000)
    draft = create_draft_positions(
        positions,
        {
            "SPY": 40,
            "QQQ": 20,
            "VXUS": 10,
            "BND": 20,
            "CASH": 10,
        },
    )
    frame = positions_to_frame(draft)
    active = frame[frame["Enabled"] & (frame["Market Value"] > 0)]

    assert active["Market Value"].sum() == pytest.approx(100_000)
    assert active["Weight"].sum() == pytest.approx(1.0)
    assert active.loc[active["Ticker"] == "SPY", "Weight"].iloc[0] == pytest.approx(0.40)


def test_short_history_adds_low_confidence_note():
    positions = demo_asset_positions(100_000)
    returns = _sample_returns(periods=45)

    metrics = compute_portfolio_metrics(positions, returns, risk_free_rate=0.04)

    assert any("45 overlapping trading days" in n for n in metrics.data_quality_notes)
    assert any("low-confidence" in n for n in metrics.data_quality_notes)


def test_full_history_has_no_short_history_note():
    positions = demo_asset_positions(100_000)
    returns = _sample_returns()

    metrics = compute_portfolio_metrics(positions, returns, risk_free_rate=0.04)

    assert not any("low-confidence" in n for n in metrics.data_quality_notes)


def test_unestimable_benchmark_beta_adds_note():
    """A benchmark with constant (zero-variance) returns means beta can't be
    estimated — the metrics must say so rather than silently reporting NaN."""
    positions = demo_asset_positions(100_000)
    returns = _sample_returns()
    flat_benchmark = pd.Series(0.0, index=returns.index)

    metrics = compute_portfolio_metrics(
        positions, returns, benchmark_returns=flat_benchmark, risk_free_rate=0.04
    )

    assert np.isnan(metrics.beta_to_benchmark)
    assert any("beta could not be estimated" in n.lower() for n in metrics.data_quality_notes)
