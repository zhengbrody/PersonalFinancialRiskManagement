"""Cross-source agreement — per-field classification between INDEPENDENT sources.

Production reality (2026-07): the fields with two genuinely independent sources
fetched SIMULTANEOUSLY are ``last_price`` and ``market_cap`` (the FactPack merge
always runs the free yfinance enrichment alongside FMP). Statement fields
(revenue / net income / EPS) ride a FALLBACK ladder — when FMP answers, yfinance
statements are never fetched, so only ONE source exists at a time and the honest
status is ``only_one_source``. The machinery below supports all five so the
statement fields light up the moment a second simultaneous source exists.

Rules (enforced here, tested in test_source_agreement.py):
  * a fallback that merely FILLED a null, a cached copy, or a derived value is
    NOT a second independent source — callers only pass values both sources
    actually reported;
  * unit mismatch → ``incomparable`` (never silently converted);
  * statement fields with different fiscal periods (``as_of``) → ``incomparable``;
  * ``disagreement`` LOWERS confidence downstream but never overwrites either
    side's raw value (both observations are preserved verbatim);
  * fewer than two finite values → ``only_one_source`` (never fabricated 100%).

Pure functions, no I/O.
"""

from __future__ import annotations

import math
from typing import Optional

from ..schemas.confidence import AgreementStatus, FieldAgreement, SourceObservation

# Per-field relative tolerance — unit-aware and deliberately field-specific:
#   last_price  2%  — providers snapshot at different times (EOD close vs a
#                     delayed/consolidated quote); intraday drift inside 2% is
#                     quote-timing, not a source conflict
#   market_cap  3%  — share-count vintages differ between providers
#   revenue     2%  — restatements / rounding on the same fiscal period
#   net_income  2%
#   eps         2%  (+ an absolute epsilon for near-zero EPS, below)
FIELD_TOLERANCES: dict[str, float] = {
    "last_price": 0.02,
    "market_cap": 0.03,
    "revenue": 0.02,
    "net_income": 0.02,
    "eps": 0.02,
}

# Honest caveat attached to price disagreements — a big gap USUALLY means a
# source conflict, but quote-timing can contribute; the user sees both values.
_PRICE_DISAGREE_NOTE = "may partly reflect different quote times (EOD vs delayed)"

# Statement fields must be for the SAME fiscal period to be comparable at all.
_PERIOD_SENSITIVE = {"revenue", "net_income", "eps"}

# Near-zero EPS makes relative diffs explode; below this absolute gap two EPS
# figures are treated as exact (one cent — the display precision).
_EPS_ABS_EPSILON = 0.01

# "Exact" = equal after rounding to the field's display precision.
_DISPLAY_DECIMALS: dict[str, int] = {
    "last_price": 2,
    "eps": 2,
    # totals compare at 4 significant figures via the relative path below
}


def _finite(v: Optional[float]) -> bool:
    return v is not None and isinstance(v, (int, float)) and math.isfinite(float(v))


def _rel_diff(a: float, b: float) -> float:
    denom = max(abs(a), abs(b))
    if denom == 0:
        return 0.0
    return abs(a - b) / denom


def compare_field(
    field: str,
    a: SourceObservation,
    b: Optional[SourceObservation],
) -> FieldAgreement:
    """Classify one field's cross-source pair. ``b=None`` → only_one_source."""
    tol = FIELD_TOLERANCES.get(field)
    obs = [o for o in (a, b) if o is not None]

    def out(status: AgreementStatus, *, diff: Optional[float] = None, note: Optional[str] = None):
        return FieldAgreement(
            field=field,
            status=status,
            rel_tolerance=tol,
            observed_rel_diff=(round(diff, 6) if diff is not None else None),
            observations=obs,
            note=note,
        )

    if b is None or not _finite(b.value):
        return out("only_one_source")
    if not _finite(a.value):
        return out("only_one_source", note="primary value missing")
    if tol is None:
        return out("incomparable", note=f"no tolerance defined for field '{field}'")

    # Unit mismatch → incomparable, never silently converted.
    if (a.unit or None) != (b.unit or None):
        return out("incomparable", note=f"units differ ({a.unit or '?'} vs {b.unit or '?'})")

    # Statement fields must describe the SAME fiscal period.
    if field in _PERIOD_SENSITIVE:
        if not a.as_of or not b.as_of:
            return out("incomparable", note="fiscal period unknown for one source")
        if a.as_of[:10] != b.as_of[:10]:
            return out(
                "incomparable",
                note=f"different fiscal periods ({a.as_of[:10]} vs {b.as_of[:10]})",
            )

    av, bv = float(a.value), float(b.value)

    # Exact: equal at display precision (or within the absolute EPS epsilon).
    nd = _DISPLAY_DECIMALS.get(field)
    if nd is not None and round(av, nd) == round(bv, nd):
        return out("exact", diff=_rel_diff(av, bv))
    if field == "eps" and abs(av - bv) <= _EPS_ABS_EPSILON:
        return out("exact", diff=_rel_diff(av, bv))
    if av == bv:
        return out("exact", diff=0.0)

    diff = _rel_diff(av, bv)
    if diff <= tol:
        return out("within_tolerance", diff=diff)
    return out(
        "disagreement",
        diff=diff,
        note=_PRICE_DISAGREE_NOTE if field == "last_price" else None,
    )


def aggregate_agreement(checks: list[FieldAgreement]) -> Optional[float]:
    """The share of COMPARABLE checks that agree (exact | within_tolerance).
    ``None`` when nothing was comparable — 'where available', never fabricated."""
    comparable = [c for c in checks if c.status in ("exact", "within_tolerance", "disagreement")]
    if not comparable:
        return None
    agreeing = sum(1 for c in comparable if c.status in ("exact", "within_tolerance"))
    return round(agreeing / len(comparable), 3)


def disagreement_fields(checks: list[FieldAgreement]) -> list[str]:
    return [c.field for c in checks if c.status == "disagreement"]
