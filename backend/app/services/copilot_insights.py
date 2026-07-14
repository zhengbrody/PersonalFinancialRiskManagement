"""Deterministic proactive insights (Copilot PR4).

Generated from the user's OWN snapshots + live score, the cached market/ML
regime, and the score's data-quality read. Design rules:

  * MATERIALITY: every kind has an explicit threshold below which nothing is
    emitted — day-to-day noise never becomes an insight.
  * DEDUP + COOLDOWN: at most ONE insight per kind per response; ids are
    STABLE for the underlying episode (a change insight is keyed to the prior
    snapshot it was measured against; a state insight to the state itself), so
    a client-side dismissal survives while the episode persists and the same
    condition can't re-fire as a "new" card every request.
  * DIRECTIONAL GATE: when the score's own data quality is under the shared
    no-directional floor, only the data-quality insight is emitted.
  * NO ADVICE: deterministic templates only — no BUY/SELL, no price targets,
    no trade instructions; the next step is always an ANALYSIS surface.
  * FAIL-SOFT: every leg is safe()-wrapped; a data hiccup thins the list,
    never 500s.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ..schemas.copilot2 import EvidenceItem
from ..schemas.copilot_insights import InsightNextAnalysis, InsightOut, InsightsOut
from ._common import iso_now, safe
from .confidence import CRIT_NO_DIRECTIONAL

_log = logging.getLogger(__name__)

# ── materiality thresholds (one place; weight-based concentration aligns with
#    the risk cockpit's ">25% single name" convention, leverage with
#    risk_alerts' moderate band) ────────────────────────────────────────────
SCORE_MOVE_MIN_PTS = 25
DIMENSION_DRAG_MIN_PTS = 8
CONCENTRATION_LIMIT = 0.25
LEVERAGE_LIMIT = 1.5
_REGIME_STATES = ("volatile", "stress")
_REGIME_BETA_MIN = 1.0

_MAX_INSIGHTS = 5
_SEV_ORDER = {"high": 0, "watch": 1, "info": 2}


def _ev(label: str, value: Any, source: str, tool: str) -> Optional[EvidenceItem]:
    if value is None:
        return None
    from .confidence import source_type_for

    return EvidenceItem(
        label=label,
        value=str(value),
        source=source,
        source_type=source_type_for(source),
        tool=tool,
    )


def _with_ids(items: list[Optional[EvidenceItem]]) -> list[EvidenceItem]:
    out = [e for e in items if e is not None]
    for i, e in enumerate(out):
        e.id = f"E{i + 1}"
    return out


def _day(iso: Optional[str]) -> str:
    return str(iso or "")[:10] or "unknown"


def build_insights(user) -> InsightsOut:
    """All material insights for the caller, deterministic and advice-free."""
    now = iso_now()
    sp = safe("insights.score", lambda: _load(user))
    if sp is None:
        return InsightsOut(
            insights=[],
            as_of=now,
            portfolio_available=False,
            missing_data=["no active portfolio (or the portfolio could not be scored)"],
        )
    positions, score = sp
    m = score.metrics
    quality = _finite(getattr(m, "data_quality", None))
    confidence = getattr(m, "confidence", None)

    # ── directional gate: thin data → ONLY the data-quality insight ──
    if quality is not None and quality < CRIT_NO_DIRECTIONAL:
        return InsightsOut(
            insights=[_data_quality_insight(score, now)],
            as_of=now,
            portfolio_available=True,
        )

    insights: list[InsightOut] = []
    prev = safe(
        "insights.prev_snapshot",
        lambda: _snapshot(user, "previous"),
    )
    rep = safe("insights.change_report", lambda: _change_report(score, positions, prev))

    add = insights.append
    ins = safe("insights.score_move", lambda: _score_move_insight(rep, confidence, now))
    if ins:
        add(ins)
    ins = safe("insights.dimension", lambda: _dimension_insight(rep, confidence, now))
    if ins:
        add(ins)
    ins = safe(
        "insights.concentration",
        lambda: _concentration_insight(score, prev, confidence, now),
    )
    if ins:
        add(ins)
    ins = safe("insights.leverage", lambda: _leverage_insight(m, prev, confidence, now))
    if ins:
        add(ins)
    ins = safe("insights.regime", lambda: _regime_insight(m, confidence, now))
    if ins:
        add(ins)

    insights.sort(key=lambda i: _SEV_ORDER.get(i.severity, 9))
    return InsightsOut(insights=insights[:_MAX_INSIGHTS], as_of=now, portfolio_available=True)


# ── loaders (seams for tests) ─────────────────────────────────────────


def _load(user):
    from .copilot_context import load_positions_and_score

    positions, score = load_positions_and_score(user)
    return list(positions), score


def _snapshot(user, window: str) -> Optional[dict]:
    from . import snapshots

    return snapshots.get_snapshot_at_window(getattr(user, "access_token", None), window)


def _change_report(score, positions, prev):
    if not prev:
        return None
    from .score_changes import build_change_report, request_from_score

    rep = build_change_report(request_from_score(score, positions), prev)
    return rep if rep.available and rep.comparable is not False else None


# ── individual insight builders (each returns None below materiality) ─


def _score_move_insight(rep, confidence, now) -> Optional[InsightOut]:
    if rep is None or rep.score_delta is None or abs(rep.score_delta) < SCORE_MOVE_MIN_PTS:
        return None
    delta = int(rep.score_delta)
    a = rep.attribution
    parts: list[Optional[EvidenceItem]] = [
        _ev(
            "Health-score change (since last snapshot)", f"{delta:+d} pts", "engine", "score_change"
        )
    ]
    why = "A move this size is beyond day-to-day noise."
    missing: list[str] = []
    if a is not None and a.separable:
        parts += [
            _ev("Market-driven", f"{a.market_driven:+d} pts", "engine", "score_change"),
            _ev("Holdings-driven", f"{a.holding_driven:+d} pts", "engine", "score_change"),
            _ev("Data-quality-driven", f"{a.data_quality_driven:+d} pts", "engine", "score_change"),
        ]
        why = (
            "A move this size is beyond day-to-day noise; the split above shows "
            "how much came from the market versus your own changes."
        )
    elif a is not None:
        parts.append(
            _ev(
                "Market + your changes (combined)",
                f"{a.combined_market_holdings:+d} pts",
                "engine",
                "score_change",
            )
        )
        missing.append("market vs holdings split not separable on a trade day")
    return InsightOut(
        # Keyed to the PRIOR snapshot the move was measured against — the id is
        # stable for the whole day this comparison holds (cooldown/dedup).
        id=f"score_move:{_day(getattr(rep, 'as_of_previous', None) or now)}:{'down' if delta < 0 else 'up'}",
        kind="score_move",
        severity="high" if abs(delta) >= 2 * SCORE_MOVE_MIN_PTS else "watch",
        what_changed=f"Your portfolio health score moved {delta:+d} points since your last snapshot.",
        why_it_matters=why,
        evidence=_with_ids(parts),
        confidence=confidence,
        as_of=now,
        missing_data=missing,
        suggested_next_analysis=InsightNextAnalysis(
            label="Open the What-changed breakdown", href="/score"
        ),
    )


def _dimension_insight(rep, confidence, now) -> Optional[InsightOut]:
    d = getattr(rep, "top_negative_contributor", None) if rep is not None else None
    if d is None or d.points is None or d.points > -DIMENSION_DRAG_MIN_PTS:
        return None
    return InsightOut(
        id=f"dimension_drag:{d.label}:{_day(now)}",
        kind="dimension_drag",
        severity="watch",
        what_changed=f"{d.label} is the biggest drag on your score since the last snapshot.",
        why_it_matters=(
            "One dimension moving alone usually points at a specific cause "
            "(volatility, drawdown or risk fit) rather than a broad market move."
        ),
        evidence=_with_ids(
            [_ev(f"{d.label} contribution", f"{d.points:+d} pts", "engine", "score_change")]
        ),
        confidence=confidence,
        as_of=now,
        suggested_next_analysis=InsightNextAnalysis(
            label="Inspect the score drivers", href="/score"
        ),
    )


def _concentration_insight(score, prev, confidence, now) -> Optional[InsightOut]:
    conc = getattr(score, "concentration", None)
    cur = _finite(getattr(conc, "top_holding_weight", None)) if conc is not None else None
    if cur is None or cur <= CONCENTRATION_LIMIT:
        return None
    prev_conc = ((prev or {}).get("risk_metrics") or {}).get("concentration") or {}
    prev_w = _finite(prev_conc.get("top_holding_weight"))
    missing: list[str] = []
    if prev_w is not None and prev_w > CONCENTRATION_LIMIT:
        # Not a CROSSING — the state persisted; same episode id keeps the
        # card deduped/dismissable rather than re-firing as new.
        pass
    elif prev_w is None:
        missing.append("no prior snapshot to compare against")
    ticker = getattr(conc, "top_holding_ticker", None) or "your largest holding"
    evidence = _with_ids(
        [
            _ev("Largest position weight", f"{cur * 100:.1f}%", "engine", "concentration"),
            _ev("Largest position", str(ticker), "engine", "concentration"),
            (
                _ev("Prior snapshot weight", f"{prev_w * 100:.1f}%", "engine", "concentration")
                if prev_w is not None
                else None
            ),
        ]
    )
    return InsightOut(
        id=f"concentration:{ticker}",
        kind="concentration",
        severity="high" if cur >= 0.40 else "watch",
        what_changed=(
            f"A single position is {cur * 100:.1f}% of your book"
            + (
                f" (was {prev_w * 100:.1f}% at the prior snapshot)."
                if prev_w is not None and abs(cur - prev_w) >= 0.02
                else "."
            )
        ),
        why_it_matters=(
            "Above the one-quarter-of-book line, one name's bad day moves your "
            "whole portfolio more than diversification can absorb."
        ),
        evidence=evidence,
        confidence=confidence,
        as_of=now,
        missing_data=missing,
        suggested_next_analysis=InsightNextAnalysis(
            label="Review concentration in the Risk Report", href="/risk"
        ),
    )


def _leverage_insight(m, prev, confidence, now) -> Optional[InsightOut]:
    lev = _finite(getattr(m, "leverage", None))
    if lev is None or lev <= LEVERAGE_LIMIT:
        return None
    prev_lev = _finite(((prev or {}).get("risk_metrics") or {}).get("leverage"))
    missing = [] if prev_lev is not None else ["no prior snapshot to compare against"]
    return InsightOut(
        id="leverage:elevated",
        kind="leverage",
        severity="high" if lev >= 2.0 else "watch",
        what_changed=f"Your margin leverage is {lev:.2f}× (above the {LEVERAGE_LIMIT:.1f}× watch line).",
        why_it_matters=(
            "Leverage scales every loss before it reaches your equity — "
            "drawdowns and VaR grow faster than the market move itself."
        ),
        evidence=_with_ids(
            [
                _ev("Current leverage", f"{lev:.2f}×", "engine", "portfolio_score"),
                (
                    _ev("Prior snapshot leverage", f"{prev_lev:.2f}×", "engine", "portfolio_score")
                    if prev_lev is not None
                    else None
                ),
            ]
        ),
        confidence=confidence,
        as_of=now,
        missing_data=missing,
        suggested_next_analysis=InsightNextAnalysis(
            label="Stress the levered book in Scenarios", href="/scenarios"
        ),
    )


def _regime_insight(m, confidence, now) -> Optional[InsightOut]:
    beta = _finite(getattr(m, "beta_to_benchmark", None))
    if beta is None or beta < _REGIME_BETA_MIN:
        return None
    from . import ml_regime

    reg = ml_regime.get_regime()
    state = (reg or {}).get("regime")
    if state not in _REGIME_STATES:
        return None
    conf = (reg or {}).get("confidence")
    return InsightOut(
        id=f"market_regime:{state}",
        kind="market_regime",
        severity="watch",
        what_changed=f"The market risk-state model reads '{state}' and your portfolio moves with the market (beta above one).",
        why_it_matters=(
            "In an elevated risk-state, a beta-above-one book swings harder than "
            "the index — worth knowing before the next big market day."
        ),
        evidence=_with_ids(
            [
                _ev("Model risk-state", str(state), "engine", "ml_regime"),
                (
                    _ev("Model confidence", f"{float(conf):.2f}", "engine", "ml_regime")
                    if _finite(conf) is not None
                    else None
                ),
                _ev("Your beta to market", f"{beta:.2f}", "engine", "portfolio_score"),
            ]
        ),
        confidence=confidence,
        as_of=now,
        missing_data=[],
        suggested_next_analysis=InsightNextAnalysis(
            label="See the regime detail on Markets", href="/markets"
        ),
    )


def _data_quality_insight(score, now) -> InsightOut:
    m = score.metrics
    reasons = [str(r) for r in (getattr(m, "reason_codes", None) or [])][:4]
    return InsightOut(
        id=f"data_quality:{_day(now)}",
        kind="data_quality",
        severity="watch",
        what_changed="The data behind your score is too thin for directional insights right now.",
        why_it_matters=(
            "Missing prices or short history make every derived risk number "
            "less reliable — fixing the data comes before reading the metrics."
        ),
        evidence=_with_ids(
            [
                _ev(
                    "Data confidence",
                    str(getattr(m, "confidence", None)),
                    "engine",
                    "portfolio_score",
                ),
                (
                    _ev("Reason codes", ", ".join(reasons), "engine", "portfolio_score")
                    if reasons
                    else None
                ),
            ]
        ),
        confidence=getattr(m, "confidence", None),
        as_of=now,
        missing_data=reasons or ["data quality below the directional floor"],
        suggested_next_analysis=InsightNextAnalysis(
            label="Check the data-confidence panel on your score", href="/score"
        ),
    )


def _finite(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x == x and abs(x) != float("inf") else None
