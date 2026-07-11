"""Compose the trained risk-state model + the macro snapshot (VIX / Fear & Greed
/ yield curve) into ONE plain-language readout for the public /risk-today page
and a quotable social ``post_text``.

Honest framing (matches docs/ml/validation_report.md): the model's validated
skill is a PROBABILITY-RANKING signal, NOT a 4-class classifier (on 4-class
accuracy it loses to a persistence baseline). So the PRIMARY output is the
elevated-risk probability = P(volatile) + P(stress); the 4-class label is only
secondary context. When the model isn't the active tier, the data is stale, or
drift monitoring flags a problem, we DON'T show a probability — we degrade to the
deterministic VIX / Fear & Greed / yield-curve market context.

Deterministic — no LLM touches a number or a label. Reuses the already-cached
``ml_regime`` + ``ml_health`` + ``market_regime`` services (no new data fetch, no
paid call). Never raises.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from . import market_regime, ml_health, ml_regime

# Display label + plain-language blurb per risk STATE. Kept in lockstep with the
# frontend STATE map in components/regime-context.tsx (label + blurb wording).
_LABELS: dict[str, tuple[str, str]] = {
    "risk_on": ("Calm", "Volatility is expected to stay low over the next ~2 weeks."),
    "neutral": ("Normal", "Volatility is near its typical range."),
    "volatile": ("Elevated", "Choppier, higher-volatility conditions look more likely."),
    "stress": ("Stressed", "A high-volatility, risk-off environment."),
}

# Named bands for the elevated-risk probability (documented, deterministic).
# The training-set base rate is ~0.13, so "Low" ≈ at/below the unconditional rate.
_BANDS: list[tuple[float, str]] = [(0.10, "Low"), (0.25, "Moderate"), (0.45, "High")]
_BAND_MAX = "Very high"

# Data older than this many calendar days = stale → degrade (the daily fetch or
# cron likely broke). A normal weekend/holiday gap stays under this.
_STALE_DAYS = 5

# Canonical compliance caveat — MUST stay identical to the frontend
# REGIME_CAVEAT (components/regime-context.tsx). test_regime_summary pins the
# content so the "not advice / not your score" guarantee can't be weakened here.
CAVEAT = (
    "Risk-state only — not a price forecast, not investment advice, "
    "and it does not change your Health Score."
)

_SITE = "mindmarket.app/risk-today"


def _fmt_signed(x: Optional[float], digits: int = 1) -> Optional[str]:
    if x is None:
        return None
    return f"{x:+.{digits}f}"


def _macro_clause(vix, fear_greed, curve) -> str:
    """A compact 'VIX 18.4 (+0.6), curve normal, F&G 55 Greed' clause, omitting
    any leg that's null."""
    bits: list[str] = []
    if vix.current is not None:
        chg = _fmt_signed(vix.change)
        bits.append(f"VIX {vix.current:.1f}" + (f" ({chg})" if chg else ""))
    if curve.status:
        bits.append(f"curve {curve.status.lower()}")
    if fear_greed.score is not None:
        rating = f" {fear_greed.rating}" if fear_greed.rating else ""
        bits.append(f"Fear & Greed {fear_greed.score:.0f}{rating}")
    return ", ".join(bits)


def _elevated_probability(ml: dict) -> Optional[float]:
    """P(elevated risk) = P(volatile) + P(stress), keyed BY NAME (predict_proba
    order is alphabetical, not the label order). Only the model tier carries
    class_probabilities; the heuristic/unavailable tiers return {} → None."""
    cp = ml.get("class_probabilities") or {}
    if not cp:
        return None
    try:
        p = float(cp.get("volatile", 0.0)) + float(cp.get("stress", 0.0))
    except (TypeError, ValueError):
        return None
    return round(max(0.0, min(1.0, p)), 4)


def _band(p: Optional[float]) -> Optional[str]:
    if p is None:
        return None
    for hi, name in _BANDS:
        if p < hi:
            return name
    return _BAND_MAX


