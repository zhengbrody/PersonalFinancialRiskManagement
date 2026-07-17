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


# ── server-side product-event stamping ──────────────────────────────
#
# ``first_*`` milestones are stamped at the REAL product event (portfolio
# created / book scored / plan saved / plan reviewed) on the server, so the
# journey is authoritative regardless of which UI path triggered the event.
# A ``first_*`` milestone is immutable once set, so a tiny in-process memo
# skips the read+write round-trip on hot paths (e.g. every score request)
# after the first successful stamp in this process.
_stamped_memo: set[tuple[str, str]] = set()


def stamp_milestone_failsoft(access_token: Optional[str], user_id: str, milestone: str) -> None:
    """Best-effort stamp — NEVER raises. A journey bookkeeping failure (missing
    table, RLS blip, network) must not fail the product endpoint it rides on."""
    key = (user_id, milestone)
    if milestone.startswith("first_") and key in _stamped_memo:
        return
    try:
        record_milestone(access_token, user_id, milestone)
        if milestone.startswith("first_"):
            _stamped_memo.add(key)
    except Exception as exc:  # noqa: BLE001 — bookkeeping only, by design
        import logging

        logging.getLogger("mindmarket.journey").warning(
            "journey.stamp_failed milestone=%s err=%s", milestone, type(exc).__name__
        )


def reset_stamp_memo() -> None:
    """Test hook — clear the in-process first-milestone memo."""
    _stamped_memo.clear()
