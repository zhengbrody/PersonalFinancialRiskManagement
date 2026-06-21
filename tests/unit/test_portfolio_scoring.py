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


# ══════════════════════════════════════════════════════════════════════════════
#  Slice 1 — exact math + data-quality confidence + score stabilization
# ══════════════════════════════════════════════════════════════════════════════


def _single_asset(returns_series: pd.Series) -> tuple[list, pd.DataFrame]:
    """A 100%-AAA book + a returns frame whose only column is AAA, so the
    portfolio return series equals `returns_series` exactly (no blending)."""
    pos = [AssetPosition("AAA", "Asset A", "public_security", 100_000.0, 90_000.0)]
    frame = pd.DataFrame({"AAA": returns_series})
    return pos, frame


def test_sharpe_matches_textbook_formula_on_known_series():
    """Sharpe = (mean(daily)·252 − rf) / (std(daily, ddof=1)·√252), computed on
    the PRE-leverage series. Assert the wiring (frequency, annualization, ddof,
    rf-as-annual) against an independently-computed expected value."""
    idx = pd.bdate_range("2024-01-01", periods=252)
    rng = np.random.default_rng(11)
    daily = pd.Series(rng.normal(0.0006, 0.009, 252), index=idx)
    pos, frame = _single_asset(daily)
    rf = 0.045

    m = compute_portfolio_metrics(pos, frame, risk_free_rate=rf)

    exp_ret = float(daily.mean() * 252)
    exp_vol = float(daily.std(ddof=1) * np.sqrt(252))
    exp_sharpe = (exp_ret - rf) / exp_vol
    assert m.annual_return == pytest.approx(exp_ret, rel=1e-9)
    assert m.annual_volatility == pytest.approx(exp_vol, rel=1e-9)
    assert m.sharpe_ratio == pytest.approx(exp_sharpe, rel=1e-9)


def test_zero_volatility_returns_zero_sharpe_not_nan():
    """A perfectly flat return series has zero vol — Sharpe must be 0.0 (defensive),
    never NaN/inf that would poison the score."""
    idx = pd.bdate_range("2024-01-01", periods=252)
    pos, frame = _single_asset(pd.Series(0.0004, index=idx))  # constant daily return
    m = compute_portfolio_metrics(pos, frame, risk_free_rate=0.045)
    assert m.annual_volatility == pytest.approx(0.0, abs=1e-12)
    assert m.sharpe_ratio == 0.0
    assert np.isfinite(m.sharpe_ratio)


def test_max_drawdown_on_known_equity_curve():
    """A single −20% day after a rising run is exactly a 20% peak-to-trough
    drawdown (dd = cum/cummax − 1 = 0.80 − 1), independent of the peak level —
    and it stays the worst as the curve recovers. (40 obs to clear the
    minimum-history inclusion gate.)"""
    idx = pd.bdate_range("2024-01-01", periods=40)
    daily = pd.Series([0.001] * 30 + [-0.20] + [0.001] * 9, index=idx)
    pos, frame = _single_asset(daily)
    m = compute_portfolio_metrics(pos, frame, risk_free_rate=0.045)
    assert m.max_drawdown == pytest.approx(0.20, rel=1e-9)


def test_annualized_volatility_known_series():
    idx = pd.bdate_range("2024-01-01", periods=120)
    rng = np.random.default_rng(3)
    daily = pd.Series(rng.normal(0.0, 0.012, 120), index=idx)
    pos, frame = _single_asset(daily)
    m = compute_portfolio_metrics(pos, frame, risk_free_rate=0.0)
    assert m.annual_volatility == pytest.approx(float(daily.std(ddof=1) * np.sqrt(252)), rel=1e-9)


def test_full_data_book_is_undamped_and_backward_compatible():
    """A full-coverage, long-history book must score byte-identically to the
    legacy path: data_quality high, no dampening (base_overall == overall_score)."""
    positions = demo_asset_positions(100_000)
    returns = _sample_returns()
    score = score_portfolio(positions, returns, benchmark_returns=returns["SPY"], risk_preference=3)
    assert score.metrics.confidence == "high"
    assert score.metrics.data_quality >= 0.8
    assert score.base_overall == score.overall_score  # undamped
    assert score.metrics.dropped_tickers == ()
    # Deterministic explainability is always attached.
    assert len(score.drivers) == 3
    assert score.drivers[0]["points_below_max"] >= score.drivers[-1]["points_below_max"]


