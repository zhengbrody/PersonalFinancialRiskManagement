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

from libs.mindmarket_core.score_version import (
    LEGACY_SCORE_VERSION,
    SCORE_VERSION,
    is_comparable,
)

from ..schemas.score_changes import (
    ChangeAttribution,
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


def _is_unknown_version(v: Any) -> bool:
    """A missing / legacy version means the earlier snapshot predates version
    stamping — its methodology is UNVERIFIABLE, not provably different."""
    s = str(v or "").strip()
    return not s or s == LEGACY_SCORE_VERSION


def _methodology_changed_summary(prev_version: Any, as_of: Optional[str]) -> str:
    """Deterministic notice when the two snapshots aren't directly comparable.

    Distinguishes an UNKNOWN prior methodology (a pre-versioning 'legacy'
    snapshot — we must NOT claim the calculation changed, because it may not
    have) from a genuine version change (two different known versions)."""
    when = f" (from {str(as_of)[:10]})" if as_of else ""
    if _is_unknown_version(prev_version):
        return (
            f"Your earlier score{when} predates methodology versioning, so we can't verify it "
            "used the current rules — the two aren't directly comparable. Once you have two "
            "scores under the same version, the trend will decompose normally."
        )
    return (
        f"Methodology changed since your earlier score{when}: it was computed under "
        f"{prev_version}, this one under {SCORE_VERSION}. The score change isn't directly "
        "comparable — it doesn't isolate a market or holdings move."
    )


def _preference_changed_summary(
    current: Optional[int], previous: Optional[int], as_of: Optional[str]
) -> str:
    when = f" (from {str(as_of)[:10]})" if as_of else ""
    if current is None or previous is None:
        return (
            f"Your earlier score{when} does not record the same risk profile context, so the "
            "two scores are not directly comparable. This score establishes a new baseline."
        )
    return (
        f"Risk profile changed from {previous} to {current} since your earlier score{when}. "
        "The scores are not directly comparable because the target changed, not necessarily "
        "the portfolio."
    )


def _top_contributors(
    deltas: list[ComponentDelta],
) -> tuple[Optional[DriverChange], Optional[DriverChange]]:
    """Single biggest positive / negative dimension contributor to the move
    (by signed points). None on that side when nothing moved it that way."""
    pos: Optional[ComponentDelta] = None
    neg: Optional[ComponentDelta] = None
    for d in deltas:
        pts = d.points_contribution
        if pts is None or pts == 0:
            continue
        if pts > 0 and (pos is None or pts > (pos.points_contribution or 0)):
            pos = d
        if pts < 0 and (neg is None or pts < (neg.points_contribution or 0)):
            neg = d

    def _as_driver(d: Optional[ComponentDelta]) -> Optional[DriverChange]:
        if d is None or d.points_contribution is None:
            return None
        detail = ""
        if d.previous is not None and d.current is not None:
            detail = f"{d.name} {d.previous:.1f} → {d.current:.1f}/10"
        return DriverChange(key=d.key, label=d.name, points=d.points_contribution, detail=detail)

    return _as_driver(pos), _as_driver(neg)


def _build_attribution(
    *,
    cur_overall: int,
    cur_base: int,
    prev_overall: int,
    prev_base: int,
    cur_penalty: Optional[int],
    prev_penalty: Optional[int],
    holdings_changed: bool,
) -> ChangeAttribution:
    """Split the score move into data-quality / market / holding buckets.

    Exact identity (see ChangeAttribution): the raw ``base`` score is the
    market+holding signal; ``final − base`` is the dampening+penalty adjustment.
    ``data_quality_driven`` isolates the DAMPENING part (option penalty peeled
    out when the current penalty is known); ``structural`` (= Δbase) is
    market-driven on a no-trade day, else jointly reported with holdings."""
    adjustments = (cur_overall - cur_base) - (prev_overall - prev_base)
    # Only peel out the option-penalty change when the current penalty is known;
    # otherwise fold it into data_quality (documented) rather than mis-attribute.
    if cur_penalty is not None:
        d_penalty = int(cur_penalty) - int(prev_penalty or 0)
    else:
        d_penalty = 0
    data_quality = adjustments + d_penalty  # pure dampening/fidelity shift
    options_driven = -d_penalty  # a higher penalty costs points (holding-side)
    structural = cur_base - prev_base

    if holdings_changed:
        return ChangeAttribution(
            data_quality_driven=data_quality,
            combined_market_holdings=structural + options_driven,
            separable=False,
            note=(
                "You changed holdings in this window, so the market vs. your-changes "
                "split isn't exact — they're reported together."
            ),
        )
    return ChangeAttribution(
        data_quality_driven=data_quality,
        market_driven=structural,
        holding_driven=options_driven,
        separable=True,
        note=_attribution_note(data_quality, structural, options_driven),
    )


def _attribution_note(dq: int, market: int, holding: int) -> str:
    parts = []
    if abs(market) >= abs(dq) and abs(market) >= abs(holding) and market != 0:
        parts.append("mostly a market move (your holdings didn't change)")
    if abs(dq) >= 3 and abs(dq) >= abs(market):
        parts.append("largely a data-quality shift, not a change in your portfolio")
    if abs(holding) >= 1:
        parts.append("part from your option positions")
    return "This move was " + ", ".join(parts) + "." if parts else ""


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

    # ── Risk-profile gate ──
    # The Risk Match dimension is preference-relative.  A different (or
    # unstamped legacy) profile changes the target, so refuse to attribute the
    # resulting delta to the market or the user's holdings.
    current_preference = req.risk_preference
    previous_preference = prev_rm.get("risk_preference")
    try:
        previous_preference = int(previous_preference) if previous_preference is not None else None
    except (TypeError, ValueError):
        previous_preference = None
    if (
        current_preference is None
        or previous_preference is None
        or int(current_preference) != previous_preference
    ):
        return ScoreChangeReport(
            window=window,
            available=True,
            as_of_previous=as_of,
            current_score=cur_overall,
            previous_score=prev_overall,
            score_delta=None,
            current_score_version=SCORE_VERSION,
            previous_score_version=str(prev_version) if prev_version else None,
            comparable=False,
            current_risk_preference=current_preference,
            previous_risk_preference=previous_preference,
            summary=_preference_changed_summary(current_preference, previous_preference, as_of),
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
    cur_base = int(req.base_overall) if req.base_overall is not None else cur_overall
    prev_base_raw = prev_rm.get("base_overall")
    prev_base = int(prev_base_raw) if prev_base_raw is not None else prev_overall
    if prev_base_raw is not None:
        base_score_delta = cur_base - prev_base

    # ── Top +/− contributors + market/holding/data-quality attribution ──
    top_positive, top_negative = _top_contributors(component_deltas)
    holdings_changed = bool(holdings.added or holdings.removed or holdings.reweighted)
    attribution = _build_attribution(
        cur_overall=cur_overall,
        cur_base=cur_base,
        prev_overall=prev_overall,
        prev_base=prev_base,
        cur_penalty=req.option_penalty,
        prev_penalty=prev_rm.get("option_penalty"),
        holdings_changed=holdings_changed,
    )

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
        top_positive_contributor=top_positive,
        top_negative_contributor=top_negative,
        attribution=attribution,
        summary=_summarize(score_delta, as_of, drivers, dq_changes),
        current_score_version=SCORE_VERSION,
        previous_score_version=str(prev_version) if prev_version else None,
        comparable=True,
        current_risk_preference=req.risk_preference,
        previous_risk_preference=previous_preference,
    )


def request_from_score(score, positions=None, *, window: str = "previous") -> ScoreChangeRequest:
    """Build a change-report request from a LIVE ScoreResponse-like object —
    the single shared constructor for server-side callers (the Copilot
    score-change tool, proactive insights). No recompute: it only re-shapes
    numbers the score already carries."""
    m = score.metrics
    dims = {
        k: float(d.score)
        for k, d in (getattr(score, "dimensions", None) or {}).items()
        if getattr(d, "score", None) is not None
    }
    top_positions: list[dict] = []
    total_mv = sum(float(getattr(p, "market_value", 0.0) or 0.0) for p in (positions or []))
    if total_mv > 0:
        rows = [
            {
                "ticker": str(getattr(p, "ticker", "") or "").upper(),
                "weight": float(getattr(p, "market_value", 0.0) or 0.0) / total_mv,
            }
            for p in positions
            if getattr(p, "ticker", None)
        ]
        top_positions = sorted(rows, key=lambda r: r["weight"], reverse=True)[:10]
    return ScoreChangeRequest(
        window=window,
        overall_score=int(score.overall_score),
        risk_preference=int(getattr(score, "risk_preference", 3) or 3),
        base_overall=int(getattr(score, "base_overall", None) or score.overall_score),
        dimensions=dims,
        top_positions=top_positions,
        metrics={
            "annual_volatility": getattr(m, "annual_volatility", None),
            "sharpe_ratio": getattr(m, "sharpe_ratio", None),
            "max_drawdown": getattr(m, "max_drawdown", None),
            "var_95_daily": getattr(m, "var_95_daily", None),
            "beta_to_benchmark": getattr(m, "beta_to_benchmark", None),
            "net_equity": getattr(m, "net_equity", None),
            "leverage": getattr(m, "leverage", None),
        },
        confidence=getattr(m, "confidence", None),
    )
