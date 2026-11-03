"""Long price windows must not be silently truncated by Massive.

Massive serves at most ``massive_provider._MAX_HISTORY_DAYS`` (~2y) of daily
bars. ``get_price_history`` used to ask Massive first for EVERY request and only
sent tickers Massive left missing to yfinance, so a 6800-day request came back
as ~2 years and the historical replay lost every episode before ~2024 (COVID,
2022, 2018 Q4, GFC) without any error.

These tests drive the REAL ``get_price_history`` (no stub of it) with a fake
Massive that truncates exactly as the real provider does and a fake yfinance
that has 20 years. Massive is patched on the real module object -- a
``sys.modules`` injection is silently bypassed once the package attribute is
bound by an earlier import in the full suite.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.app.schemas.providers import PriceBar, ProviderResult
from backend.app.services import market_data as md
from backend.app.services.providers import massive_provider as mp


def _today() -> pd.Timestamp:
    return pd.Timestamp.today().normalize()


def _long_series(n_years: int = 20) -> pd.Series:
    idx = pd.bdate_range(end=_today(), periods=252 * n_years)
    vals = np.linspace(50.0, 200.0, len(idx))
    # A -30% path across the COVID window so the replay sees a real drop.
    mask = (idx >= "2020-02-19") & (idx <= "2020-03-23")
    vals[mask] = vals[mask] * np.linspace(1.0, 0.7, int(mask.sum()))
    return pd.Series(vals, index=idx)


class _Yfinance20y:
    """Fake yfinance cache provider: honours the requested start date."""

    def __init__(self):
        self.calls: list[str] = []

    def fetch_with_cache(self, ticker, start, end, **kw):
        self.calls.append(ticker)
        s = _long_series()
        s = s[s.index >= pd.Timestamp(start)]
        return pd.DataFrame({"Close": s.values}, index=s.index)


@pytest.fixture
def providers(monkeypatch):
    """Massive configured + truncating to its real cap; yfinance has 20y."""
    massive_calls: list[tuple[str, int]] = []

    def fake_massive_history(ticker, *, days=365):
        massive_calls.append((ticker, days))
        capped = min(max(int(days), 1), mp._MAX_HISTORY_DAYS)
        idx = pd.bdate_range(end=_today(), start=_today() - pd.Timedelta(days=capped))
        return ProviderResult(
            data=[PriceBar(date=d.strftime("%Y-%m-%d"), close=100.0) for d in idx],
            source="massive",
        )

    yf = _Yfinance20y()
    monkeypatch.setattr(mp, "is_configured", lambda: True)
    monkeypatch.setattr(mp, "get_daily_history", fake_massive_history)
    monkeypatch.setattr(md, "_build_cache_provider", lambda: yf)
    return massive_calls, yf


def test_long_window_uses_yfinance_full_history(providers):
    massive_calls, yf = providers
    prov: dict = {}
    frame = md.get_price_history(["AAPL", "SPY"], days=6800, provenance=prov)

    assert prov["by_ticker"] == {"AAPL": "yfinance", "SPY": "yfinance"}
    assert prov["missing"] == []
    assert massive_calls == []  # nothing missing -> Massive never asked
    # ~18.6 years, not Massive's 2.
    assert frame.index.min() < _today() - pd.Timedelta(days=6700)


def test_short_window_still_prefers_massive(providers):
    """Regression: a window Massive can serve keeps the Massive-first path."""
    massive_calls, yf = providers
    prov: dict = {}
    md.get_price_history(["AAPL", "SPY"], days=365, provenance=prov)

    assert prov["by_ticker"] == {"AAPL": "massive", "SPY": "massive"}
    assert [t for t, _ in massive_calls] == ["AAPL", "SPY"]
    assert yf.calls == []


def test_window_at_massive_cap_still_prefers_massive(providers):
    """Exactly the cap is served in full by Massive -> unchanged ordering."""
    massive_calls, yf = providers
    prov: dict = {}
    md.get_price_history(["SPY"], days=mp._MAX_HISTORY_DAYS, provenance=prov)
    assert prov["by_ticker"] == {"SPY": "massive"}
    assert yf.calls == []


def test_long_window_backfills_from_massive_when_yfinance_misses(providers, monkeypatch):
    """A ticker yfinance cannot serve still gets Massive's (shorter) series,
    labelled honestly as massive -- same coverage as before the fix."""
    massive_calls, yf = providers

    class _YfNoXyz(_Yfinance20y):
        def fetch_with_cache(self, ticker, start, end, **kw):
            if ticker == "XYZ":
                return None
            return super().fetch_with_cache(ticker, start, end, **kw)

    monkeypatch.setattr(md, "_build_cache_provider", lambda: _YfNoXyz())
    prov: dict = {}
    frame = md.get_price_history(["SPY", "XYZ"], days=6800, provenance=prov)

    assert prov["by_ticker"] == {"SPY": "yfinance", "XYZ": "massive"}
    assert prov["missing"] == []
    assert [t for t, _ in massive_calls] == ["XYZ"]
    assert "XYZ" in frame.columns


def test_historical_replay_keeps_pre_2024_episodes(providers, test_client, mint_token, monkeypatch):
    """End to end through the real get_price_history: the old episodes come back."""
    from backend.app.services import historical_scenarios as hs

    monkeypatch.setattr(
        hs, "_resolve_active_holdings", lambda user: {"AAPL": {"shares": 10}, "SPY": {"shares": 5}}
    )
    resp = test_client.post(
        "/api/v1/risk/historical_scenarios",
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200, resp.json()
    labels = {s["label"] for s in resp.json()["data"]["scenarios"]}
    assert {
        "COVID-19 crash",
        "2022 bear market",
        "2018 Q4 selloff",
        "Global Financial Crisis",
    } <= labels
    covid = next(s for s in resp.json()["data"]["scenarios"] if s["label"] == "COVID-19 crash")
    assert covid["portfolio_return"] is not None and covid["portfolio_return"] < 0


def test_history_window_reaches_oldest_episode_start():
    """The fetch window is derived from today, so it can never decay past the
    GFC peak (a fixed 6800 days only reached 2008-03 by late 2026)."""
    from datetime import date, timedelta

    from backend.app.services import historical_scenarios as hs

    for today in (date(2026, 6, 1), date(2026, 11, 2), date(2031, 1, 1)):
        reach = today - timedelta(days=hs._history_days(today))
        assert reach <= date(2007, 10, 9)


def test_episode_skipped_when_history_starts_mid_window():
    """A frame that begins months after the episode start is a partial replay;
    it must not be reported under the episode's label."""
    from backend.app.services import historical_scenarios as hs

    idx = pd.bdate_range(start="2008-03-21", end="2009-12-31")
    frame = pd.DataFrame({"SPY": np.linspace(100, 60, len(idx))}, index=idx)
    assert hs._episode(frame, {"SPY": 1.0}, "2007-10-09", "2009-03-09") is None

    full_idx = pd.bdate_range(start="2007-10-09", end="2009-12-31")
    full = pd.DataFrame({"SPY": np.linspace(100, 60, len(full_idx))}, index=full_idx)
    assert hs._episode(full, {"SPY": 1.0}, "2007-10-09", "2009-03-09") is not None
