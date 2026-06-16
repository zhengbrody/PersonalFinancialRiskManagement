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


def test_get_price_history_prefers_massive_when_configured(monkeypatch):
    """Production path: Massive is the primary OHLC source; yfinance is not
    called when Massive resolves every requested ticker."""
    from backend.app.schemas.providers import PriceBar, ProviderResult
    from backend.app.services import market_data as md
    from backend.app.services.providers import massive_provider as mp

    monkeypatch.setattr(mp, "is_configured", lambda: True)

    def fake_massive_history(ticker, *, days=365):
        return ProviderResult(
            data=[
                PriceBar(date="2026-06-01", close=10.0),
                PriceBar(date="2026-06-02", close=11.0),
            ],
            source="massive",
        )

    class _NoYfinance:
        def fetch_with_cache(self, *a, **k):
            raise AssertionError("yfinance should not be called when Massive has coverage")

    monkeypatch.setattr(mp, "get_daily_history", fake_massive_history)
    monkeypatch.setattr(md, "_build_cache_provider", lambda: _NoYfinance())

    prov: dict = {}
    frame = md.get_price_history(["SPY", "BND"], days=30, provenance=prov)

    assert sorted(frame.columns) == ["BND", "SPY"]
    assert prov["by_ticker"] == {"BND": "massive", "SPY": "massive"}
    assert prov["missing"] == []


def test_get_price_history_falls_back_to_yfinance_when_massive_missing(monkeypatch):
    """If Massive misses or is rate-limited for a ticker, yfinance fills that
    ticker and the provenance marks it as fallback."""
    from backend.app.schemas.providers import PriceBar, ProviderResult
    from backend.app.services import market_data as md
    from backend.app.services.providers import massive_provider as mp

    monkeypatch.setattr(mp, "is_configured", lambda: True)

    def fake_massive_history(ticker, *, days=365):
        if ticker == "SPY":
            return ProviderResult(
                data=[
                    PriceBar(date="2026-06-01", close=100.0),
                    PriceBar(date="2026-06-02", close=101.0),
                ],
                source="massive",
            )
        return ProviderResult(data=None, source="massive", warnings=["no_history"])

    class _FallbackYfinance:
        def fetch_with_cache(self, ticker, start, end, **kw):
            return _make_simple_close_df(ticker, n=2)

    monkeypatch.setattr(mp, "get_daily_history", fake_massive_history)
    monkeypatch.setattr(md, "_build_cache_provider", lambda: _FallbackYfinance())

    prov: dict = {}
    frame = md.get_price_history(["SPY", "BND"], days=30, provenance=prov)

    assert sorted(frame.columns) == ["BND", "SPY"]
    assert prov["by_ticker"] == {"SPY": "massive", "BND": "yfinance"}
    assert md.yfinance_fallback_tickers(prov["by_ticker"]) == ["BND"]


def test_get_price_history_returns_empty_when_no_ticker_resolves(monkeypatch):
    """Cache returns None for every ticker — the route must see
    ``frame.empty`` so it can emit a clean 422 envelope."""

    class _FakeCache:
        def fetch_with_cache(self, ticker, start, end, **kw):
            return None

    frame = get_price_history(["XYZ"], days=30, cache_provider=_FakeCache())
    assert frame.empty


# ── intraday overlay for get_latest_prices (the live quote) ─────────


def test_get_latest_prices_overlays_intraday(monkeypatch):
    """When an intraday quote exists, it wins over the daily close + carries
    today's date."""
    from backend.app.services import market_data as md

    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=5)
    frame = pd.DataFrame({"SPY": [500, 501, 502, 503, 504.0]}, index=idx)
    monkeypatch.setattr(md, "get_price_history", lambda tickers, **k: frame)
    monkeypatch.setattr(md, "_intraday_quotes", lambda tickers: {"SPY": (754.24, "2026-06-05")})

    rows = md.get_latest_prices(["SPY"])
    assert len(rows) == 1
    assert rows[0].ticker == "SPY"
    assert rows[0].price == 754.24  # intraday, not the 504 daily close
    assert rows[0].as_of == "2026-06-05"


def test_get_latest_prices_falls_back_to_daily_close(monkeypatch):
    """No intraday (off-hours / rate-limited) → the daily close, never empty."""
    from backend.app.services import market_data as md

    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=3)
    frame = pd.DataFrame({"SPY": [500, 501, 502.0]}, index=idx)
    monkeypatch.setattr(md, "get_price_history", lambda tickers, **k: frame)
    monkeypatch.setattr(md, "_intraday_quotes", lambda tickers: {})

    rows = md.get_latest_prices(["SPY"])
    assert rows[0].price == 502.0


def test_intraday_quotes_fail_soft(monkeypatch):
    """A throwing yfinance download → {} (never raises)."""
    from backend.app.services import market_data as md

    md.reset_quote_cache()

    class _Boom:
        def download(self, *a, **k):
            raise RuntimeError("rate limited")

    monkeypatch.setitem(__import__("sys").modules, "yfinance", _Boom())
    assert md._intraday_quotes(["SPY"]) == {}
