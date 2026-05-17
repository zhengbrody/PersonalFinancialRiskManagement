"""Tests for the unified 10Y Treasury yield helper.

Background
==========
Before this helper existed, the 10Y yield appeared on four pages driven by
two different sources (yfinance ^TNX vs FRED DGS10). FRED publishes the
previous trading day's close — meaning during US trading hours FRED is
always ~1 trading day stale vs yfinance's intraday/EOD ^TNX. Users
comparing our number to a quote site flagged "wrong closing price."

These tests lock in:
    1. Preference order: yfinance first, FRED fallback only.
    2. Numeric sanity: anything outside 0.3% .. 12% is rejected as a
       unit/parsing bug (e.g. yfinance returning a 10x-scaled value).
    3. Date passthrough: the date from the source flows into the result
       so the UI / LLM can label "as of YYYY-MM-DD".
    4. Both-sources-fail returns None (callers must handle gracefully).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

import market_intelligence as mi


def _clear_caches():
    mi._FRED_MEMO.clear()
    try:
        import streamlit as _st

        _st.cache_data.clear()
    except Exception:
        pass


def _fake_tnx_history(latest: float, prev: float | None = None, date: str = "2026-05-15"):
    """Build a DataFrame mimicking what yfinance's Ticker.history returns."""
    dates = []
    closes = []
    if prev is not None:
        dates.append(pd.Timestamp("2026-05-14"))
        closes.append(prev)
    dates.append(pd.Timestamp(date))
    closes.append(latest)
    return pd.DataFrame({"Close": closes}, index=pd.DatetimeIndex(dates))


# ──────────────────────────────────────────────────────────────
# 1. yfinance success path is preferred over FRED
# ──────────────────────────────────────────────────────────────
def test_prefers_yfinance_over_fred():
    _clear_caches()
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = _fake_tnx_history(latest=4.595, prev=4.461)

    with patch.object(mi.yf, "Ticker", return_value=fake_ticker):
        # FRED should NOT be touched if yfinance succeeds; fail loudly if
        # something tries to.
        with patch.object(mi, "_fred_fetch_series_raw") as fred_mock:
            result = mi._fetch_10y_yield_uncached()
            fred_mock.assert_not_called()

    assert result is not None
    assert result["value"] == pytest.approx(4.595, abs=1e-6)
    assert result["date"] == "2026-05-15"
    assert result["change"] == pytest.approx(0.134, abs=1e-6)
    assert "Yahoo Finance" in result["source"]


# ──────────────────────────────────────────────────────────────
# 2. yfinance failure → FRED fallback
# ──────────────────────────────────────────────────────────────
def test_fred_fallback_when_yfinance_errors():
    _clear_caches()
    fake_ticker = MagicMock()
    fake_ticker.history.side_effect = RuntimeError("yfinance is down")

    fred_obs = [
        (pd.Timestamp("2026-05-13"), 4.46),
        (pd.Timestamp("2026-05-14"), 4.47),
    ]
    with patch.object(mi.yf, "Ticker", return_value=fake_ticker):
        with patch.object(mi, "_fred_fetch_series_raw", return_value=fred_obs):
            result = mi._fetch_10y_yield_uncached()

    assert result is not None
    assert result["value"] == pytest.approx(4.47, abs=1e-6)
    assert result["date"] == "2026-05-14"
    assert "FRED" in result["source"]


# ──────────────────────────────────────────────────────────────
# 3. Out-of-range yfinance value rejected (unit-bug guard)
# ──────────────────────────────────────────────────────────────
def test_rejects_yfinance_scaled_value_falls_back_to_fred():
    """If yfinance ever starts returning the 10x-scaled form (e.g.
    44.7 instead of 4.47), the range guard should kick in and we fall
    back to FRED rather than display a 45% Treasury yield to the user."""
    _clear_caches()
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = _fake_tnx_history(latest=44.7)

    fred_obs = [(pd.Timestamp("2026-05-14"), 4.47)]
    with patch.object(mi.yf, "Ticker", return_value=fake_ticker):
        with patch.object(mi, "_fred_fetch_series_raw", return_value=fred_obs):
            result = mi._fetch_10y_yield_uncached()

    # Should have rejected yfinance and fallen back to FRED.
    assert result is not None
    assert result["value"] == pytest.approx(4.47, abs=1e-6)
    assert "FRED" in result["source"]


# ──────────────────────────────────────────────────────────────
# 4. Both sources fail → None (caller handles)
# ──────────────────────────────────────────────────────────────
def test_returns_none_when_all_sources_fail():
    _clear_caches()
    fake_ticker = MagicMock()
    fake_ticker.history.side_effect = RuntimeError("down")

    with patch.object(mi.yf, "Ticker", return_value=fake_ticker):
        with patch.object(mi, "_fred_fetch_series_raw", return_value=[]):
            result = mi._fetch_10y_yield_uncached()

    assert result is None


