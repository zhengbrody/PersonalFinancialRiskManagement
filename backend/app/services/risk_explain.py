"""Deterministic-first risk diagnosis.

The architecture is "skeleton → phrasing", and it exists to honour one hard
product invariant: **the LLM never invents a number.**

1. ``build_skeleton(payload)`` — PURE Python. From the already-computed numbers
   it derives the ``severity`` label, the ``primary_driver`` string, a ranked
   list of ``findings`` (each carrying the exact numbers that justify it) and a
   ranked list of ``candidate_actions``. This is the single source of truth for
   severity / driver / numbers.
2. ``render_template(skeleton)`` — deterministic prose; the fallback. Because it
   only ever formats numbers that came from the input, it cannot hallucinate.
3. ``explain(payload, llm_callable)`` — builds the skeleton, asks the LLM to
   REPHRASE it into friendlier prose (JSON out), and on ANY problem (no key,
   bad JSON, exception) returns ``render_template``. ``severity`` and
   ``primary_driver`` are always taken from the skeleton — the LLM's are
   discarded — so the headline label can never drift from the math.

Score bands (shared with the frontend gauge): Poor <400, Watch <650,
Healthy <850, Strong ≥850.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..schemas.risk_explain import (
    ExplainMetrics,
    RiskExplainInput,
    RiskExplainOutput,
    Severity,
    SuggestedAction,
)

_log = logging.getLogger(__name__)

_SEVERITY_ORDER: list[Severity] = ["low", "moderate", "elevated", "high"]

# Tunable thresholds — documented here so the rules are auditable in one place.
_CONCENTRATION_HIGH = 0.40  # one ticker ≥40% of VaR
_CONCENTRATION_NOTE = 0.30  # worth calling out
_STRESS_SEVERE = 0.25  # ≥25% loss under the stress shock
_DRAWDOWN_SEVERE = -0.40  # max drawdown at/under −40%
_DRAWDOWN_NOTE = -0.30
_SHARPE_WEAK = 0.5
_BETA_HIGH = 1.20
_VOL_HIGH = 0.25  # 25% annualised
_ILLIQUID_DAYS = 5.0
# Dimension scores are on a 0–10 scale (overall is 0–1000); ≤3.5 = weak.
_WEAK_DIMENSION_SCORE = 3.5


# ── formatting helpers (exposed so tests can build the allowed-number set) ──


def fmt_pct(x: Optional[float], digits: int = 1) -> Optional[str]:
    """Render a fraction as a percent string (0.134 → '13.4%')."""
    if x is None:
        return None
    try:
        return f"{x * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return None


def fmt_ratio(x: Optional[float], digits: int = 2) -> Optional[str]:
    if x is None:
        return None
    try:
        return f"{x:.{digits}f}"
    except (TypeError, ValueError):
        return None


def fmt_usd(x: Optional[float]) -> Optional[str]:
    if x is None:
        return None
    try:
        return f"${x:,.0f}"
    except (TypeError, ValueError):
        return None


# ── skeleton ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Finding:
    title: str  # human, already includes its numbers
    weight: int  # ranking weight (higher = more salient)


@dataclass(frozen=True)
class Skeleton:
    severity: Severity
    primary_driver: str
    findings: list[Finding] = field(default_factory=list)
    candidate_actions: list[SuggestedAction] = field(default_factory=list)
    watch_items: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)
    confidence_label: Optional[str] = None
    directional_allowed: bool = True


def _band(score: Optional[int]) -> Optional[str]:
    if score is None:
        return None
    if score >= 850:
        return "strong"
    if score >= 650:
        return "healthy"
    if score >= 400:
        return "watch"
    return "poor"


def _worst_dimension(payload: RiskExplainInput):
    """Return (key, dim) of the lowest-scoring dimension, or (None, None)."""
    best_key, best_dim, best_score = None, None, None
    for key, dim in payload.dimensions.items():
        if dim.score is None:
            continue
        if best_score is None or dim.score < best_score:
            best_key, best_dim, best_score = key, dim, dim.score
    return best_key, best_dim


def _top_contributor(payload: RiskExplainInput):
    if not payload.top_component_var:
        return None
    return max(payload.top_component_var, key=lambda c: c.pct)


def build_skeleton(payload: RiskExplainInput) -> Skeleton:
    """Pure, rule-based. Derives severity, primary driver, ranked findings and
    candidate actions from the input numbers only."""
    m: ExplainMetrics = payload.metrics

    # ── severity: band base + risk bumps ──────────────────────────────
    band = _band(payload.overall_score)
    base = {"strong": 0, "healthy": 0, "watch": 1, "poor": 2}.get(band, 1)
    level = base

    top = _top_contributor(payload)
    if top is not None and top.pct >= _CONCENTRATION_HIGH:
        level += 1
    if payload.stress_loss is not None and abs(payload.stress_loss) >= _STRESS_SEVERE:
        level += 1
    if m.sharpe_ratio is not None and m.sharpe_ratio < 0:
        level += 1
    if m.max_drawdown is not None and m.max_drawdown <= _DRAWDOWN_SEVERE:
        level += 1
    _, worst = _worst_dimension(payload)
    if worst is not None and worst.score is not None and worst.score < _WEAK_DIMENSION_SCORE:
        level += 1

    level = max(0, min(level, len(_SEVERITY_ORDER) - 1))
    severity: Severity = _SEVERITY_ORDER[level]

    # ── findings + candidate actions (ranked) ─────────────────────────
    findings: list[Finding] = []
    actions: list[SuggestedAction] = []

    # Concentration.
    if top is not None and top.pct >= _CONCENTRATION_NOTE:
        pct = fmt_pct(top.pct, 0)
        findings.append(
            Finding(f"{top.ticker} drives {pct} of portfolio VaR — your largest concentration.", 5)
        )
        actions.append(
            SuggestedAction(
                reason=f"Single-name concentration in {top.ticker}",
                evidence=f"{top.ticker} contributes {pct} of total portfolio VaR.",
                next_step=(
                    "Compare downside in the What-if lab with your largest "
                    "position scaled down, and review overall diversification."
                ),
            )
        )

    # Downside protection.
    if (m.max_drawdown is not None and m.max_drawdown <= _DRAWDOWN_NOTE) or (
        m.cvar_95_daily is not None and m.cvar_95_daily <= -0.04
    ):
        dd = fmt_pct(m.max_drawdown)
        cvar = fmt_pct(m.cvar_95_daily)
        ev_bits = [
            b
            for b in (f"max drawdown {dd}" if dd else None, f"CVaR 95 {cvar}/day" if cvar else None)
            if b
        ]
        ev = ", ".join(ev_bits) or "elevated tail loss"
        findings.append(Finding(f"Downside protection is thin: {ev}.", 4))
        actions.append(
            SuggestedAction(
                reason="Downside protection looks thin",
                evidence=ev.capitalize() + ".",
                next_step="Consider how a defensive sleeve or hedge would change your tail loss.",
            )
        )

    # Risk-adjusted return.
    if m.sharpe_ratio is not None and m.sharpe_ratio < _SHARPE_WEAK:
        sharpe = fmt_ratio(m.sharpe_ratio)
        vol = fmt_pct(m.annual_volatility)
        ev = f"Sharpe {sharpe}" + (f" at {vol} annual volatility" if vol else "")
        findings.append(Finding(f"Risk-adjusted return is weak — {ev}.", 3))
        actions.append(
            SuggestedAction(
                reason="Risk-adjusted return is weak",
                evidence=ev + ".",
                next_step="Compare your return-per-unit-risk against a low-cost benchmark.",
            )
        )

    # Market sensitivity (risk match).
    if m.beta_to_benchmark is not None and m.beta_to_benchmark >= _BETA_HIGH:
        beta = fmt_ratio(m.beta_to_benchmark)
        findings.append(Finding(f"High market sensitivity — beta {beta} to the benchmark.", 2))
        actions.append(
            SuggestedAction(
                reason="High market sensitivity",
                evidence=f"Beta {beta} to the benchmark.",
                next_step="A beta above the market amplifies moves in both directions.",
            )
        )

    # Liquidity.
    illiquid = [
        x
        for x in payload.liquidity_outliers
        if x.days_to_liquidate is not None and x.days_to_liquidate >= _ILLIQUID_DAYS
    ]
    if illiquid:
        worst_liq = max(illiquid, key=lambda x: x.days_to_liquidate or 0.0)
        days = fmt_ratio(worst_liq.days_to_liquidate, 1)
        findings.append(Finding(f"{worst_liq.ticker} could take ~{days} days to exit.", 1))
        actions.append(
            SuggestedAction(
                reason="Liquidity risk in a holding",
                evidence=f"{worst_liq.ticker} ≈ {days} days to liquidate at a tenth of ADV.",
                next_step="Thinly-traded names are hard to exit quickly in a drawdown.",
            )
        )

    findings.sort(key=lambda f: f.weight, reverse=True)

    # ── primary driver: the single most salient risk ──────────────────
    primary_driver = _primary_driver(payload, top, m)

    # ── watch items + caveats ─────────────────────────────────────────
    watch = _watch_items(payload, m, top)
    caveats = [
        "Estimates use trailing daily history and assume broadly normal conditions.",
        "Educational, not financial advice.",
    ]

    # ── data-confidence gate (rule #3) ────────────────────────────────
    # When the page passed back its unified DataConfidence, honour the conviction
    # cap: on thin/low-confidence data, LEAD with a provisional caveat so the
    # diagnosis never reads as a confident assessment. Derived here (never the
    # LLM), so `explain` stamps it back verbatim.
    dc = payload.data_confidence
    confidence_label = dc.label if dc is not None else None
    directional_allowed = bool(dc.directional_allowed) if dc is not None else True
    if dc is not None and not directional_allowed:
        caveats.insert(
            0,
            f"Data coverage is only {dc.critical_coverage:.0%} of the critical inputs "
            "— this diagnosis is provisional, not a confident assessment. Add the "
            "missing holdings/history before relying on it.",
        )
    elif dc is not None and dc.label == "low":
        caveats.insert(
            0,
            "Data confidence is low — treat the read as directional context, not a "
            "precise assessment.",
        )

    return Skeleton(
        severity=severity,
        primary_driver=primary_driver,
        findings=findings,
        candidate_actions=actions,
        watch_items=watch,
        caveats=caveats,
        confidence_label=confidence_label,
        directional_allowed=directional_allowed,
    )


def _primary_driver(payload, top, m: ExplainMetrics) -> str:
    if top is not None and top.pct >= _CONCENTRATION_NOTE:
        return f"Concentration in {top.ticker} ({fmt_pct(top.pct, 0)} of portfolio VaR)"
    if payload.stress_loss is not None and abs(payload.stress_loss) >= _STRESS_SEVERE:
        shock = fmt_pct(payload.stress_market_shock, 0)
        return f"Market-shock sensitivity ({fmt_pct(payload.stress_loss)} loss at {shock})"
    if m.sharpe_ratio is not None and m.sharpe_ratio < 0:
        return f"Poor risk-adjusted return (Sharpe {fmt_ratio(m.sharpe_ratio)})"
    if m.max_drawdown is not None and m.max_drawdown <= _DRAWDOWN_NOTE:
        return f"Downside exposure (max drawdown {fmt_pct(m.max_drawdown)})"
    _, worst = _worst_dimension(payload)
    if worst is not None and worst.name:
        return worst.name
    return "Overall portfolio balance"


def _watch_items(payload, m: ExplainMetrics, top) -> list[str]:
    items: list[str] = []
    if m.var_95_daily is not None:
        items.append(f"Daily VaR 95: {fmt_pct(m.var_95_daily)}")
    if m.annual_volatility is not None and m.annual_volatility >= _VOL_HIGH:
        items.append(f"Annual volatility: {fmt_pct(m.annual_volatility)}")
    if top is not None:
        items.append(f"Top concentration: {top.ticker} {fmt_pct(top.pct, 0)} of VaR")
    if payload.snapshot_delta and payload.snapshot_delta.prev_overall_score is not None:
        prev = payload.snapshot_delta.prev_overall_score
        if payload.overall_score is not None:
            diff = payload.overall_score - prev
            arrow = "↑" if diff > 0 else ("↓" if diff < 0 else "→")
            items.append(f"Score {arrow} {abs(diff)} vs last snapshot ({prev})")
    return items[:4]


# ── deterministic template (the fallback) ──────────────────────────────


def render_template(skeleton: Skeleton) -> RiskExplainOutput:
    bullets = [f.title for f in skeleton.findings[:4]]
    if not bullets:
        bullets = ["No standout risk concentrations in the computed metrics."]
    headline = f"{skeleton.severity.capitalize()} risk — {skeleton.primary_driver}"
    return RiskExplainOutput(
        severity=skeleton.severity,
        headline=headline,
        summary_bullets=bullets,
        primary_driver=skeleton.primary_driver,
        watch_items=list(skeleton.watch_items),
        suggested_actions=list(skeleton.candidate_actions[:4]),
        caveats=list(skeleton.caveats),
        ai_generated=False,
        confidence_label=skeleton.confidence_label,
        directional_allowed=skeleton.directional_allowed,
    )


# ── LLM phrasing (rephrase the skeleton, never invent numbers) ─────────

_SYSTEM_PROMPT = (
    "You are a senior portfolio risk analyst writing for a novice retail "
    "investor. You will be given a DETERMINISTIC risk skeleton (severity, "
    "primary driver, findings, candidate actions) computed from the user's "
    "portfolio. Rephrase it into clear, calm, plain-English guidance.\n\n"
    "HARD RULES:\n"
    "- Do NOT invent numbers. Only cite numbers that appear in the input JSON.\n"
    "- Do NOT change the severity or the primary driver.\n"
    "- Do NOT give individualised financial advice or trade orders; keep it "
    "educational.\n"
    "- Be concise: short bullets, no preamble.\n\n"
    "Return JSON ONLY, no code fences, matching exactly:\n"
    "{\n"
    '  "headline": string,\n'
    '  "summary_bullets": string[],   // 3-4 bullets\n'
    '  "watch_items": string[],\n'
    '  "suggested_actions": [{"reason": string, "evidence": string, "next_step": string}],\n'
    '  "caveats": string[]\n'
    "}"
)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(raw: str) -> Optional[dict[str, Any]]:
    """Recover a JSON object from an LLM response (strict, then fenced, then
    largest brace span). Mirrors libs.analysis.equity_research._extract_json."""
    if not raw:
        return None
    raw = raw.strip()
    for candidate in (raw, _re_group(_JSON_FENCE_RE, raw, 1), _re_group(_JSON_OBJECT_RE, raw, 0)):
        if candidate is None:
            continue
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:  # noqa: BLE001
            continue
    return None


def _re_group(rx: re.Pattern, text: str, group: int) -> Optional[str]:
    m = rx.search(text)
    return m.group(group) if m else None


def _skeleton_to_prompt(payload: RiskExplainInput, skeleton: Skeleton) -> str:
    return (
        "RISK SKELETON (authoritative — every number you may cite is here):\n"
        + json.dumps(
            {
                "severity": skeleton.severity,
                "primary_driver": skeleton.primary_driver,
                "findings": [f.title for f in skeleton.findings],
                "candidate_actions": [a.model_dump() for a in skeleton.candidate_actions],
                "watch_items": skeleton.watch_items,
                "raw_metrics": payload.metrics.model_dump(exclude_none=True),
                "overall_score": payload.overall_score,
            },
            default=str,
        )
        + "\n\nRephrase into the JSON schema from your system prompt. "
        "Cite only the numbers above."
    )


def _coerce_str_list(value: Any, limit: int = 6) -> list[str]:
    if not isinstance(value, list):
        return []
    out = [str(x).strip() for x in value if str(x).strip()]
    return out[:limit]


def explain(
    payload: RiskExplainInput,
    *,
    llm_callable: Optional[Callable[..., str]] = None,
    max_tokens: int = 900,
    temperature: float = 0.2,
) -> RiskExplainOutput:
    """Return the structured diagnosis. ``severity`` + ``primary_driver`` are
    always the deterministic skeleton's; the LLM only supplies friendlier
    prose. Any failure → deterministic template (``ai_generated=False``)."""
    skeleton = build_skeleton(payload)
    if llm_callable is None:
        return render_template(skeleton)

    try:
        raw = llm_callable(
            prompt=_skeleton_to_prompt(payload, skeleton),
            system=_SYSTEM_PROMPT,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception as exc:  # noqa: BLE001 - degrade to template
        _log.warning("risk_explain.llm_failed err=%s", type(exc).__name__)
        return render_template(skeleton)

    parsed = _extract_json(raw or "")
    headline = str((parsed or {}).get("headline") or "").strip()
    bullets = _coerce_str_list((parsed or {}).get("summary_bullets"))
    if not parsed or not headline or not bullets:
        _log.info("risk_explain.parse_or_shape_failed — using template")
        return render_template(skeleton)

    # Build actions from the LLM but stamp the disclaimer + keep them shaped.
    actions: list[SuggestedAction] = []
    for a in (parsed.get("suggested_actions") or [])[:4]:
        if not isinstance(a, dict):
            continue
        reason = str(a.get("reason") or "").strip()
        if not reason:
            continue
        actions.append(
            SuggestedAction(
                reason=reason,
                evidence=str(a.get("evidence") or "").strip(),
                next_step=str(a.get("next_step") or "").strip(),
            )
        )
    if not actions:
        actions = list(skeleton.candidate_actions[:4])

    return RiskExplainOutput(
        # severity + primary_driver + confidence gate ALWAYS from the
        # deterministic skeleton — the LLM only rephrases prose.
        severity=skeleton.severity,
        primary_driver=skeleton.primary_driver,
        headline=headline,
        summary_bullets=bullets,
        watch_items=_coerce_str_list(parsed.get("watch_items")) or list(skeleton.watch_items),
        suggested_actions=actions,
        caveats=_coerce_str_list(parsed.get("caveats")) or list(skeleton.caveats),
        ai_generated=True,
        confidence_label=skeleton.confidence_label,
        directional_allowed=skeleton.directional_allowed,
    )
