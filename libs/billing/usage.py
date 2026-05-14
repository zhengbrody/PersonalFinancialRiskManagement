"""
libs/billing/usage.py

Quota check + usage recording over Supabase. Pure functions; the
Streamlit / Lambda caller decides what to do on QuotaExceeded.

Plan tiers below MUST stay in sync with the constraints in
supabase/migrations/0002_billing.sql (the `plan` text CHECK).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

# ── Plan tiers ───────────────────────────────────────────────────
# Monthly caps. None means "unlimited within fair use" (we still
# log events for cost monitoring).
PLAN_LIMITS: dict[str, dict[str, Optional[int]]] = {
    "free": {
        "analysis": 2,
        "chat": 2,
        "tool_call": None,  # not rate-limited, just logged
    },
    "basic": {
        "analysis": 30,
        "chat": 100,
        "tool_call": None,
    },
    "pro": {
        "analysis": 150,
        "chat": 500,
        "tool_call": None,
    },
    "owner": {
        "analysis": None,
        "chat": None,
        "tool_call": None,
    },
}

PLAN_PRICING: dict[str, dict[str, Any]] = {
    "free": {"price_usd_per_month": 0, "label": "Free"},
    "basic": {"price_usd_per_month": 10, "label": "Basic"},
    "pro": {"price_usd_per_month": 29, "label": "Pro"},
    "owner": {"price_usd_per_month": 0, "label": "Owner"},
}


class QuotaExceeded(RuntimeError):
    """Raised when a user has hit their monthly cap for the given kind.

    The caller should display the remaining-count + upgrade CTA;
    DO NOT silently swallow this — letting the call go through means
    we eat the LLM/data-API cost without a paid customer.
    """

    def __init__(self, kind: str, plan: str, used: int, limit: int):
        self.kind = kind
        self.plan = plan
        self.used = used
        self.limit = limit
        super().__init__(
            f"Monthly {kind} limit reached for {plan} plan: {used}/{limit}. "
            "Paid plans are coming soon."
        )


class CostLimitExceeded(RuntimeError):
    """Raised when owner-configured daily/monthly AI spend guardrails are hit."""

    def __init__(
        self,
        *,
        scope: str,
        current_cost: float,
        estimated_cost: float,
        limit: float,
    ):
        self.scope = scope
        self.current_cost = current_cost
        self.estimated_cost = estimated_cost
        self.limit = limit
        super().__init__(
            f"{scope.capitalize()} AI cost limit reached: "
            f"${current_cost + estimated_cost:.4f}/${limit:.2f}. "
            "Please retry later or contact MindMarket AI for beta access."
        )


# ── Internal helpers ─────────────────────────────────────────────


def _client():
    """Lazy-import the auth-bound Supabase client.

    Wrapped in a function so this module is importable from Lambda
    even if it never gets called there.
    """
    from libs.auth.client import get_supabase
    from libs.auth.session import access_token

    sb = get_supabase()
    token = access_token()
    if token:
        sb.postgrest.auth(token)
    return sb


def _cost_client() -> tuple[Any, bool]:
    """Return a client for spend guardrails.

    Prefer service-role so daily/monthly cost limits protect total platform
    spend. If unavailable, fall back to the current user's RLS-scoped rows.
    """
    try:
        from libs.auth.admin_client import get_supabase_admin

        return get_supabase_admin(), True
    except Exception:
        return _client(), False


def _start_of_month_iso() -> str:
    """Return ISO-8601 midnight of the current month UTC. The view
    uses date_trunc('month', created_at), matching this."""
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def _start_of_day_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def _secret_float(name: str, default: float) -> float:
    try:
        from libs.admin.status import read_secret

        raw = read_secret(name)
        return float(raw) if raw not in (None, "") else default
    except Exception:
        return default


def is_owner_user(user_id: str) -> bool:
    """True when the current Streamlit session belongs to the owner allow-list."""
    try:
        from libs.admin.status import is_owner_email
        from libs.auth.session import current_user

        user = current_user()
        return bool(user and user.get("id") == user_id and is_owner_email(user.get("email")))
    except Exception:
        return False


# ── Public API ───────────────────────────────────────────────────


def get_user_plan(user_id: str) -> str:
    """Return the user's current plan name. Defaults to 'free' on any
    DB failure — fail-closed for billing means free is the safe path."""
    if is_owner_user(user_id):
        return "owner"
    try:
        resp = _client().table("profiles").select("plan").eq("user_id", user_id).limit(1).execute()
        rows = resp.data or []
        if rows and rows[0].get("plan") in PLAN_LIMITS:
            return rows[0]["plan"]
    except Exception:
        pass
    return "free"


def get_cost_since(user_id: str, since_iso: str) -> float:
    """Return summed usage_events.cost_usd since an ISO timestamp.

    Supabase's PostgREST client is intentionally kept simple here: fetch the
    recent cost rows and sum in Python. Cost logs are tiny at current scale,
    and this avoids depending on RPC functions before the schema needs them.
    """
    try:
        sb, global_scope = _cost_client()
        query = sb.table("usage_events").select("cost_usd").gte("created_at", since_iso)
        if not global_scope:
            query = query.eq("user_id", user_id)
        resp = query.limit(10_000).execute()
        total = 0.0
        for row in resp.data or []:
            try:
                total += float(row.get("cost_usd") or 0.0)
            except (TypeError, ValueError):
                continue
        return total
    except Exception:
        # Fail closed for cost controls; if we cannot read spend, do not
        # accidentally allow unlimited paid-provider calls.
        return float("inf")


def get_spend_status(user_id: str, *, estimated_cost_usd: float = 0.0) -> dict[str, Any]:
    """Return current daily/monthly spend against owner-configured limits."""
    daily_limit = _secret_float("MINDMARKET_DAILY_COST_LIMIT_USD", 2.0)
    monthly_limit = _secret_float("MINDMARKET_MONTHLY_COST_LIMIT_USD", 50.0)
    try:
        _, global_scope = _cost_client()
    except Exception:
        global_scope = False
    today_cost = get_cost_since(user_id, _start_of_day_iso())
    month_cost = get_cost_since(user_id, _start_of_month_iso())
    estimate = max(0.0, float(estimated_cost_usd or 0.0))
    return {
        "scope": "all_users" if global_scope else "current_user",
        "daily": {
            "used": today_cost,
            "limit": daily_limit,
            "projected": today_cost + estimate,
            "exceeded": today_cost + estimate >= daily_limit,
        },
        "monthly": {
            "used": month_cost,
            "limit": monthly_limit,
            "projected": month_cost + estimate,
            "exceeded": month_cost + estimate >= monthly_limit,
        },
    }


def check_spend_limit(user_id: str, *, estimated_cost_usd: float = 0.0) -> dict[str, Any]:
    """Raise if the next AI/data-provider call would exceed spend limits."""
    if is_owner_user(user_id):
        return get_spend_status(user_id, estimated_cost_usd=estimated_cost_usd)

    status = get_spend_status(user_id, estimated_cost_usd=estimated_cost_usd)
    if status["daily"]["exceeded"]:
        raise CostLimitExceeded(
            scope="daily",
            current_cost=float(status["daily"]["used"]),
            estimated_cost=max(0.0, float(estimated_cost_usd or 0.0)),
            limit=float(status["daily"]["limit"]),
        )
    if status["monthly"]["exceeded"]:
        raise CostLimitExceeded(
            scope="monthly",
            current_cost=float(status["monthly"]["used"]),
            estimated_cost=max(0.0, float(estimated_cost_usd or 0.0)),
            limit=float(status["monthly"]["limit"]),
        )
    return status


def get_used_this_month(user_id: str, kind: str) -> int:
    """Count usage_events of `kind` for `user_id` in the current month."""
    try:
        resp = (
            _client()
            .table("usage_events")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("kind", kind)
            .gte("created_at", _start_of_month_iso())
            .execute()
        )
        return resp.count or 0
    except Exception:
        # If we can't read usage, assume worst-case (over-quota) so we
        # don't accidentally let a user exceed silently. They'll see
        # the upgrade CTA — annoying but safe.
        return 999_999


def get_quota_status(user_id: str) -> dict[str, Any]:
    """Return a dict suitable for direct rendering in the sidebar.

    Shape:
      {
        "plan":  "free",
        "label": "Free",
        "kinds": {
          "analysis": {"used": 1, "limit": 2, "remaining": 1, "exhausted": False},
          "chat":     {"used": 0, "limit": 2, "remaining": 2, "exhausted": False},
        },
      }
    """
    plan = get_user_plan(user_id)
    out: dict[str, Any] = {
        "plan": plan,
        "label": PLAN_PRICING[plan]["label"],
        "kinds": {},
    }
    for kind, limit in PLAN_LIMITS[plan].items():
        if kind == "tool_call":
            continue  # not user-visible
        used = get_used_this_month(user_id, kind)
        if limit is None:
            out["kinds"][kind] = {
                "used": used,
                "limit": None,
                "remaining": None,
                "exhausted": False,
            }
        else:
            remaining = max(0, limit - used)
            out["kinds"][kind] = {
                "used": used,
                "limit": limit,
                "remaining": remaining,
                "exhausted": used >= limit,
            }
    return out


def record_event(
    user_id: str,
    kind: str,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
    metadata: Optional[dict] = None,
) -> None:
    """Insert a usage_events row. Caller responsible for cost calc."""
    try:
        _client().table("usage_events").insert(
            {
                "user_id": user_id,
                "kind": kind,
                "provider": provider,
                "model": model,
                "tokens_in": int(tokens_in),
                "tokens_out": int(tokens_out),
                "cost_usd": float(cost_usd),
                "metadata": metadata or {},
            }
        ).execute()
    except Exception as e:
        # Logging failure shouldn't break the user-visible action.
        # Caller's fallback: rely on app logs to detect this.
        import logging

        logging.getLogger(__name__).warning("usage.record_failed kind=%s err=%s", kind, e)


def check_quota(
    user_id: str,
    kind: str,
    *,
    estimated_cost_usd: float = 0.0,
) -> dict[str, Any]:
    """Check quota without recording an event.

    Use this when the caller needs to log the final outcome after the
    operation finishes. This avoids pre-recording a "successful" event for a
    provider call that later fails.
    """
    plan = get_user_plan(user_id)
    limit = PLAN_LIMITS.get(plan, {}).get(kind)

    if limit is None:
        check_spend_limit(user_id, estimated_cost_usd=estimated_cost_usd)
        return {
            "plan": plan,
            "used": get_used_this_month(user_id, kind),
            "limit": None,
            "remaining": None,
            "exhausted": False,
        }

    used = get_used_this_month(user_id, kind)
    if used >= limit:
        raise QuotaExceeded(kind=kind, plan=plan, used=used, limit=limit)
    check_spend_limit(user_id, estimated_cost_usd=estimated_cost_usd)
    return {
        "plan": plan,
        "used": used,
        "limit": limit,
        "remaining": max(0, limit - used),
        "exhausted": False,
    }


def check_and_consume(
    user_id: str,
    kind: str,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
    metadata: Optional[dict] = None,
) -> dict[str, Any]:
    """Check the user's quota and record this event.

    Raises QuotaExceeded BEFORE recording if over the cap.
    Returns the post-call quota status for caller to render
    (e.g. "1 of 2 used this month").

    The caller invokes this BEFORE making the LLM/data API call:

        try:
            status = check_and_consume(user_id, "chat", model="claude-...")
        except QuotaExceeded as e:
            st.error(str(e))
            st.stop()
        # ... actually call the LLM ...

    NB: there's a small race window between the count and the insert.
    See module docstring.
    """
    check_quota(user_id, kind, estimated_cost_usd=cost_usd)

    record_event(
        user_id,
        kind,
        provider=provider,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=cost_usd,
        metadata=metadata,
    )
    return get_quota_status(user_id)
