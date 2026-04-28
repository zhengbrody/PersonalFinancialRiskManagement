"""Unit tests for libs.mindmarket_core.data_prep."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from libs.mindmarket_core import data_prep as dp


# ── Currency mixing ───────────────────────────────────────


def test_all_us_no_mixing():
    has, msg = dp.detect_currency_mixing(["AAPL", "MSFT", "NVDA"])
    assert has is False
    assert msg == ""


def test_japanese_ticker_detected():
    has, msg = dp.detect_currency_mixing(["AAPL", "7203.T"])
    assert has is True
    assert "JPY" in msg or "Tokyo" in msg


def test_all_japanese_no_mixing():
    """Single non-USD currency is NOT mixing."""
    has, _ = dp.detect_currency_mixing(["7203.T", "9984.T"])
    assert has is False


# ── Winsorize ─────────────────────────────────────────────


def test_winsorize_clips_outliers():
    rng = np.random.default_rng(0)
    base = rng.normal(0, 0.01, 1000)
    base[0] = 0.5  # blowout
    base[1] = -0.5
    s = pd.Series(base)
    out = dp.winsorize_returns(s, lower_pct=0.01, upper_pct=0.99)
    assert out.iloc[0] < 0.5
    assert out.iloc[1] > -0.5


def test_winsorize_skips_short_series():
    s = pd.Series([0.1, 0.2, 0.3])
    out = dp.winsorize_returns(s)
    pd.testing.assert_series_equal(out, s)


def test_winsorize_handles_all_nan():
    s = pd.Series([float("nan")] * 50)
    out = dp.winsorize_returns(s)
    assert out.isna().all()


# ── Gap fill ──────────────────────────────────────────────


def test_smart_fill_no_gaps_returns_input():
    s = pd.Series([1.0, 2.0, 3.0])
    out = dp.smart_fill_gaps(s)
    pd.testing.assert_series_equal(out, s)


def test_smart_fill_short_gap_interpolated():
    s = pd.Series([1.0, np.nan, np.nan, 4.0])
    out = dp.smart_fill_gaps(s, method="auto")
    assert out.notna().all()


def test_ffill_method():
    s = pd.Series([1.0, np.nan, np.nan, 4.0])
    out = dp.smart_fill_gaps(s, method="ffill")
    assert out.tolist() == [1.0, 1.0, 1.0, 4.0]


def test_unknown_method_raises():
    s = pd.Series([1.0, np.nan])
    with pytest.raises(ValueError, match="fill method"):
        dp.smart_fill_gaps(s, method="garbage")
