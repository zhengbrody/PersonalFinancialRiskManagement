"""Shared builder + ENFORCEMENT for the unified data-confidence contract.

Two jobs:
  1. Build a ``DataConfidence`` from whatever confidence/provenance a surface
     already computed — mapping, never recomputing (preserves every existing
     calculation). ``source_type_for`` / ``classify_missing_reason`` normalise
     the divergent vocabularies into the shared enums.
  2. Enforce the conclusion-strength rules from a single place
     (``cap_conviction``), so low-quality data can never yield a
     high-conviction directional verdict on ANY surface.

Pure functions, no I/O.
"""

from __future__ import annotations

from typing import Iterable, Optional

from ..schemas.confidence import (
    ConfidenceLabel,
    ConfidenceReason,
    Conviction,
    DataConfidence,
    FieldProvenance,
    MissingReason,
    SourceType,
)
from .providers import registry

# ── label thresholds (one place; each surface still computes its own float) ───
_LABEL_HIGH = 0.75
_LABEL_MED = 0.45

# ── enforcement bands (rule #3, verbatim) ─────────────────────────────────────
CRIT_NO_DIRECTIONAL = 0.40  # under 40% critical coverage → no directional verdict
CRIT_LOW_CAP = 0.70  # 40–70% → conviction cannot exceed Low

_CONVICTION_ORDER: list[Conviction] = ["none", "low", "medium", "high"]
_ROLE_TO_TYPE = {
    registry.PRIMARY: "primary",
    registry.FALLBACK: "secondary",
    registry.COMPUTED: "derived",
}


def source_type_for(source: str) -> SourceType:
    """Registry role → the presentation tier (primary / secondary / derived)."""
    return _ROLE_TO_TYPE.get(registry.describe(source).kind, "derived")  # type: ignore[return-value]


def label_from(confidence: float) -> ConfidenceLabel:
    if confidence >= _LABEL_HIGH:
        return "high"
    if confidence >= _LABEL_MED:
        return "medium"
    return "low"


# Map the scattered provider warning strings → the typed MissingReason enum.
# Order matters (most specific first). Anything unmatched → "empty".
def classify_missing_reason(*signals: Optional[str]) -> MissingReason:
    blob = " ".join(s.lower() for s in signals if s)
    if not blob:
        return "empty"
    if "rate_limit" in blob or "429" in blob:
        return "rate_limited"
    if "key_missing" in blob or "no_key" in blob or "no key" in blob:
        return "no_key"
    if "requires_paid" in blob or "paid_plan" in blob or "starter" in blob or "402" in blob:
        return "unsupported"
    if "insufficient_history" in blob or "history_capped" in blob or "window_limited" in blob:
        return "insufficient_history"
    if "not_fetched" in blob or "not_applicable" in blob or "n/a" in blob:
        return "not_applicable"
    if "stale" in blob:
        return "stale_fallback"
    if "error" in blob or "exception" in blob or "timeout" in blob:
        return "provider_error"
    if "unsupported" in blob:
        return "unsupported"
    return "empty"


def field_provenance(
    field: str,
    source: str,
    *,
    as_of: Optional[str] = None,
    fetched_at: Optional[str] = None,
    stale: bool = False,
    coverage: Optional[float] = None,
    fallback_used: Optional[bool] = None,
    critical: bool = False,
    missing_reason: Optional[MissingReason] = None,
    note: Optional[str] = None,
) -> FieldProvenance:
    """One provenance row with source_type + label auto-filled from the registry.
    ``fallback_used`` defaults to the registry's fallback flag for the source."""
    info = registry.describe(source)
    return FieldProvenance(
        field=field,
        source=info.id,
        source_type=source_type_for(source),
        label=info.label,
        as_of=as_of,
        fetched_at=fetched_at,
        stale=stale,
        coverage=coverage,
        fallback_used=(info.kind == registry.FALLBACK) if fallback_used is None else fallback_used,
        critical=critical,
        missing_reason=missing_reason,
        note=note,
    )


def cross_source_agreement(values: Iterable[float], *, rel_tol: float = 0.02) -> Optional[float]:
    """Agreement in [0,1] between INDEPENDENT sources reporting the same numeric
    field. None when fewer than two finite values (honest 'where available').
    1.0 = identical; decays with the relative spread (max−min)/|mean|."""
    xs = [float(v) for v in values if v is not None]
    finite = [x for x in xs if x == x and abs(x) != float("inf")]
    if len(finite) < 2:
        return None
    mean = sum(finite) / len(finite)
    if mean == 0:
        return 1.0 if max(finite) - min(finite) == 0 else 0.0
    spread = (max(finite) - min(finite)) / abs(mean)
    # spread of 0 → 1.0; spread ≥ (rel_tol*20 = 40%) → 0.0
    return max(0.0, min(1.0, 1.0 - spread / (rel_tol * 20)))


