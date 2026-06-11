"""Copilot 2.0 — lightweight intent router + deterministic evidence gathering.

Flow (per the upgrade brief): classify → gather deterministic evidence (≤3 tool
calls) → one LLM synthesis in a fixed five-section format. The LLM only phrases
and ranks; every number it may cite is an ``EvidenceItem`` computed here by the
platform's engines/providers. With no LLM key the deterministic composer returns
the same five sections, so the feature never 500s and never invents numbers.
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Optional

from ..schemas.copilot2 import CopilotAnswer, EvidenceItem
from ._common import safe

_log = logging.getLogger(__name__)

# ── ticker extraction ───────────────────────────────────────────────

_TICKER_RE = re.compile(r"\$?\b([A-Z]{1,5})\b")
# Uppercase tokens that are NOT tickers (intent words, acronyms, units).
_STOP = {
    "I",
    "A",
    "VS",
    "OR",
    "AND",
    "THE",
    "ETF",
    "AI",
    "CEO",
    "CFO",
    "USA",
    "US",
    "IRA",
    "PE",
    "ROE",
    "ROA",
    "VAR",
    "ETC",
    "FAQ",
    "CAGR",
    "YOY",
    "TTM",
    "EPS",
    "P",
    "E",
    "S",
    "GDP",
    "CPI",
    "FED",
    "VIX",
    "MY",
    "OK",
    "TLDR",
    "IPO",
    "ATH",
    "ESG",
    "DCA",
    "FOMO",
    "YTD",
    "EOD",
    "NAV",
    "ROI",
    "APR",
    "APY",
}


def extract_tickers(message: str) -> list[str]:
    """Best-effort ticker symbols from a message: ``$TSLA`` anywhere, plus
    all-caps 1-5 letter tokens that aren't common acronyms/intent words."""
    out: list[str] = []
    for m in _TICKER_RE.finditer(message or ""):
        tok = m.group(1)
        dollar = m.group(0).startswith("$")
        if tok in _STOP and not dollar:
            continue
        if tok not in out:
            out.append(tok)
    return out[:5]


# ── intent classification (deterministic) ───────────────────────────

_KW = {
    "compare_tickers": ("compare", "versus", " vs ", " vs.", "better buy", "or "),
    "scenario_simulation": (
        "crash",
        "drop",
        "fall",
        "scenario",
        "what if",
        "recession",
        "downturn",
        "sell off",
        "selloff",
        "correction",
        "bear market",
        "-10%",
        "-20%",
        "-30%",
    ),
    "macro_rates": (
        "rate",
        "fed",
        "inflation",
        "macro",
        "vix",
        "yield curve",
        "regime",
        "interest",
        "economy",
        "market overall",
        "fear",
        "greed",
    ),
    "tax_fee_review": ("tax", "fee", "expense ratio", "harvest", "tax-loss", "loss harvest"),
    "explain_metric": ("what is", "what's a", "explain", "what does", "definition", "mean by"),
    "action_plan": (
        "what should i do",
        "action",
        "next step",
        "plan",
        "improve",
        "fix",
        "how do i",
        "recommend",
        "rebalance",
    ),
    "ticker_research": (
        "should i buy",
        "thoughts on",
        "research",
        "worth buying",
        "analyze",
        "look at",
        "is it a buy",
        "bull case",
        "bear case",
        "fair value",
    ),
    "portfolio_diagnosis": (
        "my portfolio",
        "how am i",
        "diagnose",
        "health",
        "how risky",
        "my risk",
        "my holdings",
        "am i diversified",
        "concentration",
    ),
}

