"""Data confidence scoring for AI outputs.

Every AI digest / chat answer should show *how much we trust the data
underneath it*. This module turns the messy reality (FMP rate-limit,
yfinance gaps, missing cost basis, LLM fallback model) into a single
``Confidence`` enum the UI can render as a pill.

Levels::

    high   — all primary sources fresh, no gaps
    medium — at least one secondary source missing or stale (FMP cap,
             some tickers without cost basis, cached LLM response)
    low    — primary risk data missing (no recent prices, no factor
             model output, LLM call failed and we fell back to a stub)

Public API
----------
- ``compute_confidence(...)`` → dict with ``level``, ``missing[]``,
  ``hints[]``. UI uses ``level`` for the pill, ``hints`` for tooltip.
- ``CONFIDENCE_LEVELS`` — string constants so callers don't typo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

# Public constants — import these rather than typing the strings.
CONFIDENCE_LEVELS = ("high", "medium", "low")

# Highest score wins. Scores accumulate as evidence of degradation.
# A bump of >= 3 collapses confidence one level.
_DOWNGRADE_THRESHOLD = 3
_FLOOR_LEVEL = "low"


@dataclass
class ConfidenceReport:
    level: str
    score: int = 0
    missing: list[str] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "score": self.score,
            "missing": list(self.missing),
            "hints": list(self.hints),
        }


def _add(report: ConfidenceReport, *, weight: int, hint: str, missing: str | None = None) -> None:
    """Add a downgrade signal. ``weight`` is the severity points it
    contributes to the running score."""
    report.score += weight
    report.hints.append(hint)
    if missing:
        report.missing.append(missing)


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and not math.isfinite(value):
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, (list, tuple, set, dict)) and len(value) == 0:
        return True
    return False


def compute_confidence(
    *,
    fmp_ok: bool = True,
    yfinance_missing: Iterable[str] | None = None,
    cost_basis_coverage: Optional[float] = None,
    stale_data: bool = False,
    llm_fallback: bool = False,
    risk_report_present: bool = True,
    extra_signals: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute a UI-ready confidence record.

    All parameters are optional with safe defaults. Pass the signals you
    can measure; the rest are assumed healthy.

    Parameters
    ----------
    fmp_ok:
        ``True`` when FMP API is reachable and not rate-limited.
        ``False`` downgrades the FMP-fed fields (fundamentals, peers,
        institutional ownership).
    yfinance_missing:
        Iterable of tickers we couldn't fetch prices for. Even a single
        missing ticker dings confidence because portfolio weights will
        be subtly off.
    cost_basis_coverage:
        Fraction (0..1) of market value with avg_cost set. < 0.7 is a
        meaningful gap for P&L attribution.
    stale_data:
        ``True`` when the underlying analysis used cached / EOD data
        more than ~1 trading day old.
    llm_fallback:
        ``True`` when the AI digest came from the static fallback path
        (provider down, quota exhausted, etc.).
    risk_report_present:
        ``False`` when we have *no* RiskReport — the AI is generating
        narrative without numbers, so confidence floors to low.
    extra_signals:
        Free-form dict the caller can pass to add custom degradations.
        Recognised keys:
          - ``"factor_model_failed"`` (bool) — heavy downgrade
          - ``"sample_size_short"`` (bool) — light downgrade
    """
    report = ConfidenceReport(level="high")

    # Hard floor: without a RiskReport, everything below is decoration.
    if not risk_report_present:
        report.level = _FLOOR_LEVEL
        report.missing.append("risk_report")
        report.hints.append("No analysis run — confidence is decorative only.")
        return report.to_dict()

    if llm_fallback:
        _add(
            report,
            weight=3,
            hint="AI text came from the local fallback (provider unavailable).",
            missing="llm_provider",
        )

    if not fmp_ok:
        _add(
            report,
            weight=2,
            hint="FMP fundamentals unavailable; valuation context is degraded.",
            missing="fmp",
        )

    if stale_data:
        _add(
            report,
            weight=2,
            hint="Underlying market data is older than one trading day.",
            missing="fresh_prices",
        )

    if yfinance_missing:
        missing_list = [t for t in yfinance_missing if t]
        if missing_list:
            _add(
                report,
                weight=2 if len(missing_list) >= 3 else 1,
                hint=(
                    f"Live prices missing for {len(missing_list)} ticker(s)."
                    if len(missing_list) >= 3
                    else f"Missing live prices: {', '.join(missing_list[:3])}."
                ),
                missing="prices",
            )

    if cost_basis_coverage is not None and math.isfinite(cost_basis_coverage):
        if cost_basis_coverage < 0.4:
            _add(
                report,
                weight=2,
                hint=f"Cost basis covers only {cost_basis_coverage:.0%} of MV.",
                missing="cost_basis",
            )
        elif cost_basis_coverage < 0.7:
            _add(
                report,
                weight=1,
                hint=f"Cost basis covers {cost_basis_coverage:.0%} of MV — partial P&L.",
            )

    if extra_signals and isinstance(extra_signals, dict):
        if extra_signals.get("factor_model_failed"):
            _add(report, weight=2, hint="Factor model did not converge.", missing="factor_model")
        if extra_signals.get("sample_size_short"):
            _add(report, weight=1, hint="Statistics computed on a short window (<6mo).")

    # Bucket the cumulative score into a level. Two thresholds:
    #   < 1*threshold → high
    #   < 2*threshold → medium
    #   else → low
    if report.score >= 2 * _DOWNGRADE_THRESHOLD:
        report.level = "low"
    elif report.score >= _DOWNGRADE_THRESHOLD:
        report.level = "medium"
    else:
        report.level = "high"

    return report.to_dict()


def confidence_from_meta(meta: dict | None, *, llm_fallback: bool = False) -> dict[str, Any]:
    """Convenience wrapper that pulls signals out of ``_portfolio_meta``.

    The Streamlit pages already build this dict during Run Analysis, so
    we can derive most signals automatically without each caller writing
    the same boilerplate.
    """
    meta = meta if isinstance(meta, dict) else {}
    pos_info = meta.get("position_cost_info") or {}
    cost_cov = pos_info.get("coverage_by_mv_pct") if isinstance(pos_info, dict) else None
    missing = meta.get("missing") or []
    quality = meta.get("data_quality") or {}
    return compute_confidence(
        fmp_ok=not bool(quality.get("fmp_unavailable")),
        yfinance_missing=missing,
        cost_basis_coverage=cost_cov,
        stale_data=bool(quality.get("stale")),
        llm_fallback=llm_fallback,
        risk_report_present=bool(meta.get("analysis_ready", True)),
    )
