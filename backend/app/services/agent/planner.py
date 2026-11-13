"""Deterministic planning and answer writing for the research agent.

Used in two situations: when no model is configured (or it fails mid-run), and
as the fail-closed answer when a model's own answer does not survive the
grounding check. Everything here is rules — the same question always produces
the same tool calls and the same wording.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .tools import ToolResult

_NUM = r"(\d+(?:\.\d+)?)"
_DOWN = r"(?:drop|drops|dropped|fall|falls|fell|decline|declines|declined|down|lose|loses|lost|crash|crashes|sell[- ]?off|plunge|plunges|下跌|跌|下降|暴跌)"
_UP = r"(?:rise|rises|rose|increase|increases|increased|up|gain|gains|gained|jump|jumps|rally|rallies|climb|climbs|上涨|涨|上升|上行)"

_SUBJECTS: list[tuple[str, str]] = [
    ("nasdaq_pct", r"(?:nasdaq|qqq|tech stocks|纳斯达克|纳指)"),
    (
        "equity_pct",
        r"(?:s&p ?500|s&p|spx|spy|stock market|stocks|equities|equity|the market|标普|股市|大盘)",
    ),
    ("oil_pct", r"(?:oil|crude|wti|brent|原油|油价)"),
    ("usd_pct", r"(?:us dollar|dollar|usd|dxy|美元)"),
    ("gold_pct", r"(?:gold|黄金)"),
    ("credit_pct", r"(?:high[- ]yield|credit|junk bonds|信用债|高收益债)"),
]

_MULTIPLE_WORDS = {
    "double": 2.0,
    "doubles": 2.0,
    "doubled": 2.0,
    "翻倍": 2.0,
    "triple": 3.0,
    "triples": 3.0,
    "tripled": 3.0,
    "halve": 0.5,
    "halves": 0.5,
    "halved": 0.5,
}

_EPISODES: list[tuple[str, str]] = [
    ("gfc_2008", r"(?:2008|gfc|financial crisis|lehman|金融危机)"),
    ("downgrade_2011", r"(?:2011|debt[- ]ceiling|downgrade|sovereign)"),
    ("cny_2015", r"(?:2015|china (?:devaluation|turbulence)|yuan)"),
    ("q4_2018", r"(?:2018)"),
    ("covid_2020", r"(?:covid|2020|pandemic|疫情)"),
    ("bear_2022", r"(?:2022|inflation shock|rate[- ]hike)"),
    ("svb_2023", r"(?:svb|silicon valley bank|2023|regional bank)"),
]


def _signed(text: str, subject: str) -> Optional[float]:
    """Percent move for a subject, signed by the direction word near it."""
    # The gap between a subject and its number may not cross a clause boundary
    # ("the stock market WITH the dollar up 5%" is the dollar's move).
    gap = r"(?:(?!\b(?:and|with|while|but|plus)\b)[^.;,\n，、]){0,40}?"
    pat_before = rf"(?P<sign>[-+−])?{_NUM}\s?(?:%|percent|％)\s?(?:(?P<d>{_DOWN})|(?P<u>{_UP}))\s?(?:in |for |on )?(?:the )?{subject}"
    pat_bare = rf"{subject}\s?(?P<sign>[-+−]){_NUM}\s?(?:%|percent|％)"
    pat_after = rf"{subject}{gap}(?:(?P<d>{_DOWN})|(?P<u>{_UP}))[^.;,\n\d]{{0,20}}?(?:by |to )?(?P<sign>[-+−])?{_NUM}\s?(?:%|percent|个点|％)"
    for pat in (pat_before, pat_bare, pat_after):
        m = re.search(pat, text)
        if not m:
            continue
        nums = [g for g in m.groups() if g and re.fullmatch(_NUM, g)]
        if not nums:
            continue
        v = float(nums[-1])
        groups = m.groupdict()
        if groups.get("sign") in ("-", "−") or groups.get("d"):
            return -v
        return v
    return None


def parse_shocks(question: str) -> dict[str, Any]:
    """Factor shocks stated in the question, in the stress tool's input units.
    Only what is explicitly said: no number, no shock."""
    text = " " + question.lower().replace(",", "") + " "
    out: dict[str, Any] = {}
    for key, subject in _SUBJECTS:
        v = _signed(text, subject)
        if v is not None:
            out[key] = v
    if "nasdaq_pct" in out and "equity_pct" in out:
        # "the Nasdaq" also matches generic "stocks" phrasing nearby; the more
        # specific index wins and the tool accepts only one.
        del out["equity_pct"]

    rates = re.search(
        rf"(?:yield|yields|rates|rate|收益率|利率)[^.;\n]{{0,40}}?(?:(?P<u>{_UP})|(?P<d>{_DOWN}))[^.;\n\d]{{0,20}}?(?:by )?{_NUM}\s?(?:bps|bp|basis points|个基点|基点)",
        text,
    ) or re.search(
        rf"(?P<sign>[-+−])?{_NUM}\s?(?:bps|bp|basis points)\s?(?:(?P<u>{_UP}|higher)|(?P<d>{_DOWN}|lower))?",
        text,
    )
    if rates:
        nums = [g for g in rates.groups() if g and re.fullmatch(_NUM, g)]
        gd = rates.groupdict()
        if nums:
            v = float(nums[-1])
            out["rates_bp"] = -v if (gd.get("d") or gd.get("sign") in ("-", "−")) else v

    vol = re.search(
        r"(?:volatility|vol|vix|波动率)[^.;\n]{0,30}?(double|doubles|doubled|triple|triples|tripled|halve|halves|halved|翻倍)",
        text,
    )
    if vol:
        out["vix_multiple"] = _MULTIPLE_WORDS[vol.group(1)]
    else:
        m = re.search(
            rf"(?:volatility|vix|波动率)[^.;\n]{{0,30}}?(?:x|×|times )\s?{_NUM}|{_NUM}\s?(?:x|×|times)\s?(?:the )?(?:volatility|vix)",
            text,
        )
        if m:
            out["vix_multiple"] = float(next(g for g in m.groups() if g))
    return out


def parse_changes(question: str, held: set[str]) -> list[dict[str, Any]]:
    """Position changes the user described for tickers they hold."""
    text = question.replace(",", "")
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for ticker in sorted(held, key=len, reverse=True):
        t = re.escape(ticker)
        pct: Optional[float] = None
        if re.search(
            rf"(?i)\b(?:sell all|sold all|exit|remove|close)\b[^.;\n]{{0,25}}\b{t}\b", text
        ):
            pct = -100.0
        elif re.search(
            rf"(?i)\b(?:halve|half)\b[^.;\n]{{0,25}}\b{t}\b|\b{t}\b[^.;\n]{{0,25}}\b(?:in half|by half)\b",
            text,
        ):
            pct = -50.0
        elif re.search(rf"(?i)\bdouble\b[^.;\n]{{0,25}}\b{t}\b", text):
            pct = 100.0
        else:
            m = re.search(
                rf"(?i)\b(?P<verb>cut|reduce|trim|sell|lower|decrease|add|increase|raise|buy)\b[^.;\n]{{0,30}}?\b{t}\b[^.;\n]{{0,20}}?(?:by )?{_NUM}\s?(?:%|percent)",
                text,
            )
            if m:
                v = float(m.group(m.lastindex))
                pct = v if m.group("verb").lower() in ("add", "increase", "raise", "buy") else -v
        if pct is not None and ticker not in seen:
            seen.add(ticker)
            out.append({"ticker": ticker, "change_pct": pct})
    return out


def plan(question: str, held: set[str]) -> list[tuple[str, dict[str, Any]]]:
    """The tool calls a careful analyst would make for this question, in order."""
    text = question.lower()
    calls: list[tuple[str, dict[str, Any]]] = [("portfolio_overview", {})]
    shocks = parse_shocks(question)
    changes = parse_changes(question, held)
    if shocks:
        calls.append(("run_stress_scenario", shocks))
    if changes:
        calls.append(("compare_portfolio_change", {"changes": changes}))
    episode = next((eid for eid, pat in _EPISODES if re.search(pat, text)), None)
    if episode or re.search(r"replay|historical|past cris|history|回放|历史", text):
        calls.append(("crisis_replay", {"episode_id": episode} if episode else {}))
    if re.search(r"factor|exposure|sensitiv|beta|driv|敞口|因子", text):
        calls.append(("factor_exposure", {}))
    if re.search(
        r"\bvar\b|cvar|tail|distribution|worst week|how much could i lose|尾部|在险价值", text
    ):
        calls.append(("loss_distribution", {}))
    if re.search(r"accura|trust|reliab|confiden|backtest|validat|准确|可信", text):
        calls.append(("model_accuracy", {}))
    if re.search(
        r"market (?:now|today|condition|regime)|current (?:market|regime)|vix (?:now|today|level)|macro|市场环境|当前市场",
        text,
    ):
        calls.append(("market_context", {}))
    if len(calls) == 1:
        # A general "how risky am I?" — show the worst cases and the drivers.
        calls += [("list_scenarios", {}), ("factor_exposure", {})]
    elif shocks and not re.search(r"accura|trust", text):
        calls.append(("model_accuracy", {}))
    return calls[:6]


_ZH = re.compile(r"[一-鿿]")


def is_chinese(text: str) -> bool:
    cjk = len(_ZH.findall(text))
    return cjk >= 2 and cjk >= 0.2 * max(len(text.replace(" ", "")), 1)


def compose_answer(question: str, results: list[tuple[str, ToolResult]]) -> str:
    """A grounded answer built only from tool summaries and evidence."""
    zh = is_chinese(question)
    good = [(n, r) for n, r in results if r.ok]
    if not good:
        errs = [r.error for _, r in results if r.error]
        base = "我无法完成这项分析。" if zh else "I couldn't complete this analysis."
        return base + (" " + errs[0] if errs else "")
    lines: list[str] = []
    for name, r in good:
        lines.append(f"**{_TITLES_ZH[name] if zh else _TITLES[name]}** — {r.summary}")
        for e in r.evidence[:6]:
            lines.append(f"- {e.label}: {e.value}")
    notes: list[str] = []
    for _, r in good:
        if r.provenance:
            for w in r.provenance.warnings:
                if w not in notes:
                    notes.append(w)
    if notes:
        lines.append("")
        lines.append("**数据说明**" if zh else "**What the data could not cover**")
        lines += [f"- {n}" for n in notes[:5]]
    failed = [r.error for _, r in results if not r.ok and r.error]
    if failed:
        lines.append("")
        lines.append(("未能完成：" if zh else "Not completed: ") + "; ".join(dict.fromkeys(failed)))
    lines.append("")
    lines.append(
        "以上为基于模型的情景估算，仅供学习参考，不构成投资建议。"
        if zh
        else "These are model-based scenario estimates for education, not investment advice."
    )
    return "\n".join(lines)


_TITLES = {
    "portfolio_overview": "Your account",
    "factor_exposure": "Where the risk comes from",
    "run_stress_scenario": "Your scenario",
    "run_named_scenario": "Scenario",
    "list_scenarios": "Scenario ranking",
    "crisis_replay": "Historical replay",
    "loss_distribution": "Loss distribution",
    "compare_portfolio_change": "Hypothetical change",
    "market_context": "Market now",
    "model_accuracy": "How far to trust this",
}
_TITLES_ZH = {
    "portfolio_overview": "账户概况",
    "factor_exposure": "风险来源",
    "run_stress_scenario": "你的情景",
    "run_named_scenario": "情景",
    "list_scenarios": "情景排序",
    "crisis_replay": "历史回放",
    "loss_distribution": "损失分布",
    "compare_portfolio_change": "假设调整",
    "market_context": "当前市场",
    "model_accuracy": "模型可信度",
}
