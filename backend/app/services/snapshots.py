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
    top_positions: Optional[list[dict]] = None,
    source: str = "score",
) -> None:
    """Insert a daily snapshot of the active portfolio (deduped). Never raises."""
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
        equity = _finite(getattr(m, "total_value", None)) or 0.0
        cash = max(0.0, float(cash_balance or 0.0))
        loan = max(0.0, float(margin_loan or 0.0))
        gross = equity + cash
        net_equity = gross - loan
        leverage = (gross / net_equity) if net_equity > 0 else None

        sb.table("portfolio_snapshots").insert(
            {
                "source": source,
                "net_equity": round(net_equity, 2),
                "total_long": round(gross, 2),
                "cash_balance": round(cash, 2),
                "margin_loan": round(loan, 2),
                "contributed_capital": round(float(contributed_capital or 0.0), 2),
                "leverage": round(leverage, 4) if leverage is not None else None,
                "risk_metrics": {
                    "overall_score": int(score.overall_score),
                    "annual_return": _finite(m.annual_return),
                    "annual_volatility": _finite(m.annual_volatility),
                    "sharpe_ratio": _finite(m.sharpe_ratio),
                    "max_drawdown": _finite(m.max_drawdown),
                    "var_95_daily": _finite(m.var_95_daily),
                    "beta_to_benchmark": _finite(m.beta_to_benchmark),
                },
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
            .select("created_at,risk_metrics,net_equity,leverage")
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
