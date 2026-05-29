"""MCP tool-handler contract.

Tests target the pure tool implementations in
``backend.mcp_server.tools`` directly — no MCP transport spawned. The
protocol layer is thin and well-tested upstream; what we own is the
tool shape + the wiring to our service modules.

We mock the underlying services so tests stay hermetic and fast.
"""

from __future__ import annotations

import asyncio

import numpy as np
import pandas as pd
import pytest


def _run(coro):
    """Small helper — every test runs one coroutine to completion."""
    return asyncio.run(coro)


# ── registry shape ────────────────────────────────────────────────


def test_tool_registry_has_unique_names_and_required_keys():
    from backend.mcp_server.tools import TOOLS

    names = [t["name"] for t in TOOLS]
    # Naming: prefix every tool so Claude clients with multiple servers
    # can disambiguate without collisions.
    assert all(name.startswith("mindmarket_") for name in names)
    # No duplicates — the dispatcher uses name as a dict key.
    assert len(names) == len(set(names))
    # Each entry must carry the four MCP-required fields.
    for t in TOOLS:
        assert set(t.keys()) >= {"name", "description", "input_schema", "handler"}
        assert callable(t["handler"])
        assert t["input_schema"]["type"] == "object"


def test_each_tool_has_a_human_description():
    """MCP clients show this to the user (and the LLM uses it to
    decide whether to call the tool). A blank one is a UX bug."""
    from backend.mcp_server.tools import TOOLS

    for t in TOOLS:
        assert len(t["description"]) > 40, f"Tool {t['name']} description too short"


# ── tool: get_yield_curve ─────────────────────────────────────────


def test_get_yield_curve_returns_service_payload(monkeypatch):
    from backend.app.services import macro_data as md
    from backend.mcp_server.tools import get_yield_curve

    fake = md.YieldCurveResult(
        as_of="2026-05-28",
        points=[
            md.YieldCurvePoint(tenor="3M", yield_pct=3.69),
            md.YieldCurvePoint(tenor="10Y", yield_pct=4.45),
        ],
    )
    monkeypatch.setattr(md, "get_yield_curve", lambda: fake)

    result = _run(get_yield_curve({}))
    assert result["as_of"] == "2026-05-28"
    assert [p["tenor"] for p in result["points"]] == ["3M", "10Y"]
    assert result["points"][1]["yield_pct"] == pytest.approx(4.45)


# ── tool: get_macro_series ────────────────────────────────────────


def test_get_macro_series_passes_ids_to_service(monkeypatch):
    from backend.app.services import macro_data as md
    from backend.mcp_server.tools import get_macro_series

    calls: list[tuple[list[str], int]] = []

    def _stub(ids, *, days):
        calls.append((list(ids), days))
        return [
            md.SeriesResult(
                series_id="DFF",
                label="Federal Funds Effective Rate (daily)",
                latest_value=4.31,
                latest_date="2026-05-27",
                points=[md.SeriesPoint(date="2026-05-27", value=4.31)],
            )
        ]

    monkeypatch.setattr(md, "get_fred_series_batch", _stub)

    out = _run(get_macro_series({"series_ids": ["DFF"], "days": 60}))
    assert calls == [(["DFF"], 60)]
    assert out["series"][0]["series_id"] == "DFF"
    assert out["series"][0]["latest_value"] == pytest.approx(4.31)
    # n_points is the summary; full series isn't shipped over MCP to
    # keep the LLM context small.
    assert out["series"][0]["n_points"] == 1


# ── tool: get_market_prices ───────────────────────────────────────


def test_get_market_prices_returns_compact_rows(monkeypatch):
    from backend.app.services import market_data as mkd
    from backend.mcp_server.tools import get_market_prices

    fake_rows = [
        mkd.LatestPrice(ticker="SPY", price=521.3, as_of="2026-05-28"),
        mkd.LatestPrice(ticker="BND", price=72.5, as_of="2026-05-28"),
    ]
    monkeypatch.setattr(mkd, "get_latest_prices", lambda tickers: list(fake_rows))

    out = _run(get_market_prices({"tickers": ["SPY", "BND"]}))
    assert {r["ticker"] for r in out["prices"]} == {"SPY", "BND"}


# ── tool: score_portfolio ─────────────────────────────────────────


def _fake_history(tickers: list[str], days: int = 260) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    data = {tk: 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, days))) for tk in tickers}
    return pd.DataFrame(data, index=idx)


def test_score_portfolio_happy_path(monkeypatch):
    from backend.app.services import market_data as mkd
    from backend.mcp_server.tools import score_portfolio

    monkeypatch.setattr(
        mkd, "get_price_history", lambda tickers, *, days=365: _fake_history(list(tickers))
    )

    out = _run(
        score_portfolio(
            {
                "holdings": [
                    {"ticker": "SPY", "market_value": 60000},
                    {"ticker": "BND", "market_value": 40000},
                ],
                "risk_preference": 3,
            }
        )
    )
    assert 0 <= out["overall_score"] <= 1000
    assert set(out["dimensions"].keys()) == {
        "risk_match",
        "risk_adjusted_return",
        "downside_protection",
    }
    # Keep the payload compact — the LLM sees this as text. No giant
    # returns matrix; just the headline numbers.
    assert "annual_return" in out["metrics"]


def test_score_portfolio_raises_when_no_holdings():
    from backend.mcp_server.tools import score_portfolio

    with pytest.raises(ValueError, match="No tickers"):
        _run(score_portfolio({"holdings": []}))


def test_score_portfolio_raises_when_market_data_empty(monkeypatch):
    from backend.app.services import market_data as mkd
    from backend.mcp_server.tools import score_portfolio

    monkeypatch.setattr(mkd, "get_price_history", lambda tickers, *, days=365: pd.DataFrame())

    with pytest.raises(ValueError, match="No market data"):
        _run(score_portfolio({"holdings": [{"ticker": "ZZZZ", "market_value": 1000}]}))
