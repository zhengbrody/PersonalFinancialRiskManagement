"""Options risk explanation — deterministic skeleton → optional LLM rephrase.

Mirrors ``risk_explain``: a pure-Python ``build_skeleton`` derives severity, the
primary driver, findings, and **educational** inspection actions from the
already-computed option exposure + flags. ``render_template`` is the
deterministic fallback. ``explain`` asks the LLM only to REPHRASE the skeleton
into friendlier prose — it may never change severity, the primary driver, or any
number, and any failure falls back to the template.

Suggested actions are educational ("Inspect rolling this expiry", "Check
collateral for the short put"), never trade execution, and always carry
"Educational, not financial advice."
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

from ..schemas.options import OptionExplainAction, OptionExplainInput, OptionExplainOutput
from .risk_explain import _extract_json  # shared, more-robust JSON recovery

_DISCLAIMER = "Educational, not financial advice."

# Flag code → educational inspection action (reason filled from the flag detail).
_ACTION_BY_CODE: dict[str, dict[str, str]] = {
    "uncovered_short_call": {
        "title": "Review coverage for your short call(s)",
        "next_step": "Confirm you hold ≥100 shares per contract, or inspect a defined-risk hedge.",
    },
    "under_collateralized_short": {
        "title": "Check collateral for the short option(s)",
        "next_step": "Verify cash/buying power covers assignment so you aren't force-liquidated.",
    },
    "short_gamma": {
        "title": "Review the hedge for short gamma",
        "next_step": "Inspect how fast losses accelerate on a gap move; consider a long-option wing.",
    },
    "large_negative_theta": {
        "title": "Inspect whether the time decay is worth the thesis",
        "next_step": "Weigh the daily premium bleed against your expected move + timing.",
    },
    "concentrated_expiry": {
        "title": "Inspect rolling part of this expiry",
        "next_step": "Spreading exposure across dates reduces single-day pin/expiry risk.",
    },
    "high_single_underlying": {
        "title": "Inspect concentration in one underlying",
        "next_step": "A single name driving most option risk is a concentrated bet — size accordingly.",
    },
    "missing_option_data": {
        "title": "Add a market price / IV for unpriced contracts",
        "next_step": "Those figures are modelled (theoretical) until a live quote is supplied.",
    },
}


@dataclass(frozen=True)
class Skeleton:
    severity: str
    primary_driver: str
    findings: list[str] = field(default_factory=list)
    actions: list[OptionExplainAction] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


def build_skeleton(payload: OptionExplainInput) -> Skeleton:
    """Pure-Python derivation from the option exposure + flags."""
    e = payload.exposure
    # Flags may arrive as pydantic models (OptionFlagOut) or plain dicts —
    # normalise to dicts so the rest is uniform.
    flags = [f.model_dump() if hasattr(f, "model_dump") else dict(f) for f in (e.flags or [])]

    has_high = any(f.get("severity") == "high" for f in flags)
    has_watch = any(f.get("severity") == "watch" for f in flags)
    if has_high:
        severity = "high"
    elif has_watch:
        severity = "elevated"
    elif (e.net_gamma or 0) < 0 or (e.net_theta or 0) < 0:
        severity = "moderate"
    else:
        severity = "low"

    # Primary driver = the highest-severity flag's detail.
    ordered = sorted(
        flags, key=lambda f: {"high": 0, "watch": 1, "info": 2}.get(f.get("severity"), 9)
    )
    primary_driver = (
        ordered[0].get("detail")
        if ordered
        else "Your option exposure looks balanced — no uncovered or concentrated risk stands out."
    )

    findings = [f.get("detail", "") for f in ordered][:5]

    actions: list[OptionExplainAction] = []
    seen: set[str] = set()
    for f in ordered:
        code = f.get("code", "")
        if code in _ACTION_BY_CODE and code not in seen:
            seen.add(code)
            tmpl = _ACTION_BY_CODE[code]
            actions.append(
                OptionExplainAction(
                    title=tmpl["title"], reason=f.get("detail", ""), next_step=tmpl["next_step"]
                )
            )

    caveats = [
        "Greeks and scenario P&L are model estimates; contracts marked 'modelled' "
        "lack a live quote and use a theoretical price.",
        _DISCLAIMER,
    ]
    return Skeleton(
        severity=severity,
        primary_driver=primary_driver,
        findings=findings,
        actions=actions,
        caveats=caveats,
    )


def _headline(skeleton: Skeleton) -> str:
    label = {"high": "High", "elevated": "Elevated", "moderate": "Moderate", "low": "Low"}[
        skeleton.severity
    ]
    return f"{label} option risk — {skeleton.primary_driver}"


def render_template(skeleton: Skeleton) -> OptionExplainOutput:
    """Deterministic prose — the fallback (and the contract the LLM rephrases)."""
    return OptionExplainOutput(
        severity=skeleton.severity,
        headline=_headline(skeleton),
        summary_bullets=skeleton.findings[:4] or [skeleton.primary_driver],
        suggested_actions=skeleton.actions,
        caveats=skeleton.caveats,
        ai_generated=False,
    )


_SYSTEM = (
    "You explain an options portfolio's risk to a retail investor. You are given a "
    "deterministic skeleton (severity, primary driver, findings, actions). REPHRASE it "
    "into a clear headline + 2-4 short bullets. Do NOT invent numbers, Greeks, or "
    "probabilities, and do NOT change the severity or the actions. Return JSON with keys "
    "headline (string) and summary_bullets (array of strings)."
)


def explain(
    payload: OptionExplainInput,
    *,
    llm_callable: Optional[Callable[..., str]] = None,
) -> OptionExplainOutput:
    """Skeleton → (optional) LLM rephrase. Severity / actions / caveats are always
    the skeleton's; only headline + bullets may be LLM-phrased. Any failure →
    deterministic template."""
    skeleton = build_skeleton(payload)
    if llm_callable is None:
        return render_template(skeleton)

    prompt = (
        f"Severity: {skeleton.severity}\nPrimary driver: {skeleton.primary_driver}\n"
        f"Findings:\n" + "\n".join(f"- {x}" for x in skeleton.findings)
    )
    try:
        raw = llm_callable(prompt=prompt, system=_SYSTEM, max_tokens=400, temperature=0.2)
    except Exception:  # noqa: BLE001 - any LLM trouble → template
        return render_template(skeleton)

    parsed = _extract_json(raw or "")
    headline = (parsed or {}).get("headline")
    bullets = (parsed or {}).get("summary_bullets")
    if not headline or not isinstance(bullets, list) or not bullets:
        return render_template(skeleton)

    return OptionExplainOutput(
        severity=skeleton.severity,  # locked
        headline=str(headline),
        summary_bullets=[str(b) for b in bullets][:4],
        suggested_actions=skeleton.actions,  # locked
        caveats=skeleton.caveats,  # locked
        ai_generated=True,
    )
