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
    # NON-TRANSACTIONAL risk-management levers (see generate_risk_levers).
    # This platform never emits buy/sell instructions for specific securities.
    risk_levers: list[dict]
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


def scan_unrealized_losses(
    positions: Iterable[AssetPosition],
    *,
    min_loss_pct: float = 0.05,
    min_loss_usd: float = 500.0,
) -> list[dict]:
    """Positions carrying material unrealized losses — factual P&L the user
    already sees on the holdings page, surfaced here as a TAX-AWARENESS
    dimension. Deliberately carries no swap/replacement suggestion: whether
    to realize a loss is an individual tax decision (wash-sale, lot
    selection) this platform does not make."""
    rows = []
    for p in positions:
        if not p.enabled or p.market_value <= 0 or p.asset_type == "cash":
            continue
        # Unknown cost basis → the loss can't be sized → not reportable.
        if p.unrealized_pnl is None or p.unrealized_pnl_pct is None:
            continue
        if p.unrealized_pnl <= -min_loss_usd and p.unrealized_pnl_pct <= -min_loss_pct:
            rows.append(
                {
                    "ticker": p.ticker,
                    "loss_usd": float(abs(p.unrealized_pnl)),
                    "loss_pct": float(abs(p.unrealized_pnl_pct)),
                    "note": (
                        f"{p.ticker} has an unrealized loss of {_money(abs(p.unrealized_pnl))} "
                        f"({_pct(abs(p.unrealized_pnl_pct))}). Whether to realize it is a tax "
                        "decision — wash-sale and lot-selection rules apply."
                    ),
                }
            )
    return sorted(rows, key=lambda row: row["loss_usd"], reverse=True)


def generate_risk_levers(score: PortfolioScore, positions: Iterable[AssetPosition]) -> list[dict]:
    """Deterministic, NON-TRANSACTIONAL risk-management levers.

    COMPLIANCE BOUNDARY: each lever names a risk dimension, quantifies where
    the book stands against a neutral reference band, and says how to
    EVALUATE it on the platform (What-if lab, Scenarios, Risk Report). A
    lever NEVER instructs the user to buy or sell a specific security, never
    names a replacement security, and never gives a dollar amount to trade —
    this is risk analytics, not investment advice."""
    active = [p for p in positions if p.enabled and p.market_value > 0]
    total_value = sum(p.market_value for p in active)
    if total_value <= 0:
        return []

    m = score.metrics
    levers: list[dict] = []

    def _lever(
        lever: str, dimension: str, headline: str, current: str, reference: str, evaluate: str
    ) -> None:
        levers.append(
            {
                "lever": lever,
                "risk_dimension": dimension,
                "headline": headline,
                "current": current,
                "reference": reference,
                "evaluate": evaluate,
            }
        )

    invested = [p for p in active if p.asset_type != "cash"]
    invested_total = sum(p.market_value for p in invested)
    if invested and invested_total > 0:
        top_weight = max(p.market_value for p in invested) / invested_total
        if top_weight > 0.25:
            _lever(
                "reduce_single_name_concentration",
                "concentration",
                "Reduce single-name concentration",
                f"the largest holding is {_pct(top_weight)} of invested value",
                "diversified reference band: no single position above ~10-25%",
                "compare downside in the What-if lab with the largest position scaled down",
            )

    leverage = float(getattr(m, "leverage", 1.0) or 1.0)
    if leverage > 1.05:
        _lever(
            "review_leverage",
            "leverage",
            "Review margin leverage",
            f"gross exposure is {leverage:.2f}× net equity",
            "an unlevered book is 1.00×; leverage scales drawdowns and VaR proportionally",
            "check the margin section of the Risk Report and stress a -20% move in Scenarios",
        )

    risk_target_vol = float(score.risk_target["annual_volatility"])
    if m.annual_volatility > risk_target_vol * 1.15 or m.max_drawdown > 0.25:
        _lever(
            "compare_lower_beta_downside",
            "market_risk",
            "Compare downside under a lower-beta allocation",
            (
                f"annual volatility is {_pct(m.annual_volatility)} vs your selected "
                f"target of {_pct(risk_target_vol)}"
            ),
            "your own risk preference sets the band; beta near 1.0 moves one-for-one with the index",
            "run a lower-beta allocation in the What-if lab and compare VaR and max drawdown",
        )

    cash_weight = float(getattr(m, "cash_weight", 0.0) or 0.0)
    if cash_weight < 0.02:
        _lever(
            "increase_liquidity_buffer",
            "liquidity",
            "Review the liquidity buffer",
            f"cash is {_pct(cash_weight)} of the book",
            "a 2-5% cash buffer is a common reference for absorbing drawdowns without forced selling",
            "review upcoming cash needs against the liquidity section of the Risk Report",
        )
    elif cash_weight > 0.20:
        _lever(
            "review_cash_allocation",
            "allocation",
            "Review the cash allocation",
            f"cash is {_pct(cash_weight)} of the book",
            "cash dampens both drawdown and expected return; the right level is a plan decision",
            "compare score and downside with a different cash weight in the What-if lab",
        )

    losses = scan_unrealized_losses(active)
    if losses:
        _lever(
            "review_unrealized_losses",
            "tax",
            "Review unrealized losses with a tax professional",
            (
                f"{len(losses)} position(s) carry unrealized losses beyond "
                f"{_pct(0.05)} / {_money(500)}; the largest is {_pct(losses[0]['loss_pct'])} "
                "of that position"
            ),
            "realizing a loss is a tax decision — wash-sale and lot-selection rules apply",
            "this platform does not recommend trades; discuss any harvesting with a tax professional",
        )

    return levers


