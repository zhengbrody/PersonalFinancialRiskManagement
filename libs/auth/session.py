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

from typing import Optional

from .client import AuthError, get_supabase


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
    """JWT for downstream API calls (e.g. Phase 3 Lambdas with Cognito-style validation)."""
    return _ss().get(_KEY_ACCESS)


def _user_to_dict(user) -> dict:
    """Convert Supabase's User object to a JSON-friendly dict."""
    return {
        "id": user.id,
        "email": user.email,
        "user_metadata": getattr(user, "user_metadata", {}) or {},
        "created_at": getattr(user, "created_at", None),
    }
