"""One resolver for the risk profile used by signed-in product surfaces.

Only an explicitly confirmed ``copilot_preferences.risk_tolerance`` is durable
truth.  Missing/unconfirmed storage resolves to the neutral baseline (3), while
an explicit request override is kept distinct and applies to that request only.
No preference is inferred from holdings, conversations, or behaviour.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal, Optional

from libs.mindmarket_core.portfolio_scoring import RISK_TARGETS

PreferenceSource = Literal["confirmed", "neutral_baseline", "request_override"]


@dataclass(frozen=True)
class ResolvedRiskPreference:
    value: int
    source: PreferenceSource
    confirmed_at: Optional[str] = None

    @property
    def cache_key(self) -> str:
        """Stable discriminator for caches whose output depends on preference."""
        return f"{self.source}:{self.value}:{self.confirmed_at or '-'}"


def resolve_risk_preference(
    user: Any,
    explicit_override: Optional[int] = None,
) -> ResolvedRiskPreference:
    """Resolve request override → confirmed row → neutral baseline, in order."""
    if explicit_override is not None:
        value = int(explicit_override)
        if not 1 <= value <= 5:
            raise ValueError("risk_preference must be between 1 and 5")
        return ResolvedRiskPreference(value=value, source="request_override")

    from . import copilot_preferences

    row = copilot_preferences.get_confirmed_strict(
        getattr(user, "access_token", None), getattr(user, "id", None)
    )
    raw = (row or {}).get("risk_tolerance")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = None
    if row and value is not None and 1 <= value <= 5:
        return ResolvedRiskPreference(
            value=value,
            source="confirmed",
            confirmed_at=str(row.get("confirmed_at") or "") or None,
        )
    return ResolvedRiskPreference(value=3, source="neutral_baseline")


def build_risk_fit(score: Any, data_confidence: Any = None) -> dict[str, Any]:
    """Interpret measured vol/beta against the score's selected target.

    The ±0.20 band uses the same normalized 65% volatility / 35% beta gap
    already used by the score's Risk Match dimension.  When confidence blocks
    directional conclusions, no signed interpretation is emitted.
    """
    preference = max(1, min(5, int(getattr(score, "risk_preference", 3) or 3)))
    target = RISK_TARGETS[preference]
    target_label = str(target["label"])

    directional_allowed = None
    if isinstance(data_confidence, dict):
        directional_allowed = data_confidence.get("directional_allowed")
    elif data_confidence is not None:
        directional_allowed = getattr(data_confidence, "directional_allowed", None)
    if directional_allowed is False:
        return {
            "status": "unavailable",
            "signed_gap": None,
            "target_label": target_label,
            "reason_codes": ["data_confidence_blocks_direction"],
        }

    metrics = getattr(score, "metrics", None)
    annual_vol = _finite(getattr(metrics, "annual_volatility", None))
    beta = _finite(getattr(metrics, "beta_to_benchmark", None))
    if annual_vol is None:
        return {
            "status": "unavailable",
            "signed_gap": None,
            "target_label": target_label,
            "reason_codes": ["missing_annual_volatility"],
        }

    target_vol = float(target["annual_volatility"])
    target_beta = float(target["beta"])
    vol_gap = (annual_vol - target_vol) / (target_vol * 0.75 + 0.02)
    reasons: list[str] = []
    if beta is None:
        signed_gap = vol_gap
        reasons.append("missing_beta")
    else:
        beta_gap = (beta - target_beta) / (target_beta * 0.65 + 0.25)
        signed_gap = 0.65 * vol_gap + 0.35 * beta_gap

    if signed_gap > 0.20:
        status = "above"
        reasons.append("risk_above_target")
    elif signed_gap < -0.20:
        status = "below"
        reasons.append("risk_below_target")
    else:
        status = "aligned"
        reasons.append("risk_aligned_with_target")
    return {
        "status": status,
        "signed_gap": round(float(signed_gap), 4),
        "target_label": target_label,
        "reason_codes": reasons,
    }


def _finite(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
