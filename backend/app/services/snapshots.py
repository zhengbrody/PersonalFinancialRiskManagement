"""Portfolio snapshots — the "what changed since last visit" memory.

Writes at most one snapshot per ~day per user (deduped) when the active
portfolio is scored, so the dashboard can show a day-over-day delta
("health 612 → 598 since May 28"). RLS-scoped via the caller's JWT — the
``portfolio_snapshots`` table defaults ``user_id`` to ``auth.uid()`` and only
lets a user read/write their own rows. Everything is FAIL-SOFT: snapshots are
a nice-to-have and must never break scoring or the dashboard.

Table: supabase/migrations/0004_risk_memory.sql.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from libs.mindmarket_core.score_version import SCORE_VERSION

_log = logging.getLogger(__name__)

# Record at most one snapshot per this window so deltas mean "what moved since
# the prior day", not noise from every dashboard re-score on page load.
_SNAPSHOT_MIN_GAP_HOURS = 20


def _client(access_token: str):
    from libs.auth.client import get_supabase

    return get_supabase(access_token=access_token)


def _iso_hours_ago(hours: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _finite(v: Any) -> Optional[float]:
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def record_snapshot(
    access_token: Optional[str],
    *,
    score: Any,
    cash_balance: float = 0.0,
    margin_loan: float = 0.0,
    contributed_capital: float = 0.0,
    extra_metrics: Optional[dict[str, Any]] = None,
    top_positions: Optional[list[dict]] = None,
    concentration: Optional[Any] = None,
    overall_override: Optional[int] = None,
    option_penalty: Optional[int] = None,
    source: str = "score",
) -> None:
    """Insert a daily snapshot of the active portfolio (deduped). Never raises.

    Stores the per-dimension scores, the deterministic data-quality read, and a
    compact concentration summary alongside the headline metrics — so the
    "what changed?" engine can attribute a score move to its components against
    the user's OWN prior snapshot (not a generic benchmark)."""
    if not access_token:
        return
    try:
        sb = _client(access_token)
        # Dedup: already recorded within the gap window → skip.
        recent = (
            sb.table("portfolio_snapshots")
            .select("id")
            .gte("created_at", _iso_hours_ago(_SNAPSHOT_MIN_GAP_HOURS))
            .limit(1)
            .execute()
        )
        if recent.data:
            return

        m = score.metrics
        cash = max(0.0, float(cash_balance or 0.0))
        loan = max(0.0, float(margin_loan or 0.0))
        extra = extra_metrics or {}
        # On active scores the engine's total_value already includes a CASH
        # position when cash_balance > 0. Prefer the explicit account metric so
        # snapshots don't double-count cash.
        gross = _finite(extra.get("total_value"))
        if gross is None:
            gross = (_finite(getattr(m, "total_value", None)) or 0.0) + cash
        net_equity = _finite(extra.get("net_equity"))
        if net_equity is None:
            net_equity = gross - loan
        leverage = (gross / net_equity) if net_equity > 0 else None

        final_overall = (
            int(overall_override) if overall_override is not None else int(score.overall_score)
        )
        risk_metrics = {
            # The FINAL displayed score (post option-penalty) so day-over-day
            # deltas match what the user saw.
            "overall_score": final_overall,
            "base_overall": int(getattr(score, "base_overall", 0) or score.overall_score),
            "annual_return": _finite(m.annual_return),
            "annual_volatility": _finite(m.annual_volatility),
            "sharpe_ratio": _finite(m.sharpe_ratio),
            "max_drawdown": _finite(m.max_drawdown),
            "var_95_daily": _finite(m.var_95_daily),
            "beta_to_benchmark": _finite(m.beta_to_benchmark),
            # Per-dimension scores (0..10) — the basis for component-delta attribution.
            "dimensions": {
                k: _finite(getattr(d, "score", None))
                for k, d in (getattr(score, "dimensions", {}) or {}).items()
            },
        }
        for key in (
            "daily_pnl",
            "daily_return",
            "total_pnl",
            "total_return",
            "total_value",
            "net_equity",
            "cash_balance",
            "margin_loan",
            "contributed_capital",
        ):
            val = _finite((extra_metrics or {}).get(key))
            if val is not None:
                risk_metrics[key] = val

        # Deterministic input-health snapshot (the data_quality JSONB column was
        # reserved in migration 0004 and is now populated).
        data_quality = {
            "confidence": getattr(m, "confidence", None),
            "data_quality": _finite(getattr(m, "data_quality", None)),
            "observations": int(getattr(m, "observations", 0) or 0),
            "data_coverage": _finite(getattr(m, "data_coverage", None)),
            "dropped_tickers": list(getattr(m, "dropped_tickers", ()) or []),
        }
        # Compact concentration summary (top name / top sector / HHI) for the
        # concentration-change driver. `concentration` is the API ConcentrationOut.
        conc: dict[str, Any] = {}
        if concentration is not None:
            conc = {
                "top_holding_ticker": getattr(concentration, "top_holding_ticker", None),
                "top_holding_weight": _finite(getattr(concentration, "top_holding_weight", None)),
                "top5_weight": _finite(getattr(concentration, "top5_weight", None)),
                "hhi": _finite(getattr(concentration, "hhi", None)),
                "top_sector": getattr(concentration, "top_sector", None),
                "top_sector_weight": _finite(getattr(concentration, "top_sector_weight", None)),
            }
        if conc:
            risk_metrics["concentration"] = conc
        if option_penalty:
            risk_metrics["option_penalty"] = int(option_penalty)

        sb.table("portfolio_snapshots").insert(
            {
                "source": source,
                # The methodology version that produced this score — stamped so a
                # later trend comparison can refuse to diff across versions.
                "score_version": SCORE_VERSION,
                "net_equity": round(net_equity, 2),
                "total_long": round(gross, 2),
                "cash_balance": round(cash, 2),
                "margin_loan": round(loan, 2),
                "contributed_capital": round(float(contributed_capital or 0.0), 2),
                "leverage": round(leverage, 4) if leverage is not None else None,
                "risk_metrics": risk_metrics,
                "data_quality": data_quality,
                "top_positions": (top_positions or [])[:10],
            }
        ).execute()
    except Exception as exc:  # noqa: BLE001 - never break scoring
        _log.warning("snapshot.record_failed reason=%s", type(exc).__name__)


