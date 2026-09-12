"""Conservative task routing before evidence collection. No LLM authorizes trades.

A task classification is not user consent. Concepts can be explained without
account data. Personal requests collect missing inputs; candidate evaluation
uses a separate typed calculation contract, never free-form narrative approval.
"""

import re

from ..schemas.decision_support import DecisionSupport, DecisionTask
from .analyst_methods import select_methods

_TOPICS = (
    ("put", r"\b(?:put|puts)\b|卖出?看跌|认沽"),
    ("margin", r"\bmargin\b|融资|购买力|buying power"),
    ("valuation", r"\bvaluation\b|\bdcf\b|估值"),
    ("diversification", r"diversif|correlat|分散|相关性"),
)
_PERSONAL = re.compile(
    r"\b(?:my|mine|should i|which (?:stocks?|holdings?)|recommend|sell|buy|reduce)\b|我的|我该|建议|卖哪些|卖哪只|减仓",
    re.I,
)
_EXPLANATION = re.compile(
    r"\b(?:what is|what are|explain|how does|how do|define|difference between)\b|什么是|解释|有什么区别|如何运作",
    re.I,
)
_COMPARE = re.compile(r"\b(?:compare|comparison|test a change)\b|比较|对比|测试调整", re.I)
_CANDIDATE = re.compile(
    r"\b(?:recommend|should i|which (?:stocks?|holdings?)|what (?:should|could) i (?:sell|reduce))\b|建议|卖哪些|卖哪只|应该|减哪些",
    re.I,
)


def classify_task(message: str) -> tuple[DecisionTask, str] | None:
    topic = next((key for key, pattern in _TOPICS if re.search(pattern, message, re.I)), None)
    # Explicit account decisions outrank an educational prefix in a mixed request.
    if _CANDIDATE.search(message):
        return (
            DecisionTask(
                kind="candidate_request", missing_inputs=["goal", "budget", "protected_holdings"]
            ),
            topic or "downside",
        )
    if _COMPARE.search(message):
        return (
            DecisionTask(
                kind="specified_comparison", missing_inputs=["holding", "amount", "proceeds"]
            ),
            topic or "downside",
        )
    if (
        topic
        and _EXPLANATION.search(message)
        and not re.search(r"\bmy\b|我的|我该|建议|应该", message, re.I)
    ):
        return DecisionTask(kind="explanation"), topic
    if topic and _PERSONAL.search(message):
        return (
            DecisionTask(
                kind="clarification", missing_inputs=["goal", "budget", "protected_holdings"]
            ),
            topic,
        )
    return None


def describe_task(
    task: DecisionTask, topic: str, lang: str
) -> tuple[DecisionSupport, dict[str, str]]:
    zh = lang == "zh"
    explanation = {
        "put": (
            "A cash-secured put receives a premium in exchange for an obligation to buy the underlying if assigned. The premium is not stable income: downside losses and assignment funding still matter.",
            "现金担保 Put 收取权利金，同时承担被指派时买入标的的义务。权利金不等于稳定收入，仍须考虑下行损失与接盘资金。",
        ),
        "margin": (
            "Cash, a margin loan and broker buying power are different. Cash is an account asset; margin is debt; buying power depends on the broker's collateral rules and account permissions. It cannot be inferred from leverage alone.",
            "现金、融资余额与券商购买力不同：现金是账户资产，融资是负债，购买力取决于券商担保规则和账户权限，不能仅凭杠杆倍数推算。",
        ),
        "valuation": (
            "Turn a business story into testable revenue, margin and reinvestment assumptions. Compare the valuation under favourable and adverse assumptions, and identify evidence that would invalidate the story.",
            "把公司故事转化为可检验的收入、利润率与再投资假设，比较有利和不利假设下的估值，并明确什么证据会推翻原来的判断。",
        ),
        "diversification": (
            "Diversification depends on shared exposures and how holdings move together, not only the number of holdings. Measure contributions to portfolio risk and consider whether correlations could rise under stress.",
            "分散化取决于共同暴露与持仓如何一起变化，而不只是持仓数量。需要计算组合风险贡献，并考虑压力下相关性上升的情况。",
        ),
    }
    methods = select_methods(topic)
    if task.kind == "explanation":
        direct = explanation[topic][int(zh)]
        relevance = (
            "这是通用方法解释，尚未对您的账户进行计算。"
            if zh
            else "This is a general explanation; no account calculation has been performed."
        )
        coverage = "explained"
    else:
        coverage = "insufficient_data"
        if task.kind == "specified_comparison":
            direct = (
                "可以比较这个假设。请在本窗口的 Test a change 中确认持仓、金额，以及留现金还是偿还融资；计算后再比较风险和代价。"
                if zh
                else "We can compare that assumption. Confirm the holding, amount and whether proceeds stay as cash or repay margin in Test a change in this conversation, then compare the calculated risks and tradeoffs."
            )
        else:
            direct = (
                "可以先比较保持不动与受约束的减仓候选。请先明确目标：增加现金、降低融资，还是增加券商购买力？同时确认资金预算和不可卖出的持仓。"
                if zh
                else "We can compare keeping the portfolio with constrained reduction candidates. First confirm the goal: increase cash, reduce margin debt, or increase broker buying power? Also confirm the budget and holdings that must not be sold."
            )
        if topic in {"put", "margin"}:
            task = task.model_copy(
                update={
                    "missing_inputs": [
                        *task.missing_inputs,
                        "broker_and_account_type",
                        "assignment_underlying",
                    ]
                }
            )
            direct += (
                "卖 Put 不等于稳定收入。接盘义务、融资与担保要求需要单独核算，不能未经重算卖掉保护头寸。"
                if zh
                else " Selling puts is not stable income. Assignment, financing and collateral need separate checks; protection must be recalculated before removing a covering position."
            )
        relevance = (
            "本次尚未计算候选，也未确认您的任务约束；不会把聊天中的假设当作已核实的账户事实。"
            if zh
            else "No candidate has been evaluated and no task constraints have been confirmed. Assumptions in the question are not verified account facts."
        )
    change = (
        "目标、持仓、价格或券商规则变化时需重新计算；缺少输入时不做精确排名。"
        if zh
        else "Recalculate when goals, holdings, prices or broker rules change. Missing inputs prevent precise candidate ranking."
    )
    return DecisionSupport(
        task=task,
        coverage=coverage,
        methods=methods,
        limitations=["Method references are not account evidence or execution instructions."],
    ), {
        "direct_answer": direct,
        "portfolio_relevance": relevance,
        "what_would_change": change,
    }
