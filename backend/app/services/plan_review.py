"""Deterministic risk-plan review (PR2).

Compares a plan's stored BASELINE metrics to the CURRENT metrics the client
passes back, per each metric's intrinsic better-direction, and returns a factual
verdict (improved / worsened / inconclusive) + confidence + what couldn't be
compared. Pure Python — no LLM, no recompute, no advice, no holdings mutation.
"""

from __future__ import annotations

import math
from typing import Any, Optional

# Direction of "improvement" per tracked metric.
_HIGHER_BETTER = {"overall_score", "sharpe_ratio"}
_LOWER_BETTER = {
    "annual_volatility",
    "var_95",
    "var_95_daily",
    "cvar_95",
    "cvar_95_daily",
    "top_holding_weight",
    "leverage",
}
# Magnitude-based (smaller |x| is better) — sign-agnostic on purpose:
#   * beta_to_benchmark: closer to market-neutral;
#   * max_drawdown: the backend emits it BOTH ways — /score positive (abs), /risk
#     negative — so a smaller DRAWDOWN MAGNITUDE is the only convention-safe
#     "improvement" (a plan's baseline can come from either source).
_MAGNITUDE_LOWER_BETTER = {"beta_to_benchmark", "max_drawdown"}

_TRACKED = _HIGHER_BETTER | _LOWER_BETTER | _MAGNITUDE_LOWER_BETTER


def _finite(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _extract(d: dict[str, Any], name: str) -> Optional[float]:
    """Read a metric from the top level OR a nested ``metrics`` block (the score
    response nests them), whichever is present."""
    if not isinstance(d, dict):
        return None
    if name in d:
        return _finite(d[name])
    inner = d.get("metrics")
    if isinstance(inner, dict) and name in inner:
        return _finite(inner[name])
    return None


def _material(delta: float, baseline: float) -> bool:
    """Filter noise: a move counts only if it clears a small relative floor."""
    return abs(delta) > max(1e-4, 0.005 * abs(baseline))


def _improved(metric: str, baseline: float, current: float) -> Optional[bool]:
    """True/False by the metric's better-direction, or None when the move is
    immaterial (so noise never flips the verdict)."""
    delta = current - baseline
    if not _material(delta, baseline):
        return None
    if metric in _MAGNITUDE_LOWER_BETTER:
        return abs(current) < abs(baseline)
    if metric in _HIGHER_BETTER:
        return current > baseline
    return current < baseline  # _LOWER_BETTER


def build_review(
    baseline: dict[str, Any], current: dict[str, Any], expected_impact: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Return a plan-review dict (matches RiskPlanReviewOut). ``expected_impact``
    is accepted for future use but the verdict is driven purely by intrinsic
    metric directions — so it can't be gamed by a mislabeled expectation."""
    baseline = baseline or {}
    current = current or {}
    metrics: list[dict[str, Any]] = []
    missing: list[str] = []
    improved_n = worsened_n = 0

    for name in sorted(_TRACKED):
        b = _extract(baseline, name)
        if b is None:
            continue  # not part of this plan's baseline → not tracked
        c = _extract(current, name)
        if c is None:
            missing.append(name)
            metrics.append(
                {"metric": name, "baseline": b, "current": None, "delta": None, "improved": None}
            )
            continue
        imp = _improved(name, b, c)
        if imp is True:
            improved_n += 1
        elif imp is False:
            worsened_n += 1
        metrics.append(
            {"metric": name, "baseline": b, "current": c, "delta": c - b, "improved": imp}
        )

    if improved_n > worsened_n:
        verdict = "improved"
    elif worsened_n > improved_n:
        verdict = "worsened"
    else:
        verdict = "inconclusive"

    comparable = improved_n + worsened_n
    confidence = "high" if comparable >= 4 else "medium" if comparable >= 2 else "low"

    return {
        "verdict": verdict,
        "confidence": confidence,
        "metrics": metrics,
        "missing_data": missing,
    }
