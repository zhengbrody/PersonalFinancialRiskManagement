"""``GET /api/v1/health`` — public liveness probe (+ opt-in deep readiness).

Public per ADR-0004 (no auth dep). The bare GET returns the app's deployed
version + environment + a coarse "do core modules import cleanly?" check so a
broken deploy fails this endpoint before serving real traffic.

``?deep=1`` adds a timeboxed (~2s) READINESS view: Supabase REST reachability
+ required-config presence + core-service initialization. Deep mode answers
"is the product actually usable", not just "is the process up".

⚠️ The Docker healthcheck (compose.split.yml) hits the SHALLOW GET and must
NEVER be pointed at ``?deep=1`` — a transient Supabase blip would flip the
container unhealthy and risk a restart loop for an outage the container can't
fix. External uptime monitors are the right consumer of deep mode.

Response discipline: booleans / status strings / latency numbers / categories
ONLY — never a secret value, URL token, user datum, or raw exception text.
"""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.request

from fastapi import APIRouter, Depends, Query, Request, Response

from ...core.config import Settings, get_settings
from ...core.responses import ok
from ...schemas.envelope import Envelope

router = APIRouter(prefix="/api/v1", tags=["health"])

# Deep-probe timebox: ONE dependency ping bounded at 2s keeps the whole deep
# response inside ~2s even when Supabase blackholes the connection.
_DEEP_PROBE_TIMEOUT_S = 2.0


@router.head("/health", include_in_schema=False)
def health_head() -> Response:
    """HEAD liveness — uptime monitors (UptimeRobot etc.) default to HEAD,
    and FastAPI GET-only routes answer 405 to it (caught live by the first
    monitor alert, 2026-07-01). Bodyless 200 = process is up and routing;
    the GET below remains the real import-sanity probe.
    """
    return Response(status_code=200)


def _import_check() -> tuple[bool, str | None]:
    """Import the load-bearing internal modules so a broken deploy (missing
    dep, broken import path, syntax error in a transitive) surfaces here
    instead of at the first real call. Re-done per call intentionally."""
    try:
        # These are the modules every Phase-1 endpoint depends on.
        import engine.quant  # noqa: F401
        import libs.analysis.equity_research  # noqa: F401
        import libs.auth.portfolios  # noqa: F401
        import libs.risk.action_cards  # noqa: F401
        import libs.risk.confidence  # noqa: F401

        return True, None
    except Exception as exc:  # pragma: no cover - tested via monkeypatch
        return False, f"{type(exc).__name__}: {exc}"


def _probe_supabase_rest(settings: Settings) -> dict:
    """Timeboxed reachability ping against Supabase's PUBLIC JWKS endpoint
    (unauthenticated — no service key required, no user data involved).

    Reachability semantics: ANY HTTP response < 500 proves Supabase REST is
    up and routable (401/403 = reachable, auth simply not attempted); 5xx,
    timeout, DNS/conn failure = NOT reachable. Only booleans + latency +
    an exception CLASS NAME ever leave this function — never a URL, token,
    or raw error text.
    """
    base = (settings.supabase_url or "").rstrip("/")
    if not base:
        return {
            "name": "supabase_rest",
            "category": "dependency",
            "ok": False,
            "reason": "not_configured",
        }
    url = f"{base}/auth/v1/.well-known/jwks.json"
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=_DEEP_PROBE_TIMEOUT_S) as resp:
            status = int(getattr(resp, "status", 200) or 200)
    except urllib.error.HTTPError as exc:
        status = int(exc.code)
    except Exception as exc:  # timeout / DNS / connection refused / TLS
        return {
            "name": "supabase_rest",
            "category": "dependency",
            "ok": False,
            "reason": type(exc).__name__,
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        }
    return {
        "name": "supabase_rest",
        "category": "dependency",
        "ok": status < 500,
        "status_class": f"{status // 100}xx",
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
    }


def _deep_checks(settings: Settings, import_ok: bool) -> tuple[list[dict], bool]:
    """The deep readiness view. Returns (checks, all_required_ok).

    Config checks are PRESENCE booleans only (the key names are public
    knowledge — compose.split.yml documents them; the VALUES never appear).
    ``required=False`` rows inform without degrading overall status.
    """
    checks: list[dict] = []

    probe = _probe_supabase_rest(settings)
    checks.append({**probe, "required": True})

    auth_ok = bool(settings.supabase_url) and bool(
        settings.supabase_jwt_secret or settings.supabase_anon_key
    )
    checks.append({"name": "auth_config", "category": "config", "ok": auth_ok, "required": True})
    # Service-role key has NO Settings field (read from env by admin_client) —
    # account deletion / digest / admin cost reads are dead without it (the
    # gap found live 2026-07-14).
    checks.append(
        {
            "name": "service_role_config",
            "category": "config",
            "ok": bool(os.environ.get("SUPABASE_SERVICE_KEY", "").strip()),
            "required": True,
        }
    )
    checks.append(
        {
            "name": "llm_config",
            "category": "config",
            "ok": bool(settings.deepseek_api_key or settings.anthropic_api_key),
            "required": False,  # AI degrades to deterministic templates by design
        }
    )
    checks.append(
        {
            "name": "market_data_config",
            "category": "config",
            "ok": bool(os.environ.get("MASSIVE_API_KEY", "").strip()),
            "required": False,  # yfinance fallback keeps prices flowing
        }
    )
    checks.append(
        {"name": "core_modules", "category": "runtime", "ok": import_ok, "required": True}
    )

    all_required_ok = all(c["ok"] for c in checks if c.get("required"))
    return checks, all_required_ok


@router.get(
    "/health",
    summary="Liveness + import sanity (+ ?deep=1 readiness)",
    response_model=Envelope[dict],
)
def health(
    request: Request,
    settings: Settings = Depends(get_settings),
    deep: int = Query(0, description="1 = add timeboxed dependency/config readiness checks"),
):
    """Return a coarse health snapshot; ``?deep=1`` adds readiness checks.

    Deep mode returns HTTP 503 when a REQUIRED check fails (degraded) so an
    external monitor can alert on "healthy container, unusable product".
    The shallow path keeps its original contract (always 200 + status field).
    """
    started = time.perf_counter()

    import_ok, import_error = _import_check()

    payload: dict = {
        "status": "ok" if import_ok else "degraded",
        "app": settings.app_name,
        "version": settings.app_version,
        "environment": settings.environment,
        "modules_importable": import_ok,
        "import_error": import_error,
    }

    status_code = 200
    if deep:
        checks, all_required_ok = _deep_checks(settings, import_ok)
        payload["deep"] = True
        payload["checks"] = checks
        payload["status"] = "ok" if (import_ok and all_required_ok) else "degraded"
        if not (import_ok and all_required_ok):
            status_code = 503

    return ok(payload, request=request, started_at=started, status_code=status_code)
