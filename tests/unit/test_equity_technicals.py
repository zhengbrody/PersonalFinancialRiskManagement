"""Pure technical helpers in equity_research — RSI, realized vol, FCF CAGR.
No network: synthetic pandas inputs only."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from libs.analysis.equity_research import _fcf_cagr, _realized_vol, _rsi_from_closes


def test_realized_vol_zero_for_constant_growth_and_positive_for_choppy():
    # Each day ×1.01 → every daily return is exactly 1% → std 0 → vol 0.
    flat = pd.Series([100 * (1.01**i) for i in range(40)])
    assert _realized_vol(flat, 20) == pytest.approx(0.0, abs=1e-9)

    # Choppy ±2%/day → a known daily std, annualized by sqrt(252).
    px, closes = 100.0, [100.0]
    for i in range(40):
        px *= 1.02 if i % 2 == 0 else 0.98
        closes.append(px)
    series = pd.Series(closes)
    daily_std = series.pct_change().dropna().tail(20).std(ddof=1)
    assert _realized_vol(series, 20) == pytest.approx(daily_std * math.sqrt(252.0))


def test_realized_vol_none_when_too_short():
    assert _realized_vol(pd.Series([100.0, 101.0, 102.0]), 20) is None


def test_rsi_from_closes_bounds_and_short_guard():
    # A monotonically rising series → RSI saturates near 100.
    rising = pd.Series([100 + i for i in range(30)])
    rsi = _rsi_from_closes(rising)
    assert rsi is not None and 90 <= rsi <= 100
    # Too short → None.
    assert _rsi_from_closes(pd.Series([1.0, 2.0])) is None


class _FakeTicker:
    def __init__(self, cashflow):
        self.cashflow = cashflow


def test_fcf_cagr_from_cashflow_statement():
    # yfinance lays out columns newest→oldest; row "Free Cash Flow".
    # oldest→newest = 100 → 200 over 2 steps (3 cols) → CAGR = sqrt(2)-1.
    cf = pd.DataFrame(
        {"2024": [200.0], "2023": [150.0], "2022": [100.0]},
        index=["Free Cash Flow"],
    )
    cagr = _fcf_cagr(_FakeTicker(cf))
    assert cagr == pytest.approx((200.0 / 100.0) ** (1 / 2) - 1.0)


def test_fcf_cagr_fail_soft():
    # Missing row → None.
    cf = pd.DataFrame({"2024": [1.0]}, index=["Net Income"])
    assert _fcf_cagr(_FakeTicker(cf)) is None
    # Negative endpoint → None (root undefined).
    neg = pd.DataFrame({"2024": [100.0], "2022": [-50.0]}, index=["Free Cash Flow"])
    assert _fcf_cagr(_FakeTicker(neg)) is None
    # No cashflow attribute / empty → None.
    assert _fcf_cagr(_FakeTicker(None)) is None
    assert _fcf_cagr(_FakeTicker(pd.DataFrame())) is None
