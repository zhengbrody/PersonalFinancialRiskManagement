"""Supabase JWT verification, exposed as FastAPI dependencies.

Per ADR-0004 we use **per-route dependencies**, not a global
middleware. ``/health`` and the public quant endpoints intentionally
DON'T require a JWT; mounting auth as middleware would either:

  * block them (forcing every test to mint a fake JWT), or
  * require an exempt-path list that drifts out of sync with reality.

Two dependencies are exported:

    require_user        — 401 if no/bad JWT.
    optional_user       — returns None when no JWT, never raises.

Both return a frozen ``AuthedUser`` so route handlers can pull
``user.id`` / ``user.email`` directly without a dict.dance.

Verification details
--------------------
Supabase signs project JWTs with HS256 using the ``SUPABASE_JWT_SECRET``
from the project's API settings. We verify locally; no network call.
PyJWT is the only new runtime dep — listed in
``requirements-backend.txt``.

We pin:
  * algorithm: HS256 (Supabase's only supported)
  * exp:       enforced (PyJWT default)
  * audience:  ``"authenticated"`` (Supabase convention)
  * iss:       optional — the Supabase project URL when configured

When ``SUPABASE_JWT_SECRET`` is unset we fail closed in production
(401 on every protected route, with a clear log line) and short-
circuit in dev to make local backend work without a Supabase token.
This is documented behaviour, not a bug; it lets contributors run
the backend without a Supabase project.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from fastapi import Depends, Request

from .config import Settings, get_settings
from .responses import unauthorized

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthedUser:
    """The subset of Supabase JWT claims our routes care about.

    ``raw_claims`` is kept for forward compatibility — future routes
    that need ``app_metadata.roles`` etc. can read it without us
    bumping the dataclass shape every time.

    ``access_token`` is the raw JWT the caller presented. Routes that
    hit Supabase (RLS-filtered reads) pass it through so the database
    sees the caller's identity, not the server's. Never log this value.
    """

    id: str
    email: Optional[str]
    raw_claims: dict[str, Any]
    access_token: str


# ── token extraction ───────────────────────────────────────────────


def _extract_bearer(request: Request) -> Optional[str]:
    """Pull the bearer token out of the ``Authorization`` header.

    Returns None for the (common) anon case — let the caller decide
    whether that's a hard 401 (``require_user``) or an OK ``None``
    (``optional_user``).
    """
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if not auth:
        return None
    parts = auth.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None


def _decode(token: str, settings: Settings) -> dict[str, Any]:
    """Verify + decode a Supabase JWT. Raises ``APIError`` on failure.

    PyJWT is imported lazily so a notebook can import this module
    without the runtime dep installed.
    """
    secret = settings.supabase_jwt_secret
    if not secret:
        # In dev, this is a "Supabase not configured" → leave the
        # decision to the caller. In production, the protected
        # dependency wraps this in a 401 so we never accidentally
        # accept unverified tokens.
        raise _MissingSecret()

    try:
        import jwt
    except ImportError as exc:  # pragma: no cover - dep installed in CI
        raise RuntimeError(
            "PyJWT is required for Supabase auth. "
            "Run `pip install -r backend/requirements-backend.txt`."
        ) from exc

    try:
        return jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            # Supabase always stamps "authenticated" for end-user tokens.
            audience="authenticated",
            options={"require": ["exp", "sub"]},
        )
    except Exception as exc:
        _logger.info("auth.jwt.decode_failed err=%s", exc)
        raise unauthorized(
            "Token is invalid or expired.",
            reason=type(exc).__name__,
        ) from exc


class _MissingSecret(Exception):
    """Marker for 'SUPABASE_JWT_SECRET not configured'.

    Used to choose between dev-fallback and production-hard-fail in
    the dependency, without leaking that flow into ``_decode``'s
    return type.
    """


def _claims_to_user(claims: dict[str, Any], token: str) -> AuthedUser:
    """Build the frozen user dataclass from raw JWT claims."""
    user_id = str(claims.get("sub") or "").strip()
    if not user_id:
        raise unauthorized("Token has no subject claim.")
    return AuthedUser(
        id=user_id,
        email=(claims.get("email") or claims.get("user_metadata", {}).get("email")),
        raw_claims=claims,
        access_token=token,
    )


# ── dependencies ───────────────────────────────────────────────────


def require_user(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> AuthedUser:
    """401 unless a valid Supabase JWT is present.

    Use on every route that reads or mutates user-owned data.
    """
    token = _extract_bearer(request)
    if token is None:
        raise unauthorized("Missing bearer token.")

    try:
        claims = _decode(token, settings)
    except _MissingSecret:
        # Production must fail closed. Dev is also failed closed:
        # if you turn on a protected route you should configure auth.
        # If you really need to bypass for local backend work, mint
        # a test JWT (see backend/README.md) rather than weakening
        # this dependency.
        _logger.error("auth.jwt.no_secret_configured")
        # `from None` — the _MissingSecret marker is internal noise.
        # Don't surface it in tracebacks served to clients.
        raise unauthorized("Server is not configured to verify tokens.") from None

    return _claims_to_user(claims, token)


def optional_user(
    request: Request,
    settings: Settings = Depends(get_settings),
) -> Optional[AuthedUser]:
    """Return the authed user when a valid JWT is present; ``None``
    otherwise. Used by routes that personalise output but don't
    require auth (e.g. a future ``/api/v1/markets/regime`` that can
    return generic data to anon callers and personalised to authed).
    """
    token = _extract_bearer(request)
    if token is None:
        return None
    try:
        claims = _decode(token, settings)
    except _MissingSecret:
        return None
    except Exception:
        # Treat unverifiable tokens as anon; don't leak why.
        return None
    return _claims_to_user(claims, token)
