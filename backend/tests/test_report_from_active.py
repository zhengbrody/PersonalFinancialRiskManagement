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

        def __call__(self, tickers, *, days=365, cache_provider=None, provenance=None):
            if self.raise_on_call is not None:
                raise self.raise_on_call
            cols = [t for t in tickers if t in self.frame.columns]
            if provenance is not None:
                provenance["by_ticker"] = {c: "yfinance" for c in cols}
                provenance["missing"] = [t for t in tickers if t not in cols]
            return self.frame[cols] if cols else pd.DataFrame()

        def latest(self, tickers, *, cache_provider=None, provenance=None):
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
    # Engine computes this (risk_engine.py run(): returns.corr()); default None
    # keeps every pre-desk test byte-identical (correlation block → null).
    corr_matrix: Optional[pd.DataFrame] = None


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


def test_report_ships_cockpit_dimensions_and_losses(
    test_client,
    mint_token,
    fake_active_portfolio,
    fake_price_history,
    fake_engine,
    fake_capital,
    monkeypatch,
):
    """The explainable cockpit blocks (dimensions[] + losses) reach the wire,
    with a genuine 1-day VaR distinct from the report's 21-day var_95."""
    from backend.app.services import snapshots

    monkeypatch.setattr(snapshots, "get_snapshot_history", lambda *a, **k: [])
    fake_capital["cash_balance"] = 1000.0
    fake_capital["margin_loan"] = 0.0
    fake_capital["contributed_capital"] = 40000.0
    fake_active_portfolio.set(
        {"SPY": {"shares": 100, "avg_cost": 400.0}, "BND": {"shares": 50, "avg_cost": 70.0}}
    )
    fake_price_history.set(_make_history(["BND", "SPY"]))
    fake_engine.last_report = _FakeReport(
        portfolio_factor_betas=pd.DataFrame(
            {"beta": [0.95], "r_squared": [0.8], "t_stat": [30.0], "p_value": [0.0]},
            index=["SPY"],
        ),
        component_var_pct=pd.Series({"SPY": 0.6, "BND": 0.4}),
        liquidity_risk=pd.DataFrame(
            {"Days_to_Liquidate": [0.5, 1.2], "ADV_30d": [1.0e9, 5.0e7]}, index=["SPY", "BND"]
        ),
    )

    token = mint_token(sub="user-cockpit")
    resp = test_client.post(
        "/api/v1/risk/report_from_active",
        json={"market_shock": -0.10},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.json()
    data = resp.json()["data"]

    # Dimensions — the eight-key unified model reaches the client.
    dims = {d["key"]: d for d in data["dimensions"]}
    assert set(dims) == {
        "concentration",
        "volatility",
        "drawdown",
        "beta",
        "correlation",
        "liquidity",
        "leverage",
        "options",
    }
    # every measurable dimension carries the required cockpit fields
    for d in data["dimensions"]:
        if d["measurable"]:
            assert d["status"] in ("calm", "normal", "elevated", "high")
            assert d["explanation"] and d["action"]
    # no options in this book → options is honest n/a, not a fake zero
    assert dims["options"]["measurable"] is False and dims["options"]["status"] == "n/a"
    # unlevered book (no margin)
    assert dims["leverage"]["status"] == "calm"

    # Losses — % AND $, with 1-day distinct from the 21-day headline.
    losses = data["losses"]
    assert losses["var_1d_95"]["horizon"] == "1d"
    assert losses["var_1d_95"]["pct"] is not None and losses["var_1d_95"]["usd"] is not None
    assert losses["var_21d_95"]["horizon"] == "21d"
    assert losses["var_21d_95"]["pct"] == pytest.approx(data["var_95"])
    assert losses["margin_buffer"]["status"] == "none"  # no margin loan


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


# ── data-quality notes ────────────────────────────────────────────


def test_nan_beta_fallback_and_short_history_are_flagged(
    test_client,
    mint_token,
    fake_active_portfolio,
    fake_price_history,
    fake_engine,
    fake_capital,
):
    """The stress test silently substitutes beta=1.0 for NaN betas and
    annualizes off whatever history exists — both must surface as
    data_quality_notes instead of staying invisible."""
    fake_active_portfolio.set(
        {
            "SPY": {"shares": 100, "avg_cost": 400.0},
            "BND": {"shares": 50, "avg_cost": 70.0},
        }
    )
    fake_price_history.set(_make_history(["BND", "SPY"], days=40))
    fake_engine.last_report = _FakeReport(betas={"SPY": 0.96, "BND": float("nan")})

    resp = test_client.post(
        "/api/v1/risk/report_from_active",
        json={},
        headers={"Authorization": f"Bearer {mint_token(sub='user-dq')}"},
    )
    assert resp.status_code == 200, resp.json()
    notes = resp.json()["data"]["data_quality_notes"]
    assert any("BND" in n and "beta" in n.lower() for n in notes)
    assert any("40 trading days" in n for n in notes)


def test_all_nan_betas_flag_benchmark_unavailable(
    test_client,
    mint_token,
    fake_active_portfolio,
    fake_price_history,
    fake_engine,
    fake_capital,
):
    fake_active_portfolio.set({"SPY": {"shares": 100, "avg_cost": 400.0}})
    fake_price_history.set(_make_history(["SPY"]))
    fake_engine.last_report = _FakeReport(betas={"SPY": float("nan")})

    resp = test_client.post(
        "/api/v1/risk/report_from_active",
        json={},
        headers={"Authorization": f"Bearer {mint_token(sub='user-dq2')}"},
    )
    assert resp.status_code == 200, resp.json()
    notes = resp.json()["data"]["data_quality_notes"]
    assert any("Benchmark data was unavailable" in n for n in notes)


def test_clean_report_has_no_data_quality_notes(
    test_client,
    mint_token,
    fake_active_portfolio,
    fake_price_history,
    fake_engine,
    fake_capital,
):
    fake_active_portfolio.set({"SPY": {"shares": 100, "avg_cost": 400.0}})
    fake_price_history.set(_make_history(["SPY"]))
    fake_engine.last_report = _FakeReport()

    resp = test_client.post(
        "/api/v1/risk/report_from_active",
        json={},
        headers={"Authorization": f"Bearer {mint_token(sub='user-dq3')}"},
    )
    assert resp.status_code == 200, resp.json()
    assert resp.json()["data"]["data_quality_notes"] == []


def test_concentration_block_is_deterministic_arithmetic(
    test_client,
    mint_token,
    fake_active_portfolio,
    fake_price_history,
    fake_engine,
    fake_capital,
):
    fake_active_portfolio.set(
        {
            "SPY": {"shares": 100, "avg_cost": 400.0},
            "BND": {"shares": 50, "avg_cost": 70.0},
        }
    )
    fake_price_history.set(_make_history(["BND", "SPY"]))
    fake_engine.last_report = _FakeReport()

    resp = test_client.post(
        "/api/v1/risk/report_from_active",
        json={},
        headers={"Authorization": f"Bearer {mint_token(sub='user-conc')}"},
    )
    assert resp.status_code == 200, resp.json()
    conc = resp.json()["data"]["concentration"]
    assert conc is not None

    mv_spy = 100 * float(fake_price_history.frame["SPY"].dropna().iloc[-1])
    mv_bnd = 50 * float(fake_price_history.frame["BND"].dropna().iloc[-1])
    total = mv_spy + mv_bnd
    w_top = max(mv_spy, mv_bnd) / total
    hhi = (mv_spy / total) ** 2 + (mv_bnd / total) ** 2

    assert conc["num_holdings"] == 2
    assert conc["top_holding_ticker"] == ("SPY" if mv_spy > mv_bnd else "BND")
    assert conc["top_holding_weight"] == pytest.approx(w_top)
    assert conc["top5_weight"] == pytest.approx(1.0)
    assert conc["hhi"] == pytest.approx(hhi)
    assert conc["effective_holdings"] == pytest.approx(1.0 / hhi)


def test_component_return_is_weight_times_annualized_mean(
    test_client,
    mint_token,
    fake_active_portfolio,
    fake_price_history,
    fake_engine,
    fake_capital,
):
    """component_return mirrors component VaR on the return side:
    contribution_i = w_i x mean(daily r_i) x 252, from the same price frame."""
    fake_active_portfolio.set(
        {
            "SPY": {"shares": 100, "avg_cost": 400.0},
            "BND": {"shares": 50, "avg_cost": 70.0},
        }
    )
    frame = _make_history(["BND", "SPY"])
    fake_price_history.set(frame)
    fake_engine.last_report = _FakeReport()

    resp = test_client.post(
        "/api/v1/risk/report_from_active",
        json={},
        headers={"Authorization": f"Bearer {mint_token(sub='user-cr')}"},
    )
    assert resp.status_code == 200, resp.json()
    rows = {r["ticker"]: r["contribution"] for r in resp.json()["data"]["component_return"]}
    assert set(rows) == {"SPY", "BND"}

    mv_spy = 100 * float(frame["SPY"].dropna().iloc[-1])
    mv_bnd = 50 * float(frame["BND"].dropna().iloc[-1])
    total = mv_spy + mv_bnd
    rets = frame.pct_change().dropna(how="all")
    for tk, mv in (("SPY", mv_spy), ("BND", mv_bnd)):
        expected = (mv / total) * float(rets[tk].dropna().mean()) * 252.0
        assert rows[tk] == pytest.approx(expected)


def test_concentration_sector_rollup(
    test_client,
    mint_token,
    fake_active_portfolio,
    fake_price_history,
    fake_engine,
    fake_capital,
):
    """Sector weights come from the deterministic resolver: a per-holding
    `sector` override wins; known tickers use the canonical SECTOR_MAP."""
    fake_active_portfolio.set(
        {
            "SPY": {"shares": 100, "avg_cost": 400.0},  # SECTOR_MAP: Broad Market ETF
            "BND": {"shares": 50, "avg_cost": 70.0, "sector": "Bonds"},  # override
        }
    )
    frame = _make_history(["BND", "SPY"])
    fake_price_history.set(frame)
    fake_engine.last_report = _FakeReport()

    resp = test_client.post(
        "/api/v1/risk/report_from_active",
        json={},
        headers={"Authorization": f"Bearer {mint_token(sub='user-sect')}"},
    )
    assert resp.status_code == 200, resp.json()
    conc = resp.json()["data"]["concentration"]
    sectors = {s["sector"]: s["weight"] for s in conc["sectors"]}

    mv_spy = 100 * float(frame["SPY"].dropna().iloc[-1])
    mv_bnd = 50 * float(frame["BND"].dropna().iloc[-1])
    total = mv_spy + mv_bnd
    assert sectors["Broad Market ETF"] == pytest.approx(mv_spy / total)
    assert sectors["Bonds"] == pytest.approx(mv_bnd / total)
    assert sum(sectors.values()) == pytest.approx(1.0)
    assert conc["top_sector"] in sectors
    assert conc["top_sector_weight"] == pytest.approx(max(sectors.values()))


def test_option_overlay_folds_into_engine_weights_and_notes(
    test_client,
    mint_token,
    fake_active_portfolio,
    fake_price_history,
    fake_engine,
    fake_capital,
    monkeypatch,
):
    """An option holding is folded into its underlying's risk weight via the
    delta-equivalent overlay, and a data-quality note explains it."""
    import backend.app.services.options_analytics as oa

    monkeypatch.setattr(
        oa,
        "analyze_contracts",
        lambda specs, **k: {
            "results": [
                {
                    "underlying": "AAPL",
                    "quantity": 2,
                    "contract_multiplier": 100,
                    "greeks": {"delta": 0.6, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0},
                }
            ]
        },
    )
    fake_active_portfolio.set(
        {
            "SPY": {"shares": 100, "avg_cost": 400.0},
            "AAPL270115C00150000": {
                "shares": 2,
                "asset_type": "option",
                "option_type": "call",
                "underlying": "AAPL",
                "strike": 150,
                "expiry": "2027-01-15",
                "contract_multiplier": 100,
            },
        }
    )
    fake_price_history.set(_make_history(["SPY", "AAPL"]))
    fake_engine.last_report = _FakeReport()

    resp = test_client.post(
        "/api/v1/risk/report_from_active",
        json={},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]

    # The overlay added AAPL (option underlying) to the engine weights.
    assert "AAPL" in (fake_engine.last_dp_weights or {})
    # And a note explains the delta-equivalent fold-in.
    assert any("delta-equivalent" in n for n in body["data_quality_notes"])


# ── desk analytics: correlation + rolling volatility ───────────────


def _corr_df(tickers: list[str], pairs: dict[tuple[str, str], float]) -> pd.DataFrame:
    """Symmetric correlation DataFrame with diag=1 and given off-diag pairs."""
    import numpy as np

    n = len(tickers)
    m = np.eye(n)
    idx = {t: i for i, t in enumerate(tickers)}
    for (a, b), v in pairs.items():
        m[idx[a], idx[b]] = v
        m[idx[b], idx[a]] = v
    return pd.DataFrame(m, index=tickers, columns=tickers)


def _report_data(test_client, mint_token, payload=None):
    resp = test_client.post(
        "/api/v1/risk/report_from_active",
        json=payload or {},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200, resp.json()
    return resp.json()["data"]


def test_correlation_block_insights(
    test_client, mint_token, fake_active_portfolio, fake_price_history, fake_engine, fake_capital
):
    """Hand-computed insights: avg ρ, most-correlated pair, best diversifier,
    weight-descending ticker order, DR ≥ 1 (a mathematical identity)."""
    fake_active_portfolio.set(
        {"SPY": {"shares": 100}, "QQQ": {"shares": 30}, "BND": {"shares": 50}}
    )
    fake_price_history.set(_make_history(["SPY", "QQQ", "BND"]))
    fake_engine.last_report = _FakeReport(
        corr_matrix=_corr_df(
            ["SPY", "QQQ", "BND"],
            {("SPY", "QQQ"): 0.9, ("SPY", "BND"): 0.2, ("QQQ", "BND"): 0.1},
        )
    )

    corr = _report_data(test_client, mint_token)["correlation"]
    assert corr is not None
    # avg of upper triangle = (0.9 + 0.2 + 0.1) / 3
    assert corr["avg_pairwise"] == pytest.approx(0.4, abs=1e-9)
    assert corr["top_pair"] == {"a": "SPY", "b": "QQQ", "rho": 0.9}
    # per-ticker avg ρ: SPY .55, QQQ .5, BND .15 → BND diversifies best
    assert corr["best_diversifier"]["ticker"] == "BND"
    assert corr["best_diversifier"]["avg_rho"] == pytest.approx(0.15, abs=1e-9)
    # ~100-level prices → MV order by shares: SPY(100) > BND(50) > QQQ(30)
    assert corr["tickers"] == ["SPY", "BND", "QQQ"]
    assert corr["truncated"] is False and corr["total_tickers"] == 3
    # matrix: rounded, symmetric, diag 1.0
    i, j = corr["tickers"].index("SPY"), corr["tickers"].index("QQQ")
    assert corr["matrix"][i][j] == corr["matrix"][j][i] == 0.9
    assert all(corr["matrix"][k][k] == 1.0 for k in range(3))
    # Σŵσ / σ_p ≥ 1 by construction — violating this means broken math.
    assert corr["diversification_ratio"] is not None
    assert corr["diversification_ratio"] >= 1.0


def test_correlation_nan_pair_skipped(
    test_client, mint_token, fake_active_portfolio, fake_price_history, fake_engine, fake_capital
):
    fake_active_portfolio.set({"SPY": {"shares": 100}, "BND": {"shares": 50}})
    fake_price_history.set(_make_history(["SPY", "BND"]))
    m = _corr_df(["SPY", "BND"], {("SPY", "BND"): float("nan")})
    fake_engine.last_report = _FakeReport(corr_matrix=m)

    corr = _report_data(test_client, mint_token)["correlation"]
    # The ONLY off-diag pair is NaN → no finite pair → whole block null.
    assert corr is None


def test_correlation_null_when_absent_or_single(
    test_client, mint_token, fake_active_portfolio, fake_price_history, fake_engine, fake_capital
):
    fake_active_portfolio.set({"SPY": {"shares": 100}})
    fake_price_history.set(_make_history(["SPY"]))
    fake_engine.last_report = _FakeReport()  # corr_matrix defaults to None
    assert _report_data(test_client, mint_token)["correlation"] is None

    fake_engine.last_report = _FakeReport(corr_matrix=_corr_df(["SPY"], {}))
    assert _report_data(test_client, mint_token)["correlation"] is None


def test_correlation_capped_at_30_by_weight(
    test_client, mint_token, fake_active_portfolio, fake_price_history, fake_engine, fake_capital
):
    import numpy as np

    tickers = [f"S{i:02d}" for i in range(31)]
    # Descending shares → S00 heaviest … S30 lightest (prices all ~100).
    fake_active_portfolio.set({t: {"shares": 310 - 10 * i} for i, t in enumerate(tickers)})
    fake_price_history.set(_make_history(tickers))
    m = np.full((31, 31), 0.5)
    np.fill_diagonal(m, 1.0)
    fake_engine.last_report = _FakeReport(
        corr_matrix=pd.DataFrame(m, index=tickers, columns=tickers)
    )

    corr = _report_data(test_client, mint_token)["correlation"]
    assert corr["truncated"] is True
    assert corr["total_tickers"] == 31
    assert len(corr["tickers"]) == 30 and len(corr["matrix"]) == 30
    assert "S30" not in corr["tickers"]  # the lightest name is the one dropped


def test_rolling_vol_arithmetic_with_risk_scale(
    test_client, mint_token, fake_active_portfolio, fake_price_history, fake_engine, fake_capital
):
    """current == hand-computed rolling(21).std(ddof=1) × √252 × risk_scale;
    the in-frame SPY benchmark is the same computation UNscaled."""
    import math as _math

    import numpy as np

    fake_active_portfolio.set({"SPY": {"shares": 100}, "BND": {"shares": 50}})
    frame = _make_history(["SPY", "BND"])
    fake_price_history.set(frame)
    fake_engine.last_report = _FakeReport()

    # Margin = half the equity book → net = equity/2 → risk_scale = 2.0.
    latest_equity = 100 * float(frame["SPY"].iloc[-1]) + 50 * float(frame["BND"].iloc[-1])
    fake_capital["margin_loan"] = latest_equity / 2.0

    data = _report_data(test_client, mint_token)
    rv = data["rolling_volatility"]
    assert rv is not None and rv["window_days"] == 21 and rv["benchmark_ticker"] == "SPY"

    # Recompute exactly what the endpoint should have done.
    mvs = {
        "SPY": 100 * float(frame["SPY"].iloc[-1]),
        "BND": 50 * float(frame["BND"].iloc[-1]),
    }
    total = sum(mvs.values())
    w = np.array([mvs["SPY"] / total, mvs["BND"] / total])
    rets = frame[["SPY", "BND"]].pct_change().dropna(how="any")
    port = pd.Series(rets[["SPY", "BND"]].to_numpy().dot(w), index=rets.index)
    expected_last = float(port.rolling(21).std().dropna().iloc[-1]) * _math.sqrt(252.0) * 2.0
    assert rv["current"] == pytest.approx(expected_last, rel=1e-3)

    spy_expected = float(
        (frame["SPY"].pct_change().dropna().rolling(21).std() * _math.sqrt(252.0)).dropna().iloc[-1]
    )
    # Benchmark is UNscaled — levering the book must not touch the index line.
    assert rv["series"][-1]["benchmark"] == pytest.approx(spy_expected, rel=1e-3)
    # current is defined as the series' last portfolio point.
    assert rv["series"][-1]["portfolio"] == pytest.approx(rv["current"], rel=1e-9)
    assert rv["state"] in {"calm", "normal", "elevated"}
    assert len(rv["series"]) <= 252


def test_rolling_vol_benchmark_fail_soft(
    test_client, mint_token, fake_active_portfolio, fake_price_history, fake_engine, fake_capital
):
    fake_active_portfolio.set({"QQQ": {"shares": 10}, "BND": {"shares": 50}})
    fake_price_history.set(_make_history(["QQQ", "BND"]))  # no SPY anywhere
    fake_engine.last_report = _FakeReport()

    rv = _report_data(test_client, mint_token)["rolling_volatility"]
    assert rv is not None
    assert rv["benchmark_ticker"] is None
    assert all(p["benchmark"] is None for p in rv["series"])
    assert rv["current"] is not None  # portfolio line intact


def test_rolling_vol_null_on_short_history(
    test_client, mint_token, fake_active_portfolio, fake_price_history, fake_engine, fake_capital
):
    fake_active_portfolio.set({"SPY": {"shares": 100}})
    fake_price_history.set(_make_history(["SPY"], days=30))  # < 2×window returns
    fake_engine.last_report = _FakeReport()

    assert _report_data(test_client, mint_token)["rolling_volatility"] is None


def test_diversification_ratio_hand_pinned(
    test_client, mint_token, fake_active_portfolio, fake_price_history, fake_engine, fake_capital
):
    """Two equal-weight, equal-vol, UNCORRELATED assets → DR = √2 exactly.
    Pins the arithmetic (not just the ≥1 identity): a ddof mismatch between
    numerator and denominator would shift this off √2."""
    import numpy as np

    n = 48  # multiple of 4 so the ±1% patterns are exactly uncorrelated
    r_a = np.tile([0.01, -0.01], n // 2)  # period 2
    r_b = np.tile([0.01, 0.01, -0.01, -0.01], n // 4)  # period 4, ρ(a,b)=0
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n + 1)
    frame = pd.DataFrame(
        {
            "AAA": 100.0 * np.cumprod(np.concatenate([[1.0], 1 + r_a])),
            "BBB": 100.0 * np.cumprod(np.concatenate([[1.0], 1 + r_b])),
        },
        index=idx,
    )
    # Equal weights: same share count, and both prices end near 100.
    fake_active_portfolio.set({"AAA": {"shares": 100}, "BBB": {"shares": 100}})
    fake_price_history.set(frame)
    fake_engine.last_report = _FakeReport(
        corr_matrix=_corr_df(["AAA", "BBB"], {("AAA", "BBB"): 0.0})
    )

    corr = _report_data(test_client, mint_token)["correlation"]
    # Weights aren't exactly 50/50 (prices drift slightly), so allow ~1%.
    assert corr["diversification_ratio"] == pytest.approx(math.sqrt(2.0), rel=0.015)
