"""Saved AI insights — user-curated AI digests / chat answers.

Schema in ``supabase/migrations/0004_risk_memory.sql``. Same RLS pattern
as portfolios / snapshots: the database enforces ``auth.uid() = user_id``;
this layer just attaches the JWT.

Public API
----------
- ``save_insight(page, title, content, ...)``: returns the inserted row
  or raises ``AuthError`` if the user is not signed in. Unlike
  ``snapshots.write_snapshot``, save is an *explicit user action*, so
  failures must surface to the UI as toast/error.
- ``list_insights(limit=50)``: most-recent first.
- ``delete_insight(insight_id)``: idempotent.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Optional

from .client import AuthError, get_supabase
from .session import access_token, current_user

_logger = logging.getLogger(__name__)


def _authed_client():
    user = current_user()
    if user is None:
        raise AuthError("Not authenticated.")
    sb = get_supabase()
    token = access_token()
    if token:
        sb.postgrest.auth(token)
    return sb


def _finite_or_zero(v: Any) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return x if math.isfinite(x) else 0.0


def _trim_text(value: Any, *, max_len: int, name: str) -> str:
    """Return a trimmed string, raising ``ValueError`` if it's empty.

    The DB CHECK constraints already enforce non-empty + length bounds;
    we duplicate them client-side so the user sees a friendly error
    rather than a PostgREST 400.
    """
    s = "" if value is None else str(value).strip()
    if not s:
        raise ValueError(f"{name} is required.")
    return s[:max_len]


def save_insight(
    *,
    page: str,
    title: str,
    content: str,
    provider: str | None = None,
    model: str | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
    metadata: dict | None = None,
    portfolio_id: str | None = None,
) -> dict[str, Any]:
    """Persist a saved insight for the current user."""
    payload = {
        "page": _trim_text(page, max_len=60, name="page"),
        "title": _trim_text(title, max_len=200, name="title"),
        "content": _trim_text(content, max_len=20000, name="content"),
        "provider": (str(provider).strip()[:40] if provider else None),
        "model": (str(model).strip()[:80] if model else None),
        "tokens_in": max(0, int(tokens_in or 0)),
        "tokens_out": max(0, int(tokens_out or 0)),
        "cost_usd": _finite_or_zero(cost_usd),
        "metadata": metadata if isinstance(metadata, dict) else {},
        "portfolio_id": portfolio_id,
    }

    sb = _authed_client()
    try:
        resp = sb.table("saved_insights").insert(payload).execute()
    except Exception as exc:
        # Surfaced to the user — explicit action, must not silently fail.
        _logger.warning("saved_insights.insert_failed: %s", exc)
        raise AuthError(f"Could not save insight: {exc}") from exc
    rows = resp.data or []
    if not rows:
        raise AuthError("Insert returned no row — check RLS policy.")
    return rows[0]


def list_insights(limit: int = 50) -> list[dict[str, Any]]:
    """Return the user's most-recent insights, newest first.

    Returns ``[]`` for anonymous users or when the table is missing —
    the UI shows an empty-state in both cases, so we don't need to
    distinguish.
    """
    if limit <= 0:
        return []
    try:
        sb = _authed_client()
    except AuthError:
        return []
    try:
        resp = (
            sb.table("saved_insights")
            .select("*")
            .order("created_at", desc=True)
            .limit(int(limit))
            .execute()
        )
    except Exception as exc:
        _logger.warning("saved_insights.list_failed: %s", exc)
        return []
    return resp.data or []


def delete_insight(insight_id: str) -> bool:
    """Delete one owned insight. Returns True when a row was removed
    (or already absent — idempotent), False on hard error."""
    if not insight_id:
        raise ValueError("insight_id is required.")
    try:
        sb = _authed_client()
    except AuthError:
        raise
    try:
        sb.table("saved_insights").delete().eq("id", str(insight_id)).execute()
        return True
    except Exception as exc:
        _logger.warning("saved_insights.delete_failed: %s", exc)
        return False


def get_insight(insight_id: str) -> Optional[dict[str, Any]]:
    """Return a single insight by id. RLS already restricts to own row;
    returns ``None`` when not found (or when RLS hides it)."""
    try:
        sb = _authed_client()
    except AuthError:
        return None
    try:
        resp = sb.table("saved_insights").select("*").eq("id", str(insight_id)).limit(1).execute()
    except Exception as exc:
        _logger.warning("saved_insights.get_failed: %s", exc)
        return None
    rows = resp.data or []
    return rows[0] if rows else None