def get_previous_snapshot(access_token: Optional[str]) -> Optional[dict]:
    """The most recent snapshot OLDER than the gap window — the prior-day
    baseline to diff today's score against. None if there isn't one. Never
    raises."""
    if not access_token:
        return None
    try:
        sb = _client(access_token)
        resp = (
            sb.table("portfolio_snapshots")
            .select("created_at,risk_metrics,net_equity,leverage,contributed_capital")
            .lt("created_at", _iso_hours_ago(_SNAPSHOT_MIN_GAP_HOURS))
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001
        _log.warning("snapshot.read_failed reason=%s", type(exc).__name__)
        return None


_WINDOW_HOURS = {
    "previous": _SNAPSHOT_MIN_GAP_HOURS,  # the prior-day baseline
    "7d": 7 * 24,
    "30d": 30 * 24,
}


def get_snapshot_at_window(access_token: Optional[str], window: str = "previous") -> Optional[dict]:
    """The most recent snapshot OLDER than the window's lower bound — i.e. the
    user's own prior state ~1 day / ~7 days / ~30 days ago. Returns the full row
    (risk_metrics + data_quality + top_positions) for change attribution, or None
    if there is no snapshot that old. Never raises."""
    if not access_token:
        return None
    hours = _WINDOW_HOURS.get(window, _SNAPSHOT_MIN_GAP_HOURS)
    try:
        sb = _client(access_token)
        resp = (
            sb.table("portfolio_snapshots")
            .select(
                "created_at,score_version,risk_metrics,data_quality,top_positions,"
                "net_equity,leverage,contributed_capital"
            )
            .lt("created_at", _iso_hours_ago(hours))
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        rows = resp.data or []
        return rows[0] if rows else None
    except Exception as exc:  # noqa: BLE001
        _log.warning("snapshot.window_read_failed window=%s reason=%s", window, type(exc).__name__)
        return None


def get_snapshot_history(access_token: Optional[str], *, limit: int = 90) -> list[dict]:
    """Recent snapshots oldest→newest, flattened to a chartable shape:
    ``[{as_of, overall_score, annual_volatility, var_95_daily, sharpe_ratio,
    max_drawdown, net_equity}]``. Fail-soft to ``[]``; never raises."""
    if not access_token:
        return []
    try:
        sb = _client(access_token)
        resp = (
            sb.table("portfolio_snapshots")
            .select("created_at,risk_metrics,net_equity,contributed_capital,leverage")
            .order("created_at", desc=True)
            .limit(max(1, min(limit, 365)))
            .execute()
        )
        rows = list(reversed(resp.data or []))  # oldest → newest for plotting
        out: list[dict] = []
        for r in rows:
            m = r.get("risk_metrics") or {}
            dims = m.get("dimensions") or {}
            conc = m.get("concentration") or {}
            dq = r.get("data_quality") or {}
            out.append(
                {
                    "as_of": r.get("created_at"),
                    "overall_score": m.get("overall_score"),
                    "annual_volatility": _finite(m.get("annual_volatility")),
                    "var_95_daily": _finite(m.get("var_95_daily")),
                    "sharpe_ratio": _finite(m.get("sharpe_ratio")),
                    "max_drawdown": _finite(m.get("max_drawdown")),
                    "net_equity": _finite(r.get("net_equity")),
                    "daily_pnl": _finite(m.get("daily_pnl")),
                    "daily_return": _finite(m.get("daily_return")),
                    "total_pnl": _finite(m.get("total_pnl")),
                    "total_return": _finite(m.get("total_return")),
                    "contributed_capital": _finite(r.get("contributed_capital")),
                    # Per-dimension trend + confidence (additive).
                    "risk_match": _finite(dims.get("risk_match")),
                    "risk_adjusted_return": _finite(dims.get("risk_adjusted_return")),
                    "downside_protection": _finite(dims.get("downside_protection")),
                    "confidence": dq.get("confidence") or m.get("confidence"),
                    # Series backing the cockpit's per-dimension historical
                    # percentiles (additive; already stored, just surfaced).
                    "beta_to_benchmark": _finite(m.get("beta_to_benchmark")),
                    "leverage": _finite(r.get("leverage") or m.get("leverage")),
                    "concentration_top_holding": _finite(conc.get("top_holding_weight")),
                }
            )
        return out
    except Exception as exc:  # noqa: BLE001
        _log.warning("snapshot.history_failed reason=%s", type(exc).__name__)
        return []