# ──────────────────────────────────────────────────────────────
# 5. Empty yfinance history → FRED fallback
# ──────────────────────────────────────────────────────────────
def test_empty_yfinance_history_falls_back():
    _clear_caches()
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = pd.DataFrame({"Close": []})

    fred_obs = [(pd.Timestamp("2026-05-14"), 4.47)]
    with patch.object(mi.yf, "Ticker", return_value=fake_ticker):
        with patch.object(mi, "_fred_fetch_series_raw", return_value=fred_obs):
            result = mi._fetch_10y_yield_uncached()

    assert result is not None
    assert result["source"].startswith("FRED")


# ──────────────────────────────────────────────────────────────
# 6. Range guard rejects FRED out-of-range too
# ──────────────────────────────────────────────────────────────
def test_rejects_fred_out_of_range():
    _clear_caches()
    fake_ticker = MagicMock()
    fake_ticker.history.side_effect = RuntimeError("yf down")

    # FRED returning 0.0 (e.g. a placeholder) should be rejected.
    fred_obs = [(pd.Timestamp("2026-05-14"), 0.0)]
    with patch.object(mi.yf, "Ticker", return_value=fake_ticker):
        with patch.object(mi, "_fred_fetch_series_raw", return_value=fred_obs):
            result = mi._fetch_10y_yield_uncached()

    assert result is None


# ──────────────────────────────────────────────────────────────
# 7. Single-day history → change is None, value still returned
# ──────────────────────────────────────────────────────────────
def test_single_day_history_returns_value_no_change():
    _clear_caches()
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = _fake_tnx_history(latest=4.5, prev=None)

    with patch.object(mi.yf, "Ticker", return_value=fake_ticker):
        result = mi._fetch_10y_yield_uncached()

    assert result is not None
    assert result["value"] == pytest.approx(4.5, abs=1e-6)
    assert result["change"] is None


# ──────────────────────────────────────────────────────────────
# 8. Public accessor returns a dict (or None) with the expected keys
# ──────────────────────────────────────────────────────────────
def test_public_accessor_shape():
    _clear_caches()
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = _fake_tnx_history(latest=4.595, prev=4.461)

    with patch.object(mi.yf, "Ticker", return_value=fake_ticker):
        result = mi.fetch_10y_yield()

    assert result is not None
    for key in ("value", "date", "change", "source"):
        assert key in result, f"missing key {key} in result {result}"


# ──────────────────────────────────────────────────────────────
# 9. Floating chat injects the unified 10Y (not stale FRED DGS10)
# ──────────────────────────────────────────────────────────────
def test_chat_context_uses_unified_10y_helper(monkeypatch):
    """The chat context must inject the value returned by fetch_10y_yield
    (yfinance-first, FRED-fallback) with its observation date — NOT the
    stale FRED DGS10 row that fetch_macro_releases returns."""
    import importlib
    import sys

    fake_st = MagicMock()
    fake_st.session_state = {"weights": {"AAPL": 1.0}}
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    sys.modules.pop("ui.floating_chat", None)
    module = importlib.import_module("ui.floating_chat")

    # Stub the active-portfolio loaders so the context builder doesn't
    # hit the real Supabase client.
    monkeypatch.setattr("libs.auth.active_portfolio.get_active_holdings", lambda: {}, raising=False)
    monkeypatch.setattr(
        "libs.auth.active_portfolio.get_active_margin_loan", lambda: 0, raising=False
    )
    monkeypatch.setattr(
        "libs.auth.active_portfolio.get_active_portfolio_meta", lambda: {}, raising=False
    )

    fake_macro = [
        {
            "Series": "CPI YoY",
            "Latest": "3.20%",
            "Date": "2026-04-01",
            "fred_id": "CPIAUCSL",
            "Source": "FRED",
        },
        # IMPORTANT: this DGS10 row (stale, T-1) must NOT appear in the
        # chat context — the unified helper supersedes it.
        {
            "Series": "10Y Treasury Yield",
            "Latest": "4.47%",
            "Date": "2026-05-14",
            "fred_id": "DGS10",
            "Source": "FRED",
        },
    ]
    fake_10y = {
        "value": 4.595,
        "date": "2026-05-15",
        "change": 0.134,
        "source": "Yahoo Finance (^TNX)",
    }
    with patch("market_intelligence.fetch_macro_releases", return_value=fake_macro):
        with patch("market_intelligence.fetch_10y_yield", return_value=fake_10y):
            context = module._build_portfolio_context(depth="deep")

    # The fresh value must be present...
    assert "4.59" in context
    assert "2026-05-15" in context
    assert "Yahoo Finance" in context
    # ...and the stale FRED 10Y line must NOT be the source of the 10Y.
    assert "4.47%" not in context, "stale FRED DGS10 row leaked into chat context"
    assert "2026-05-14" not in context, "stale FRED date leaked into chat context"
