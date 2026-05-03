"""
libs/auth/portfolios.py

CRUD for the per-user `portfolios` table. Schema is defined in
supabase/migrations/0001_init.sql and lives in Supabase Postgres.

Schema (defined SQL-side):
    portfolios (
        id           uuid    PRIMARY KEY DEFAULT uuid_generate_v4(),
        user_id      uuid    NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
        name         text    NOT NULL,
        holdings     jsonb   NOT NULL,    -- {ticker: {shares, avg_cost?}, ...}
        margin_loan  numeric DEFAULT 0,
        is_default   boolean DEFAULT false,
        created_at   timestamptz DEFAULT now(),
        updated_at   timestamptz DEFAULT now()
    )

Row Level Security on this table:
    - SELECT/UPDATE/DELETE: only rows where user_id = auth.uid()
    - INSERT: user_id MUST equal auth.uid()
This is enforced server-side by Supabase, NOT by this Python code.
Even if a bug here let someone send `user_id="someone-else's-id"`, the
INSERT would be rejected at the database level.

When called from a Streamlit page, the Supabase client uses the
authenticated user's JWT (from session.access_token()), so the RLS
filters apply automatically.
"""
from __future__ import annotations

from typing import Optional

from .client import AuthError, get_supabase
from .session import current_user, access_token


def _authed_client():
    """Return a Supabase client that has the current user's JWT attached.

    Anon-key client + user JWT = RLS-filtered queries.
    """
    user = current_user()
    if user is None:
        raise AuthError("Not authenticated.")
    sb = get_supabase()
    token = access_token()
    if token:
        # supabase-py 2.x: session is set globally on the client; if you
        # have multiple users in one process (you don't, in Streamlit),
        # use a per-call header instead.
        sb.postgrest.auth(token)
    return sb


def list_portfolios() -> list[dict]:
    """Return all portfolios owned by the current user, default first."""
    sb = _authed_client()
    resp = (
        sb.table("portfolios")
        .select("*")
        .order("is_default", desc=True)
        .order("created_at", desc=True)
        .execute()
    )
    return resp.data or []


def get_default_portfolio() -> Optional[dict]:
    """Return the user's default portfolio, or None if they haven't created one."""
    sb = _authed_client()
    resp = (
        sb.table("portfolios")
        .select("*")
        .eq("is_default", True)
        .limit(1)
        .execute()
    )
    rows = resp.data or []
    return rows[0] if rows else None


def create_portfolio(
    name: str,
    holdings: dict,
    margin_loan: float = 0.0,
    is_default: bool = False,
) -> dict:
    """Insert a new portfolio. user_id is set server-side via DEFAULT auth.uid()
    (configured in the migration), so we don't pass it from the client."""
    sb = _authed_client()

    if is_default:
        # Demote any existing default first — Postgres trigger could do this
        # transactionally, but a 2-step write is simpler and the race window
        # is irrelevant for a single user.
        sb.table("portfolios").update({"is_default": False}).eq(
            "is_default", True
        ).execute()

    resp = (
        sb.table("portfolios")
        .insert({
            "name": name,
            "holdings": holdings,
            "margin_loan": margin_loan,
            "is_default": is_default,
        })
        .execute()
    )
    rows = resp.data or []
    if not rows:
        raise AuthError("Insert returned no row — check RLS policy.")
    return rows[0]


def update_portfolio(portfolio_id: str, **fields) -> dict:
    """Patch fields on a single portfolio. RLS prevents touching others' rows."""
    allowed = {"name", "holdings", "margin_loan", "is_default"}
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"Cannot update fields: {bad}")

    sb = _authed_client()
    if fields.get("is_default"):
        sb.table("portfolios").update({"is_default": False}).eq(
            "is_default", True
        ).neq("id", portfolio_id).execute()

    resp = (
        sb.table("portfolios")
        .update(fields)
        .eq("id", portfolio_id)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        raise AuthError("No row updated — wrong id or RLS blocked you.")
    return rows[0]


def delete_portfolio(portfolio_id: str) -> None:
    """Delete a single portfolio. RLS prevents deleting others' rows."""
    sb = _authed_client()
    sb.table("portfolios").delete().eq("id", portfolio_id).execute()
