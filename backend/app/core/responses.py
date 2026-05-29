"""Response envelope helpers — the API contract from ADR-0004.

Every endpoint MUST return either ``ok(data, ...)`` or raise
``APIError``. Routers don't construct raw dicts.

Envelope shape::

    {
      "data":  <serialisable payload>  | null,
      "error": { "code", "message", "details" } | null,
      "meta":  { "request_id", "elapsed_ms" }
    }

Why this matters
----------------
Frontends (Next.js Phase 2) write a single ``apiFetch<T>()`` wrapper
that knows how to unwrap this envelope. Without a strict contract the
wrapper grows per-endpoint specials and the typed React Query layer
breaks. Pinning the shape now saves us that mess later.
"""

from __future__ import annotations

import math
import time
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


def _scrub_nans(value: Any) -> Any:
    """Replace ``NaN`` / ``Inf`` floats with ``None`` recursively.

    Starlette's ``JSONResponse`` calls ``json.dumps`` with
    ``allow_nan=False`` (per RFC 8259, NaN is not valid JSON). When a
    quant endpoint emits NaN — e.g. a beta that's undefined because no
    benchmark was supplied — we'd otherwise crash with a 500 *inside*
    the response renderer, which is too late for the envelope wrapper
    to catch.

    Walk the payload once at ``ok()`` time so every endpoint is safe.
    """
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {k: _scrub_nans(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_nans(v) for v in value]
    if isinstance(value, tuple):
        return [_scrub_nans(v) for v in value]
    return value


# ── error model ────────────────────────────────────────────────────


@dataclass(frozen=True)
class APIError(Exception):
    """Application-level error that maps to an envelope payload.

    Always carries an HTTP status, a short ``code`` string callers
    can switch on (``"unauthorized"``, ``"validation_failed"`` …),
    and a human message. The ``details`` dict is for structured
    context (e.g. ``{"field": "weights", "issue": "must sum to 1"}``).
    """

    status: int
    code: str
    message: str
    details: dict[str, Any] | None = None

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details or {},
        }


# Convenience constructors so call-sites read naturally.
def bad_request(message: str, **details: Any) -> APIError:
    return APIError(status=400, code="bad_request", message=message, details=details or None)


def unauthorized(message: str = "Authentication required.", **details: Any) -> APIError:
    return APIError(status=401, code="unauthorized", message=message, details=details or None)


def forbidden(message: str = "Access denied.", **details: Any) -> APIError:
    return APIError(status=403, code="forbidden", message=message, details=details or None)


def not_found(message: str = "Resource not found.", **details: Any) -> APIError:
    return APIError(status=404, code="not_found", message=message, details=details or None)


def unprocessable(message: str, **details: Any) -> APIError:
    return APIError(status=422, code="unprocessable", message=message, details=details or None)


def server_error(message: str = "Internal error.", **details: Any) -> APIError:
    return APIError(status=500, code="server_error", message=message, details=details or None)


# ── envelope helpers ───────────────────────────────────────────────


def _meta(request: Request | None = None, *, started_at: float | None = None) -> dict[str, Any]:
    """Build the ``meta`` block.

    ``request_id`` prefers the ``X-Request-Id`` header (so a Next.js
    client can correlate logs); otherwise we mint a uuid4. ``elapsed_ms``
    is computed from ``started_at`` (a ``time.perf_counter()`` value
    captured at the top of the route) when present.
    """
    request_id: str
    if request is not None:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    else:
        request_id = str(uuid.uuid4())

    meta: dict[str, Any] = {"request_id": request_id}
    if started_at is not None:
        meta["elapsed_ms"] = int((time.perf_counter() - started_at) * 1000)
    return meta


def ok(
    data: Any,
    *,
    request: Request | None = None,
    started_at: float | None = None,
    status_code: int = 200,
) -> JSONResponse:
    """Return a successful envelope. Pass ``started_at = time.perf_counter()``
    captured at the top of the route to get ``meta.elapsed_ms`` for free."""
    body = {
        "data": _scrub_nans(data),
        "error": None,
        "meta": _meta(request, started_at=started_at),
    }
    return JSONResponse(content=body, status_code=status_code)


def fail(
    error: APIError,
    *,
    request: Request | None = None,
    started_at: float | None = None,
) -> JSONResponse:
    """Return an error envelope at the HTTPstatus the error carries."""
    body = {
        "data": None,
        "error": error.to_payload(),
        "meta": _meta(request, started_at=started_at),
    }
    return JSONResponse(content=body, status_code=error.status)


# ── exception handlers (wired in main.py) ──────────────────────────


async def api_error_handler(request: Request, exc: APIError) -> JSONResponse:
    """Catch every ``raise APIError(...)`` and emit the envelope."""
    return fail(exc, request=request)


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """Bridge FastAPI's built-in ``HTTPException`` (raised by
    dependencies and validators) into our envelope.

    Without this, dependency-raised 401s would emit FastAPI's default
    ``{"detail": "..."}`` shape and break the Next.js apiFetch wrapper.
    """
    err = APIError(
        status=exc.status_code,
        code=_status_to_code(exc.status_code),
        message=str(exc.detail) if exc.detail else "Request failed.",
    )
    return fail(err, request=request)


async def validation_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Re-shape Pydantic / FastAPI request-validation errors into our
    envelope. We hand back the validator-emitted ``errors()`` list as
    ``details`` so the frontend can highlight the offending field.

    Note: this catches ``RequestValidationError``; importing it lazily
    keeps the module independently importable from a notebook without
    a FastAPI install.
    """
    try:
        # Pydantic v2's errors() can embed the offending ``input`` value
        # which may be a model instance (not JSON serialisable). Drop it
        # — the loc/msg/type tuple is what the frontend uses anyway.
        errors_list = exc.errors() if hasattr(exc, "errors") else []
        errors_list = [
            {k: v for k, v in e.items() if k != "input" and k != "ctx"} for e in errors_list
        ]
    except Exception:
        errors_list = []
    err = APIError(
        status=422,
        code="validation_failed",
        message="One or more fields failed validation.",
        details={"errors": errors_list},
    )
    return fail(err, request=request)


async def not_found_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch Starlette's bare 404 (raised when no route matches) and
    re-shape it into our envelope. Without this, unknown paths return
    Starlette's default ``{"detail": "Not Found"}`` shape."""
    err = APIError(status=404, code="not_found", message="Resource not found.")
    return fail(err, request=request)


def _status_to_code(status: int) -> str:
    return {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "unprocessable",
        429: "rate_limited",
        500: "server_error",
        502: "bad_gateway",
        503: "service_unavailable",
    }.get(status, "error")
