"""
libs/auth/session.py

Per-Streamlit-session auth state. We keep the Supabase access token +
refresh token in st.session_state so reruns don't kick the user out;
on first import we attempt to restore from cookie if present.

The flow:
  1. User submits email + password via login form
  2. sign_in_with_password() calls Supabase Auth, gets {access_token,
     refresh_token, user}
  3. We store all three in st.session_state under stable keys
  4. Subsequent calls use current_user() to access the authenticated user

Limitations of Streamlit auth:
  - st.session_state is per-tab; closing the browser drops the session.
    "Remember me" requires writing to a browser cookie, which Streamlit
    doesn't natively support — Phase 3 may add streamlit-extras' cookie
    helpers if there's demand.
  - No CSRF protection out of the box. Streamlit's reactive model means
    every interaction is a new HTTP request, so CSRF tokens would need
    middleware. Acceptable risk: this is a personal-portfolio app, not
    a banking site.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from typing import Optional

from .client import AuthError, get_supabase

_logger = logging.getLogger(__name__)

# Refresh the access token once it's within this many seconds of expiring.
# Supabase JWTs default to 3600s lifetime; 60s buffer leaves room for the
# refresh round-trip while still letting most calls reuse the cached token.
_REFRESH_BUFFER_SEC = 60

# Stable keys in st.session_state. Prefix with `_auth_` so other code
# can't accidentally collide.
_KEY_USER = "_auth_user"
_KEY_ACCESS = "_auth_access_token"
_KEY_REFRESH = "_auth_refresh_token"


def _ss():
    """Lazy import streamlit so this module is importable from Lambda."""
    import streamlit as st

    return st.session_state


def is_authenticated() -> bool:
    """Cheap check — used to gate UI; doesn't validate the token's freshness."""
    return _ss().get(_KEY_USER) is not None


def current_user() -> Optional[dict]:
    """Return the cached user dict, or None.

    Shape (subset of Supabase's User):
        {"id": "...", "email": "...", "user_metadata": {...}}
    """
    return _ss().get(_KEY_USER)


def sign_up_with_password(email: str, password: str) -> dict:
    """Register a new account. Returns the user dict on success.

    Supabase by default requires email confirmation — until the user
    clicks the link in their inbox, sign-in will fail with
    "Email not confirmed". Set this in Auth → Providers → Email if you
    want to disable confirmation for dev (not recommended for production).
    """
    sb = get_supabase()
    try:
        resp = sb.auth.sign_up({"email": email, "password": password})
    except Exception as e:
        # Supabase returns AuthApiError subclass with .message; surface it.
        msg = getattr(e, "message", None) or str(e)
        raise AuthError(msg)

    if resp.user is None:
        raise AuthError("Sign-up returned no user — check Supabase logs.")

    return _user_to_dict(resp.user)


def sign_in_with_password(email: str, password: str) -> dict:
    """Authenticate. Stores tokens + user in session state. Returns user dict."""
    sb = get_supabase()
    try:
        resp = sb.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as e:
        msg = getattr(e, "message", None) or str(e)
        raise AuthError(msg)

    if resp.user is None or resp.session is None:
        raise AuthError("Login failed — server returned no session.")

    user_dict = _user_to_dict(resp.user)
    state = _ss()
    state[_KEY_USER] = user_dict
    state[_KEY_ACCESS] = resp.session.access_token
    state[_KEY_REFRESH] = resp.session.refresh_token
    return user_dict


def sign_out() -> None:
    """Clear session and revoke the token server-side."""
    state = _ss()
    if state.get(_KEY_ACCESS):
        try:
            get_supabase().auth.sign_out()
        except Exception:
            pass  # best-effort; even if the network call fails, we still clear locally
    for k in (_KEY_USER, _KEY_ACCESS, _KEY_REFRESH):
        state.pop(k, None)


def access_token() -> Optional[str]:
    """JWT for downstream API calls.

    Auto-refreshes silently when the cached token is within
    _REFRESH_BUFFER_SEC of expiry. Returns None if the user is signed out.
    """
    _maybe_refresh_token()
    return _ss().get(_KEY_ACCESS)


def _jwt_expiry(token: str) -> Optional[int]:
    """Read the `exp` claim from a JWT without verifying its signature.

    We don't need to verify here — the server will verify on every request.
    We only want to know whether to proactively refresh.
    """
    try:
        _, payload_b64, _ = token.split(".")
        padded = payload_b64 + "=" * (-len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded))
        exp = payload.get("exp")
        return int(exp) if exp is not None else None
    except Exception:
        return None


def _maybe_refresh_token() -> None:
    """Refresh the access token via the refresh token when it's near expiry.

    Without this, PostgREST starts returning 401 ~1 hour after login and
    every Supabase call silently fails until the user re-signs-in.
    """
    state = _ss()
    access = state.get(_KEY_ACCESS)
    refresh = state.get(_KEY_REFRESH)
    if not access or not refresh:
        return
    exp = _jwt_expiry(access)
    if exp is None:
        return
    if exp - int(time.time()) > _REFRESH_BUFFER_SEC:
        return
    try:
        resp = get_supabase().auth.refresh_session(refresh)
        if resp and resp.session is not None:
            state[_KEY_ACCESS] = resp.session.access_token
            state[_KEY_REFRESH] = resp.session.refresh_token
            _logger.info("auth.session.refreshed")
    except Exception as e:
        # Leave stale token in place — the next downstream 401 will surface
        # to the user, who can sign back in. Better than a silent crash.
        _logger.warning("auth.session.refresh_failed: %s", e)


def _user_to_dict(user) -> dict:
    """Convert Supabase's User object to a JSON-friendly dict."""
    return {
        "id": user.id,
        "email": user.email,
        "user_metadata": getattr(user, "user_metadata", {}) or {},
        "created_at": getattr(user, "created_at", None),
    }
