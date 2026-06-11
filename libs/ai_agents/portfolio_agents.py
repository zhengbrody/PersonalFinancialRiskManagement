"""Lightweight ReAct-style portfolio agents.

The agents run deterministic Python tools first, then optionally ask an LLM to
format the already-computed facts. This keeps financial calculations local and
auditable while still giving users a natural-language assistant.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Callable, Iterable

from libs.mindmarket_core.portfolio_scoring import AssetPosition, PortfolioScore

LLMCallable = Callable[..., str]


@dataclass(frozen=True)
class AgentResult:
    agent_name: str
    response_markdown: str
    draft_trades: list[dict]
    tool_trace: list[str]
    # True when the markdown came from the LLM; False = deterministic
    # fallback template. Lets the UI label AI output honestly.
    llm_used: bool = False


def _money(value: float) -> str:
    return f"${value:,.0f}"


def _pct(value: float) -> str:
    return f"{value:.1%}"


def _position_weights(positions: Iterable[AssetPosition]) -> dict[str, float]:
    active = [p for p in positions if p.enabled and p.market_value > 0]
    total = sum(p.market_value for p in active)
    if total <= 0:
        return {}
    return {p.ticker: p.market_value / total for p in active}


def build_agent_context(score: PortfolioScore, positions: Iterable[AssetPosition]) -> dict:
    active = [p for p in positions if p.enabled and p.market_value > 0]
    return {
        "portfolio_score": score.as_dict(),
        "positions": [
            {
                "ticker": p.ticker,
                "name": p.name,
                "asset_type": p.asset_type,
                "market_value": round(float(p.market_value), 2),
                "weight": round(_position_weights(active).get(p.ticker, 0.0), 6),
                # Unknown cost basis surfaces as null, not a fabricated 0 —
                # the agent must not claim a P&L it can't ground.
                "cost_basis": (None if p.cost_basis is None else round(float(p.cost_basis), 2)),
                "unrealized_pnl": (
                    None if p.unrealized_pnl is None else round(float(p.unrealized_pnl), 2)
                ),
                "unrealized_pnl_pct": (
                    None if p.unrealized_pnl_pct is None else round(float(p.unrealized_pnl_pct), 6)
                ),
                "expense_ratio": round(float(p.expense_ratio), 6),
                "proxy_ticker": p.proxy_ticker,
            }
            for p in active
        ],
    }


def scan_hidden_fees(positions: Iterable[AssetPosition]) -> list[dict]:
    fee_rows = []
    for p in positions:
        if not p.enabled or p.market_value <= 0 or p.expense_ratio <= 0:
            continue
        annual_fee = float(p.market_value * p.expense_ratio)
        if annual_fee >= 10 or p.expense_ratio >= 0.0020:
            fee_rows.append(
                {
                    "ticker": p.ticker,
                    "expense_ratio": p.expense_ratio,
                    "annual_fee_usd": annual_fee,
                    "severity": "review" if p.expense_ratio < 0.004 else "high",
                    "note": f"Estimated annual fund fee: {_money(annual_fee)}.",
                }
            )
    return sorted(fee_rows, key=lambda row: row["annual_fee_usd"], reverse=True)


def scan_tax_loss_harvesting(
    positions: Iterable[AssetPosition],
    *,
    min_loss_pct: float = 0.05,
    min_loss_usd: float = 500.0,
) -> list[dict]:
    opportunities = []
    for p in positions:
        if not p.enabled or p.market_value <= 0 or p.asset_type == "cash":
            continue
        # Unknown cost basis → can't size a loss → not a harvest candidate.
        if p.unrealized_pnl is None or p.unrealized_pnl_pct is None:
            continue
        if p.unrealized_pnl <= -min_loss_usd and p.unrealized_pnl_pct <= -min_loss_pct:
            opportunities.append(
                {
                    "ticker": p.ticker,
                    "loss_usd": float(abs(p.unrealized_pnl)),
                    "loss_pct": float(abs(p.unrealized_pnl_pct)),
                    "proxy_ticker": p.proxy_ticker,
                    "note": (
                        f"{p.ticker} has an unrealized loss of {_money(abs(p.unrealized_pnl))} "
                        f"({_pct(abs(p.unrealized_pnl_pct))})."
                    ),
                }
            )
    return sorted(opportunities, key=lambda row: row["loss_usd"], reverse=True)


def generate_draft_trades(score: PortfolioScore, positions: Iterable[AssetPosition]) -> list[dict]:
    """Generate non-binding trade drafts from local metrics and holdings."""

    active = [p for p in positions if p.enabled and p.market_value > 0]
    total_value = sum(p.market_value for p in active)
    if total_value <= 0:
        return []

    weights = _position_weights(active)
    trades: list[dict] = []
    metrics = score.metrics
    risk_target_vol = float(score.risk_target["annual_volatility"])
    high_risk_order = ["QQQ", "SPY", "VXUS"]

    if metrics.annual_volatility > risk_target_vol * 1.15 or metrics.max_drawdown > 0.25:
        source = next((tk for tk in high_risk_order if weights.get(tk, 0.0) >= 0.08), None)
        if source:
            amount = min(total_value * 0.05, total_value * weights[source] * 0.25)
            trades.append(
                {
                    "action": "SELL",
                    "ticker": source,
                    "amount_usd": round(amount, 2),
                    "reason": (
                        "Reduce equity beta because realized portfolio volatility is above "
                        "the selected risk target."
                    ),
                }
            )
            trades.append(
                {
                    "action": "BUY",
                    "ticker": "BND",
                    "amount_usd": round(amount * 0.70, 2),
                    "reason": "Shift part of the risk budget into duration / defensive exposure.",
                }
            )
            trades.append(
                {
                    "action": "BUY",
                    "ticker": "CASH",
                    "amount_usd": round(amount * 0.30, 2),
                    "reason": "Keep liquidity available for drawdown control and future deployment.",
                }
            )

    if metrics.cash_weight > 0.20 and score.dimensions["risk_match"].score >= 6.5:
        deploy = total_value * min(metrics.cash_weight - 0.15, 0.05)
        if deploy > 500:
            trades.append(
                {
                    "action": "BUY",
                    "ticker": "SPY",
                    "amount_usd": round(deploy * 0.60, 2),
                    "reason": "Deploy excess cash while preserving broad market diversification.",
                }
            )
            trades.append(
                {
                    "action": "BUY",
                    "ticker": "BND",
                    "amount_usd": round(deploy * 0.40, 2),
                    "reason": "Pair cash deployment with lower-volatility ballast.",
                }
            )

    for opp in scan_tax_loss_harvesting(active)[:2]:
        if opp.get("proxy_ticker"):
            trades.append(
                {
                    "action": "TAX_LOSS_SWAP_DRAFT",
                    "ticker": opp["ticker"],
                    "amount_usd": round(opp["loss_usd"], 2),
                    "replacement": opp["proxy_ticker"],
                    "reason": (
                        "Potential tax-loss harvesting candidate. Verify wash-sale rules "
                        "and tax-lot details before execution."
                    ),
                }
            )

    return trades


def build_formatter_messages(
    *,
    user_message: str,
    context: dict,
    tool_results: dict,
    agent_name: str,
) -> tuple[str, str]:
    """Build the ``(system, prompt)`` pair for the LLM formatter.

    Pulled out of ``_call_llm_formatter`` so BOTH the non-streaming path
    (below) and the streaming Copilot endpoint reuse the exact same
    grounding rules + structure — no second, drifting prompt.
    """
    system = (
        "You are MindMarket's portfolio AI copilot for a NOVICE retail investor "
        "(many use margin and lack risk discipline). Ground EVERY number ONLY in "
        "the supplied JSON context, tool_results, and any live data tools you "
        "call — never invent prices, returns, Sharpe, drawdown, beta, implied "
        "volatility, taxes, fees, or trades. If tax-lot detail is missing, say "
        "tax-lot verification is required.\n\n"
        "Voice — Robinhood skin, Citadel bone: open with a one-line plain-English "
        "takeaway a beginner understands, then back it with the exact figures. Be "
        "thorough and quantitatively rigorous, but skimmable. Use GitHub-Flavored "
        "**Markdown**: bold section headers, short bullet lists, and **Markdown "
        "tables** whenever you compare holdings / metrics / scenarios or list "
        "several numbers (tables RENDER in the UI — prefer them over comma lists). "
        "Lean defensive ('don't lose money'): surface tail risk, concentration, "
        "and margin/liquidation danger, and suggest simple hedges (e.g. trimming, "
        "a cash/SGOV ballast) when warranted.\n\n"
        "CRITICAL: write a COMPLETE answer — finish every section, never stop "
        "mid-sentence or mid-conclusion. Answer in the user's language."
    )
    prompt = (
        f"Agent: {agent_name}\n"
        f"User message: {user_message}\n\n"
        "Exact JSON context:\n"
        f"{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
        "Deterministic Python tool results:\n"
        f"{json.dumps(tool_results, ensure_ascii=False, indent=2)}\n\n"
        "Write a COMPLETE, well-structured Markdown answer:\n"
        "1. **Takeaway** — one plain-English sentence.\n"
        "2. **Assessment** — what the numbers mean for this portfolio.\n"
        "3. **Evidence** — a Markdown table of the key metrics / holdings you cite.\n"
        "4. **Actions** — concrete, prioritized steps with a one-line rationale each.\n"
        "Use tables wherever you present multiple numbers. Finish all four sections."
    )
    return system, prompt


def _call_llm_formatter(
    *,
    llm_callable: LLMCallable | None,
    user_message: str,
    context: dict,
    tool_results: dict,
    agent_name: str,
) -> str | None:
    if llm_callable is None:
        return None
    system, prompt = build_formatter_messages(
        user_message=user_message,
        context=context,
        tool_results=tool_results,
        agent_name=agent_name,
    )
    try:
        text = llm_callable(prompt=prompt, system=system, max_tokens=3500, temperature=0.3)
    except Exception:
        return None
    return text.strip() if isinstance(text, str) and text.strip() else None


class PortfolioAnalyzerAgent:
    name = "Portfolio Analyzer Agent"

    def prepare(self, score: PortfolioScore, positions: Iterable[AssetPosition]) -> dict:
        """Build the turn's context / tool_results / fallback WITHOUT the LLM
        call, so both ``run()`` and the streaming endpoint share one path."""
        metric = score.metrics
        weakest = min(score.dimensions.values(), key=lambda item: item.score)
        fallback_md = (
            f"**Assessment:** Portfolio score is **{score.overall_score}/1000**. "
            f"The weakest dimension is **{weakest.name}** at **{weakest.score:.1f}/10** "
            f"({weakest.status}).\n\n"
            f"**Evidence:** Sharpe is **{metric.sharpe_ratio:.2f}**, annual volatility is "
            f"**{_pct(metric.annual_volatility)}**, max drawdown is "
            f"**{_pct(metric.max_drawdown)}**, and daily VaR(95%) is "
            f"**{_pct(metric.var_95_daily)}**.\n\n"
            f"**Action:** Focus first on {weakest.name.lower()}: {weakest.detail}"
        )
        return {
            "agent_name": self.name,
            "context": build_agent_context(score, positions),
            "tool_results": {
                "overall_score": score.overall_score,
                "annual_return": metric.annual_return,
                "annual_volatility": metric.annual_volatility,
                "sharpe_ratio": metric.sharpe_ratio,
                "max_drawdown": metric.max_drawdown,
                "var_95_daily": metric.var_95_daily,
                "beta_to_benchmark": metric.beta_to_benchmark,
                "dimensions": {k: asdict(v) for k, v in score.dimensions.items()},
            },
            "tool_trace": [
                "read_exact_quant_score",
                "read_exact_sharpe_vol_drawdown_var_beta",
                "format_post_investment_diagnosis",
            ],
            "draft_trades": [],
            "fallback_md": fallback_md,
        }

    def run(
        self,
        user_message: str,
        score: PortfolioScore,
        positions: Iterable[AssetPosition],
        *,
        llm_callable: LLMCallable | None = None,
    ) -> AgentResult:
        plan = self.prepare(score, positions)
        llm_text = _call_llm_formatter(
            llm_callable=llm_callable,
            user_message=user_message,
            context=plan["context"],
            tool_results=plan["tool_results"],
            agent_name=plan["agent_name"],
        )
        return AgentResult(
            plan["agent_name"],
            llm_text or plan["fallback_md"],
            plan["draft_trades"],
            plan["tool_trace"],
            llm_used=bool(llm_text),
        )


class StrategyOptimizerAgent:
    name = "Strategy Optimizer Agent"

    def prepare(self, score: PortfolioScore, positions: Iterable[AssetPosition]) -> dict:
        """Build the turn's scans / context / tool_results / fallback WITHOUT
        the LLM call (shared by ``run()`` and the streaming endpoint)."""
        positions_list = list(positions)
        fees = scan_hidden_fees(positions_list)
        tax_losses = scan_tax_loss_harvesting(positions_list)
        draft_trades = generate_draft_trades(score, positions_list)

        fee_text = (
            "; ".join(
                f"{row['ticker']} estimated fee {_money(row['annual_fee_usd'])}" for row in fees
            )
            if fees
            else "No material fund-fee issue detected from the available expense ratios."
        )
        tax_text = (
            "; ".join(
                f"{row['ticker']} loss {_money(row['loss_usd'])} ({_pct(row['loss_pct'])})"
                for row in tax_losses
            )
            if tax_losses
            else "No tax-loss harvesting candidate crossed the local threshold."
        )
        trade_text = (
            "\n".join(
                f"- **{t['action']} {t['ticker']}** {_money(t['amount_usd'])}: {t['reason']}"
                for t in draft_trades
            )
            if draft_trades
            else "- No draft trade is necessary from the current rule set."
        )
        fallback_md = (
            f"**Fee scan:** {fee_text}\n\n"
            f"**Tax-loss scan:** {tax_text}\n\n"
            f"**Draft trades:**\n{trade_text}\n\n"
            "These are draft suggestions only; confirm tax lots, wash-sale exposure, "
            "liquidity, and transaction costs before execution."
        )
        return {
            "agent_name": self.name,
            "context": build_agent_context(score, positions_list),
            "tool_results": {
                "hidden_fees": fees,
                "tax_loss_harvesting": tax_losses,
                "draft_trades": draft_trades,
            },
            "tool_trace": [
                "scan_hidden_fund_fees",
                "scan_unrealized_tax_losses",
                "generate_non_binding_draft_trades",
            ],
            "draft_trades": draft_trades,
            "fallback_md": fallback_md,
        }

    def run(
        self,
        user_message: str,
        score: PortfolioScore,
        positions: Iterable[AssetPosition],
        *,
        llm_callable: LLMCallable | None = None,
    ) -> AgentResult:
        plan = self.prepare(score, positions)
        llm_text = _call_llm_formatter(
            llm_callable=llm_callable,
            user_message=user_message,
            context=plan["context"],
            tool_results=plan["tool_results"],
            agent_name=plan["agent_name"],
        )
        return AgentResult(
            plan["agent_name"],
            llm_text or plan["fallback_md"],
            plan["draft_trades"],
            plan["tool_trace"],
            llm_used=bool(llm_text),
        )


class PortfolioAgentRouter:
    """Minimal router that dispatches to the two resident agents."""

    optimizer_keywords = (
        "optimize",
        "rebalance",
        "trade",
        "tax",
        "loss",
        "fee",
        "cost",
        "harvest",
        "调仓",
        "交易",
        "税",
        "费用",
        "优化",
        "亏损",
    )
    analyzer_keywords = (
        "analyze",
        "diagnose",
        "score",
        "risk",
        "sharpe",
        "drawdown",
        "var",
        "分析",
        "诊断",
        "评分",
        "风险",
        "回撤",
    )

    def __init__(self) -> None:
        self.analyzer = PortfolioAnalyzerAgent()
        self.optimizer = StrategyOptimizerAgent()

    def route(
        self,
        user_message: str,
        score: PortfolioScore,
        positions: Iterable[AssetPosition],
        *,
        llm_callable: LLMCallable | None = None,
    ) -> AgentResult:
        text = (user_message or "").lower()
        wants_optimizer = any(keyword in text for keyword in self.optimizer_keywords)
        wants_analyzer = any(keyword in text for keyword in self.analyzer_keywords)
        wants_both = any(keyword in text for keyword in ("both", "full", "全面", "全部", "完整"))

        if wants_both or (wants_optimizer and wants_analyzer):
            analyzer = self.analyzer.run(
                user_message,
                score,
                positions,
                llm_callable=llm_callable,
            )
            optimizer = self.optimizer.run(
                user_message,
                score,
                positions,
                llm_callable=llm_callable,
            )
            return AgentResult(
                agent_name="Portfolio Analyzer + Strategy Optimizer",
                response_markdown=(
                    f"### {analyzer.agent_name}\n{analyzer.response_markdown}\n\n"
                    f"### {optimizer.agent_name}\n{optimizer.response_markdown}"
                ),
                draft_trades=optimizer.draft_trades,
                tool_trace=analyzer.tool_trace + optimizer.tool_trace,
            )
        if wants_optimizer:
            return self.optimizer.run(
                user_message,
                score,
                positions,
                llm_callable=llm_callable,
            )
        return self.analyzer.run(
            user_message,
            score,
            positions,
            llm_callable=llm_callable,
        )

    def prepare(
        self,
        user_message: str,
        score: PortfolioScore,
        positions: Iterable[AssetPosition],
    ) -> dict:
        """Route + assemble ``(agent_name, system, prompt, tool_results,
        draft_trades)`` WITHOUT calling the LLM. The streaming endpoint streams
        this, so the live (streaming) path gets the SAME agent routing as the
        non-streaming ``route()`` — fee/tax/rebalance questions reach the
        optimizer's scans instead of analyzer-only metrics. For a combined
        ('both') ask we merge both agents' tool_results into one streamed turn.
        """
        text = (user_message or "").lower()
        wants_optimizer = any(keyword in text for keyword in self.optimizer_keywords)
        wants_analyzer = any(keyword in text for keyword in self.analyzer_keywords)
        wants_both = any(keyword in text for keyword in ("both", "full", "全面", "全部", "完整"))

        positions = list(positions)
        if wants_both or (wants_optimizer and wants_analyzer):
            a = self.analyzer.prepare(score, positions)
            o = self.optimizer.prepare(score, positions)
            agent_name = "Portfolio Analyzer + Strategy Optimizer"
            context = a["context"]
            tool_results = {**a["tool_results"], **o["tool_results"]}
            draft_trades = o["draft_trades"]
        elif wants_optimizer:
            p = self.optimizer.prepare(score, positions)
            agent_name, context, tool_results, draft_trades = (
                p["agent_name"],
                p["context"],
                p["tool_results"],
                p["draft_trades"],
            )
        else:
            p = self.analyzer.prepare(score, positions)
            agent_name, context, tool_results, draft_trades = (
                p["agent_name"],
                p["context"],
                p["tool_results"],
                p["draft_trades"],
            )

        system, prompt = build_formatter_messages(
            user_message=user_message,
            context=context,
            tool_results=tool_results,
            agent_name=agent_name,
        )
        return {
            "agent_name": agent_name,
            "system": system,
            "prompt": prompt,
            "tool_results": tool_results,
            "draft_trades": draft_trades,
        }
