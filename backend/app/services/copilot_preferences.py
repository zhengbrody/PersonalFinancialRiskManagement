"""Copilot user-CONFIRMED preferences repository (PR3).

RLS-scoped through the caller's JWT (``copilot_preferences`` policies allow
``auth.uid() = user_id`` only) — the service NEVER uses the service role for
user reads/writes, so cross-user isolation is enforced by Postgres, not by a
WHERE clause.

Two access tiers:
  * API tier (``get_row`` / ``upsert_confirmed`` / ``clear``): raises so the
    endpoints can map a missing 0009 table to 503 service_unavailable.
  * Copilot tier (``get_confirmed``): FAIL-SOFT — any repository failure (or
    an unconfirmed row) returns None and the answer simply carries no
    preference context; the Copilot never 500s because of this table.

Consent semantics: ONLY the explicit PUT (the confirmation act) writes;
``confirmed_at IS NULL`` == no memory. Nothing here is ever inferred from
chats/holdings/behavior. Preference VALUES are never logged.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

_log = logging.getLogger(__name__)

_TABLE = "copilot_preferences"

# The columns the API reads/writes — a single source so a schema drift shows
# up here, not scattered across queries.
_FIELDS = (
    "risk_tolerance",
    "investment_horizon",
    "liquidity_need",
    "concentration_limit",
    "margin_limit",
    "metadata",
)
_SELECT = ",".join((*_FIELDS, "confirmed_at", "updated_at"))


def table_missing(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "does not exist" in msg or "42p01" in msg or "pgrst205" in msg


def _client(access_token: Optional[str]):
    from libs.auth.client import get_supabase

    return get_supabase(access_token=access_token)


def get_row(access_token: Optional[str], user_id: str) -> Optional[dict[str, Any]]:
    """The caller's own row (RLS enforces ownership), or None. Raises on
    repository errors — the API maps a missing table to 503."""
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
    return dict(rows[0]) if rows else None


def upsert_confirmed(
    access_token: Optional[str], user_id: str, values: dict[str, Any]
) -> dict[str, Any]:
    """THE confirmation act: persist the user's explicitly-confirmed values
    and stamp ``confirmed_at``. RLS's WITH CHECK rejects any user_id that
    isn't the caller's own auth.uid(). Raises on repository errors."""
    now = datetime.now(timezone.utc).isoformat()
    payload = {k: values.get(k) for k in _FIELDS}
    payload["metadata"] = values.get("metadata") or {}
    payload.update({"user_id": user_id, "confirmed_at": now, "updated_at": now})
    _client(access_token).table(_TABLE).upsert(payload, on_conflict="user_id").execute()
    return get_row(access_token, user_id) or payload


def clear(access_token: Optional[str], user_id: str) -> None:
    """Complete erasure of the caller's preference row (their own only, per
    RLS). Raises on repository errors."""
    _client(access_token).table(_TABLE).delete().eq("user_id", user_id).execute()


def get_confirmed(access_token: Optional[str], user_id: Optional[str]) -> Optional[dict[str, Any]]:
    """FAIL-SOFT read for the Copilot context: the row ONLY when the user has
    explicitly confirmed (``confirmed_at`` set); None on no row, no
    confirmation, or ANY repository failure. Never raises, never logs values."""
    if not user_id:
        return None
    try:
        row = get_row(access_token, user_id)
    except Exception as exc:  # noqa: BLE001 - preferences are a nice-to-have
        _log.warning("copilot_preferences.read_failed err=%s", type(exc).__name__)
        return None
    if not row or not row.get("confirmed_at"):
        return None
    return row