_METRIC_GLOSSARY = {
    "sharpe": "The Sharpe ratio is return earned per unit of total risk — higher is better; above 1 is good, below 0 means you weren't paid for the risk.",
    "var": "Value at Risk (95%) is the daily loss your portfolio is unlikely to exceed on a normal day — you'd expect a worse day roughly 1 in 20.",
    "cvar": "Conditional VaR (expected shortfall) is the average loss on the worst ~5% of days — it captures how bad the tail gets beyond VaR.",
    "beta": "Beta measures how much your portfolio moves with the market: 1.0 moves in step, >1 amplifies market swings, <1 dampens them.",
    "drawdown": "Max drawdown is the largest peak-to-trough decline over the period — how deep a hole you'd have sat in at the worst point.",
    "volatility": "Volatility is the annualized standard deviation of returns — how much your portfolio's value swings up and down.",
    "alpha": "Alpha is return above what the market move (beta) alone would explain — the value added beyond passive exposure.",
}


def classify(message: str, tickers: list[str]) -> str:
    text = f" {(message or '').lower()} "
    n_tk = len(tickers)

    def has(intent: str) -> bool:
        return any(k in text for k in _KW[intent])

    # Compare needs ≥2 tickers AND a comparison cue.
    if n_tk >= 2 and (has("compare_tickers") or " vs" in text or "/" in text):
        return "compare_tickers"
    if has("explain_metric"):
        return "explain_metric"
    if has("tax_fee_review"):
        return "tax_fee_review"
    if has("scenario_simulation"):
        return "scenario_simulation"
    if has("macro_rates") and n_tk == 0:
        return "macro_rates"
    if n_tk >= 1 and (has("ticker_research") or not has("portfolio_diagnosis")):
        return "ticker_research"
    if has("action_plan"):
        return "action_plan"
    return "portfolio_diagnosis"


# ── evidence formatting helpers ─────────────────────────────────────


def _money(v) -> Optional[str]:
    return f"${v:,.0f}" if isinstance(v, (int, float)) else None


def _pct(v) -> Optional[str]:
    return f"{v * 100:.1f}%" if isinstance(v, (int, float)) else None


def _num(v, nd=2) -> Optional[str]:
    return f"{v:.{nd}f}" if isinstance(v, (int, float)) else None


def _ev(label, value, source) -> Optional[EvidenceItem]:
    return EvidenceItem(label=label, value=value, source=source) if value is not None else None


def _compact(items) -> list[EvidenceItem]:
    return [i for i in items if i is not None]


# ── per-intent evidence gathering (≤3 deterministic tool calls each) ──


def _score_evidence(score) -> list[EvidenceItem]:
    m = score.metrics
    return _compact(
        [
            _ev("Health score", f"{score.overall_score}/1000", "engine"),
            _ev("Annual return", _pct(m.annual_return), "engine"),
            _ev("Annual volatility", _pct(m.annual_volatility), "engine"),
            _ev("Sharpe ratio", _num(m.sharpe_ratio), "engine"),
            _ev("Max drawdown", _pct(m.max_drawdown), "engine"),
            _ev("Daily VaR (95%)", _pct(m.var_95_daily), "engine"),
            _ev("Beta to market", _num(m.beta_to_benchmark), "engine"),
            _ev("Portfolio value", _money(m.total_value), "engine"),
        ]
    )


def _factpack_evidence(fp, prefix: str = "") -> list[EvidenceItem]:
    p = f"{prefix} " if prefix else ""
    src = "fmp"
    items = _compact(
        [
            _ev(f"{p}Price", _money(fp.price), src),
            _ev(f"{p}P/E", _num(fp.valuation.pe, 1), src),
            _ev(f"{p}Valuation band", fp.valuation.band, "derived"),
            _ev(f"{p}Net margin", _pct(fp.quality.net_margin), src),
            _ev(f"{p}ROE", _pct(fp.quality.roe), src),
            _ev(f"{p}Revenue CAGR", _pct(fp.growth.revenue_cagr), "derived"),
            _ev(f"{p}Analyst implied upside", _pct(fp.analyst.implied_upside_pct), "derived"),
        ]
    )
    for d in fp.drivers[:2]:
        items.append(EvidenceItem(label=f"{p}Driver", value=d, source="derived"))
    for r in fp.risk_flags[:2]:
        items.append(EvidenceItem(label=f"{p}Risk", value=r, source="derived"))
    return items


