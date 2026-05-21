from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from libs.mindmarket_core.portfolio_scoring import (
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
