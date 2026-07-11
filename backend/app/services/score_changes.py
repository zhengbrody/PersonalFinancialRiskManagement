"""Deterministic score-change attribution — the "what changed?" engine.

Given the user's CURRENT (live) score and their OWN prior snapshot, decompose the
score move into per-dimension contributions, input-metric changes, a ranked
driver list, data-quality changes, and a holdings diff — all in pure Python. The
score is a deterministic function of the dimension scores, so the overall delta
decomposes EXACTLY into ``weight × Δdimension × 1000/9`` per dimension; we rank by
that. An LLM may phrase the ``summary``; it must never invent a driver.
"""

from __future__ import annotations

import math
from typing import Any, Optional

from libs.mindmarket_core.score_version import SCORE_VERSION, is_comparable

from ..schemas.score_changes import (
    ComponentDelta,
    DataQualityChange,
    DriverChange,
    HoldingsChange,
    InputChange,
    ScoreChangeReport,
    ScoreChangeRequest,
)

_DIM_WEIGHTS = {"risk_match": 0.35, "risk_adjusted_return": 0.35, "downside_protection": 0.30}
_DIM_NAMES = {
    "risk_match": "Risk Match",
    "risk_adjusted_return": "Risk-adjusted Return",
    "downside_protection": "Downside Protection",
}
_PTS_PER_DIM_POINT = 1000.0 / 9.0  # one 0..10 dimension point → this many overall pts (× weight)

# (key, label, unit) for the headline input metrics we attribute.
_INPUT_SPECS = [
    ("annual_volatility", "Annualized volatility", "pct"),
    ("sharpe_ratio", "Sharpe ratio", "ratio"),
    ("max_drawdown", "Max drawdown", "pct"),
    ("var_95_daily", "Daily VaR (95%)", "pct"),
    ("beta_to_benchmark", "Beta to market", "ratio"),
    ("net_equity", "Net equity", "usd"),
    ("leverage", "Leverage", "x"),
]


def _finite(v: Any) -> Optional[float]:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def _direction(delta: Optional[float], eps: float = 1e-9) -> str:
    if delta is None:
        return ""
    if delta > eps:
        return "up"
    if delta < -eps:
        return "down"
    return "flat"


def _prev_metric(prev_rm: dict, prev_row: dict, key: str) -> Optional[float]:
    """Prior value of a metric: prefer risk_metrics, fall back to the numeric
    snapshot columns (net_equity / leverage live there too)."""
    val = _finite(prev_rm.get(key))
    if val is None and key in ("net_equity", "leverage", "contributed_capital"):
        val = _finite(prev_row.get(key))
    return val


def _holdings_diff(current: list[dict], previous: list[dict]) -> HoldingsChange:
    """Added / removed / reweighted from the top-positions lists. Fail-soft."""

    def _wmap(rows: list[dict]) -> dict[str, float]:
        out: dict[str, float] = {}
        for r in rows or []:
            tk = str((r or {}).get("ticker") or "").upper()
            w = _finite((r or {}).get("weight"))
            if tk and w is not None:
                out[tk] = w
        return out

    cur = _wmap(current)
    prev = _wmap(previous)
    if not cur and not prev:
        return HoldingsChange()
    added = sorted(set(cur) - set(prev))
    removed = sorted(set(prev) - set(cur))
    reweighted = []
    for tk in sorted(set(cur) & set(prev)):
        d = cur[tk] - prev[tk]
        if abs(d) >= 0.02:  # ≥2 percentage points of weight
            reweighted.append(
                {
                    "ticker": tk,
                    "previous": round(prev[tk], 4),
                    "current": round(cur[tk], 4),
                    "delta": round(d, 4),
                }
            )
    reweighted.sort(key=lambda r: abs(r["delta"]), reverse=True)
    return HoldingsChange(added=added, removed=removed, reweighted=reweighted)


def _summarize(
    score_delta: Optional[int],
    as_of: Optional[str],
    drivers: list[DriverChange],
    dq_changes: list[DataQualityChange],
) -> str:
    """One deterministic sentence — no LLM."""
    if score_delta is None:
        return "No earlier snapshot to compare against yet."
    when = f" since {str(as_of)[:10]}" if as_of else ""
    if score_delta == 0:
        base = f"Health score is unchanged{when}."
    else:
        verb = "rose" if score_delta > 0 else "fell"
        base = f"Health score {verb} {abs(score_delta)} pts{when}"
        if drivers:
            d = drivers[0]
            base += f", mostly {d.label} ({d.points:+d} pts)"
            if d.detail:
                base += f" — {d.detail}"
        base += "."
    if dq_changes:
        base += " " + dq_changes[0].note
    return base


def _methodology_changed_summary(prev_version: Any, as_of: Optional[str]) -> str:
    """Deterministic notice when the two snapshots use different methodologies."""
    when = f" (snapshot from {str(as_of)[:10]})" if as_of else ""
    prev = str(prev_version or "unknown")
    return (
        f"Methodology changed since your earlier score{when}: it was computed under "
        f"{prev}, this one under {SCORE_VERSION}. The score change is not directly "
        "comparable — it doesn't isolate a market or holdings move."
    )


