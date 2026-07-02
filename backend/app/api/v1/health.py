"""``GET /api/v1/health`` — public liveness probe.

Public per ADR-0004 (no auth dep). Returns the app's deployed
version + environment + a coarse "do core modules import cleanly?"
check so a broken deploy fails this endpoint before serving real
traffic.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request, Response

from ...core.config import Settings, get_settings
from ...core.responses import ok

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.head("/health", include_in_schema=False)
def health_head() -> Response:
    """HEAD liveness — uptime monitors (UptimeRobot etc.) default to HEAD,
    and FastAPI GET-only routes answer 405 to it (caught live by the first
    monitor alert, 2026-07-01). Bodyless 200 = process is up and routing;
    the GET below remains the real import-sanity probe.
    """
    return Response(status_code=200)


@router.get("/health", summary="Liveness + import sanity")
def health(request: Request, settings: Settings = Depends(get_settings)):
    """Return a coarse health snapshot.

    Imports the load-bearing internal modules so a broken deploy
    (missing dep, broken import path, syntax error in a transitive)
    surfaces at ``/health`` instead of at the first real call.
    The imports are intentionally re-done per call rather than at
    module load — that way a hot patch + reload doesn't need a
    process restart to be visible here.
    """
    started = time.perf_counter()

    import_ok = True
    import_error: str | None = None
    try:
        # These are the modules every Phase-1 endpoint depends on.
        # If any of them fail to import, the deploy is broken.
        import engine.quant  # noqa: F401
        import libs.analysis.equity_research  # noqa: F401
        import libs.auth.portfolios  # noqa: F401
        import libs.risk.action_cards  # noqa: F401
        import libs.risk.confidence  # noqa: F401
    except Exception as exc:  # pragma: no cover - tested via monkeypatch
        import_ok = False
        import_error = f"{type(exc).__name__}: {exc}"

    return ok(
        {
            "status": "ok" if import_ok else "degraded",
            "app": settings.app_name,
            "version": settings.app_version,
            "environment": settings.environment,
            "modules_importable": import_ok,
            "import_error": import_error,
        },
        request=request,
        started_at=started,
    )