def _is_stale(as_of: Optional[str], today: Optional[date]) -> bool:
    if not as_of:
        return True
    try:
        d = datetime.strptime(str(as_of)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return True
    return ((today or date.today()) - d).days > _STALE_DAYS


def build_summary(
    ml: dict,
    snapshot: "market_regime.RegimeSnapshot",
    health: Optional[dict] = None,
    today: Optional[date] = None,
) -> dict:
    """Pure composition — testable without network. ``ml`` is ml_regime.get_regime()
    output; ``snapshot`` is a market_regime RegimeSnapshot; ``health`` is
    ml_health.get_ml_health() (or None to skip the drift gate)."""
    state = ml.get("regime")
    source = ml.get("source", "unavailable")
    label, blurb = _LABELS.get(state, (None, None)) if state else (None, None)
    conf = ml.get("confidence")

    vix, fg, curve = snapshot.vix, snapshot.fear_greed, snapshot.yield_curve
    macro_clause = _macro_clause(vix, fg, curve)

    elevated = _elevated_probability(ml)
    data_as_of = ml.get("last_updated")
    health = health or {}
    health_serving = health.get("status")  # ok | not_ready | unavailable | None
    health_overall = health.get("overall_status")  # healthy | watch | drift | None
    stale = _is_stale(data_as_of, today)

    # Show the probability ONLY when the model tier is active, the data is fresh,
    # and drift monitoring is healthy. Otherwise degrade to market context.
    is_model = source == "model" and elevated is not None
    show_probability = (
        is_model and not stale and health_serving == "ok" and health_overall != "drift"
    )
    degraded = not show_probability

    degraded_reason: Optional[str] = None
    if degraded:
        if not is_model:
            degraded_reason = "model_unavailable"
        elif stale:
            degraded_reason = "stale_data"
        elif health_overall == "drift":
            degraded_reason = "model_drift"
        elif health_serving != "ok":
            degraded_reason = f"health_{health_serving or 'unknown'}"
        else:
            degraded_reason = "unavailable"

    prob_band = _band(elevated) if show_probability else None
    prob_pct = round(elevated * 100) if show_probability and elevated is not None else None

    # Headline + post_text (deterministic, None-guarded, probability-first).
    if show_probability:
        headline = f"Elevated-risk probability: {prob_pct}%"
        post_parts = [f"Elevated-risk probability {prob_pct}% ({prob_band})."]
        if macro_clause:
            post_parts.append(macro_clause + ".")
        post_parts.append("Experimental probability signal — not a price or return forecast.")
    elif macro_clause:
        headline = "Today's market snapshot"
        post_parts = [
            f"Market snapshot: {macro_clause}.",
            "Model probability signal unavailable — showing deterministic market data only.",
        ]
    else:
        headline = "Market read temporarily unavailable"
        post_parts = ["Market read temporarily unavailable."]

    post_parts.append(f"Context, not advice. {_SITE}")
    post_text = " ".join(post_parts)
    if len(post_text) > 280:
        post_text = post_text[:277].rstrip() + "…"

    return {
        "headline": headline,
        # Primary (validated) signal:
        "elevated_risk_probability": elevated if show_probability else None,
        "probability_band": prob_band,
        # Secondary (context-only) 4-class read:
        "regime_state": state,
        "label": label,
        "blurb": blurb,
        "confidence": conf,
        "drivers": [
            {"label": d.get("label", ""), "vs_normal": d.get("vs_normal", "")}
            for d in (ml.get("top_drivers") or [])
            if d.get("label")
        ],
        "vix": {"current": vix.current, "change": vix.change, "level": vix.level},
        "fear_greed": {"score": fg.score, "rating": fg.rating},
        "curve": {
            "status": curve.status,
            "spread_3m_10y": curve.spread_3m_10y,
            "inverted": curve.inverted,
        },
        "as_of": data_as_of,
        "source": source,
        "model_version": ml.get("model_version"),
        "health_status": health_overall,
        "degraded": degraded,
        "degraded_reason": degraded_reason,
        "caveat": CAVEAT,
        "post_text": post_text,
    }


def get_regime_summary() -> dict:
    """Compose the cached model + drift-health + macro services. Never raises —
    each leg is independently fail-soft, so a dead upstream degrades gracefully.
    ml_health shares ml_regime's cached serving frame, so there's no extra fetch."""
    try:
        ml = ml_regime.get_regime()
    except Exception:  # noqa: BLE001 - defensive; get_regime already fail-soft
        ml = {"source": "unavailable"}
    try:
        health = ml_health.get_ml_health()
    except Exception:  # noqa: BLE001 - ml_health already fail-soft
        health = {}
    try:
        snapshot = market_regime.get_market_regime()
    except Exception:  # noqa: BLE001 - market_regime already fail-soft
        snapshot = market_regime.RegimeSnapshot(
            vix=market_regime.VixState(None, None, None),
            fear_greed=market_regime.FearGreedState(None, None),
            yield_curve=market_regime.YieldCurveState(None, None, None),
        )
    return build_summary(ml, snapshot, health)
