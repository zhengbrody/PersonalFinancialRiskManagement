"""Risk-plans repository — RLS-scoped through the caller's JWT (PR2).

Every read/write goes through ``get_supabase(access_token=...)`` so Postgres
RLS (``auth.uid() = user_id`` + a portfolio-ownership WITH CHECK) enforces
tenancy — never the service role, never a hand-rolled WHERE as the only guard.
A missing 0012 table raises ``table_missing`` so the endpoints map it to 503.
Plan CONTENT (titles, hypotheses, blobs) is never logged.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

_TABLE = "risk_plans"
_SELECT = (
    "id,portfolio_id,title,status,source,hypothesis,baseline,proposed_changes,"
    "expected_impact,data_confidence,review_at,reviewed_at,resolved_at,outcome,"
    "created_at,updated_at"
)
_PATCHABLE = (
    "title",
    "status",
    "hypothesis",
    "proposed_changes",
    "expected_impact",
    "review_at",
    "outcome",
)


def table_missing(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "does not exist" in msg or "42p01" in msg or "pgrst205" in msg


def _client(access_token: Optional[str]):
    from libs.auth.client import get_supabase

    return get_supabase(access_token=access_token)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_plans(
    access_token: Optional[str], user_id: str, portfolio_id: Optional[str] = None
) -> list[dict[str, Any]]:
    q = _client(access_token).table(_TABLE).select(_SELECT).eq("user_id", user_id)
    if portfolio_id:
        q = q.eq("portfolio_id", portfolio_id)
    rows = q.order("created_at", desc=True).execute().data or []
    return [dict(r) for r in rows]


def get_plan(access_token: Optional[str], user_id: str, plan_id: str) -> Optional[dict[str, Any]]:
    rows = (
        _client(access_token)
        .table(_TABLE)
        .select(_SELECT)
        .eq("user_id", user_id)
        .eq("id", plan_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    return dict(rows[0]) if rows else None


def create_plan(
    access_token: Optional[str], user_id: str, values: dict[str, Any]
) -> dict[str, Any]:
    """Insert. RLS's WITH CHECK rejects a portfolio_id the caller doesn't own
    (→ the endpoint maps that to 422). We set user_id explicitly AND the DB
    DEFAULT is auth.uid(), so a forged user_id can't slip in."""
    now = _now()
    payload = {
        "user_id": user_id,
        "portfolio_id": values["portfolio_id"],
        "title": values["title"],
        "source": values["source"],
        "status": values.get("status", "draft"),
        "hypothesis": values.get("hypothesis"),
        "baseline": values.get("baseline") or {},
        "proposed_changes": values.get("proposed_changes") or {},
        "expected_impact": values.get("expected_impact") or {},
        "data_confidence": values.get("data_confidence") or {},
        "review_at": values.get("review_at"),
        "created_at": now,
        "updated_at": now,
    }
    rows = _client(access_token).table(_TABLE).insert(payload).execute().data or []
    return dict(rows[0]) if rows else payload


def update_plan(
    access_token: Optional[str], user_id: str, plan_id: str, fields: dict[str, Any]
) -> Optional[dict[str, Any]]:
    """Patch only whitelisted columns for the caller's own plan. Status
    transitions stamp the matching timestamp deterministically."""
    patch = {k: fields[k] for k in _PATCHABLE if k in fields}
    if not patch:
        return get_plan(access_token, user_id, plan_id)
    patch["updated_at"] = _now()
    if patch.get("status") == "resolved":
        patch.setdefault("resolved_at", _now())
    rows = (
        _client(access_token)
        .table(_TABLE)
        .update(patch)
        .eq("user_id", user_id)
        .eq("id", plan_id)
        .execute()
        .data
        or []
    )
    return dict(rows[0]) if rows else None


def mark_reviewed(access_token: Optional[str], user_id: str, plan_id: str) -> None:
    """Stamp reviewed_at when a plan is reviewed (best-effort — a review is
    valid even if this bookkeeping write fails)."""
    _client(access_token).table(_TABLE).update({"reviewed_at": _now(), "updated_at": _now()}).eq(
        "user_id", user_id
    ).eq("id", plan_id).execute()


def delete_plan(access_token: Optional[str], user_id: str, plan_id: str) -> None:
    _client(access_token).table(_TABLE).delete().eq("user_id", user_id).eq("id", plan_id).execute()
