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
                "tool_results": {
                    "hidden_fees": [
                        {
                            "ticker": "SPY",
                            "annual_fee_usd": 42.0,
                            "note": "Estimated annual fund fee: $42.",
                        }
                    ],
                    "unrealized_losses": [{"ticker": "QQQ", "loss_usd": 900.0, "loss_pct": 0.12}],
                },
                "risk_levers": [
                    {
                        "lever": "review_leverage",
                        "risk_dimension": "leverage",
                        "headline": "Review margin leverage",
                        "current": "gross exposure is 1.40x net equity",
                        "reference": "an unlevered book is 1.00x",
                        "evaluate": "stress a -20% move in Scenarios",
                    }
                ],
            }

    monkeypatch.setattr("libs.ai_agents.portfolio_agents.StrategyOptimizerAgent", lambda: _Agent())
    out = _run(tools.generate_action_cards({"holdings": [{"ticker": "SPY", "market_value": 1}]}))
    kinds = [c["kind"] for c in out["action_cards"]]
    assert kinds == ["fee_drag", "unrealized_losses", "risk_lever"]
    # Compliance: no BUY/SELL/ticker-amount trade combos anywhere in the payload.
    import json as _json
    import re as _re

    payload = _json.dumps(out)
    assert not _re.search(r"\b(BUY|SELL)\b", payload)
    assert "draft_trades" not in out
    assert "not trade instructions" in out["note"]


def test_generate_action_cards_real_path_no_mocked_agent(monkeypatch):
    """End-to-end through the REAL StrategyOptimizerAgent: guards the
    AssetPositionInput → .to_position() seam (review-caught: the old code
    AttributeError'd on every real invocation and only the mocked-agent test
    passed) and re-asserts the no-trade-instruction boundary on real output."""
    import json
    import re

    import numpy as np
    import pandas as pd

    import backend.mcp_server.tools as tools
    from backend.app.services import market_data

    idx = pd.bdate_range(end="2026-06-30", periods=300)
    rng = np.random.default_rng(3)
    frame = pd.DataFrame(
        {
            "QQQ": 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.02, 300))),
            "SPY": 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, 300))),
        },
        index=idx,
    )
    monkeypatch.setattr(market_data, "get_price_history", lambda tickers, days=365: frame)

    out = _run(
        tools.generate_action_cards(
            {
                "holdings": [
                    # concentrated AND at an unrealized loss → levers + tax card
                    {"ticker": "QQQ", "market_value": 60_000, "cost_basis": 70_000},
                    {"ticker": "SPY", "market_value": 20_000, "cost_basis": 19_000},
                ],
                "risk_preference": 1,
            }
        )
    )
    kinds = {c["kind"] for c in out["action_cards"]}
    assert "risk_lever" in kinds
    assert "unrealized_losses" in kinds
    payload = json.dumps(out)
    assert not re.search(r"\b(BUY|SELL)\b", payload)
    assert "TAX_LOSS_SWAP" not in payload and '"replacement"' not in payload
