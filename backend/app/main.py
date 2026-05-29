"""FastAPI app instance for MindMarket — Phase 1.

Run locally::

    uvicorn backend.app.main:app --reload --port 8000

This file ONLY wires things up; every behaviour lives in a child
module (``core/`` for cross-cutting concerns, ``api/v1/`` for routes).
"""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from .api.v1 import equity, health, market, portfolios, risk
from .core.config import get_settings
from .core.cors import cors_kwargs
from .core.responses import (
    APIError,
    api_error_handler,
    http_exception_handler,
    not_found_handler,
    validation_exception_handler,
)


def create_app() -> FastAPI:
    """Build a fresh FastAPI app. Factory pattern lets tests spin
    up an isolated app with a swapped Settings instance, instead of
    importing the module-level ``app`` and inheriting its config."""
    settings = get_settings()

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

    # Routers. Each router carries its own ``prefix`` and ``tags`` so
    # this file stays a directory of imports.
    app.include_router(health.router)
    app.include_router(risk.router)
    app.include_router(equity.router)
    app.include_router(portfolios.router)
    app.include_router(market.router)

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