def _gather(intent: str, message: str, tickers: list[str], *, user) -> list[EvidenceItem]:
    if intent in ("ticker_research", "compare_tickers"):
        from . import research_factpack as rf

        ev: list[EvidenceItem] = []
        for tk in (tickers[:3] if intent == "compare_tickers" else tickers[:1]):
            fp = safe(f"factpack:{tk}", lambda tk=tk: rf.build_fact_pack(tk))
            if fp is not None:
                ev += _factpack_evidence(fp, prefix=tk if intent == "compare_tickers" else "")
        return ev

    if intent == "macro_rates":
        from . import market_regime

        snap = safe("regime", lambda: market_regime.get_market_regime())
        if snap is None:
            return []
        d = snap.model_dump() if hasattr(snap, "model_dump") else dict(snap)
        vix = d.get("vix") or {}
        fg = d.get("fear_greed") or {}
        yc = d.get("yield_curve") or {}
        return _compact(
            [
                _ev("VIX", _num(vix.get("current"), 1), "macro"),
                _ev("VIX level", vix.get("level"), "macro"),
                _ev("Fear & Greed", _num(fg.get("score"), 0), "macro"),
                _ev("F&G rating", fg.get("rating"), "macro"),
                _ev("Yield curve", yc.get("status"), "macro"),
                _ev("3m-10y spread", _num(yc.get("spread_3m_10y"), 2), "macro"),
            ]
        )

    if intent == "explain_metric":
        ev = []
        text = (message or "").lower()
        for key, definition in _METRIC_GLOSSARY.items():
            if key in text or (key == "var" and "value at risk" in text):
                ev.append(EvidenceItem(label=key.upper(), value=definition, source="glossary"))
        # Attach the user's own current value when we have a portfolio.
        score = safe("score", lambda: _load_score(user))
        if score is not None:
            ev += _score_evidence(score)
        return ev

    # Portfolio-grounded intents: diagnosis / scenario / tax-fee / action.
    score_positions = safe("score_pos", lambda: _load_score_positions(user))
    if score_positions is None:
        return []
    positions, score = score_positions
    ev = _score_evidence(score)
    ev += safe("desk_view", lambda: _institutional_evidence(score, positions)) or []

    if intent in ("tax_fee_review", "action_plan"):
        scans = safe("optimizer", lambda: _optimizer_scans(score, positions))
        for label, value in (scans or {}).items():
            ev.append(EvidenceItem(label=label, value=value, source="engine"))
    return ev


def _institutional_evidence(score, positions) -> list[EvidenceItem]:
    """Professional-desk comparison rows (the 'Citadel bone'): the user's
    engine-computed metrics next to static institutional reference points.
    Both sides are deterministic — the LLM may only restate them."""
    from libs.ai_agents.portfolio_agents import build_institutional_comparison

    return [
        EvidenceItem(
            label=f"Desk view — {row['metric']}",
            value=f"{row['yours']} vs {row['institutional_reference']} ({row['assessment']})",
            source="reference",
        )
        for row in build_institutional_comparison(score, positions)
    ]


def _load_score(user):
    from .copilot_context import load_positions_and_score

    _positions, score = load_positions_and_score(user)
    return score


def _load_score_positions(user):
    from .copilot_context import load_positions_and_score

    positions, score = load_positions_and_score(user)
    return list(positions), score


def _optimizer_scans(score, positions) -> dict[str, str]:
    """Fee + tax-loss scan summaries from the resident optimizer agent."""
    from libs.ai_agents.portfolio_agents import StrategyOptimizerAgent

    prep = StrategyOptimizerAgent().prepare(score, positions)
    out: dict[str, str] = {}
    tr = prep.get("tool_results", {}) or {}
    fees = tr.get("hidden_fees") or tr.get("fees")
    tax = tr.get("tax_loss_harvest") or tr.get("tax_loss")
    if isinstance(fees, dict) and fees.get("summary"):
        out["Hidden-fee scan"] = str(fees["summary"])
    if isinstance(tax, dict) and tax.get("summary"):
        out["Tax-loss scan"] = str(tax["summary"])
    draft = prep.get("draft_trades") or []
    if draft:
        out["Suggested trades"] = f"{len(draft)} non-binding draft trade(s) identified"
    return out