def cap_conviction(
    base: Conviction,
    critical_coverage: float,
    *,
    stale: bool = False,
    missing_critical: bool = False,
) -> tuple[Conviction, bool, list[ConfidenceReason]]:
    """Rule #3 in ONE place. Returns (capped_conviction, directional_allowed,
    reasons).

      * critical_coverage < 40%   → no directional verdict (conviction "none")
      * 40–70%                    → conviction ≤ "low"
      * stale OR missing critical → conviction reduced (≤ "low")

    Never RAISES a conviction — only caps."""
    reasons: list[ConfidenceReason] = []
    idx = _CONVICTION_ORDER.index(base) if base in _CONVICTION_ORDER else len(_CONVICTION_ORDER) - 1
    directional = True

    if critical_coverage < CRIT_NO_DIRECTIONAL:
        directional = False
        idx = 0
        reasons.append(
            ConfidenceReason(
                code="critical_coverage_below_40",
                severity="high",
                detail=(
                    f"Only {critical_coverage:.0%} of the critical inputs are present "
                    "(< 40%) — not enough to support a directional view."
                ),
            )
        )
    elif critical_coverage < CRIT_LOW_CAP:
        idx = min(idx, _CONVICTION_ORDER.index("low"))
        reasons.append(
            ConfidenceReason(
                code="critical_coverage_40_70",
                severity="watch",
                detail=(
                    f"Critical-input coverage is {critical_coverage:.0%} (40–70%) — "
                    "conviction is capped at Low."
                ),
            )
        )

    if stale and idx > _CONVICTION_ORDER.index("low"):
        idx = _CONVICTION_ORDER.index("low")
        reasons.append(
            ConfidenceReason(
                code="stale_critical_data",
                severity="watch",
                detail="Key data is stale — conviction reduced until it refreshes.",
            )
        )
    if missing_critical and idx > _CONVICTION_ORDER.index("low"):
        idx = _CONVICTION_ORDER.index("low")
        reasons.append(
            ConfidenceReason(
                code="missing_critical_data",
                severity="watch",
                detail="A critical dataset is missing — conviction reduced.",
            )
        )

    return _CONVICTION_ORDER[idx], directional, reasons


def default_confidence(
    overall_coverage: float, critical_coverage: float, *, stale: bool, missing_count: int
) -> float:
    """A confidence float for surfaces that don't already compute one (risk
    report, Copilot). Critical coverage is weighted heaviest; stale + missing
    penalise. Surfaces WITH their own float (score, research) pass it in and this
    is not used."""
    score = 0.35 * _clamp01(overall_coverage) + 0.5 * _clamp01(critical_coverage)
    score += 0.15  # baseline for having assembled a response at all
    if stale:
        score -= 0.15
    score -= 0.05 * max(0, missing_count)
    return round(_clamp01(score), 3)


def build_data_confidence(
    *,
    overall_coverage: float,
    critical_coverage: float,
    sources: list[FieldProvenance],
    missing: Optional[list[FieldProvenance]] = None,
    confidence: Optional[float] = None,
    label: Optional[ConfidenceLabel] = None,
    base_conviction: Conviction = "high",
    as_of: Optional[str] = None,
    fetched_at: Optional[str] = None,
    cross_agreement: Optional[float] = None,
    extra_reasons: Optional[list[ConfidenceReason]] = None,
) -> DataConfidence:
    """Assemble the unified block. ``confidence`` is the surface's OWN float when
    it has one (score/research); else a default is derived. Pass ``label`` to use
    the surface's OWN high/med/low label (e.g. the engine's) instead of
    re-bucketing the float — keeps the score page's two badges consistent.
    Applies the conviction cap so every surface enforces rule #3 identically."""
    missing = list(missing or [])
    stale = any(s.stale for s in sources) or any(
        m.missing_reason == "stale_fallback" for m in missing
    )
    stale_critical = any(s.stale and s.critical for s in sources) or any(
        m.critical and m.missing_reason == "stale_fallback" for m in missing
    )
    fallback_used = any(s.fallback_used for s in sources)
    missing_critical = any(m.critical and (m.coverage or 0) < 1.0 for m in missing)

    if confidence is None:
        confidence = default_confidence(
            overall_coverage, critical_coverage, stale=stale, missing_count=len(missing)
        )
    confidence = _clamp01(confidence)

    conviction, directional, cap_reasons = cap_conviction(
        base_conviction,
        critical_coverage,
        stale=stale_critical,
        missing_critical=missing_critical,
    )

    reasons = list(extra_reasons or []) + cap_reasons
    return DataConfidence(
        label=label if label is not None else label_from(confidence),
        confidence=confidence,
        overall_coverage=round(_clamp01(overall_coverage), 3),
        critical_coverage=round(_clamp01(critical_coverage), 3),
        as_of=as_of,
        fetched_at=fetched_at,
        stale=stale,
        fallback_used=fallback_used,
        cross_source_agreement=cross_agreement,
        conviction_cap=conviction,
        directional_allowed=directional,
        sources=sources,
        missing=missing,
        reason_codes=reasons,
    )


def _clamp01(x: float) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0.0
    if v != v:  # NaN
        return 0.0
    return max(0.0, min(1.0, v))