def detect_reply_language(text: str) -> str | None:
    """Deterministically detect a clearly non-English message so the reply
    language is FORCED rather than left to the model's judgment.

    Currently detects Chinese: ≥2 CJK ideographs that make up ≥20% of the
    non-space characters (so "buy NVDA?" with one stray character doesn't
    flip the answer). Returns the language name for the prompt, or None."""
    if not text:
        return None
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    dense = len([c for c in text if not c.isspace()])
    if cjk >= 2 and dense > 0 and cjk / dense >= 0.2:
        return "Simplified Chinese (简体中文)"
    return None


# Closed-set display labels for the Chinese deterministic fallbacks. The
# scoring engine emits English; these two sets are finite so they are safe to
# map at the display layer. Free-text fields (dimension `detail`, lever
# text) are engine DATA and stay verbatim.
_DIMENSION_ZH = {
    "Risk Match": "风险匹配",
    "Risk-adjusted Return": "风险调整后收益",
    "Downside Protection": "下行保护",
}
_STATUS_ZH = {"Excellent": "优秀", "Good": "良好", "Needs Work": "待改进", "Poor": "较差"}


# ── risk reference comparison ─────────────────────────────────────────
# Static, neutral risk-management reference bands (long-run rules of thumb,
# not any firm's practice). These are CONSTANTS in code — the LLM may cite
# them verbatim but never alter them, and every "yours" value comes from the
# deterministic score engine. They quantify risk dimensions; they are not
# targets to trade toward and carry no buy/sell implication.


def _assess(value: float, good_below: float | None = None, good_above: float | None = None) -> str:
    if good_below is not None:
        return "within the reference band" if value <= good_below else "above it"
    if good_above is not None:
        return "meets the reference bar" if value >= good_above else "below it"
    return ""


