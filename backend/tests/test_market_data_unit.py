"""Unit tests for ``backend.app.services.market_data._extract_close_series``.

Locks the yfinance shape-tolerance contract in place. This function
exists because yfinance's column shape changed over versions:

  * Old: single-index columns (``Close``, ``High``…).
  * New (yf 0.2.x): MultiIndex columns (``('Close', 'AA')``, …) even
    on a single-ticker download.

If the unwrap regresses, every multi-ticker ``score_from_active`` and
``report_from_active`` call 500s in production with "If using all
scalar values, you must pass an index" — which is exactly the bug we
hit in Phase 9 staging."""

from __future__ import annotations

import pandas as pd
import pytest

from backend.app.services.market_data import (
    _extract_close_series,
    get_price_history,
)


def _make_simple_close_df(ticker: str, n: int = 5) -> pd.DataFrame:
    """yfinance "old" shape — single-level columns."""
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    return pd.DataFrame(
        {
            "Close": [100.0 + i for i in range(n)],
            "Open": [99.0 + i for i in range(n)],
            "High": [101.0 + i for i in range(n)],
            "Low": [98.0 + i for i in range(n)],
            "Volume": [1_000_000 + i for i in range(n)],
        },
        index=idx,
    )


def _make_multiindex_close_df(ticker: str, n: int = 5) -> pd.DataFrame:
    """yfinance "new" shape — MultiIndex columns even for one ticker."""
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    cols = pd.MultiIndex.from_tuples(
        [
            ("Close", ticker),
            ("High", ticker),
            ("Low", ticker),
            ("Open", ticker),
            ("Volume", ticker),
        ]
    )
    return pd.DataFrame(
        [[100.0 + i, 101.0 + i, 98.0 + i, 99.0 + i, 1_000_000 + i] for i in range(n)],
        index=idx,
        columns=cols,
    )


# ── unit: _extract_close_series ──────────────────────────────────


def test_extract_close_handles_single_index_columns():
    df = _make_simple_close_df("AA")
    s = _extract_close_series(df)
    assert isinstance(s, pd.Series)
    assert len(s) == 5
    assert s.iloc[0] == pytest.approx(100.0)


def test_extract_close_handles_multiindex_columns():
    """The yf-0.2.x shape that broke Phase 9 cutover."""
    df = _make_multiindex_close_df("AA")
    s = _extract_close_series(df)
    # Must be a Series (not a DataFrame), or pd.DataFrame({...}) blows
    # up in the caller.
    assert isinstance(s, pd.Series)
    assert len(s) == 5
    assert s.iloc[-1] == pytest.approx(104.0)


def test_extract_close_handles_fallback_first_column():
    """Some pre-flattened cache entries have a single un-named column."""
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=3)
    df = pd.DataFrame({"price": [10.0, 11.0, 12.0]}, index=idx)
    s = _extract_close_series(df)
    assert isinstance(s, pd.Series)
    assert list(s) == [10.0, 11.0, 12.0]


def test_extract_close_returns_none_on_empty_frame():
    s = _extract_close_series(pd.DataFrame())
    assert s is None


# ── integration: get_price_history end-to-end with MultiIndex ────


def test_get_price_history_assembles_dataframe_from_multiindex_inputs(monkeypatch):
    """Reproduces the Phase-9 production bug: multi-ticker request →
    yfinance hands back MultiIndex DataFrames per ticker → the
    extractor must collapse them so the outer DataFrame builds cleanly.
    """

    class _FakeCache:
        def fetch_with_cache(self, ticker, start, end, **kw):
            return _make_multiindex_close_df(ticker)

    frame = get_price_history(["SPY", "AA", "GLD"], days=90, cache_provider=_FakeCache())
    assert isinstance(frame, pd.DataFrame)
    assert sorted(frame.columns) == ["AA", "GLD", "SPY"]
    # Each column carries the same fixture values (1 col per ticker,
    # length 5) so we just check the shape + a sample value.
    assert frame.shape == (5, 3)
    assert frame["SPY"].iloc[0] == pytest.approx(100.0)


def test_get_price_history_returns_empty_when_no_ticker_resolves(monkeypatch):
    """Cache returns None for every ticker — the route must see
    ``frame.empty`` so it can emit a clean 422 envelope."""

    class _FakeCache:
        def fetch_with_cache(self, ticker, start, end, **kw):
            return None

    frame = get_price_history(["XYZ"], days=30, cache_provider=_FakeCache())
    assert frame.empty
