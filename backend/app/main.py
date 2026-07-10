"""FastAPI app instance for MindMarket — Phase 1.

Run locally::

    uvicorn backend.app.main:app --reload --port 8000

This file ONLY wires things up; every behaviour lives in a child
module (``core/`` for cross-cutting concerns, ``api/v1/`` for routes).
"""

from __future__ import annotations

import logging
import os
import sys
import time

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from .api.v1 import (
    account,
    billing,
    copilot,
    data,
    digest,
    feedback,
    health,
    institutions,
    macro,
    market,
    ml,
    options,
    portfolios,
    public_risk,
    quant,
    regime_summary,
    reports,
    research,
    risk,
)
from .core.config import get_settings
from .core.cors import cors_kwargs
from .core.responses import (
    APIError,
    api_error_handler,
    http_exception_handler,
    not_found_handler,
    validation_exception_handler,
)


def _running_under_pytest() -> bool:
    """Hard guard for monitoring. Local shells can inherit production env vars;
    pytest/TestClient must never emit production Sentry events.

    ``PYTEST_CURRENT_TEST`` is only set *during* a test, not while the module-level
    ``app = create_app()`` runs at import/collection time, and ``sys.argv[0]`` is
    ``__main__.py`` (not "pytest") under ``python -m pytest`` — so neither alone is
    enough. ``"pytest" in sys.modules`` is true the moment pytest is the runner,
    regardless of how it was invoked, and covers the import-time init path."""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    if "pytest" in sys.modules:
        return True
    return any("pytest" in os.path.basename(arg) for arg in sys.argv)


class MetricsMiddleware:
    """Pure-ASGI request-metrics middleware.

    Records ``method · matched-route · status · latency`` into the in-process
    ``services.metrics`` registry for the owner live-activity dashboard. Written
    as raw ASGI (not Starlette's ``BaseHTTPMiddleware``) on purpose: that base
    class buffers the response body, which would break the Copilot SSE stream.
    This wrapper only intercepts ``http.response.start`` to read the status and
    times the call — the body bytes stream straight through untouched."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        from .services import metrics

        start = time.perf_counter()
        status = {"code": 500}

        async def _send(message):
            if message.get("type") == "http.response.start":
                status["code"] = message.get("status", 500)
            await send(message)

        try:
            await self.app(scope, receive, _send)
        finally:
            # ``scope["route"]`` is populated by Starlette's router during the
            # call above, so it's available here. Use the route TEMPLATE
            # (`/portfolios/{id}`) to bound cardinality; fall back to raw path.
            route = scope.get("route")
            path = getattr(route, "path", None) or scope.get("path", "?")
            metrics.record_request(
                scope.get("method", "?"),
                path,
                status["code"],
                (time.perf_counter() - start) * 1000.0,
            )


def _quiet_expected_provider_noise() -> None:
    """Free upstreams can log expected misses at ERROR level (Yahoo crumb,
    delisted symbols). Routes already return partial data + warnings; avoid
    turning provider log spam into Sentry issues."""
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def _maybe_init_sentry(settings) -> None:
    """Initialise Sentry — PRODUCTION ONLY, so dev/CI/test never send events.
    The FastAPI integration (sentry-sdk[fastapi]) auto-captures unhandled 500s.
    Errors-only (no perf tracing) to keep cost bounded. Never raises."""
    if _running_under_pytest() or settings.environment != "production" or not settings.sentry_dsn:
        return
    try:
        import sentry_sdk

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            release=settings.app_version,
            traces_sample_rate=0.0,  # error tracking only for now
            send_default_pii=False,  # don't ship user PII to Sentry
            # Privacy Policy: error reports carry stack traces + request
            # metadata, NEVER request bodies (a failing POST /copilot/chat
            # would otherwise attach the user's prompt text).
            max_request_body_size="never",
        )
    except Exception:  # noqa: BLE001 - monitoring must never break boot
        pass


def create_app() -> FastAPI:
    """Build a fresh FastAPI app. Factory pattern lets tests spin
    up an isolated app with a swapped Settings instance, instead of
    importing the module-level ``app`` and inheriting its config."""
    settings = get_settings()
    _quiet_expected_provider_noise()
    _maybe_init_sentry(settings)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        # OpenAPI docs are useful in dev; locked behind the deploy
        # boundary in production (Caddy can refuse /docs externally).
        docs_url="/docs",
        redoc_url=None,
        openapi_url="/openapi.json",
    )

    # CORS first — same kwargs hand-built in core.cors so the
    # production allow-list is auditable in one place.
    app.add_middleware(CORSMiddleware, **cors_kwargs(settings))

    # Live request metrics (in-process counters → owner /admin/metrics). Cheap,
    # fail-soft, streaming-safe (pure ASGI). Added after CORS so CORS preflights
    # are still counted.
    app.add_middleware(MetricsMiddleware)

    # Routers. Each router carries its own ``prefix`` and ``tags`` so
    # this file stays a directory of imports.
    app.include_router(health.router)
    app.include_router(account.router)
    app.include_router(public_risk.router)
    app.include_router(risk.router)
    app.include_router(portfolios.router)
    app.include_router(market.router)
    app.include_router(macro.router)
    app.include_router(regime_summary.router)
    app.include_router(billing.router)
    app.include_router(copilot.router)
    app.include_router(quant.router)
    app.include_router(options.router)
    app.include_router(research.router)
    app.include_router(reports.router)
    app.include_router(institutions.router)
    app.include_router(feedback.router)
    app.include_router(data.router)
    app.include_router(ml.router)
    app.include_router(digest.router)

    # Envelope-aware exception handlers. Order matters: register the
    # narrower types first so FastAPI's resolver picks them over the
    # generic Exception fallback.
    app.add_exception_handler(APIError, api_error_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)
    # Starlette emits a bare 404 response (not an HTTPException) when no
    # route matches — register a status-code handler so unknown paths
    # still produce our envelope.
    app.add_exception_handler(404, not_found_handler)

    return app


# Module-level instance for ``uvicorn backend.app.main:app``. Tests
# build their own via ``create_app()`` to keep isolation tight.
app = create_app()
