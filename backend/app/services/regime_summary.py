"""Compose the trained risk-state model + the macro snapshot (VIX / Fear & Greed
/ yield curve) into ONE plain-language readout for the public /risk-today page
and a quotable social ``post_text``.

Deterministic — no LLM touches a number or a label. Reuses the already-cached
``ml_regime`` + ``market_regime`` services (no new data fetch, no paid call).
Fail-soft: if the model is down we still render the macro snapshot; if even that
is down we return an honest "unavailable" headline. Never raises.
"""

from __future__ import annotations

from typing import Optional

from . import market_regime, ml_regime

# Display label + plain-language blurb per risk STATE. Kept in lockstep with the
# frontend STATE map in components/regime-context.tsx (label + blurb wording).
_LABELS: dict[str, tuple[str, str]] = {
    "risk_on": ("Calm", "Volatility is expected to stay low over the next ~2 weeks."),
    "neutral": ("Normal", "Volatility is near its typical range."),
    "volatile": ("Elevated", "Choppier, higher-volatility conditions look more likely."),
    "stress": ("Stressed", "A high-volatility, risk-off environment."),
}

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


def build_summary(ml: dict, snapshot: "market_regime.RegimeSnapshot") -> dict:
    """Pure composition — testable without network. ``ml`` is ml_regime.get_regime()
    output; ``snapshot`` is a market_regime RegimeSnapshot."""
    state = ml.get("regime")
    source = ml.get("source", "unavailable")
    label, blurb = _LABELS.get(state, (None, None)) if state else (None, None)
    conf = ml.get("confidence")
    conf_pct = round(conf * 100) if isinstance(conf, (int, float)) else None

    vix, fg, curve = snapshot.vix, snapshot.fear_greed, snapshot.yield_curve
    macro_clause = _macro_clause(vix, fg, curve)

    # Headline + post_text (deterministic, None-guarded).
    if label:
        headline = f"Market risk-state: {label}"
        lead = headline + (f" ({conf_pct}% confidence)" if conf_pct is not None else "")
    else:
        headline = "Market risk read temporarily unavailable"
        lead = "Market risk read" if not macro_clause else "Today's market snapshot"

    post_parts = [lead + "."]
    if macro_clause:
        post_parts.append(macro_clause + ".")
    if blurb:
        post_parts.append(blurb)
    post_parts.append(f"Context, not advice. {_SITE}")
    post_text = " ".join(post_parts)
    if len(post_text) > 280:
        post_text = post_text[:277].rstrip() + "…"

    return {
        "headline": headline,
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
        "as_of": ml.get("last_updated"),
        "source": source,
        "model_version": ml.get("model_version"),
        "caveat": CAVEAT,
        "post_text": post_text,
    }


def get_regime_summary() -> dict:
    """Compose the cached model + macro services. Never raises — each leg is
    independently fail-soft, so a dead upstream degrades gracefully."""
    try:
        ml = ml_regime.get_regime()
    except Exception:  # noqa: BLE001 - defensive; get_regime already fail-soft
        ml = {"source": "unavailable"}
    try:
        snapshot = market_regime.get_market_regime()
    except Exception:  # noqa: BLE001 - market_regime already fail-soft
        snapshot = market_regime.RegimeSnapshot(
            vix=market_regime.VixState(None, None, None),
            fear_greed=market_regime.FearGreedState(None, None),
            yield_curve=market_regime.YieldCurveState(None, None, None),
        )
    return build_summary(ml, snapshot)