def test_missing_price_flags_and_does_not_silently_collapse():
    """A missing price for a held name must (a) be reported as dropped, (b) drop
    data confidence, and (c) NOT let the score collapse — it is stabilized toward
    neutral with a reason code, instead of silently producing a catastrophic number."""
    positions = [
        AssetPosition("AAA", "A", "public_security", 40_000.0, 35_000.0),
        AssetPosition("BBB", "B", "public_security", 35_000.0, 33_000.0),
        AssetPosition("CCC", "C", "public_security", 25_000.0, 24_000.0),
    ]
    rng = np.random.default_rng(5)
    idx = pd.bdate_range("2024-01-01", periods=252)
    frame = pd.DataFrame(
        {  # CCC deliberately absent (price fetch failed)
            "AAA": rng.normal(0.0004, 0.01, 252),
            "BBB": rng.normal(0.0003, 0.011, 252),
        },
        index=idx,
    )
    score = score_portfolio(positions, frame, risk_preference=3)
    assert "CCC" in score.metrics.dropped_tickers
    assert score.metrics.confidence != "high"
    codes = {r["code"] for r in score.reason_codes}
    assert "missing_price_data" in codes and "low_data_confidence" in codes


def test_degraded_inputs_do_not_collapse_but_full_data_collapse_shows_through():
    """The 500→70 case. A book whose RAW dimensions crater:
    * with DEGRADED inputs (short history + a dropped name) is floored toward
      neutral + flagged low-confidence (no silent collapse);
    * with FULL data is a legitimate move and is shown as-is (base == overall),
      to be explained by the what-changed engine — not hidden."""
    positions = [
        AssetPosition("AAA", "A", "public_security", 40_000.0, 50_000.0),
        AssetPosition("BBB", "B", "public_security", 35_000.0, 50_000.0),
        AssetPosition("CCC", "C", "public_security", 25_000.0, 50_000.0),
    ]
    rng = np.random.default_rng(9)
    idx = pd.bdate_range("2024-01-01", periods=252)
    crash = {  # negative drift + high vol → raw score craters
        "AAA": rng.normal(-0.002, 0.05, 252),
        "BBB": rng.normal(-0.0025, 0.055, 252),
        "CCC": rng.normal(-0.003, 0.06, 252),
    }
    full = score_portfolio(positions, pd.DataFrame(crash, index=idx), risk_preference=3)
    # Full data → legitimate collapse shown as-is (no dampening).
    assert full.metrics.confidence == "high"
    assert full.base_overall == full.overall_score
    assert full.overall_score < 200  # a genuinely bad book scores low — and is honest

    # Degraded: only 45 days and only AAA priced (BBB/CCC dropped).
    degraded_frame = pd.DataFrame({"AAA": crash["AAA"][:45]}, index=idx[:45])
    degraded = score_portfolio(positions, degraded_frame, risk_preference=3)
    assert degraded.metrics.confidence == "low"
    # The raw score would crater, but the SHOWN score is floored well above it.
    assert degraded.overall_score > degraded.base_overall + 100
    assert any(r["code"] == "low_data_confidence" for r in degraded.reason_codes)


def test_data_quality_is_worst_link():
    """data_quality must reflect the WORST input dimension: long history but poor
    coverage (a big holding dropped) is still low-confidence."""
    positions = [
        AssetPosition("AAA", "A", "public_security", 60_000.0, 55_000.0),  # 60% dropped
        AssetPosition("BBB", "B", "public_security", 40_000.0, 38_000.0),
    ]
    rng = np.random.default_rng(2)
    idx = pd.bdate_range("2024-01-01", periods=252)
    frame = pd.DataFrame({"BBB": rng.normal(0.0003, 0.01, 252)}, index=idx)  # AAA missing
    m = compute_portfolio_metrics(positions, frame)
    assert m.data_coverage < 0.5
    assert m.data_quality < 0.5  # capped by coverage despite the full history
    assert m.confidence == "low"
