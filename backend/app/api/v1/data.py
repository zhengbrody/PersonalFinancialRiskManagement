"""``GET /api/v1/data/health`` — owner-facing data-source health.

One view of every external data provider: its role, whether it's configured,
and its live call outcomes (healthy / missing key / rate-limited / falling back
/ idle) from the in-process metrics. Reuses the provider registry + the same
``metrics`` counters the admin live-activity card reads — no new instrumentation.
Owner-gated (it reveals which provider keys are present, never their values).
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import forbidden, ok
from ...schemas.envelope import Envelope

router = APIRouter(prefix="/api/v1/data", tags=["data"])


def _configured() -> dict[str, bool]:
    from ...core.config import get_settings
    from ...services.providers import massive_provider
    from ...services.providers import registry as reg

    s = get_settings()
    return {
        reg.MASSIVE: bool(massive_provider._key()),
        reg.FMP: bool(getattr(s, "fmp_api_key", "")),
        reg.FRED: True,  # keyless public CSV
        reg.TREASURY: True,  # keyless public CSV
        reg.SEC: True,  # keyless EDGAR
        reg.YFINANCE: True,  # keyless fallback
    }


def _status(configured: bool, m: dict) -> str:
    if not configured:
        return "missing"
    if m.get("rate_limited"):
        return "rate_limited"
    if m.get("error") and not m.get("ok"):
        return "error"
    if m.get("ok"):
        return "healthy"
    return "idle"


@router.get(
    "/health",
    summary="Per-provider data-source health (owner): configured · role · live outcomes",
    response_model=Envelope[dict],
)
def data_health(request: Request, user: AuthedUser = Depends(require_user)):
    from libs.admin.status import is_owner_email

    if not is_owner_email(user.email):
        raise forbidden("Owner only.")

    started = time.perf_counter()
    from ...services import metrics
    from ...services.providers import registry as reg

    configured = _configured()
    by_name = {p["name"]: p for p in metrics.snapshot().get("providers", [])}

    providers = []
    for info in reg.registry():
        if info.kind == reg.COMPUTED:  # engine/derived/glossary aren't external sources
            continue
        m = by_name.get(info.id, {})
        conf = configured.get(info.id, True)
        providers.append(
            {
                "id": info.id,
                "label": info.label,
                "role": info.role,
                "kind": info.kind,
                "configured": conf,
                "status": _status(conf, m),
                "calls": m.get("calls", 0),
                "ok": m.get("ok", 0),
                "cache_hit": m.get("cache_hit", 0),
                "empty": m.get("empty", 0),
                "error": m.get("error", 0),
                "rate_limited": m.get("rate_limited", 0),
                "no_key": m.get("no_key", 0),
            }
        )
    # primary providers first, then by activity
    providers.sort(key=lambda p: (p["kind"] != reg.PRIMARY, -p["calls"]))

    payload = {
        "providers": providers,
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
    }
    return ok(payload, request=request, started_at=started)
