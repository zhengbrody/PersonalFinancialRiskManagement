"""Contract tests for ``POST /api/v1/quant/backtest``.

Asserts:
  * Auth required (401 without bearer).
  * Empty active portfolio → 422 ``no_active_portfolio``.
  * equal_weight / static / momentum happy paths → 200 with scalar stats
    and a non-empty equity_curve of ``{date, value}`` points.

Hermetic: monkeypatches the Supabase resolver, ``backtest_engine._download_prices``
(so CI never hits yfinance), and ``services.market_data.get_price_history``
(the static-weights price lookup). Deterministic — seeded RNG.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# ── fixtures ────────────────────────────────────────────────────────


@pytest.fixture
def fake_active_portfolio(monkeypatch):
    """Patch ``libs.auth.active_portfolio.get_active_holdings`` so the
    endpoint doesn't hit Supabase."""

    class _Stub:
        def __init__(self) -> None:
            self.holdings: dict[str, dict] = {}
            self.calls: list[str | None] = []

        def set(self, holdings: dict[str, dict]) -> None:
            self.holdings = holdings

        def __call__(self, access_token=None):
            self.calls.append(access_token)
            return dict(self.holdings)

    stub = _Stub()
    import libs.auth.active_portfolio as ap

    monkeypatch.setattr(ap, "get_active_holdings", stub)
    return stub


def _make_prices(tickers: list[str], days: int = 900) -> pd.DataFrame:
    """Deterministic adjusted-close frame spanning ~3.5y of trading days —
    enough history for momentum's lookback buffer AND a multi-point curve.

    Each ticker is a seeded geometric random walk around 100 with a slight
    upward drift, so the engine produces non-degenerate stats."""
    rng = np.random.default_rng(7)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    data: dict[str, np.ndarray] = {}
    for tk in sorted(tickers):
        returns = rng.normal(0.0004, 0.011, days)
        data[tk] = 100.0 * np.exp(np.cumsum(returns))
    return pd.DataFrame(data, index=idx)


@pytest.fixture
def fake_download(monkeypatch):
    """Patch ``backtest_engine._download_prices`` to return a deterministic
    frame for whatever tickers (incl. the benchmark) the engine requests.

    The engine slices the returned frame by date internally, so we always
    hand back the full window and let it trim."""

    full = {"frame": _make_prices(["SPY"])}  # replaced per-test via set()

    class _Stub:
        def __init__(self) -> None:
            self.calls: list[list[str]] = []

        def set(self, tickers: list[str]) -> None:
            full["frame"] = _make_prices(tickers)

        def __call__(self, tickers, start_date, end_date, *args, **kwargs):
            self.calls.append(list(tickers))
            frame = full["frame"]
            cols = [t for t in tickers if t in frame.columns]
            # Mimic the real loader: trim to [start_date, end_date].
            sub = frame.loc[
                (frame.index >= pd.Timestamp(start_date)) & (frame.index <= pd.Timestamp(end_date)),
                cols,
            ]
            if sub.empty:
                raise ValueError(f"no data for {tickers}")
            return sub

    stub = _Stub()
    import backtest_engine

    monkeypatch.setattr(backtest_engine, "_download_prices", stub)
    return stub


@pytest.fixture
def fake_price_history(monkeypatch):
    """Patch ``services.market_data.get_price_history`` (static-weights
    current-price lookup)."""

    state = {"frame": pd.DataFrame()}

    class _Stub:
        def set(self, frame: pd.DataFrame) -> None:
            state["frame"] = frame

        def __call__(self, tickers, *, days=365, cache_provider=None):
            frame = state["frame"]
            cols = [t for t in tickers if t in frame.columns]
            return frame[cols] if cols else pd.DataFrame()

    stub = _Stub()
    from backend.app.services import market_data as md

    monkeypatch.setattr(md, "get_price_history", stub)
    return stub


# ── auth gate ──────────────────────────────────────────────────────


def test_requires_bearer_token(test_client):
    resp = test_client.post("/api/v1/quant/backtest", json={"strategy": "equal_weight"})
    assert resp.status_code == 401
    assert resp.json()["error"]["code"] == "unauthorized"


