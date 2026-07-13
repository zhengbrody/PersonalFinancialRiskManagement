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
from .providers import registry as reg

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


# A safe INTERNAL app path: leading "/", then only path chars (letters, digits,
# "/", "_", "-"), ≤120 total. This deliberately rejects URLs ("://"), query
# strings ("?", "&", "="), path traversal + hosts (".", ":"), whitespace/prose,
# angle brackets and any control character — so untrusted `route` context can
# never carry an injection into the classifier or the LLM prompt (F1).
_ROUTE_RE = re.compile(r"^/[A-Za-z0-9/_-]{0,119}$")
_CONTEXT_TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.-]{0,9}$")


def _safe_route(route: Optional[str]) -> Optional[str]:
    """Return ``route`` only if it's a strict safe internal path; else None.
    ``route`` is UNTRUSTED (client-supplied page context) — anything that isn't a
    plain internal path (URLs, query injection, prose, control chars) is dropped
    so it never reaches classify() or the prompt."""
    if not route or not isinstance(route, str):
        return None
    if route.startswith("//") or "//" in route:
        return None
    return route if _ROUTE_RE.fullmatch(route) else None


def _safe_ticker(ticker: Optional[str]) -> Optional[str]:
    """Normalize a page-context ticker and reject everything but a bounded
    exchange-style symbol. Unlike message extraction, context must not accept a
    leading ``$`` or arbitrary prose because it is copied into the model prompt."""
    if not ticker or not isinstance(ticker, str):
        return None
    normalized = ticker.strip().upper()
    return normalized if _CONTEXT_TICKER_RE.fullmatch(normalized) else None


# ── intent classification (deterministic) ───────────────────────────

# English keywords are space-delimited word tokens; Chinese has no word
# boundaries, so CJK keywords rely on plain containment — keep them ≥2 chars
# and unambiguous (the same "safe tokens" discipline as the English set).
_KW = {
    "compare_tickers": (
        "compare",
        "versus",
        " vs ",
        " vs.",
        "better buy",
        "or ",
        "对比",
        "比较",
        "相比",
        "哪个更好",
    ),
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
        "下跌",
        "大跌",
        "暴跌",
        "崩盘",
        "回调",
        "熊市",
        "衰退",
        "如果市场",
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
        "利率",
        "美联储",
        "通胀",
        "宏观",
        "收益率曲线",
        "恐慌",
        "贪婪",
    ),
    "tax_fee_review": (
        "tax",
        "fee",
        "expense ratio",
        "harvest",
        "tax-loss",
        "loss harvest",
        "税务",
        "税损",
        "缴税",
        "报税",
        "费用",
        "费率",
    ),
    "explain_metric": (
        "what is",
        "what's a",
        "explain",
        "what does",
        "definition",
        "mean by",
        # "是什么" (suffix form) is deliberately absent — "我最大的风险是什么"
        # is a diagnosis question, not a definition lookup.
        "解释",
        "什么是",
        "怎么理解",
        "含义",
    ),
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
        "怎么办",
        "该怎么",
        "怎么改善",
        "如何改善",
        "如何提高",
        "再平衡",
        "优化",
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
        "研究",
        "分析一下",
        "看法",
        "估值",
        "基本面",
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
        "我的组合",
        "我的投资组合",
        "我的持仓",
        "风险高",
        "风险太高",
        "分散",
        "集中度",
        "健康",
    ),
    # Safe tokens only — avoid substrings that hide in common words (e.g. "put"
    # in "input", "loan" in "download", bare "call" in a ticker question).
    "margin_risk": (
        "margin",
        "leverage",
        "leveraged",
        "over-leveraged",
        "over leveraged",
        "borrowed money",
        "buying power",
        "maintenance",
        "保证金",
        "杠杆",
        "融资买入",
    ),
    "options_risk": (
        "option",
        "options",
        "greeks",
        "gamma",
        "theta",
        "vega",
        "covered call",
        "call spread",
        "put spread",
        "iron condor",
        "expiry",
        "assignment",
        "期权",
        "希腊字母",
        "行权",
    ),
}

