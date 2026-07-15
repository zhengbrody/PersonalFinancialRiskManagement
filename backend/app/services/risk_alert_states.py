"""Risk-alert lifecycle-state repository — RLS-scoped (PR2).

One row per (user, portfolio, alert_key) — the alert_key is the deterministic
alert's STABLE episode id. State never changes the alert computation; it only
records what the user did with it (seen/snoozed/resolved), consistently across
devices. RLS enforces tenancy + portfolio ownership.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

_TABLE = "risk_alert_states"
_SELECT = "portfolio_id,alert_key,state,snooze_until,updated_at"


def table_missing(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "does not exist" in msg or "42p01" in msg or "pgrst205" in msg


def _client(access_token: Optional[str]):
    from libs.auth.client import get_supabase

    return get_supabase(access_token=access_token)


def list_states(
    access_token: Optional[str], user_id: str, portfolio_id: str
) -> list[dict[str, Any]]:
    rows = (
        _client(access_token)
        .table(_TABLE)
        .select(_SELECT)
        .eq("user_id", user_id)
        .eq("portfolio_id", portfolio_id)
        .execute()
        .data
        or []
    )
    return [dict(r) for r in rows]


def upsert_state(
    access_token: Optional[str], user_id: str, values: dict[str, Any]
) -> dict[str, Any]:
    """Set the lifecycle state for one alert episode. UNIQUE(user_id,
    portfolio_id, alert_key) makes this an idempotent upsert. RLS's WITH CHECK
    rejects a portfolio the caller doesn't own."""
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "user_id": user_id,
        "portfolio_id": values["portfolio_id"],
        "alert_key": values["alert_key"],
        "state": values["state"],
        "snooze_until": values.get("snooze_until") if values["state"] == "snoozed" else None,
        "updated_at": now,
    }
    _client(access_token).table(_TABLE).upsert(
        payload, on_conflict="user_id,portfolio_id,alert_key"
    ).execute()
    return payload
