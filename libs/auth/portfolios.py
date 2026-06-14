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
        contributed_capital numeric DEFAULT 0,
        cash_balance numeric DEFAULT 0,
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

_CAPITAL_FIELDS = {"contributed_capital", "cash_balance"}


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
        # String passthrough fields, incl. the option-contract identity. Without
        # underlying/expiry/option_type/option_side the option is unusable on
        # read-back (the cockpit + analytics drop it), so they MUST survive the
        # DB write — this rebuild-from-scratch is otherwise lossy.
        for k in (
            "sector",
            "account",
            "asset_type",
            "currency",
            "option_type",
            "option_side",
            "underlying",
            "expiry",
        ):
            if h.get(k):
                pos[k] = h[k]
        # Numeric option fields — keep finite positives (strike must be > 0;
        # contract_multiplier defaults to 100 on read if absent).
        for k in ("strike", "contract_multiplier"):
            v = h.get(k)
            if v not in (None, ""):
                vf = _finite_or_zero(v)
                if vf > 0:
                    pos[k] = vf
        if "margin_eligible" in h:
            pos["margin_eligible"] = bool(h["margin_eligible"])
        clean[str(tk).strip().upper()] = pos
    return clean


def _is_missing_capital_column_error(exc: Exception) -> bool:
    """True when production DB has not applied migration 0003 yet.

    Supabase/PostgREST reports this as a schema-cache or SQL column error.
    During rolling deploys we strip the new optional fields and retry so
    existing portfolio CRUD keeps working until the migration is applied.
    """
    msg = str(exc).lower()
    mentions_capital_field = any(field in msg for field in _CAPITAL_FIELDS)
    return mentions_capital_field and (
        "schema cache" in msg or "column" in msg or "42703" in msg or "could not find" in msg
    )


def _strip_capital_fields(payload: dict) -> dict:
    return {k: v for k, v in payload.items() if k not in _CAPITAL_FIELDS}


def _authed_client(access_token_override: Optional[str] = None):
    """Return a Supabase client that has the caller's JWT attached.

    Two modes:

    * **Streamlit (no override):** reads the current user's JWT from
      ``session.access_token()`` and attaches it to the module-cached
      singleton.

    * **FastAPI (explicit override):** builds a fresh per-call client
      bound to the supplied token. Avoids cross-request JWT pollution
      when the backend serves multiple users in one process.
    """
    if access_token_override:
        return get_supabase(access_token=access_token_override)
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


def list_portfolios(access_token: Optional[str] = None) -> list[dict]:
    """Return all portfolios owned by the caller, default first.

    Pass ``access_token`` from a FastAPI route so the query is RLS-
    filtered to the JWT holder. Streamlit callers omit it.
    """
    sb = _authed_client(access_token_override=access_token)
    resp = (
        sb.table("portfolios")
        .select("*")
        .order("is_default", desc=True)
        .order("created_at", desc=True)
        .execute()
    )
    return resp.data or []


def get_default_portfolio(access_token: Optional[str] = None) -> Optional[dict]:
    """Return the caller's default portfolio, or None if unset.

    See ``list_portfolios`` for the access-token contract.
    """
    sb = _authed_client(access_token_override=access_token)
    resp = sb.table("portfolios").select("*").eq("is_default", True).limit(1).execute()
    rows = resp.data or []
    return rows[0] if rows else None


def get_portfolio(portfolio_id: str, access_token: Optional[str] = None) -> Optional[dict]:
    """Return one owned portfolio by id, or None when RLS hides it."""
    sb = _authed_client(access_token_override=access_token)
    resp = sb.table("portfolios").select("*").eq("id", portfolio_id).limit(1).execute()
    rows = resp.data or []
    return rows[0] if rows else None


def create_portfolio(
    name: str,
    holdings: dict,
    margin_loan: float = 0.0,
    contributed_capital: float = 0.0,
    cash_balance: float = 0.0,
    is_default: bool = False,
    access_token: Optional[str] = None,
) -> dict:
    """Insert a new portfolio. user_id is set server-side via DEFAULT auth.uid()
    (configured in the migration), so we don't pass it from the client.

    Pass ``access_token`` from a FastAPI route so Supabase RLS sees
    the caller's identity. Streamlit callers omit it (session-bound)."""
    sb = _authed_client(access_token_override=access_token)

    if is_default:
        # Demote any existing default first — Postgres trigger could do this
        # transactionally, but a 2-step write is simpler and the race window
        # is irrelevant for a single user.
        sb.table("portfolios").update({"is_default": False}).eq("is_default", True).execute()

    payload = {
        "name": name,
        "holdings": _sanitize_holdings(holdings),
        "margin_loan": _finite_or_zero(margin_loan),
        "contributed_capital": _finite_or_zero(contributed_capital),
        "cash_balance": _finite_or_zero(cash_balance),
        "is_default": is_default,
    }
    try:
        resp = sb.table("portfolios").insert(payload).execute()
    except Exception as exc:
        if not _is_missing_capital_column_error(exc):
            raise
        resp = sb.table("portfolios").insert(_strip_capital_fields(payload)).execute()
    rows = resp.data or []
    if not rows:
        raise AuthError("Insert returned no row — check RLS policy.")
    return rows[0]


def update_portfolio(portfolio_id: str, *, access_token: Optional[str] = None, **fields) -> dict:
    """Patch fields on a single portfolio. RLS prevents touching others' rows.

    Keyword-only ``access_token`` is the FastAPI passthrough; Streamlit
    callers continue to omit it and use the session-bound singleton."""
    allowed = {
        "name",
        "holdings",
        "margin_loan",
        "contributed_capital",
        "cash_balance",
        "is_default",
    }
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"Cannot update fields: {bad}")

    # Sanitize numeric/JSON fields so PostgREST never sees NaN/Inf.
    if "holdings" in fields and fields["holdings"] is not None:
        fields["holdings"] = _sanitize_holdings(fields["holdings"])
    if "margin_loan" in fields and fields["margin_loan"] is not None:
        fields["margin_loan"] = _finite_or_zero(fields["margin_loan"])
    if "contributed_capital" in fields and fields["contributed_capital"] is not None:
        fields["contributed_capital"] = _finite_or_zero(fields["contributed_capital"])
    if "cash_balance" in fields and fields["cash_balance"] is not None:
        fields["cash_balance"] = _finite_or_zero(fields["cash_balance"])

    sb = _authed_client(access_token_override=access_token)
    if fields.get("is_default"):
        sb.table("portfolios").update({"is_default": False}).eq("is_default", True).neq(
            "id", portfolio_id
        ).execute()

    try:
        resp = sb.table("portfolios").update(fields).eq("id", portfolio_id).execute()
    except Exception as exc:
        if not _is_missing_capital_column_error(exc):
            raise
        legacy_fields = _strip_capital_fields(fields)
        if not legacy_fields:
            raise AuthError(
                "Portfolio capital fields are not deployed in Supabase yet. "
                "Run migration 0003_portfolio_capital.sql before saving principal/cash."
            ) from exc
        resp = sb.table("portfolios").update(legacy_fields).eq("id", portfolio_id).execute()
    rows = resp.data or []
    if not rows:
        raise AuthError("No row updated — wrong id or RLS blocked you.")
    return rows[0]


def delete_portfolio(portfolio_id: str, access_token: Optional[str] = None) -> None:
    """Delete a single portfolio. RLS prevents deleting others' rows."""
    sb = _authed_client(access_token_override=access_token)
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
