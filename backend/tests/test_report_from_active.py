"""Contract tests for ``POST /api/v1/risk/report_from_active``.

Asserts:
  * Auth required (401 without bearer).
  * Same 422 codes as /score_from_active for empty + missing-data paths
    (frontends can share the error UI between the two routes).
  * Happy path: a fake RiskReport is serialised into the JSON-safe
    RiskReportOut and the response carries every section the UI needs.
  * NaN values from the engine are scrubbed (envelope rule).

We mock the heavy parts (DataProvider, RiskEngine, market_data) so
tests run hermetically and fast — same pattern as
test_score_from_active.py."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Optional

import pandas as pd
import pytest


@pytest.fixture
def fake_active_portfolio(monkeypatch):
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


@pytest.fixture
def fake_price_history(monkeypatch):
    class _Stub:
        def __init__(self) -> None:
            self.frame: pd.DataFrame = pd.DataFrame()
            self.current_prices: dict[str, float] = {}
            self.raise_on_call: Exception | None = None

        def set(self, frame: pd.DataFrame) -> None:
            self.frame = frame

        def set_current_prices(self, prices: dict[str, float]) -> None:
            self.current_prices = prices

        def raise_with(self, exc: Exception) -> None:
            self.raise_on_call = exc

        def __call__(self, tickers, *, days=365, cache_provider=None):
            if self.raise_on_call is not None:
                raise self.raise_on_call
            cols = [t for t in tickers if t in self.frame.columns]
            return self.frame[cols] if cols else pd.DataFrame()

        def latest(self, tickers, *, cache_provider=None):
            rows = []
            for t in tickers:
                if t not in self.frame.columns:
                    continue
                series = self.frame[t].dropna()
                if series.empty:
                    continue
                rows.append(
                    SimpleNamespace(
                        ticker=t,
                        price=float(self.current_prices.get(t, series.iloc[-1])),
                        as_of=pd.Timestamp(series.index[-1]).strftime("%Y-%m-%d"),
                    )
                )
            return rows

    stub = _Stub()
    from backend.app.services import market_data as md

    monkeypatch.setattr(md, "get_price_history", stub)
    monkeypatch.setattr(md, "get_latest_prices", stub.latest)
    return stub


@dataclass
class _FakeReport:
    """Mirror enough of risk_engine.RiskReport to drive the serialiser."""

    annual_return: float = 0.08
    annual_volatility: float = 0.12
    sharpe_ratio: float = 0.5
    max_drawdown: float = -0.07
    var_95: float = 0.012
    var_99: float = 0.018
    cvar_95: float = 0.017
    risk_free_rate: float = 0.045
    betas: dict[str, float] = field(default_factory=lambda: {"SPY": 0.96})
    factor_betas: Optional[pd.DataFrame] = None
    # Portfolio-level factor regression (index=factor, cols=beta/r²/t/p) —
    # this is what the report serialises, NOT the per-asset factor_betas matrix.
    portfolio_factor_betas: Optional[pd.DataFrame] = None
    component_var_pct: Optional[pd.Series] = None
    stress_loss: float = 0.09
    stress_market_shock: float = -0.10
    stress_asset_losses: dict[str, float] = field(
        default_factory=lambda: {"SPY": 0.10, "BND": 0.02}
    )
    macro_betas: Optional[dict[str, Any]] = field(
        default_factory=lambda: {"rates": 0.4, "usd": -0.1, "oil": 0.05}
    )
    liquidity_risk: Optional[pd.DataFrame] = None
    drawdown_stats: Optional[dict[str, Any]] = field(
        default_factory=lambda: {"max_drawdown_pct": -0.07, "longest_drawdown_days": 90}
    )


@pytest.fixture
def fake_engine(monkeypatch):
    """Patch ``DataProvider`` + ``RiskEngine`` constructors so the
    route runs without yfinance or pandas-heavy math."""

    class _DP:
        def __init__(self, weights=None, holdings=None, **_):
            self.weights = dict(weights or {})
            self.holdings = dict(holdings or {})

    class _Engine:
        last_report: _FakeReport | None = None
        last_kwargs: dict | None = None
        last_dp_weights: dict | None = None

        def __init__(self, dp, **kwargs):
            _Engine.last_dp_weights = dp.weights
            _Engine.last_kwargs = kwargs
            self._report = _Engine.last_report

        def run(self):
            if self._report is None:
                raise RuntimeError("fake engine: no report configured")
            return self._report

    import data_provider as dpmod
    import risk_engine as rem

    monkeypatch.setattr(dpmod, "DataProvider", _DP)
    monkeypatch.setattr(rem, "RiskEngine", _Engine)
    return _Engine


@pytest.fixture
def fake_capital(monkeypatch):
    """Token-scoped cash + margin getters; defaults to none (scale=1.0)."""
    state = {"cash_balance": 0.0, "margin_loan": 0.0, "contributed_capital": 0.0}
    import libs.auth.active_portfolio as ap

    monkeypatch.setattr(
        ap,
        "get_active_capital_inputs",
        lambda access_token=None: {
            "cash_balance": state["cash_balance"],
            "contributed_capital": state["contributed_capital"],
        },
    )
    monkeypatch.setattr(
        ap, "get_active_margin_loan", lambda access_token=None: state["margin_loan"]
    )
    return state


def _make_history(tickers: list[str], days: int = 260) -> pd.DataFrame:
    """Deterministic levels around 100 — only the *last* row matters
    for weight calc; the rest is unused under the engine mock."""
    import numpy as np

    rng = np.random.default_rng(13)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    data = {tk: 100.0 + rng.normal(0.0, 1.0, days).cumsum() for tk in tickers}
    return pd.DataFrame(data, index=idx)


# ── auth + empty paths ────────────────────────────────────────────


def test_requires_bearer(test_client):
    resp = test_client.post("/api/v1/risk/report_from_active", json={})
    assert resp.status_code == 401


def test_no_active_portfolio(test_client, mint_token, fake_active_portfolio):
    fake_active_portfolio.set({})
    resp = test_client.post(
        "/api/v1/risk/report_from_active",
        json={},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "no_active_portfolio"


def test_no_market_data(test_client, mint_token, fake_active_portfolio, fake_price_history):
    fake_active_portfolio.set({"SPY": {"shares": 100}})
    fake_price_history.set(pd.DataFrame())
    resp = test_client.post(
        "/api/v1/risk/report_from_active",
        json={},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "no_market_data"
    assert body["error"]["details"]["tickers"] == ["SPY"]


def test_market_data_exception_is_server_error(
    test_client, mint_token, fake_active_portfolio, fake_price_history
):
    fake_active_portfolio.set({"SPY": {"shares": 100}})
    fake_price_history.raise_with(RuntimeError("yfinance refused"))
    resp = test_client.post(
        "/api/v1/risk/report_from_active",
        json={},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 500
    assert resp.json()["error"]["code"] == "server_error"


# ── happy path + serialisation ────────────────────────────────────


def test_happy_path_returns_full_report(
    test_client,
    mint_token,
    fake_active_portfolio,
    fake_price_history,
    fake_engine,
    fake_capital,
):
    fake_capital["cash_balance"] = 1000.0
    fake_capital["margin_loan"] = 250.0
    fake_capital["contributed_capital"] = 40000.0
    fake_active_portfolio.set(
        {
            "SPY": {"shares": 100, "avg_cost": 400.0},
            "BND": {"shares": 50, "avg_cost": 70.0},
        }
    )
    fake_price_history.set(_make_history(["BND", "SPY"]))

    # Portfolio-level factor regression: one row per factor (the shape the
    # real RiskEngine.portfolio_factor_betas produces).
    portfolio_factor_betas = pd.DataFrame(
        {
            "beta": [1.02, 0.85],
            "r_squared": [0.91, 0.80],
            "t_stat": [42.0, 18.0],
            "p_value": [0.0, 0.0],
        },
        index=["SPY", "QQQ"],
    )
    component_var = pd.Series({"SPY": 0.6, "BND": 0.4})
    # RiskEngine liquidity columns are PascalCase: ADV_30d / Days_to_Liquidate.
    liquidity = pd.DataFrame(
        {"Days_to_Liquidate": [0.5, 1.2], "ADV_30d": [1.0e9, 5.0e7]},
        index=["SPY", "BND"],
    )
    fake_engine.last_report = _FakeReport(
        portfolio_factor_betas=portfolio_factor_betas,
        component_var_pct=component_var,
        liquidity_risk=liquidity,
    )

    token = mint_token(sub="user-r")
    resp = test_client.post(
        "/api/v1/risk/report_from_active",
        json={"market_shock": -0.10},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.json()
    body = resp.json()
    assert body["error"] is None
    data = body["data"]

    latest_equity = 100 * float(fake_price_history.frame["SPY"].dropna().iloc[-1]) + 50 * float(
        fake_price_history.frame["BND"].dropna().iloc[-1]
    )
    previous_equity = 100 * float(fake_price_history.frame["SPY"].dropna().iloc[-2]) + 50 * float(
        fake_price_history.frame["BND"].dropna().iloc[-2]
    )
    expected_net = latest_equity + 1000.0 - 250.0
    expected_scale = latest_equity / expected_net
    expected_daily_pnl = latest_equity - previous_equity

    # KPI block. Cash dilutes and margin levers equity risk, so the
    # magnitude metrics use the investor's net-equity scale.
    assert data["var_95"] == pytest.approx(0.012 * expected_scale)
    assert data["cvar_95"] == pytest.approx(0.017 * expected_scale)
    assert data["sharpe_ratio"] == pytest.approx(0.5)

    assert data["total_value"] == pytest.approx(latest_equity + 1000.0, abs=0.01)
    assert data["net_equity"] == pytest.approx(expected_net, abs=0.01)
    assert data["daily_pnl"] == pytest.approx(expected_daily_pnl, abs=0.01)
    assert data["daily_return"] == pytest.approx(
        expected_daily_pnl / (previous_equity + 1000.0 - 250.0)
    )
    assert data["total_pnl"] == pytest.approx(expected_net - 40000.0, abs=0.01)
    assert data["total_return"] == pytest.approx((expected_net - 40000.0) / 40000.0)

    # Tables made it through serialisation.
    assert [r["factor"] for r in data["factor_betas"]] == ["SPY", "QQQ"]
    assert data["factor_betas"][0]["beta"] == pytest.approx(1.02)
    cvar_by_ticker = {r["ticker"]: r["pct"] for r in data["component_var_pct"]}
    assert cvar_by_ticker == {"SPY": pytest.approx(0.6), "BND": pytest.approx(0.4)}

    # Stress block.
    assert data["stress_loss"] == pytest.approx(0.09 * expected_scale)
    assert data["stress_market_shock"] == pytest.approx(-0.10)
    stress_by_ticker = {r["ticker"]: r["loss_pct"] for r in data["stress_asset_losses"]}
    assert stress_by_ticker == {"SPY": pytest.approx(0.10), "BND": pytest.approx(0.02)}

    # Macro betas pass through as a flat dict.
    assert data["macro_betas"] == {"rates": 0.4, "usd": -0.1, "oil": 0.05}

    # Liquidity ships market_value computed from the price frame.
    liq_by_ticker = {r["ticker"]: r for r in data["liquidity"]}
    assert "SPY" in liq_by_ticker
    assert liq_by_ticker["SPY"]["days_to_liquidate"] == pytest.approx(0.5)
    assert liq_by_ticker["SPY"]["market_value"] > 0  # 100 shares × last close

    # The active-portfolio resolver received the caller's JWT (RLS
    # contract).
    assert fake_active_portfolio.calls == [token]

    # Engine got the body's market_shock.
    assert fake_engine.last_kwargs["market_shock"] == pytest.approx(-0.10)


def test_margin_scales_report_risk_to_net_equity(
    test_client,
    mint_token,
    fake_active_portfolio,
    fake_price_history,
    fake_engine,
    fake_capital,
):
    """A margin loan equal to half the equity → net_equity = ½·equity →
    risk scalar = 2.0. The magnitude metrics (vol, VaR, CVaR, stress
    loss) must double; Sharpe (scale-invariant) and betas (leverage-
    invariant) must NOT change."""
    history = _make_history(["SPY"])
    fake_active_portfolio.set({"SPY": {"shares": 100, "avg_cost": 50.0}})
    fake_price_history.set(history)
    fake_engine.last_report = _FakeReport()  # var_95=0.012, cvar=0.017, vol=0.12

    equity_value = 100 * float(history["SPY"].dropna().iloc[-1])
    fake_capital["margin_loan"] = 0.5 * equity_value  # → leverage 2×

    resp = test_client.post(
        "/api/v1/risk/report_from_active",
        json={},
        headers={"Authorization": f"Bearer {mint_token(sub='user-lev-rep')}"},
    )
    assert resp.status_code == 200, resp.json()
    data = resp.json()["data"]

    assert data["var_95"] == pytest.approx(0.012 * 2.0, rel=1e-6)
    assert data["cvar_95"] == pytest.approx(0.017 * 2.0, rel=1e-6)
    assert data["annual_volatility"] == pytest.approx(0.12 * 2.0, rel=1e-6)
    assert data["stress_loss"] == pytest.approx(0.09 * 2.0, rel=1e-6)
    # Sharpe is invariant under this leverage/cash mix.
    assert data["sharpe_ratio"] == pytest.approx(0.5, rel=1e-6)
    # Per-asset betas are leverage-invariant.
    assert data["betas"]["SPY"] == pytest.approx(0.96)


def test_nan_values_are_scrubbed_to_null(
    test_client,
    mint_token,
    fake_active_portfolio,
    fake_price_history,
    fake_engine,
):
    """An engine that emits NaN for ``sharpe_ratio`` (e.g. zero
    volatility window) must surface as ``null`` in the envelope, not
    crash the JSONResponse renderer."""
    fake_active_portfolio.set({"SPY": {"shares": 100}})
    fake_price_history.set(_make_history(["SPY"]))
    fake_engine.last_report = _FakeReport(
        sharpe_ratio=float("nan"),
        max_drawdown=float("-inf"),
    )

    resp = test_client.post(
        "/api/v1/risk/report_from_active",
        json={},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["sharpe_ratio"] is None
    assert data["max_drawdown"] is None
    # var_95 was finite; it must NOT be nulled.
    assert isinstance(data["var_95"], float)
    assert math.isfinite(data["var_95"])