# Chinese display names for the closed intent set — used only by the Chinese
# deterministic template (the English intent token mid-sentence read like an
# unfilled blank).
_INTENT_ZH = {
    "portfolio_diagnosis": "组合诊断",
    "scenario_simulation": "情景模拟",
    "macro_rates": "宏观与利率",
    "tax_fee_review": "税务与费用",
    "explain_metric": "指标解释",
    "action_plan": "行动计划",
    "ticker_research": "个股研究",
    "compare_tickers": "个股对比",
    "margin_risk": "保证金风险",
    "options_risk": "期权风险",
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


def classify(message: str, tickers: list[str], *, route: Optional[str] = None) -> str:
    text = f" {(message or '').lower()} "
    n_tk = len(tickers)
    r = (route or "").lower()

    def has(intent: str) -> bool:
        return any(k in text for k in _KW[intent])

    # Compare needs ≥2 tickers AND a comparison cue.
    if n_tk >= 2 and (has("compare_tickers") or " vs" in text or "/" in text):
        return "compare_tickers"
    if has("explain_metric"):
        return "explain_metric"
    if has("tax_fee_review"):
        return "tax_fee_review"
    # Margin / options questions are portfolio-grounded — check before scenario
    # and ticker_research so "am I over-leveraged" / "my options risk" route here.
    if has("margin_risk"):
        return "margin_risk"
    if has("options_risk") and n_tk == 0:
        return "options_risk"
    if has("scenario_simulation"):
        return "scenario_simulation"
    if has("macro_rates") and n_tk == 0:
        return "macro_rates"
    if n_tk >= 1 and (has("ticker_research") or not has("portfolio_diagnosis")):
        return "ticker_research"
    if has("action_plan"):
        return "action_plan"
    # Page-awareness (light bias — only when the message has no stronger cue):
    # on the research page with a ticker in view, an ambiguous question is about
    # that stock; on the risk/score/scenarios pages it's about the portfolio.
    if n_tk >= 1 and r.startswith("/research"):
        return "ticker_research"
    return "portfolio_diagnosis"


# ── evidence formatting helpers ─────────────────────────────────────


def _money(v) -> Optional[str]:
    return f"${v:,.0f}" if isinstance(v, (int, float)) else None


def _pct(v) -> Optional[str]:
    return f"{v * 100:.1f}%" if isinstance(v, (int, float)) else None


def _num(v, nd=2) -> Optional[str]:
    return f"{v:.{nd}f}" if isinstance(v, (int, float)) else None


def _ev(label, value, source) -> Optional[EvidenceItem]:
    if value is None:
        return None
    from .confidence import source_type_for

    return EvidenceItem(
        label=label, value=value, source=source, source_type=source_type_for(source)
    )


# Evidence sources that carry HARD data (computed or provider-reported) vs the
# "soft" reference sources — used to gauge how directional the answer can be.
_HARD_EVIDENCE_SOURCES = {
    "engine",
    "fmp",
    "massive",
    "yfinance",
    "macro",
    "fred",
    "treasury",
    "sec",
}


def _answer_confidence(evidence: list[EvidenceItem], quality_floor: Optional[float] = None):
    """A DataConfidence for a Copilot answer. Critical coverage is the share of
    HARD facts among the evidence, CLAMPED by the grounding data's own quality
    (``quality_floor``) — so an all-engine answer over a thin-history book is
    still low-critical and can't be directional (rule #3). A thin or
    reference-only answer can't be directional either."""
    from .confidence import build_data_confidence, field_provenance

    total = len(evidence)
    hard = sum(1 for e in evidence if e.source in _HARD_EVIDENCE_SOURCES)
    overall = min(1.0, total / 4.0)  # ~4+ vetted facts = full coverage
    critical = (hard / total) if total else 0.0
    if quality_floor is not None:
        critical = min(critical, max(0.0, min(1.0, quality_floor)))
    seen: dict[str, int] = {}
    for e in evidence:
        seen[e.source] = seen.get(e.source, 0) + 1
    sources = [field_provenance(f"evidence ({src})", src, coverage=1.0) for src in seen]
    base = (
        "high"
        if critical >= 0.85
        else "medium" if critical >= 0.70 else "low" if critical >= 0.40 else "none"
    )
    return build_data_confidence(
        overall_coverage=overall,
        critical_coverage=critical,
        sources=sources,
        confidence=round(0.4 * overall + 0.6 * critical, 3),
        base_conviction=base,
    )


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
            # Margin context — present (>1) only for a leveraged book, so
            # margin_risk questions are grounded in the real leverage + carry.
            _ev(
                "Leverage",
                (
                    f"{getattr(m, 'leverage', 1.0):.2f}×"
                    if getattr(m, "leverage", None) and m.leverage > 1.0001
                    else None
                ),
                "engine",
            ),
            _ev(
                "Margin cost / yr",
                (
                    _pct(getattr(m, "margin_cost_annual", None))
                    if getattr(m, "margin_cost_annual", None)
                    else None
                ),
                "engine",
            ),
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


_OPTION_TERMS = (
    "option",
    "delta",
    "gamma",
    "theta",
    "vega",
    "implied vol",
    "assignment",
    "covered call",
    "protective put",
    "short call",
    "short put",
    "strike",
    "expiry",
    "premium",
)


def _mentions_options(message: str) -> bool:
    m = (message or "").lower()
    return any(t in m for t in _OPTION_TERMS)


def _option_specs(holdings: dict) -> list:
    """Option holdings → analytics specs (signed by long/short). Pure parse."""
    from types import SimpleNamespace

    specs = []
    for h in (holdings or {}).values():
        if not isinstance(h, dict) or str(h.get("asset_type") or "").lower() != "option":
            continue
        u = str(h.get("underlying") or "").upper()
        strike, expiry = h.get("strike"), h.get("expiry")
        ot = str(h.get("option_type") or "").lower()
        if not u or strike in (None, 0) or not expiry or ot not in ("call", "put"):
            continue
        sign = -1.0 if str(h.get("option_side") or "long").lower() == "short" else 1.0
        specs.append(
            SimpleNamespace(
                underlying=u,
                option_type=ot,
                strike=float(strike),
                expiry=str(expiry),
                quantity=sign * float(h.get("shares") or 0.0),
                avg_premium=h.get("avg_cost"),
                contract_multiplier=float(h.get("contract_multiplier") or 100.0),
            )
        )
    return specs


def _option_evidence(message: str, user) -> list[EvidenceItem]:
    """Deterministic option-exposure evidence (net Greeks + risk flags) for the
    active book — only when the question is option-related AND the book holds
    options. Lets the Copilot answer 'am I short gamma?', 'net delta?', 'biggest
    option risk?' citing computed numbers only."""
    if not _mentions_options(message):
        return []
    from libs.auth.active_portfolio import get_active_holdings

    from . import options_analytics, options_exposure

    holdings = get_active_holdings(access_token=user.access_token) or {}
    specs = _option_specs(holdings)
    if not specs:
        return []
    results = options_analytics.analyze_contracts(specs).get("results", [])
    exp = options_exposure.build_exposure(results)
    gamma_note = (
        "net short gamma (losses accelerate on a move)"
        if exp["net_gamma"] < 0
        else "net long gamma"
    )
    items = _compact(
        [
            _ev("Option net delta", _num(exp["net_delta"], 1), "engine"),
            _ev("Option net gamma", f"{exp['net_gamma']:.2f} — {gamma_note}", "engine"),
            _ev("Option theta / day", _money(exp["net_theta"]), "engine"),
            _ev("Option net vega (per 1% IV)", _money(exp["net_vega"]), "engine"),
            _ev("Option notional", _money(exp["option_notional"]), "engine"),
            _ev(
                "Option contracts",
                f"{exp['contracts']} ({exp['short_contracts']} short)",
                "engine",
            ),
        ]
    )
    for f in exp["flags"][:2]:
        items.append(
            EvidenceItem(label=f"Option risk — {f['code']}", value=f["detail"], source="engine")
        )
    return items


def _score_quality(score) -> Optional[float]:
    """The portfolio score's OWN data-quality (0..1) — the real grounding-data
    ceiling for a portfolio-backed answer (not the evidence source-mix)."""
    m = getattr(score, "metrics", None)
    dq = getattr(m, "data_quality", None) if m is not None else None
    try:
        return float(dq) if dq is not None else None
    except (TypeError, ValueError):
        return None


_CHANGE_TERMS = (
    "change",
    "changed",
    "fall",
    "fell",
    "drop",
    "dropped",
    "down",
    "up",
    "since",
    "yesterday",
    "worse",
    "better",
    "why did",
    "moved",
    "变化",
    "下跌",
    "下降",
    "为什么",
    "跌了",
    "涨了",
    "变了",
)


def _asks_about_change(message: str) -> bool:
    m = (message or "").lower()
    return any(t in m for t in _CHANGE_TERMS)


_PORTFOLIO_REL_TERMS = (
    "my portfolio",
    "my book",
    "my holdings",
    "my risk",
    "my position",
    "how much of my",
    "in my",
    "contribute",
    "contribution",
    "exposure",
    "do i hold",
    "do i own",
    "of this name",
    "this name",
    "我的组合",
    "我的持仓",
    "我的投资组合",
    "贡献",
    "占比",
    "占我",
    "仓位",
    "持仓",
)


def _asks_portfolio_relative(message: str) -> bool:
    """True when a ticker question is asked RELATIVE to the user's own book —
    so a research answer should also carry the holding's portfolio exposure."""
    m = (message or "").lower()
    return any(t in m for t in _PORTFOLIO_REL_TERMS)


def _score_change_evidence(user, score, positions=None) -> list[EvidenceItem]:
    """Deterministic 'why did my score change?' evidence: the move vs the user's
    OWN prior snapshot, decomposed into market / holdings / data-quality (reuses
    ``score_changes.build_change_report`` from the cockpit). Light — a snapshot
    fetch + arithmetic, no engine run. Empty when there's no prior snapshot or the
    methodology isn't comparable. ``positions`` (when given) lets the diff tell a
    market move from a holdings move."""
    from ..schemas.score_changes import ScoreChangeRequest
    from . import snapshots
    from .score_changes import build_change_report

    prev = snapshots.get_snapshot_at_window(user.access_token, "previous")
    if not prev:
        return []
    m = score.metrics
    dims = {
        k: float(d.score)
        for k, d in (getattr(score, "dimensions", None) or {}).items()
        if getattr(d, "score", None) is not None
    }
    top_positions: list[dict] = []
    total_mv = sum(float(getattr(p, "market_value", 0.0) or 0.0) for p in (positions or []))
    if total_mv > 0:
        rows = [
            {
                "ticker": str(getattr(p, "ticker", "") or "").upper(),
                "weight": float(getattr(p, "market_value", 0.0) or 0.0) / total_mv,
            }
            for p in positions
            if getattr(p, "ticker", None)
        ]
        top_positions = sorted(rows, key=lambda r: r["weight"], reverse=True)[:10]
    req = ScoreChangeRequest(
        window="previous",
        overall_score=int(score.overall_score),
        base_overall=int(getattr(score, "base_overall", None) or score.overall_score),
        dimensions=dims,
        top_positions=top_positions,
        metrics={
            "annual_volatility": getattr(m, "annual_volatility", None),
            "sharpe_ratio": getattr(m, "sharpe_ratio", None),
            "max_drawdown": getattr(m, "max_drawdown", None),
            "var_95_daily": getattr(m, "var_95_daily", None),
            "beta_to_benchmark": getattr(m, "beta_to_benchmark", None),
            "net_equity": getattr(m, "net_equity", None),
            "leverage": getattr(m, "leverage", None),
        },
        confidence=getattr(m, "confidence", None),
    )
    rep = build_change_report(req, prev)
    if not rep.available:
        return []
    if rep.comparable is False:
        # F4: an incompatible prior methodology is an EXPLICIT limitation — never
        # imply "no change". Surface the deterministic methodology-change notice so
        # the answer says the two scores aren't directly comparable.
        return [
            EvidenceItem(
                label="Score change",
                value=(
                    rep.summary
                    or "Not directly comparable — your earlier score used a different "
                    "methodology version."
                ),
                source="engine",
            )
        ]
    if rep.score_delta is None:
        return []
    items = [_ev("Score change (since last snapshot)", f"{rep.score_delta:+d} pts", "engine")]
    a = rep.attribution
    if a is not None:
        if a.separable:
            items += [
                _ev("↳ Market-driven", _signed_pts(a.market_driven), "engine"),
                _ev("↳ Holdings-driven", _signed_pts(a.holding_driven), "engine"),
                _ev("↳ Data-quality-driven", _signed_pts(a.data_quality_driven), "engine"),
            ]
        else:
            items += [
                _ev("↳ Market + your changes", _signed_pts(a.combined_market_holdings), "engine"),
                _ev("↳ Data-quality-driven", _signed_pts(a.data_quality_driven), "engine"),
            ]
    if rep.top_negative_contributor is not None:
        d = rep.top_negative_contributor
        items.append(_ev("Biggest drag", f"{d.label} ({d.points:+d} pts)", "engine"))
    return _compact(items)


def _signed_pts(v) -> Optional[str]:
    return f"{v:+d} pts" if isinstance(v, int) else None


def _dropped_tickers(score) -> set[str]:
    """Uppercase set of tickers the engine HELD but could not price (dropped from
    the returns matrix). Authoritative 'held-but-unpriced' ownership check (F2)."""
    m = getattr(score, "metrics", None)
    return {str(t).upper() for t in (getattr(m, "dropped_tickers", None) or [])}


def _ticker_exposure_evidence(
    tickers: list[str], positions, dropped_tickers=()
) -> list[EvidenceItem]:
    """How much a QUERIED ticker contributes to the caller's OWN book, three-way
    (F2): PRICED → weight + market value + rank; HELD-BUT-UNPRICED → an explicit
    'held — current price unavailable' (never 'not held'); otherwise NOT HELD.
    ``dropped_tickers`` is the engine's held-but-unpriceable set (authoritative
    ownership for the unpriced case). Weight-based exposure, honestly labelled —
    NOT a component-VaR contribution (that needs the risk report; F5)."""
    if not tickers:
        return []
    dropped = {str(t).upper() for t in (dropped_tickers or [])}
    by_ticker: dict[str, float] = {}
    total = 0.0
    for p in positions or []:
        tk = str(getattr(p, "ticker", "") or "").upper()
        mv = float(getattr(p, "market_value", 0.0) or 0.0)
        if tk and mv > 0:
            by_ticker[tk] = by_ticker.get(tk, 0.0) + mv
            total += mv
    ranked = sorted(by_ticker.items(), key=lambda kv: kv[1], reverse=True)
    rank_of = {tk: i + 1 for i, (tk, _mv) in enumerate(ranked)}
    items: list[EvidenceItem] = []
    for tk in tickers[:2]:
        u = tk.upper()
        mv = by_ticker.get(u)
        if mv is not None and total > 0:
            items.append(_ev(f"{u} weight in your book", _pct(mv / total), "engine"))
            items.append(_ev(f"{u} market value", _money(mv), "engine"))
            items.append(
                EvidenceItem(
                    label=f"{u} position rank",
                    value=f"#{rank_of[u]} of {len(ranked)} holdings",
                    source="engine",
                )
            )
        elif u in dropped:
            # HELD but the current price is unavailable — explicit, never "not held".
            items.append(
                EvidenceItem(
                    label=f"{u} in your book",
                    value="held — current price unavailable",
                    source="engine",
                )
            )
        else:
            items.append(EvidenceItem(label=f"{u} in your book", value="not held", source="engine"))
    return _compact(items)


def _gather(intent: str, message: str, tickers: list[str], *, user):
    """Returns (evidence, quality_floor). ``quality_floor`` is the grounding
    data's OWN quality (0..1) when the answer rests on the portfolio score /
    FactPack — so a thin-history book can't yield a directional Copilot answer
    just because its evidence is engine-computed. None when the answer rests on
    reference/macro data (gated by evidence presence, not a directional call)."""
    if intent in ("ticker_research", "compare_tickers"):
        from . import research_factpack as rf

        ev: list[EvidenceItem] = []
        floors: list[float] = []
        for tk in (tickers[:3] if intent == "compare_tickers" else tickers[:1]):
            fp = safe(f"factpack:{tk}", lambda tk=tk: rf.build_fact_pack(tk))
            if fp is not None:
                ev += _factpack_evidence(fp, prefix=tk if intent == "compare_tickers" else "")
                floors.append(float(getattr(fp.data_quality, "coverage", 0.0) or 0.0))
        # Portfolio-aware research: when the question is asked relative to the
        # user's own book ("how much of my risk is this name?"), add the
        # researched ticker's exposure in their portfolio (best-effort).
        floor = min(floors) if floors else 0.0
        if _asks_portfolio_relative(message):
            sp = safe("score_pos", lambda: _load_score_positions(user))
            if sp is not None:
                dropped = _dropped_tickers(sp[1])
                ev += _ticker_exposure_evidence(tickers, sp[0], dropped) or []
                if any(t.upper() in dropped for t in tickers):
                    floor = min(floor if floor is not None else 1.0, 0.5)
        return ev, floor

    if intent == "macro_rates":
        from . import market_regime

        snap = safe("regime", lambda: market_regime.get_market_regime())
        if snap is None:
            return [], None
        d = snap.model_dump() if hasattr(snap, "model_dump") else dict(snap)
        vix = d.get("vix") or {}
        fg = d.get("fear_greed") or {}
        yc = d.get("yield_curve") or {}
        return (
            _compact(
                [
                    _ev("VIX", _num(vix.get("current"), 1), "macro"),
                    _ev("VIX level", vix.get("level"), "macro"),
                    _ev("Fear & Greed", _num(fg.get("score"), 0), "macro"),
                    _ev("F&G rating", fg.get("rating"), "macro"),
                    _ev("Yield curve", yc.get("status"), "macro"),
                    _ev("3m-10y spread", _num(yc.get("spread_3m_10y"), 2), "macro"),
                ]
            ),
            None,
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
        return ev, (_score_quality(score) if score is not None else None)

    # Portfolio-grounded intents: diagnosis / scenario / tax-fee / action.
    score_positions = safe("score_pos", lambda: _load_score_positions(user))
    if score_positions is None:
        return [], None
    positions, score = score_positions
    ev = _score_evidence(score)
    ev += safe("options", lambda: _option_evidence(message, user)) or []
    ev += safe("risk_reference", lambda: _risk_reference_evidence(score, positions)) or []

    # Context-aware, minimum-tool selection (rule #3): only pull the score-change
    # decomposition when the question is about a change, and per-ticker exposure
    # only when a ticker is in play (message or page context).
    dropped = _dropped_tickers(score)
    if _asks_about_change(message):
        ev += safe("score_change", lambda: _score_change_evidence(user, score, positions)) or []
    if tickers:
        ev += (
            safe("ticker_exposure", lambda: _ticker_exposure_evidence(tickers, positions, dropped))
            or []
        )

    if intent in ("tax_fee_review", "action_plan"):
        scans = safe("optimizer", lambda: _optimizer_scans(score, positions))
        for label, value in (scans or {}).items():
            ev.append(EvidenceItem(label=label, value=value, source="engine"))
    # A portfolio answer's ceiling is the SCORE's own data quality. A queried
    # ticker that's HELD BUT UNPRICED makes THIS answer less reliable → clamp the
    # floor so conviction drops (F2).
    floor = _score_quality(score)
    if any(t.upper() in dropped for t in tickers):
        floor = min(floor if floor is not None else 1.0, 0.5)
    return ev, floor


def _risk_reference_evidence(score, positions) -> list[EvidenceItem]:
    """Risk-reference rows: the user's engine-computed metrics next to static,
    neutral risk-management reference bands. Both sides are deterministic —
    the LLM may only restate them; they carry no buy/sell implication."""
    from libs.ai_agents.portfolio_agents import build_risk_reference_comparison

    return [
        EvidenceItem(
            label=f"Risk reference — {row['metric']}",
            value=f"{row['yours']} vs {row['reference_band']} ({row['assessment']})",
            source="reference",
        )
        for row in build_risk_reference_comparison(score, positions)
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
    """Fee / unrealized-loss / risk-lever summaries from the resident
    optimizer agent — risk-management observations, never trade instructions."""
    from libs.ai_agents.portfolio_agents import StrategyOptimizerAgent

    prep = StrategyOptimizerAgent().prepare(score, positions)
    out: dict[str, str] = {}
    tr = prep.get("tool_results", {}) or {}
    fees = tr.get("hidden_fees") or []
    if fees:
        total = sum(float(row.get("annual_fee_usd", 0.0)) for row in fees)
        out["Hidden-fee scan"] = (
            f"{len(fees)} fund holding(s) carry an estimated expense drag of ${total:,.0f}/yr"
        )
    losses = tr.get("unrealized_losses") or []
    if losses:
        out["Unrealized-loss review"] = (
            f"{len(losses)} position(s) carry unrealized losses beyond the threshold — "
            "realizing a loss is a tax decision (wash-sale rules apply); "
            "review with a tax professional"
        )
    levers = prep.get("risk_levers") or []
    if levers:
        out["Risk levers"] = "; ".join(lv["headline"] for lv in levers[:4])
    return out


# ── synthesis (LLM over evidence → 5 sections; deterministic fallback) ──

_SYSTEM = (
    "You are MindMarket's portfolio Copilot. You receive EVIDENCE: vetted numbers "
    "computed by the platform's engines and data providers. Each evidence line "
    "ends with [source: NAME]. RULES: use ONLY the evidence values — never invent "
    "prices, ratios, or figures; ATTRIBUTE figures to their source in prose (e.g. "
    "'per FMP', 'per the MindMarket engine', 'per FRED'); if a source is missing or "
    "the evidence is thin, SAY SO plainly rather than implying confidence you don't "
    "have. A DERIVED / estimated figure (source ending 'derived' or 'estimate') must "
    "be described as an estimate — never as a provider-reported fact. BOUNDARY — "
    "risk analytics, not investment advice: never tell the user "
    "to buy or sell a specific security, never name a security to add or swap in, "
    "and never give a dollar amount to trade; frame Next Actions as risk-management "
    "levers (e.g. reduce single-name concentration, review leverage, adjust the "
    "liquidity buffer, compare downside under a lower-beta allocation) evaluated "
    "in the platform's What-if lab / Scenarios / Risk Report. "
    "Answer in EXACTLY these markdown sections, each a bold header:\n"
    "**Conclusion** — 1-2 direct sentences answering the question.\n"
    "**Evidence** — bullet the specific numbers you used, each tagged with its source.\n"
    "**Risks** — what could go wrong / caveats.\n"
    "**Next Actions** — 2-4 concrete, specific steps.\n"
    "**Disclaimer** — one line: educational, not financial advice.\n"
    "Be concise and specific."
)


def _evidence_block(evidence: list[EvidenceItem], *, chinese: bool = False) -> str:
    if not evidence:
        if chinese:
            return "（暂无可用证据 —— 可能没有活跃的投资组合，或某个数据提供方离线）"
        return "(no evidence available — likely no active portfolio or a data provider is offline)"
    # Tag each figure with its human SOURCE LABEL so the model can attribute it.
    return "\n".join(f"- {e.label}: {e.value} [source: {reg.label(e.source)}]" for e in evidence)


def _deterministic_answer(intent: str, message: str, evidence: list[EvidenceItem]) -> str:
    # Deterministic template — match the user's language (same rule as the
    # LLM path's forced-language instruction; evidence labels/values are
    # data and stay verbatim). Default English path is unchanged.
    from libs.ai_agents.portfolio_agents import detect_reply_language

    pretty = intent.replace("_", " ")
    if detect_reply_language(message):
        ev = _evidence_block(evidence, chinese=True)
        pretty_zh = _INTENT_ZH.get(intent, pretty)
        return (
            f"**结论**\n以下是与您的**{pretty_zh}**问题相关的数据结果。\n\n"
            f"**证据**\n{ev}\n\n"
            "**风险**\n这些是来自市场数据的时点数字，可能随时变动；"
            "数据覆盖不足会降低可信度。\n\n"
            "**下一步**\n- 对照您的目标复查上述证据。\n"
            "- 打开对应页面（风险、研究、情景）查看完整分析。\n\n"
            "**免责声明**\n教育性分析，不构成投资建议。"
        )
    ev = _evidence_block(evidence)
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
    route: Optional[str] = None,
    ticker: Optional[str] = None,
) -> CopilotAnswer:
    # route + ticker are UNTRUSTED client context. Sanitize BOTH before either
    # touches the classifier or the LLM prompt (F1): route must be a strict safe
    # internal path, ticker a valid symbol; anything else is dropped.
    route = _safe_route(route)
    ticker = _safe_ticker(ticker)
    tickers = extract_tickers(message)
    # The page's currently-viewed ticker is CONTEXT — fold it into the ticker set
    # so exposure/factpack tools see it, but it never becomes citable evidence
    # unless a deterministic tool computes a number for it.
    if ticker and ticker not in tickers:
        tickers = [ticker, *tickers][:5]
    intent = classify(message, tickers, route=route)
    evidence, quality_floor = _gather(intent, message, tickers, user=user)
    dc = _answer_confidence(evidence, quality_floor)

    if llm_callable is None:
        return CopilotAnswer(
            intent=intent,
            tickers=tickers,
            answer_markdown=_deterministic_answer(intent, message, evidence),
            evidence=evidence,
            data_only=True,
            conviction=dc.conviction_cap,
            data_confidence=dc,
        )

    # Force the reply language when the question is clearly non-English —
    # detection is deterministic (CJK ratio), not left to the model.
    from libs.ai_agents.portfolio_agents import detect_reply_language

    lang = detect_reply_language(message)
    system = _SYSTEM
    if not dc.directional_allowed:
        # Rule #3: too little hard data for a directional read — instruct the
        # model to withhold a directional conclusion and say so.
        system += (
            "\nDATA-CONFIDENCE GATE: the available evidence is too thin for a "
            "directional conclusion. In **Conclusion**, state plainly that there "
            "isn't enough data to give a confident answer and what's missing — do "
            "NOT assert a directional view."
        )
    if lang:
        system += (
            f"\nLANGUAGE: the user wrote in {lang} — write the ENTIRE answer in {lang}, "
            "translating the five section headers too (for Chinese use **结论**, "
            "**证据**, **风险**, **下一步**, **免责声明**). Keep tickers and standard "
            "abbreviations (VaR, Sharpe, P/E) as-is."
        )

    context_line = ""
    if route or ticker:
        bits = []
        if route:
            bits.append(f"page {route}")
        if ticker:
            bits.append(f"viewing {str(ticker).upper()}")
        context_line = f"User context: {', '.join(bits)} (context only — cite only EVIDENCE)\n"
    prompt = (
        f"User question: {message}\n"
        f"Detected intent: {intent}\n"
        f"Tickers: {', '.join(tickers) or 'none'}\n"
        f"{context_line}\n"
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
            conviction=dc.conviction_cap,
            data_confidence=dc,
        )
    except Exception:  # noqa: BLE001 - any LLM failure → deterministic 5-section
        _log.warning("copilot.ask.llm_failed intent=%s", intent)
        return CopilotAnswer(
            intent=intent,
            tickers=tickers,
            answer_markdown=_deterministic_answer(intent, message, evidence),
            evidence=evidence,
            data_only=True,
            conviction=dc.conviction_cap,
            data_confidence=dc,
        )