# ── synthesis (LLM over evidence → 5 sections; deterministic fallback) ──

_SYSTEM = (
    "You are MindMarket's portfolio Copilot. You receive EVIDENCE: vetted numbers "
    "computed by the platform's engines and data providers. RULES: use ONLY the "
    "evidence values — never invent prices, ratios, or figures; if the evidence is "
    "thin, say so. Answer in EXACTLY these markdown sections, each a bold header:\n"
    "**Conclusion** — 1-2 direct sentences answering the question.\n"
    "**Evidence** — bullet the specific numbers you used (from the evidence).\n"
    "**Risks** — what could go wrong / caveats.\n"
    "**Next Actions** — 2-4 concrete, specific steps.\n"
    "**Disclaimer** — one line: educational, not financial advice.\n"
    "Be concise and specific."
)


def _evidence_block(evidence: list[EvidenceItem]) -> str:
    if not evidence:
        return "(no evidence available — likely no active portfolio or data provider offline)"
    return "\n".join(f"- {e.label}: {e.value} [{e.source}]" for e in evidence)


def _deterministic_answer(intent: str, message: str, evidence: list[EvidenceItem]) -> str:
    ev = _evidence_block(evidence)
    pretty = intent.replace("_", " ")
    return (
        f"**Conclusion**\nHere is what the data shows for your **{pretty}** question.\n\n"
        f"**Evidence**\n{ev}\n\n"
        "**Risks**\nThese are point-in-time figures from market data and may move; "
        "thin coverage limits confidence.\n\n"
        "**Next Actions**\n- Review the evidence above against your goals.\n"
        "- Open the matching page (Risk, Research, Scenarios) for the full breakdown.\n\n"
        "**Disclaimer**\nEducational analysis, not financial advice."
    )


def answer(
    message: str,
    *,
    user,
    llm_callable: Optional[Callable[..., str]] = None,
) -> CopilotAnswer:
    tickers = extract_tickers(message)
    intent = classify(message, tickers)
    evidence = _gather(intent, message, tickers, user=user)

    if llm_callable is None:
        return CopilotAnswer(
            intent=intent,
            tickers=tickers,
            answer_markdown=_deterministic_answer(intent, message, evidence),
            evidence=evidence,
            data_only=True,
        )

    # Force the reply language when the question is clearly non-English —
    # detection is deterministic (CJK ratio), not left to the model.
    from libs.ai_agents.portfolio_agents import detect_reply_language

    lang = detect_reply_language(message)
    system = _SYSTEM
    if lang:
        system += (
            f"\nLANGUAGE: the user wrote in {lang} — write the ENTIRE answer in {lang}, "
            "translating the five section headers too (for Chinese use **结论**, "
            "**证据**, **风险**, **下一步**, **免责声明**). Keep tickers and standard "
            "abbreviations (VaR, Sharpe, P/E) as-is."
        )

    prompt = (
        f"User question: {message}\n"
        f"Detected intent: {intent}\n"
        f"Tickers: {', '.join(tickers) or 'none'}\n\n"
        f"EVIDENCE:\n{_evidence_block(evidence)}\n\n"
        "Write the answer now in the five required sections."
    )
    try:
        text = llm_callable(prompt=prompt, system=system, max_tokens=1100, temperature=0.3)
        if not (text or "").strip():
            raise ValueError("empty")
        return CopilotAnswer(
            intent=intent,
            tickers=tickers,
            answer_markdown=text,
            evidence=evidence,
            data_only=False,
            model="claude-sonnet-4-6",
        )
    except Exception:  # noqa: BLE001 - any LLM failure → deterministic 5-section
        _log.warning("copilot.ask.llm_failed intent=%s", intent)
        return CopilotAnswer(
            intent=intent,
            tickers=tickers,
            answer_markdown=_deterministic_answer(intent, message, evidence),
            evidence=evidence,
            data_only=True,
        )