# ── empty portfolio ─────────────────────────────────────────────────


def test_no_active_portfolio_returns_422(test_client, mint_token, fake_active_portfolio):
    fake_active_portfolio.set({})
    resp = test_client.post(
        "/api/v1/quant/backtest",
        json={"strategy": "equal_weight"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "no_active_portfolio"


# ── happy paths ──────────────────────────────────────────────────────

_STAT_KEYS = {
    "total_return",
    "annual_return",
    "annual_volatility",
    "sharpe_ratio",
    "sortino_ratio",
    "calmar_ratio",
    "max_drawdown",
    "win_rate",
    "alpha",
    "beta",
}


def _assert_envelope(data: dict, *, strategy: str):
    assert data["strategy"] == strategy
    assert data["benchmark"] == "SPY"
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)
    assert set(data["stats"].keys()) == _STAT_KEYS
    # At least the headline metrics resolved to numbers.
    assert isinstance(data["stats"]["total_return"], (int, float))
    curve = data["equity_curve"]
    assert isinstance(curve, list) and len(curve) > 0
    pt = curve[0]
    assert set(pt.keys()) == {"date", "value"}
    assert isinstance(pt["value"], (int, float))
    # ISO date.
    assert len(pt["date"]) == 10 and pt["date"][4] == "-"


def test_equal_weight_happy_path(test_client, mint_token, fake_active_portfolio, fake_download):
    fake_active_portfolio.set({"AAPL": {"shares": 10}, "MSFT": {"shares": 5}})
    fake_download.set(["AAPL", "MSFT", "SPY"])

    resp = test_client.post(
        "/api/v1/quant/backtest",
        json={"strategy": "equal_weight", "years": 3, "rebalance_freq": "M"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200, resp.json()
    _assert_envelope(resp.json()["data"], strategy="equal_weight")


def test_static_happy_path_derives_weights(
    test_client, mint_token, fake_active_portfolio, fake_download, fake_price_history
):
    holdings = {"AAPL": {"shares": 10}, "MSFT": {"shares": 5}}
    fake_active_portfolio.set(holdings)
    fake_download.set(["AAPL", "MSFT", "SPY"])
    # Current-price lookup for market-value weight derivation.
    fake_price_history.set(_make_prices(["AAPL", "MSFT"], days=10))

    resp = test_client.post(
        "/api/v1/quant/backtest",
        json={"strategy": "static", "years": 2},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200, resp.json()
    _assert_envelope(resp.json()["data"], strategy="static")


def test_static_no_priced_holdings_returns_422(
    test_client, mint_token, fake_active_portfolio, fake_download, fake_price_history
):
    # All zero-share rows → no market value → no_priced_holdings.
    fake_active_portfolio.set({"AAPL": {"shares": 0}})
    fake_price_history.set(_make_prices(["AAPL"], days=10))
    resp = test_client.post(
        "/api/v1/quant/backtest",
        json={"strategy": "static"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "no_priced_holdings"


def test_momentum_happy_path(test_client, mint_token, fake_active_portfolio, fake_download):
    # Universe must be >= top_n; use 6 names, top_n=3.
    universe = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META"]
    fake_active_portfolio.set({tk: {"shares": 10} for tk in universe})
    fake_download.set(universe + ["SPY"])

    resp = test_client.post(
        "/api/v1/quant/backtest",
        json={
            "strategy": "momentum",
            "years": 3,
            "lookback": 126,
            "top_n": 3,
            "rebalance_freq": "M",
        },
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200, resp.json()
    _assert_envelope(resp.json()["data"], strategy="momentum")


def test_token_forwarded_to_resolver(test_client, mint_token, fake_active_portfolio, fake_download):
    """The caller's JWT must reach the active-portfolio resolver so RLS
    applies (same security contract as /risk/score_from_active)."""
    fake_active_portfolio.set({"AAPL": {"shares": 10}, "MSFT": {"shares": 5}})
    fake_download.set(["AAPL", "MSFT", "SPY"])
    token = mint_token(sub="user-quant")
    resp = test_client.post(
        "/api/v1/quant/backtest",
        json={"strategy": "equal_weight"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.json()
    assert fake_active_portfolio.calls == [token]
