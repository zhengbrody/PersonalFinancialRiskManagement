"""Per-user journey-milestone repository — RLS-scoped (PR2).

One row per user; each column is a milestone timestamp. ``first_*`` milestones
are set ONCE (only if still null); ``last_workspace_view`` always updates. No
holdings / tickers / amounts / question text is ever stored — timestamps only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

_TABLE = "user_journey_state"
_MILESTONES = (
    "first_portfolio_at",
    "first_score_at",
    "first_driver_viewed_at",
    "first_stress_test_at",
    "first_plan_at",
    "first_plan_reviewed_at",
    "last_workspace_view",
)
_SELECT = ",".join(_MILESTONES)


def table_missing(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "does not exist" in msg or "42p01" in msg or "pgrst205" in msg


def _client(access_token: Optional[str]):
    from libs.auth.client import get_supabase

    return get_supabase(access_token=access_token)


def get_state(access_token: Optional[str], user_id: str) -> dict[str, Any]:
    rows = (
        _client(access_token)
        .table(_TABLE)
        .select(_SELECT)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return dict(rows[0]) if rows else {m: None for m in _MILESTONES}


def record_milestone(access_token: Optional[str], user_id: str, milestone: str) -> dict[str, Any]:
    """Stamp a milestone. ``first_*`` is written only if currently null (once);
    ``last_workspace_view`` always updates. Upsert keeps it one-row-per-user."""
    if milestone not in _MILESTONES:
        raise ValueError("unknown milestone")
    now = datetime.now(timezone.utc).isoformat()
    current = get_state(access_token, user_id)
    is_first = milestone.startswith("first_")
    if is_first and current.get(milestone):
        return current  # already stamped — first-time-only, don't overwrite
    payload = {"user_id": user_id, milestone: now, "updated_at": now}
    _client(access_token).table(_TABLE).upsert(payload, on_conflict="user_id").execute()
    current[milestone] = now
    return current