def build_risk_reference_comparison(
    score: PortfolioScore, positions: Iterable[AssetPosition]
) -> list[dict]:
    """Deterministic rows comparing the investor's metrics to neutral
    risk-management reference bands. Skips metrics that are missing/NaN
    rather than guessing."""
    import math

    m = score.metrics
    rows: list[dict] = []

    def _row(metric: str, yours, reference: str, assessment: str) -> None:
        rows.append(
            {
                "metric": metric,
                "yours": yours,
                "reference_band": reference,
                "assessment": assessment,
            }
        )

    if math.isfinite(m.sharpe_ratio):
        _row(
            "Sharpe ratio",
            round(m.sharpe_ratio, 2),
            "≥ 1.0 is strong; broad equity indexes have run roughly 0.4-0.6 long-run",
            _assess(m.sharpe_ratio, good_above=1.0),
        )
    if math.isfinite(m.annual_volatility):
        _row(
            "Annual volatility",
            round(m.annual_volatility, 4),
            "6-12% annualized is a common moderate-risk reference band",
            _assess(m.annual_volatility, good_below=0.12),
        )
    if math.isfinite(m.max_drawdown):
        _row(
            "Max drawdown",
            round(m.max_drawdown, 4),
            "a 20% drawdown is a common trigger for a de-risking review",
            _assess(m.max_drawdown, good_below=0.20),
        )
    if math.isfinite(m.var_95_daily):
        _row(
            "Daily VaR (95%)",
            round(m.var_95_daily, 4),
            "1-2% of portfolio value per day is a common daily risk-budget reference",
            _assess(m.var_95_daily, good_below=0.02),
        )
    if math.isfinite(m.beta_to_benchmark):
        _row(
            "Beta to market",
            round(m.beta_to_benchmark, 2),
            "|β| < 0.3 reads as market-neutral; a broad index fund is 1.0",
            "market-neutral profile" if abs(m.beta_to_benchmark) < 0.3 else "directional book",
        )

    active = [p for p in positions if p.asset_type != "cash" and p.market_value > 0]
    total = sum(p.market_value for p in active)
    if active and total > 0:
        top = max(active, key=lambda p: p.market_value)
        top_w = top.market_value / total
        _row(
            f"Largest position ({top.ticker})",
            round(top_w, 4),
            "common diversification references keep single names near 5-10%",
            _assess(top_w, good_below=0.10),
        )
    return rows


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
    lang = detect_reply_language(user_message)
    lang_rule = (
        f"LANGUAGE: the user wrote in {lang} — write the ENTIRE answer in {lang}, "
        "including section headers and table headers. Keep tickers and standard "
        "abbreviations (VaR, Sharpe, ETF, P/E) as-is."
        if lang
        else "Answer in the user's language."
    )
    system = (
        "You are MindMarket's portfolio risk copilot for a NOVICE retail investor "
        "(many use margin and lack risk discipline). Ground EVERY number ONLY in "
        "the supplied JSON context, tool_results, and any live data tools you "
        "call — never invent prices, returns, Sharpe, drawdown, beta, implied "
        "volatility, taxes, or fees. If tax-lot detail is missing, say "
        "tax-lot verification is required.\n\n"
        "BOUNDARY — risk analytics, NOT investment advice: never tell the user to "
        "buy or sell a specific security, never name a security to add or a "
        "replacement/swap, and never give a dollar amount to trade. Frame every "
        "recommendation as a risk-management LEVER tied to the supplied numbers — "
        "e.g. reduce single-name concentration, review leverage, increase the "
        "liquidity buffer, compare downside under a lower-beta allocation — and "
        "point to the platform's What-if lab, Scenarios, or Risk Report to "
        "evaluate it. Tax questions get facts plus 'review with a tax "
        "professional', never a harvest/swap instruction.\n\n"
        "Voice: open with a one-line plain-English takeaway a beginner "
        "understands, then back it with the exact figures. Be thorough and "
        "quantitatively rigorous, but skimmable. Use GitHub-Flavored "
        "**Markdown**: bold section headers, short bullet lists, and **Markdown "
        "tables** whenever you compare holdings / metrics / scenarios or list "
        "several numbers (tables RENDER in the UI — prefer them over comma lists). "
        "Lean defensive ('don't lose money'): surface tail risk, concentration, "
        "and margin/liquidation danger.\n\n"
        "When tool_results.risk_reference_comparison is present and relevant, add "
        "a short 'risk reference' Markdown table comparing the investor's numbers "
        "to the supplied neutral reference bands. Cite ONLY the supplied "
        "reference values — do not add benchmarks of your own.\n\n"
        "CRITICAL: write a COMPLETE answer — finish every section, never stop "
        f"mid-sentence or mid-conclusion. {lang_rule}"
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
        "4. **Levers** — prioritized risk-management levers with a one-line "
        "rationale each (no buy/sell instructions, no specific securities to trade).\n"
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

    def prepare(
        self,
        score: PortfolioScore,
        positions: Iterable[AssetPosition],
        *,
        user_message: str | None = None,
    ) -> dict:
        """Build the turn's context / tool_results / fallback WITHOUT the LLM
        call, so both ``run()`` and the streaming endpoint share one path.

        ``user_message`` (optional) only picks the FALLBACK template's
        language: a Chinese question gets a Chinese deterministic fallback
        (same structure, same numbers). Default (None/English) is unchanged."""
        metric = score.metrics
        weakest = min(score.dimensions.values(), key=lambda item: item.score)
        if detect_reply_language(user_message or ""):
            zh_name = _DIMENSION_ZH.get(weakest.name, weakest.name)
            zh_status = _STATUS_ZH.get(weakest.status, weakest.status)
            fallback_md = (
                f"**评估：** 组合评分为 **{score.overall_score}/1000**。"
                f"最薄弱的维度是 **{zh_name}**，为 **{weakest.score:.1f}/10**"
                f"（{zh_status}）。\n\n"
                f"**证据：** Sharpe 为 **{metric.sharpe_ratio:.2f}**，年化波动率为 "
                f"**{_pct(metric.annual_volatility)}**，最大回撤为 "
                f"**{_pct(metric.max_drawdown)}**，日 VaR(95%) 为 "
                f"**{_pct(metric.var_95_daily)}**。\n\n"
                f"**行动：** 请优先关注{zh_name}：{weakest.detail}"
            )
        else:
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
        positions_list = list(positions)
        return {
            "agent_name": self.name,
            "context": build_agent_context(score, positions_list),
            "tool_results": {
                "overall_score": score.overall_score,
                "annual_return": metric.annual_return,
                "annual_volatility": metric.annual_volatility,
                "sharpe_ratio": metric.sharpe_ratio,
                "max_drawdown": metric.max_drawdown,
                "var_95_daily": metric.var_95_daily,
                "beta_to_benchmark": metric.beta_to_benchmark,
                "dimensions": {k: asdict(v) for k, v in score.dimensions.items()},
                "risk_reference_comparison": build_risk_reference_comparison(score, positions_list),
            },
            "tool_trace": [
                "read_exact_quant_score",
                "read_exact_sharpe_vol_drawdown_var_beta",
                "compare_vs_risk_reference_bands",
                "format_post_investment_diagnosis",
            ],
            "risk_levers": [],
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
        plan = self.prepare(score, positions, user_message=user_message)
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
            plan["risk_levers"],
            plan["tool_trace"],
            llm_used=bool(llm_text),
        )


class StrategyOptimizerAgent:
    name = "Strategy Optimizer Agent"

    def prepare(
        self,
        score: PortfolioScore,
        positions: Iterable[AssetPosition],
        *,
        user_message: str | None = None,
    ) -> dict:
        """Build the turn's scans / context / tool_results / fallback WITHOUT
        the LLM call (shared by ``run()`` and the streaming endpoint).

        ``user_message`` (optional) only picks the FALLBACK template's
        language — a Chinese question gets a Chinese deterministic fallback."""
        positions_list = list(positions)
        fees = scan_hidden_fees(positions_list)
        losses = scan_unrealized_losses(positions_list)
        risk_levers = generate_risk_levers(score, positions_list)

        if detect_reply_language(user_message or ""):
            fee_text = (
                "; ".join(
                    f"{row['ticker']} 预计年费 {_money(row['annual_fee_usd'])}" for row in fees
                )
                if fees
                else "未从可用的费率数据中发现明显的基金费用问题。"
            )
            loss_text = (
                f"{len(losses)} 个持仓存在超过阈值的未实现亏损（最大约为该仓位的 "
                f"{_pct(losses[0]['loss_pct'])}）。是否实现亏损属于税务决策"
                "（涉及洗售与计税批次规则），请与税务专业人士讨论。"
                if losses
                else "没有持仓的未实现亏损超过本地阈值。"
            )
            lever_text = (
                "\n".join(
                    f"- **{lv['headline']}** — 现状：{lv['current']}；"
                    f"参照：{lv['reference']}。评估方式：{lv['evaluate']}。"
                    for lv in risk_levers
                )
                if risk_levers
                else "- 当前规则集未触发任何风险管理杠杆。"
            )
            fallback_md = (
                f"**费用扫描：** {fee_text}\n\n"
                f"**未实现亏损：** {loss_text}\n\n"
                f"**风险管理杠杆：**\n{lever_text}\n\n"
                "以上为风险管理杠杆，不是交易指令 —— MindMarket 不建议买卖任何"
                "具体证券。教育性内容，不构成投资建议；税务问题请咨询专业人士。"
            )
        else:
            fee_text = (
                "; ".join(
                    f"{row['ticker']} estimated fee {_money(row['annual_fee_usd'])}" for row in fees
                )
                if fees
                else "No material fund-fee issue detected from the available expense ratios."
            )
            loss_text = (
                f"{len(losses)} position(s) carry unrealized losses beyond the local "
                f"threshold (the largest is {_pct(losses[0]['loss_pct'])} of that "
                "position). Whether to realize a loss is a tax decision — wash-sale "
                "and lot-selection rules apply; review with a tax professional."
                if losses
                else "No position carries an unrealized loss beyond the local threshold."
            )
            lever_text = (
                "\n".join(
                    f"- **{lv['headline']}** — now: {lv['current']}; "
                    f"reference: {lv['reference']}. Evaluate: {lv['evaluate']}."
                    for lv in risk_levers
                )
                if risk_levers
                else "- No risk-management lever is triggered by the current rule set."
            )
            fallback_md = (
                f"**Fee scan:** {fee_text}\n\n"
                f"**Unrealized losses:** {loss_text}\n\n"
                f"**Risk levers:**\n{lever_text}\n\n"
                "These are risk-management levers, not trade instructions — "
                "MindMarket does not recommend buying or selling any specific "
                "security. Educational only, not investment advice."
            )
        return {
            "agent_name": self.name,
            "context": build_agent_context(score, positions_list),
            "tool_results": {
                "hidden_fees": fees,
                "unrealized_losses": losses,
                "risk_levers": risk_levers,
                "risk_reference_comparison": build_risk_reference_comparison(score, positions_list),
            },
            "tool_trace": [
                "scan_hidden_fund_fees",
                "scan_unrealized_losses",
                "compare_vs_risk_reference_bands",
                "generate_risk_levers",
            ],
            "risk_levers": risk_levers,
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
        plan = self.prepare(score, positions, user_message=user_message)
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
            plan["risk_levers"],
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
                risk_levers=optimizer.risk_levers,
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
        risk_levers)`` WITHOUT calling the LLM. The streaming endpoint streams
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
            a = self.analyzer.prepare(score, positions, user_message=user_message)
            o = self.optimizer.prepare(score, positions, user_message=user_message)
            agent_name = "Portfolio Analyzer + Strategy Optimizer"
            context = a["context"]
            tool_results = {**a["tool_results"], **o["tool_results"]}
            risk_levers = o["risk_levers"]
        elif wants_optimizer:
            p = self.optimizer.prepare(score, positions, user_message=user_message)
            agent_name, context, tool_results, risk_levers = (
                p["agent_name"],
                p["context"],
                p["tool_results"],
                p["risk_levers"],
            )
        else:
            p = self.analyzer.prepare(score, positions, user_message=user_message)
            agent_name, context, tool_results, risk_levers = (
                p["agent_name"],
                p["context"],
                p["tool_results"],
                p["risk_levers"],
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
            "risk_levers": risk_levers,
        }