def build_change_report(
    req: ScoreChangeRequest, prev_snapshot: Optional[dict]
) -> ScoreChangeReport:
    window = req.window if req.window in ("previous", "7d", "30d") else "previous"
    cur_overall = int(req.overall_score)
    prev_rm = (prev_snapshot or {}).get("risk_metrics") or {}
    prev_overall = prev_rm.get("overall_score")
    available = bool(prev_snapshot) and prev_overall is not None

    if not available:
        return ScoreChangeReport(
            window=window,
            available=False,
            current_score=cur_overall,
            current_score_version=SCORE_VERSION,
            summary="No earlier snapshot in this window yet — scores accrue over time.",
        )

    prev_overall = int(prev_overall)
    as_of = (prev_snapshot or {}).get("created_at")

    # ── Methodology-version gate ──
    # If the prior snapshot was produced by a DIFFERENT methodology version, the
    # move is not a market/holdings change — it's (partly) a rules change. Refuse
    # to express a comparable delta or decompose it; surface a clear notice.
    prev_version = (prev_snapshot or {}).get("score_version")
    if not is_comparable(prev_version, SCORE_VERSION):
        return ScoreChangeReport(
            window=window,
            available=True,
            as_of_previous=as_of,
            current_score=cur_overall,
            previous_score=prev_overall,
            score_delta=None,  # not a directly comparable delta
            current_score_version=SCORE_VERSION,
            previous_score_version=str(prev_version) if prev_version else None,
            comparable=False,
            summary=_methodology_changed_summary(prev_version, as_of),
        )

    score_delta = cur_overall - prev_overall

    # ── Component deltas (exact decomposition of the score move) ──
    prev_dims = prev_rm.get("dimensions") or {}
    component_deltas: list[ComponentDelta] = []
    drivers: list[DriverChange] = []
    for k in _DIM_WEIGHTS:
        cur_s = _finite(req.dimensions.get(k))
        prev_s = _finite(prev_dims.get(k))
        if cur_s is None or prev_s is None:
            component_deltas.append(
                ComponentDelta(key=k, name=_DIM_NAMES[k], current=cur_s, previous=prev_s)
            )
            continue
        d = cur_s - prev_s
        pts = int(round(_DIM_WEIGHTS[k] * d * _PTS_PER_DIM_POINT))
        component_deltas.append(
            ComponentDelta(
                key=k,
                name=_DIM_NAMES[k],
                current=round(cur_s, 1),
                previous=round(prev_s, 1),
                delta=round(d, 1),
                points_contribution=pts,
            )
        )
        if abs(pts) >= 1:
            drivers.append(
                DriverChange(
                    key=k,
                    label=_DIM_NAMES[k],
                    points=pts,
                    detail=f"{_DIM_NAMES[k]} {prev_s:.1f} → {cur_s:.1f}/10",
                )
            )

    # ── Input-metric changes ──
    input_changes: list[InputChange] = []
    for key, label, unit in _INPUT_SPECS:
        cur_v = _finite(req.metrics.get(key))
        prev_v = _prev_metric(prev_rm, prev_snapshot or {}, key)
        if cur_v is None and prev_v is None:
            continue
        delta = (cur_v - prev_v) if (cur_v is not None and prev_v is not None) else None
        input_changes.append(
            InputChange(
                key=key,
                label=label,
                previous=prev_v,
                current=cur_v,
                delta=(round(delta, 6) if delta is not None else None),
                unit=unit,
                direction=_direction(delta),
            )
        )

    # ── Data-quality changes ──
    prev_dq = (prev_snapshot or {}).get("data_quality") or {}
    dq_changes: list[DataQualityChange] = []
    cur_conf = req.confidence
    prev_conf = prev_dq.get("confidence") or prev_rm.get("confidence")
    if cur_conf and prev_conf and cur_conf != prev_conf:
        worsened = (
            ["high", "medium", "low"].index(cur_conf) > ["high", "medium", "low"].index(prev_conf)
            if cur_conf in ("high", "medium", "low") and prev_conf in ("high", "medium", "low")
            else None
        )
        note = f"Data confidence changed {prev_conf} → {cur_conf}" + (
            " — the score is more stabilized; verify your holdings/prices." if worsened else "."
        )
        dq_changes.append(
            DataQualityChange(
                key="confidence",
                label="Data confidence",
                previous=prev_conf,
                current=cur_conf,
                note=note,
            )
        )
    cur_dropped = set(t.upper() for t in (req.dropped_tickers or []))
    prev_dropped = set(str(t).upper() for t in (prev_dq.get("dropped_tickers") or []))
    newly_dropped = sorted(cur_dropped - prev_dropped)
    if newly_dropped:
        dq_changes.append(
            DataQualityChange(
                key="missing_prices",
                label="Missing price data",
                previous=", ".join(sorted(prev_dropped)) or None,
                current=", ".join(sorted(cur_dropped)) or None,
                note="Now missing price history: " + ", ".join(newly_dropped) + ".",
            )
        )

    # ── Holdings diff (optional — only when the client passed top_positions) ──
    holdings = _holdings_diff(req.top_positions, (prev_snapshot or {}).get("top_positions") or [])

    # ── Rank drivers (component contributions, biggest |points| first) ──
    drivers.sort(key=lambda x: abs(x.points), reverse=True)

    base_score_delta = None
    cur_base = req.base_overall if req.base_overall is not None else cur_overall
    prev_base = prev_rm.get("base_overall")
    if prev_base is not None:
        base_score_delta = int(cur_base) - int(prev_base)

    return ScoreChangeReport(
        window=window,
        available=True,
        as_of_previous=as_of,
        current_score=cur_overall,
        previous_score=prev_overall,
        score_delta=score_delta,
        base_score_delta=base_score_delta,
        component_deltas=component_deltas,
        input_changes=input_changes,
        top_drivers=drivers,
        data_quality_changes=dq_changes,
        holdings_changes=holdings,
        summary=_summarize(score_delta, as_of, drivers, dq_changes),
        current_score_version=SCORE_VERSION,
        previous_score_version=str(prev_version) if prev_version else None,
        comparable=True,
    )
