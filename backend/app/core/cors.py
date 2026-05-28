"""Environment-aware CORS configuration.

Returned as a kwargs dict so ``main.py`` does the actual
``app.add_middleware(CORSMiddleware, **cors_kwargs(...))`` — keeping
FastAPI imports out of this module so settings + responses stay
import-cheap (handy for tests / docs generation).
"""

from __future__ import annotations

from typing import Any

from .config import Settings


def cors_kwargs(settings: Settings) -> dict[str, Any]:
    """Build the CORSMiddleware kwargs dict.

    Rules:
      * Production: only origins from ``settings.allowed_origins``.
        Empty list is acceptable and produces a 403 for any
        cross-origin request — that's a feature, not a bug, when
        the deploy is mis-configured.
      * Dev / staging: localhost + 127.0.0.1 on the Next.js dev port.
        We do NOT use ``allow_origin_regex`` because regexes silently
        catch typos like ``localhost:3001`` if a dev moves the port.
      * Methods + headers: allowed list is explicit (no ``"*"``); we
        only allow what an authenticated SaaS frontend needs.
    """
    origins = settings.allowed_origins
    return {
        "allow_origins": origins,
        "allow_credentials": True,
        "allow_methods": ["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        "allow_headers": [
            "Authorization",
            "Content-Type",
            "X-Request-Id",
        ],
        # Surface request-id back so the frontend can correlate logs.
        "expose_headers": ["X-Request-Id"],
        "max_age": 600,
    }
