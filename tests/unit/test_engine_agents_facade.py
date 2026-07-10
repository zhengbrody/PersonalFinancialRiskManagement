"""Tests for the engine/ + agents/ public facades.

These guarantee that:
1. The public re-export paths actually expose the same callables as the
   private impl, so a future move of the impl can't silently break
   `from engine import score_portfolio` callers.
2. The new validated entrypoints (score_portfolio_from_input,
   route_message) thread input through Pydantic correctly and adapt
   the agent's legacy dataclass to the typed AgentResponse.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from agents.orchestrator import route_message
from domain.models import AgentResponse, AssetPositionInput, PortfolioInput
from engine.quant import (
    score_portfolio,
    score_portfolio_from_input,
)
from libs.mindmarket_core.portfolio_scoring import score_portfolio as _internal_score


def _sample_returns(periods: int = 252) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2024-01-01", periods=periods)
    spy = rng.normal(0.00035, 0.010, periods)
    return pd.DataFrame(
        {
            "SPY": spy,
            "QQQ": spy * 1.2 + rng.normal(0.0, 0.006, periods),
            "BND": rng.normal(0.00012, 0.003, periods),
        },
        index=idx,
    )


def _sample_input() -> PortfolioInput:
    return PortfolioInput(
        positions=[
            AssetPositionInput(
                ticker="SPY",
                name="SPDR S&P 500",
                asset_type="public_security",
                market_value=60_000,
                cost_basis=50_000,
            ),
            AssetPositionInput(
                ticker="QQQ",
                name="Invesco QQQ",
                asset_type="public_security",
                market_value=30_000,
                cost_basis=25_000,
            ),
            AssetPositionInput(
                ticker="BND",
                name="Vanguard Bond",
                asset_type="public_security",
                market_value=10_000,
                cost_basis=10_500,
            ),
        ],
        risk_preference=3,
        risk_free_rate=0.04,
    )


# ── engine.quant ─────────────────────────────────────────────────────


def test_engine_score_portfolio_is_same_object_as_internal():
    """The facade re-exports the same callable; no double-wrapping."""
    assert score_portfolio is _internal_score


def test_score_portfolio_from_input_matches_direct_call():
    """Threading through Pydantic must produce the same numeric result
    as calling the math layer directly with equivalent positions."""
    portfolio = _sample_input()
    returns = _sample_returns()

    via_input = score_portfolio_from_input(portfolio, returns, benchmark_returns=returns["SPY"])
    direct = score_portfolio(
        portfolio.to_positions(),
        returns,
        benchmark_returns=returns["SPY"],
        risk_preference=3,
        risk_free_rate=0.04,
    )
    assert via_input.overall_score == direct.overall_score
    assert via_input.metrics.sharpe_ratio == direct.metrics.sharpe_ratio
    assert via_input.metrics.annual_volatility == direct.metrics.annual_volatility


# ── agents.orchestrator ───────────────────────────────────────────────


def test_route_message_empty_input_returns_friendly_prompt():
    """Empty / whitespace input must short-circuit, not crash the page."""
    portfolio = _sample_input()
    score = score_portfolio_from_input(_sample_input(), _sample_returns())
    resp = route_message("", score, portfolio.to_positions())
    assert isinstance(resp, AgentResponse)
    assert "Ask a question" in resp.response_markdown
    assert resp.tool_trace == []


def test_route_message_returns_pydantic_response_with_grounding():
    """Happy path: returns AgentResponse with grounded_in populated."""
    portfolio = _sample_input()
    returns = _sample_returns()
    score = score_portfolio_from_input(portfolio, returns)

    resp = route_message("analyze my portfolio risk", score, portfolio.to_positions())

    assert isinstance(resp, AgentResponse)
    assert resp.response_markdown  # non-empty
    # Grounded fields must equal the engine's exact outputs.
    assert resp.grounded_in["overall_score"] == score.overall_score
    assert resp.grounded_in["sharpe_ratio"] == score.metrics.sharpe_ratio
    assert resp.grounded_in["max_drawdown"] == score.metrics.max_drawdown


def test_route_message_catches_router_exception(monkeypatch):
    """A blow-up inside the agent layer must surface as typed text,
    not propagate as a 500."""
    from agents import orchestrator

    class _BoomRouter:
        def route(self, *a, **kw):
            raise RuntimeError("synthetic agent failure")

    monkeypatch.setattr(orchestrator, "PortfolioAgentRouter", lambda: _BoomRouter())

    portfolio = _sample_input()
    score = score_portfolio_from_input(portfolio, _sample_returns())
    resp = route_message("analyze", score, portfolio.to_positions())

    assert isinstance(resp, AgentResponse)
    assert "Could not produce a response" in resp.response_markdown
    assert "synthetic agent failure" in resp.response_markdown


def test_route_message_router_exception_chinese_message(monkeypatch):
    """A Chinese question gets the Chinese variant of the router-exception
    fallback (deterministic — no LLM involved)."""
    from agents import orchestrator

    class _BoomRouter:
        def route(self, *a, **kw):
            raise RuntimeError("synthetic agent failure")

    monkeypatch.setattr(orchestrator, "PortfolioAgentRouter", lambda: _BoomRouter())

    portfolio = _sample_input()
    score = score_portfolio_from_input(portfolio, _sample_returns())
    resp = route_message("分析我的组合", score, portfolio.to_positions())

    assert isinstance(resp, AgentResponse)
    assert "无法生成回答" in resp.response_markdown
    assert "synthetic agent failure" in resp.response_markdown
    assert "Could not produce a response" not in resp.response_markdown


def test_route_message_optimizer_keyword_routing():
    """Keyword 'tax' should route to optimizer (which returns
    risk levers / fee scan content, distinct from analyzer)."""
    portfolio = _sample_input()
    returns = _sample_returns()
    score = score_portfolio_from_input(portfolio, returns)

    resp = route_message(
        "check for tax-loss harvesting and fee issues",
        score,
        portfolio.to_positions(),
    )
    assert "Strategy Optimizer" in resp.agent_name or "Fee" in resp.response_markdown
