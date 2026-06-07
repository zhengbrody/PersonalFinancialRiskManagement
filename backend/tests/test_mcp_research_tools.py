"""Phase D — the 6 new MCP tools reuse the same services (no separate logic)."""

from __future__ import annotations

import asyncio

from backend.app.schemas import research as R


def _run(coro):
    return asyncio.run(coro)


# ── registry wiring ─────────────────────────────────────────────────


def test_new_tools_registered():
    from backend.mcp_server.tools import TOOLS

    names = {t["name"] for t in TOOLS}
    assert {
        "mindmarket_get_ticker_fact_pack",
        "mindmarket_compare_tickers",
        "mindmarket_get_macro_context",
        "mindmarket_get_portfolio_risk_drivers",
        "mindmarket_run_portfolio_scenario",
        "mindmarket_generate_action_cards",
    } <= names


# ── fact-pack / compare reuse research_factpack ─────────────────────


def test_get_ticker_fact_pack(monkeypatch):
    from backend.app.services import research_factpack as rf
    from backend.mcp_server.tools import get_ticker_fact_pack

    monkeypatch.setattr(
        rf, "build_fact_pack", lambda tk: R.FactPack(ticker=tk.upper(), price=100.0, name="X")
    )
    out = _run(get_ticker_fact_pack({"ticker": "aapl"}))
    assert out["ticker"] == "AAPL" and out["price"] == 100.0
    assert "valuation" in out and "data_quality" in out  # full FactPack model_dump


def test_compare_tickers_skips_bad_one(monkeypatch):
    from backend.app.services import research_factpack as rf
    from backend.mcp_server.tools import compare_tickers

    def fake(tk):
        if tk == "BAD":
            raise ValueError("nope")
        return R.FactPack(ticker=tk, price=10.0, valuation=R.ValuationBlock(pe=20.0, band="cheap"))

    monkeypatch.setattr(rf, "build_fact_pack", fake)
    out = _run(compare_tickers({"tickers": ["AAPL", "BAD", "MSFT"]}))
    tickers = [r["ticker"] for r in out["comparison"]]
    assert tickers == ["AAPL", "MSFT"]  # BAD dropped, others survive
    assert out["comparison"][0]["valuation_band"] == "cheap"


# ── macro context reuses market_regime ──────────────────────────────


def test_get_macro_context(monkeypatch):
    from backend.app.services import market_regime
    from backend.mcp_server.tools import get_macro_context

    class _Snap:
        def model_dump(self):
            return {"vix": {"current": 14.0}, "fear_greed": {"score": 60}}

    monkeypatch.setattr(market_regime, "get_market_regime", lambda: _Snap())
    out = _run(get_macro_context({}))
    assert out["vix"]["current"] == 14.0


# ── portfolio tools reuse the deterministic score ───────────────────


class _Metrics:
    def as_dict(self):
        return {
            "annual_volatility": 0.18,
            "max_drawdown": -0.25,
            "var_95_daily": -0.02,
            "beta_to_benchmark": 1.2,
            "total_value": 10000.0,
        }


class _Dim:
    def __init__(self, name, score):
        self.name = name
        self.score = score
        self.status = "ok"
        self.detail = "d"


class _Score:
    overall_score = 700
    metrics = _Metrics()
    dimensions = {"a": _Dim("Risk match", 80.0), "b": _Dim("Downside", 40.0)}


def test_risk_drivers_ranked_weakest_first(monkeypatch):
    import backend.mcp_server.tools as tools

    monkeypatch.setattr(tools, "_score_from_holdings", lambda h, **k: (_Score(), []))
    out = _run(
        tools.get_portfolio_risk_drivers({"holdings": [{"ticker": "SPY", "market_value": 1}]})
    )
    assert out["overall_score"] == 700
    assert [d["name"] for d in out["risk_drivers"]] == ["Downside", "Risk match"]  # weakest first


def test_run_scenario_linear_beta(monkeypatch):
    import backend.mcp_server.tools as tools

    monkeypatch.setattr(tools, "_score_from_holdings", lambda h, **k: (_Score(), []))
    out = _run(
        tools.run_portfolio_scenario(
            {"holdings": [{"ticker": "SPY", "market_value": 1}], "shocks": [-0.1]}
        )
    )
    assert out["method"] == "linear_beta_approximation" and out["beta_to_benchmark"] == 1.2
    # beta 1.2 * -0.10 * 10000 = -1200
    assert out["scenarios"][0]["estimated_pnl"] == -1200.0


def test_generate_action_cards(monkeypatch):
    import backend.mcp_server.tools as tools

    monkeypatch.setattr(tools, "_score_from_holdings", lambda h, **k: (_Score(), []))

    class _Agent:
        def prepare(self, score, positions):
            return {
                "tool_results": {"hidden_fees": {"summary": "You pay $42/yr in fees"}},
                "draft_trades": [],
            }

    monkeypatch.setattr("libs.ai_agents.portfolio_agents.StrategyOptimizerAgent", lambda: _Agent())
    out = _run(tools.generate_action_cards({"holdings": [{"ticker": "SPY", "market_value": 1}]}))
    assert out["action_cards"][0]["kind"] == "hidden_fees"
    assert "fees" in out["action_cards"][0]["summary"]
