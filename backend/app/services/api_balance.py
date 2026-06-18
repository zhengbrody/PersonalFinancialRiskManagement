"""Owner /admin "API balance" card — remaining LLM credit per provider.

DeepSeek exposes a real balance API (`/user/balance`) → live, exact remaining.
Anthropic does NOT expose a remaining-balance API, so the owner records the
Claude credit they topped up (config.anthropic_topup_usd) and we count down our
TRACKED Claude spend since `anthropic_topup_since` → an estimate (only counts
spend through this app). Cached so the dashboard can poll without hammering
DeepSeek. Everything fail-soft: a blip degrades to "unknown", never a 500.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, TypedDict

import httpx

from ..core.config import Settings, get_settings


class ProviderBalance(TypedDict, total=False):
    """One provider's balance-card row. The shape is partial by branch — a
    fail-soft / unconfigured result omits the figure keys — so every field is
    optional (``total=False``). Runtime is still a plain dict (same JSON on the
    wire as before); the annotation only lets MyPy catch a typo'd key here."""

    provider: str
    configured: bool
    source: str  # "live" (DeepSeek) | "estimate" (Claude)
    status: str  # "ok" | "warn" | "critical" | "unknown"
    low: bool
    currency: str
    remaining: float
    topped_up: float
    granted: float
    spent: float
    pct: float | None
    since: str
    set_via: str  # "dashboard" | "env"
    is_available: bool
    error: str


class Balances(TypedDict):
    deepseek: ProviderBalance
    anthropic: ProviderBalance


_CACHE_TTL = 60.0
_cached_at = 0.0
_cached: Balances | None = None


def _start_of_month_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()


def _f(v: Any) -> float:
    try:
        return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def _deepseek(s: Settings) -> ProviderBalance:
    """Live DeepSeek balance. `total_balance` is the available remaining;
    low-balance is an absolute floor in the account currency."""
    if not s.deepseek_api_key:
        return {"provider": "DeepSeek", "configured": False, "source": "live", "status": "unknown"}
    try:
        r = httpx.get(
            s.deepseek_balance_url,
            headers={"Authorization": f"Bearer {s.deepseek_api_key}", "Accept": "application/json"},
            timeout=10.0,
        )
        r.raise_for_status()
        body = r.json()
        info = (body.get("balance_infos") or [{}])[0]
        remaining = _f(info.get("total_balance"))
        floor = float(s.deepseek_low_balance or 0.0)
        status = "critical" if remaining < floor * 0.4 else "warn" if remaining < floor else "ok"
        return {
            "provider": "DeepSeek",
            "configured": True,
            "source": "live",
            "currency": info.get("currency") or "",
            "is_available": bool(body.get("is_available", True)),
            "remaining": remaining,
            "topped_up": _f(info.get("topped_up_balance")),
            "granted": _f(info.get("granted_balance")),
            "status": status,
            "low": status != "ok",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "provider": "DeepSeek",
            "configured": True,
            "source": "live",
            "status": "unknown",
            "low": False,
            "error": type(exc).__name__,
        }


def _anthropic(s: Settings) -> ProviderBalance:
    """Claude estimate: balance snapshot − tracked Claude spend since it was set.
    Prefers the owner's DASHBOARD-set balance (no env / restart) and counts spend
    from when they set it; falls back to the env (`ANTHROPIC_TOPUP_USD/SINCE`)."""
    dash = None
    try:
        from libs.billing.usage import get_anthropic_topup

        dash = get_anthropic_topup()
    except Exception:  # noqa: BLE001
        dash = None

    if dash and float(dash.get("balance") or 0.0) > 0:
        topup = float(dash["balance"])
        since = dash.get("set_at") or _start_of_month_iso()
        set_via = "dashboard"
    else:
        topup = float(s.anthropic_topup_usd or 0.0)
        since = s.anthropic_topup_since or _start_of_month_iso()
        set_via = "env"

    if topup <= 0:
        return {
            "provider": "Claude (Anthropic)",
            "configured": False,
            "source": "estimate",
            "status": "unknown",
        }
    try:
        from libs.billing.usage import get_cost_since_for_model_prefix

        spent = float(get_cost_since_for_model_prefix(since, "claude"))
    except Exception:  # noqa: BLE001
        spent = 0.0
    remaining = max(0.0, topup - spent)
    pct = remaining / topup if topup > 0 else None
    status = (
        "critical"
        if pct is not None and pct < s.anthropic_critical_pct
        else "warn" if pct is not None and pct < s.anthropic_warn_pct else "ok"
    )
    return {
        "provider": "Claude (Anthropic)",
        "configured": True,
        "source": "estimate",
        "currency": "USD",
        "topped_up": topup,
        "spent": spent,
        "remaining": remaining,
        "pct": pct,
        "since": since,
        "set_via": set_via,
        "status": status,
        "low": status != "ok",
    }


def balances() -> Balances:
    """Combined provider balances for the owner card. Cached 60s (the card polls;
    balances don't move second-to-second, and this protects DeepSeek's free-tier
    rate limit)."""
    global _cached_at, _cached
    now = time.time()
    if _cached is not None and now - _cached_at < _CACHE_TTL:
        return _cached
    s = get_settings()
    data: Balances = {"deepseek": _deepseek(s), "anthropic": _anthropic(s)}
    _cached_at = now
    _cached = data
    return data


def invalidate() -> None:
    """Drop the cache so the next read reflects a just-set Claude balance."""
    global _cached_at, _cached
    _cached_at = 0.0
    _cached = None
