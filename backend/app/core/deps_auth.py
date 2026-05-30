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
Supabase projects can use either the legacy HS256 shared JWT secret or
newer asymmetric signing keys exposed through the project's JWKS URL.
We support both:

  * HS256  -> verify with ``SUPABASE_JWT_SECRET``.
  * RS/ES  -> verify with ``SUPABASE_URL/auth/v1/.well-known/jwks.json``.

We pin:
  * algorithm: only HS256, RS256, ES256
  * exp:       enforced (PyJWT default)
  * audience:  ``"authenticated"`` (Supabase convention)

If verification config is missing we fail closed: protected routes
return 401 rather than accepting unverified tokens.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

from fastapi import Depends, Request

from .config import Settings, get_settings
from .responses import service_unavailable, unauthorized

_logger = logging.getLogger(__name__)

# How long to wait on the Supabase JWKS HTTPS fetch. Without a timeout
# PyJWKClient blocks the worker thread indefinitely if Supabase is slow
# or down — one outage then exhausts the thread pool. Kept short: the
# fetched keys are cached, so this only bites on a cold key cache.
_JWKS_FETCH_TIMEOUT_S = 5.0

_HMAC_ALGS = {"HS256"}
_JWKS_ALGS = {"RS256", "ES256"}
_ALLOWED_ALGS = _HMAC_ALGS | _JWKS_ALGS


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


def _jwks_url(settings: Settings) -> str:
    """Return the Supabase JWKS URL for asymmetric JWT verification."""
    base = (settings.supabase_url or "").rstrip("/")
    if not base:
        raise _MissingSecret("SUPABASE_URL is required for JWKS JWT verification.")
    return f"{base}/auth/v1/.well-known/jwks.json"


@lru_cache(maxsize=8)
def _jwk_client(jwks_url: str):
    """Cached PyJWT JWKS client. The client itself caches fetched keys.

    ``timeout`` bounds the underlying ``urllib`` fetch so a slow/down
    Supabase JWKS endpoint can't hang the request thread indefinitely.
    """
    import jwt

    return jwt.PyJWKClient(jwks_url, timeout=_JWKS_FETCH_TIMEOUT_S)


class _JWKSUnavailable(Exception):
    """Marker: the JWKS endpoint couldn't be reached/fetched in time.

    Distinct from a bad token — this is a transient upstream failure
    that must surface as 503, not 401, so clients retry and monitoring
    doesn't misread an outage as a wave of auth rejections."""


def _decode(token: str, settings: Settings) -> dict[str, Any]:
    """Verify + decode a Supabase JWT. Raises ``APIError`` on failure.

    PyJWT is imported lazily so a notebook can import this module
    without the runtime dep installed.
    """
    try:
        import jwt
    except ImportError as exc:  # pragma: no cover - dep installed in CI
        raise RuntimeError(
            "PyJWT is required for Supabase auth. "
            "Run `pip install -r backend/requirements-backend.txt`."
        ) from exc

    try:
        header = jwt.get_unverified_header(token)
    except Exception as exc:
        _logger.info("auth.jwt.bad_header err=%s", exc)
        raise unauthorized(
            "Token is invalid or expired.",
            reason=type(exc).__name__,
        ) from exc

    alg = str(header.get("alg") or "")
    if alg not in _ALLOWED_ALGS:
        _logger.info("auth.jwt.unsupported_alg alg=%s", alg)
        raise unauthorized("Token is invalid or expired.", reason="UnsupportedAlgorithm")

    try:
        if alg in _HMAC_ALGS:
            secret = settings.supabase_jwt_secret
            if not secret:
                raise _MissingSecret("SUPABASE_JWT_SECRET is required for HS256 tokens.")
            key = secret
        else:
            # Fetching the signing key hits the network (Supabase JWKS).
            # A timeout/connection error here is an UPSTREAM outage, not
            # an invalid token — isolate it so it becomes a 503, not a
            # misleading 401. PyJWKClient raises PyJWKClientError (a
            # subclass of PyJWTError) on fetch failure; urllib may raise
            # URLError/socket.timeout under it.
            try:
                signing_key = _jwk_client(_jwks_url(settings)).get_signing_key_from_jwt(token)
            except _MissingSecret:
                raise
            except jwt.exceptions.PyJWKClientError as exc:
                _logger.warning("auth.jwks.fetch_failed err=%s", exc)
                raise _JWKSUnavailable(str(exc)) from exc
            except (OSError, TimeoutError) as exc:
                _logger.warning("auth.jwks.network_error err=%s", exc)
                raise _JWKSUnavailable(str(exc)) from exc
            key = signing_key.key

        return jwt.decode(
            token,
            key,
            algorithms=[alg],
            # Supabase always stamps "authenticated" for end-user tokens.
            audience="authenticated",
            options={"require": ["exp", "sub"]},
        )
    except (_MissingSecret, _JWKSUnavailable):
        # Config-missing and upstream-outage are NOT "bad token" — let
        # them propagate so the dependency can map them to 401-config /
        # 503 respectively, not a generic 401.
        raise
    except Exception as exc:
        _logger.info("auth.jwt.decode_failed err=%s", exc)
        raise unauthorized(
            "Token is invalid or expired.",
            reason=type(exc).__name__,
        ) from exc


class _MissingSecret(Exception):
    """Marker for auth verification config missing.

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
    except _JWKSUnavailable:
        # Upstream (Supabase JWKS) is unreachable — we can't say whether
        # the token is valid. That's a transient 503, not a 401: clients
        # should retry, and a real auth rejection shouldn't be masked by
        # an outage (or vice-versa).
        raise service_unavailable("Unable to verify credentials right now; please retry.") from None

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
    except _JWKSUnavailable:
        # A JWKS outage is NOT "anon" — silently downgrading a signed-in
        # caller to anonymous would serve them the wrong (generic) data.
        # Surface the transient failure so they retry.
        raise service_unavailable("Unable to verify credentials right now; please retry.") from None
    except Exception:
        # A genuinely bad/expired token on an optional route → treat as
        # anon; don't leak why.
        return None
    return _claims_to_user(claims, token)
