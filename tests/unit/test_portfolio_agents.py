from __future__ import annotations

import numpy as np
import pandas as pd

from libs.ai_agents.portfolio_agents import (
    PortfolioAgentRouter,
    generate_draft_trades,
    scan_hidden_fees,
    scan_tax_loss_harvesting,
)
from libs.mindmarket_core.portfolio_scoring import demo_asset_positions, score_portfolio


def _returns(periods: int = 252) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    index = pd.bdate_range("2024-01-01", periods=periods)
    spy = rng.normal(0.0002, 0.011, periods)
    return pd.DataFrame(
        {
            "SPY": spy,
            "QQQ": spy * 1.4 + rng.normal(0.0, 0.010, periods),
            "VXUS": spy * 0.9 + rng.normal(0.0, 0.009, periods),
            "BND": rng.normal(0.0001, 0.003, periods),
        },
        index=index,
    )


def test_optimizer_tools_detect_fees_and_tax_loss_candidates():
    positions = demo_asset_positions(100_000)

    fees = scan_hidden_fees(positions)
    losses = scan_tax_loss_harvesting(positions)

    assert any(row["ticker"] == "QQQ" for row in fees)
    assert {row["ticker"] for row in losses} >= {"QQQ", "VXUS"}


def test_generate_draft_trades_returns_non_binding_actions():
    positions = demo_asset_positions(100_000)
    returns = _returns()
    score = score_portfolio(
        positions,
        returns,
        benchmark_returns=returns["SPY"],
        risk_preference=1,
    )

    trades = generate_draft_trades(score, positions)

    assert trades
    assert all("action" in trade and "reason" in trade for trade in trades)


def test_agent_router_dispatches_optimizer_for_tax_question():
    positions = demo_asset_positions(100_000)
    returns = _returns()
    score = score_portfolio(
        positions,
        returns,
        benchmark_returns=returns["SPY"],
        risk_preference=3,
    )
    router = PortfolioAgentRouter()

    result = router.route("Do I have tax-loss harvesting or fee issues?", score, positions)

    assert result.agent_name == "Strategy Optimizer Agent"
    assert "Tax-loss scan" in result.response_markdown
    assert result.tool_trace == [
        "scan_hidden_fund_fees",
        "scan_unrealized_tax_losses",
        "generate_non_binding_draft_trades",
    ]


def test_router_prepare_routes_optimizer_for_fee_question():
    """The streaming path uses router.prepare(): a fee/tax question must get
    the optimizer's scans (hidden_fees/tax_loss_harvesting), not analyzer-only
    metrics — this is the streaming↔/chat routing parity."""
    positions = demo_asset_positions(100_000)
    returns = _returns()
    score = score_portfolio(positions, returns, benchmark_returns=returns["SPY"], risk_preference=3)
    router = PortfolioAgentRouter()

    plan = router.prepare("What fund fees am I paying?", score, positions)
    assert plan["agent_name"] == "Strategy Optimizer Agent"
    assert "hidden_fees" in plan["tool_results"]
    assert "tax_loss_harvesting" in plan["tool_results"]
    assert plan["system"] and plan["prompt"]  # ready to stream

    # A risk/diagnosis question stays with the analyzer (metrics + dimensions).
    plan2 = router.prepare("How risky is my portfolio?", score, positions)
    assert plan2["agent_name"] == "Portfolio Analyzer Agent"
    assert "dimensions" in plan2["tool_results"]
    assert plan2["draft_trades"] == []
