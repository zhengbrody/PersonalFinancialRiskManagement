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

import math
from typing import Optional

from .client import AuthError, get_supabase
from .session import access_token, current_user


def _finite_or_zero(v) -> float:
    """Coerce v to a finite float, or 0 if it's NaN/Inf/garbage.

    Why: PostgREST rejects JSON containing NaN/Inf with
    'Out of range float values are not JSON compliant'. st.data_editor's
    empty NumberColumn cells come through as float('nan'), so any path
    that doesn't sanitize before insert will blow up at runtime.
    """
    try:
        x = float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0
    return x if math.isfinite(x) else 0.0


def _sanitize_holdings(holdings: dict) -> dict:
    """Strip NaN/Inf from a holdings dict before sending to Supabase.

    Belt-and-suspenders: callers (UI, CSV import, sync_from_server_config)
    should already filter, but enforcing it here means a single forgotten
    guard upstream can't poison the DB write.
    """
    if not isinstance(holdings, dict):
        return {}
    clean: dict = {}
    for tk, h in holdings.items():
        if not isinstance(h, dict):
            continue
        shares = _finite_or_zero(h.get("shares"))
        if shares == 0:
            continue
        pos: dict = {"shares": shares}
        ac = h.get("avg_cost")
        if ac not in (None, ""):
            ac_f = _finite_or_zero(ac)
            if ac_f > 0:
                pos["avg_cost"] = ac_f
        for k in ("sector", "account", "asset_type", "currency"):
            if h.get(k):
                pos[k] = h[k]
        if "margin_eligible" in h:
            pos["margin_eligible"] = bool(h["margin_eligible"])
        clean[str(tk).strip().upper()] = pos
    return clean


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
    resp = sb.table("portfolios").select("*").eq("is_default", True).limit(1).execute()
    rows = resp.data or []
    return rows[0] if rows else None


def get_portfolio(portfolio_id: str) -> Optional[dict]:
    """Return one owned portfolio by id, or None when RLS hides it."""
    sb = _authed_client()
    resp = sb.table("portfolios").select("*").eq("id", portfolio_id).limit(1).execute()
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
        sb.table("portfolios").update({"is_default": False}).eq("is_default", True).execute()

    resp = (
        sb.table("portfolios")
        .insert(
            {
                "name": name,
                "holdings": _sanitize_holdings(holdings),
                "margin_loan": _finite_or_zero(margin_loan),
                "is_default": is_default,
            }
        )
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

    # Sanitize numeric/JSON fields so PostgREST never sees NaN/Inf.
    if "holdings" in fields and fields["holdings"] is not None:
        fields["holdings"] = _sanitize_holdings(fields["holdings"])
    if "margin_loan" in fields and fields["margin_loan"] is not None:
        fields["margin_loan"] = _finite_or_zero(fields["margin_loan"])

    sb = _authed_client()
    if fields.get("is_default"):
        sb.table("portfolios").update({"is_default": False}).eq("is_default", True).neq(
            "id", portfolio_id
        ).execute()

    resp = sb.table("portfolios").update(fields).eq("id", portfolio_id).execute()
    rows = resp.data or []
    if not rows:
        raise AuthError("No row updated — wrong id or RLS blocked you.")
    return rows[0]


def delete_portfolio(portfolio_id: str) -> None:
    """Delete a single portfolio. RLS prevents deleting others' rows."""
    sb = _authed_client()
    sb.table("portfolios").delete().eq("id", portfolio_id).execute()


def upsert_holding(
    portfolio_id: str,
    ticker: str,
    *,
    shares: float,
    avg_cost: Optional[float] = None,
    sector: Optional[str] = None,
) -> dict:
    """Add or update one holding on an owned portfolio."""
    symbol = str(ticker or "").strip().upper()
    if not symbol:
        raise ValueError("Ticker is required.")
    try:
        share_value = float(shares)
    except (TypeError, ValueError) as exc:
        raise ValueError("Shares must be numeric.") from exc
    if share_value <= 0:
        raise ValueError("Shares must be greater than zero.")

    portfolio = get_portfolio(portfolio_id)
    if not portfolio:
        raise AuthError("Portfolio not found or RLS blocked you.")

    holdings = dict(portfolio.get("holdings") or {})
    row = {"shares": share_value}
    if avg_cost not in (None, ""):
        try:
            row["avg_cost"] = float(avg_cost)
        except (TypeError, ValueError) as exc:
            raise ValueError("Avg cost must be numeric.") from exc
    if sector:
        row["sector"] = str(sector).strip()
    holdings[symbol] = row
    return update_portfolio(portfolio_id, holdings=holdings)


def remove_holding(portfolio_id: str, ticker: str) -> dict:
    """Remove one holding from an owned portfolio."""
    symbol = str(ticker or "").strip().upper()
    if not symbol:
        raise ValueError("Ticker is required.")
    portfolio = get_portfolio(portfolio_id)
    if not portfolio:
        raise AuthError("Portfolio not found or RLS blocked you.")
    holdings = dict(portfolio.get("holdings") or {})
    holdings.pop(symbol, None)
    if not holdings:
        raise ValueError("Portfolio must keep at least one holding.")
    return update_portfolio(portfolio_id, holdings=holdings)
