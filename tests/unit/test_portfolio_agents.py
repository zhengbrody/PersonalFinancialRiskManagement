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
        "compare_vs_institutional_reference",
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


# ── reply-language detection ─────────────────────────────────────────


def test_detect_reply_language_chinese():
    from libs.ai_agents.portfolio_agents import detect_reply_language

    assert detect_reply_language("我的组合风险高吗？") == "Simplified Chinese (简体中文)"
    assert detect_reply_language("NVDA 怎么样") == "Simplified Chinese (简体中文)"
    # English / near-English stays None.
    assert detect_reply_language("How risky is my portfolio?") is None
    assert detect_reply_language("buy NVDA 吗") is None  # 1 CJK char = noise
    assert detect_reply_language("") is None


def test_formatter_messages_force_chinese_reply():
    from libs.ai_agents.portfolio_agents import build_formatter_messages

    system_zh, _ = build_formatter_messages(
        user_message="我的组合风险高吗？",
        context={},
        tool_results={},
        agent_name="x",
    )
    assert "简体中文" in system_zh and "ENTIRE answer" in system_zh

    system_en, _ = build_formatter_messages(
        user_message="How risky am I?",
        context={},
        tool_results={},
        agent_name="x",
    )
    assert "简体中文" not in system_en
    assert "Answer in the user's language." in system_en


# ── Chinese deterministic fallbacks (no LLM) ─────────────────────────


def _scored_positions():
    positions = demo_asset_positions(100_000)
    returns = _returns()
    score = score_portfolio(positions, returns, benchmark_returns=returns["SPY"], risk_preference=3)
    return score, positions


def test_analyzer_fallback_chinese_for_chinese_message():
    """Chinese question + no LLM → the analyzer's deterministic fallback
    renders in Chinese (same structure, same numbers)."""
    score, positions = _scored_positions()
    router = PortfolioAgentRouter()

    result = router.route("我的组合风险高吗？", score, positions)  # 风险 → analyzer
    assert result.agent_name == "Portfolio Analyzer Agent"
    assert "**评估：**" in result.response_markdown
    assert "**证据：**" in result.response_markdown
    assert "**Assessment:**" not in result.response_markdown
    # tool_trace is untouched by the language switch.
    assert result.tool_trace == [
        "read_exact_quant_score",
        "read_exact_sharpe_vol_drawdown_var_beta",
        "compare_vs_institutional_reference",
        "format_post_investment_diagnosis",
    ]


def test_optimizer_fallback_chinese_for_chinese_message():
    score, positions = _scored_positions()
    router = PortfolioAgentRouter()

    result = router.route("有税损收割或费用问题吗？", score, positions)  # 税/费用 → optimizer
    assert result.agent_name == "Strategy Optimizer Agent"
    assert "**费用扫描：**" in result.response_markdown
    assert "**税损收割：**" in result.response_markdown
    assert "**Fee scan:**" not in result.response_markdown


def test_fallback_stays_english_by_default():
    """English question (and prepare() without user_message) → the English
    fallback, byte-identical to before."""
    score, positions = _scored_positions()
    router = PortfolioAgentRouter()

    result = router.route("How risky is my portfolio?", score, positions)
    assert "**Assessment:**" in result.response_markdown
    assert "**评估：**" not in result.response_markdown

    # prepare() without the kwarg keeps the English fallback (existing callers).
    from libs.ai_agents.portfolio_agents import PortfolioAnalyzerAgent

    plan = PortfolioAnalyzerAgent().prepare(score, positions)
    assert "**Assessment:**" in plan["fallback_md"]


# ── institutional reference comparison ───────────────────────────────


def test_institutional_comparison_rows_are_deterministic():
    from libs.ai_agents.portfolio_agents import build_institutional_comparison

    positions = demo_asset_positions(100_000)
    returns = _returns()
    score = score_portfolio(
        positions,
        returns,
        benchmark_returns=returns["SPY"],
        risk_preference=3,
    )

    rows = build_institutional_comparison(score, positions)
    by_metric = {r["metric"]: r for r in rows}

    sharpe_row = by_metric["Sharpe ratio"]
    assert sharpe_row["yours"] == round(score.metrics.sharpe_ratio, 2)
    expected = "meets the institutional bar" if score.metrics.sharpe_ratio >= 1.0 else "below it"
    assert sharpe_row["assessment"] == expected

    # Largest-position row: weight over the non-cash book.
    active = [p for p in positions if p.asset_type != "cash" and p.market_value > 0]
    total = sum(p.market_value for p in active)
    top = max(active, key=lambda p: p.market_value)
    top_row = next(r for r in rows if r["metric"].startswith("Largest position"))
    assert top.ticker in top_row["metric"]
    assert top_row["yours"] == round(top.market_value / total, 4)

    # Every row has the four keys and a non-empty reference string.
    for r in rows:
        assert set(r) == {"metric", "yours", "institutional_reference", "assessment"}
        assert r["institutional_reference"]


def test_analyzer_prepare_carries_institutional_comparison():
    positions = demo_asset_positions(100_000)
    returns = _returns()
    score = score_portfolio(positions, returns, benchmark_returns=returns["SPY"], risk_preference=3)
    from libs.ai_agents.portfolio_agents import (
        PortfolioAnalyzerAgent,
        StrategyOptimizerAgent,
    )

    for agent in (PortfolioAnalyzerAgent(), StrategyOptimizerAgent()):
        plan = agent.prepare(score, positions)
        rows = plan["tool_results"]["institutional_comparison"]
        assert rows and any(r["metric"] == "Sharpe ratio" for r in rows)
