"""Persist the Supabase refresh_token in a browser cookie.

Why this exists
---------------
Streamlit's ``st.session_state`` is per-Streamlit-session — it dies
when the user closes the tab OR navigates fully off-domain (e.g.
Stripe Checkout). Without persistence, every Stripe round-trip silently
logs the user out, and any browser restart forces them to sign in
again.

We pick the refresh_token (not the access_token) for persistence
because:
  * Refresh tokens are long-lived (Supabase default: 30 days, rotated
    on use) — perfect for "remember me" UX.
  * Access tokens expire in 1 hour; storing them is pointless.
  * On every page load, ``load_and_restore()`` exchanges the refresh
    token for a fresh access token via Supabase, so we never use a
    stale access token.

Security notes
--------------
- The cookie is NOT httpOnly. Streamlit's cookie wrappers run in the
  browser, so they need JS access. A successful XSS on this app could
  read the token; the mitigation is the standard Streamlit defenses
  (we already render only sanitized HTML through `unsafe_allow_html`
  blocks we control).
- ``secure=True`` + ``same_site="Lax"`` so it only travels over HTTPS
  and survives top-level navigation back from Stripe (Lax allows
  GET-style returns, blocks third-party POST). Strict would break the
  Stripe-return restore.
- Expiry: 30 days, matching Supabase's default refresh-token lifetime.
  When the refresh token itself expires, we clear the cookie and
  surface a normal sign-in prompt.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

_logger = logging.getLogger(__name__)

# Versioned cookie name so we can rotate without colliding with stale
# bytes in users' browsers — bump if the storage format changes.
_COOKIE_NAME = "mm_auth_v1"
_COOKIE_DAYS = 30


def _cookies():
    """Return the EncryptedCookieManager singleton, or None if unavailable.

    Wrapped in a try/except so the rest of the auth layer keeps working
    when extra_streamlit_components isn't installed (e.g. CI containers
    that skip the optional dep).
    """
    try:
        import extra_streamlit_components as stx
        import streamlit as st
    except Exception as e:
        _logger.warning("cookie_persist: extra-streamlit-components missing: %s", e)
        return None

    # CookieManager renders an invisible iframe each call. Cache it in
    # session_state so we don't spawn N copies per rerun (each spawn
    # logs a warning and slows things down).
    key = "_auth_cookie_manager"
    if key not in st.session_state:
        # `key=` is required by stx to keep the underlying component
        # stable across reruns.
        st.session_state[key] = stx.CookieManager(key="mm_auth_cookies")
    return st.session_state[key]


def save_refresh_token(refresh_token: str) -> None:
    """Persist the refresh_token to a cookie so future page loads can
    restore the session.

    Idempotent: writing the same value twice is fine — Streamlit just
    sets the cookie header again.
    """
    if not refresh_token:
        return
    cm = _cookies()
    if cm is None:
        return
    try:
        cm.set(
            _COOKIE_NAME,
            refresh_token,
            expires_at=datetime.now(timezone.utc) + timedelta(days=_COOKIE_DAYS),
            # Lax is REQUIRED so the cookie is sent when the user clicks
            # a link from a Stripe domain back to ours. Strict would
            # strip the cookie on that hop and re-log the user out.
            same_site="lax",
            secure=True,
            key="auth_cookie_set",
        )
    except Exception as e:
        _logger.warning("cookie_persist.save_failed: %s", e)


def load_refresh_token() -> Optional[str]:
    """Return the persisted refresh_token, or None if no cookie exists."""
    cm = _cookies()
    if cm is None:
        return None
    try:
        # get() on first run returns None — the cookie iframe needs one
        # Streamlit rerun cycle to deliver the actual value. That's OK:
        # the next call within the same script run will see it once the
        # iframe has reported back.
        val = cm.get(_COOKIE_NAME)
        return val if isinstance(val, str) and val else None
    except Exception as e:
        _logger.warning("cookie_persist.load_failed: %s", e)
        return None


def clear_refresh_token() -> None:
    """Delete the cookie. Called on explicit sign-out."""
    cm = _cookies()
    if cm is None:
        return
    try:
        cm.delete(_COOKIE_NAME, key="auth_cookie_delete")
    except Exception as e:
        _logger.warning("cookie_persist.clear_failed: %s", e)


_FLAG_TRIED = "_auth_cookie_restore_attempted"


def try_restore_session() -> bool:
    """Read the cookie, exchange the refresh token for a fresh access
    token, and hydrate ``st.session_state``.

    Returns True if a session was restored, False otherwise. Idempotent:
    safe to call on every page load; the Supabase call is skipped when
    session_state already has a logged-in user.

    First-render quirk
    ------------------
    ``extra-streamlit-components`` CookieManager renders an invisible
    iframe to read ``document.cookie``. On the FIRST script run after a
    full page load, the iframe hasn't yet reported the cookie value back
    to Python — so ``load_refresh_token()`` returns None even when the
    cookie genuinely exists in the browser.

    To survive this, we ``st.rerun()`` exactly once when we get an empty
    cookie on first attempt; the iframe will have populated by then.
    The ``_FLAG_TRIED`` session-state flag prevents an infinite rerun
    loop for genuinely-signed-out users.
    """
    import streamlit as st

    if st.session_state.get("_auth_user") is not None:
        # Already signed in via session_state — nothing to do. Clear the
        # retry flag so the next genuine logout/login cycle gets a fresh
        # chance to rerun once.
        st.session_state.pop(_FLAG_TRIED, None)
        return True

    rt = load_refresh_token()
    if not rt:
        # No cookie value YET. Could mean (a) the iframe hasn't reported
        # back yet, or (b) the user really has no cookie. Try once more
        # via a single rerun; after that, accept they're signed out.
        if not st.session_state.get(_FLAG_TRIED):
            st.session_state[_FLAG_TRIED] = True
            st.rerun()
        return False

    try:
        from .client import get_supabase

        sb = get_supabase()
        # refresh_session() validates the refresh_token AND returns a
        # brand-new {access_token, refresh_token, user} triple. We swap
        # the rotated refresh_token back into the cookie so users don't
        # get logged out after one round-trip.
        resp = sb.auth.refresh_session(rt)
        session = getattr(resp, "session", None)
        user = getattr(resp, "user", None)
        if session is None or user is None:
            # Refresh token expired or was revoked — clear the bad cookie.
            clear_refresh_token()
            return False
        st.session_state["_auth_user"] = {
            "id": user.id,
            "email": user.email,
            "user_metadata": getattr(user, "user_metadata", {}) or {},
            "created_at": getattr(user, "created_at", None),
        }
        st.session_state["_auth_access_token"] = session.access_token
        st.session_state["_auth_refresh_token"] = session.refresh_token
        st.session_state.pop(_FLAG_TRIED, None)
        # Rotate cookie to the new refresh token so the next restore
        # uses a fresh one (Supabase issues a new refresh token on each
        # successful exchange).
        save_refresh_token(session.refresh_token)
        return True
    except Exception as e:
        _logger.info("cookie_persist.restore_failed: %s", e)
        # Stale or revoked token — strip the cookie so the user gets a
        # clean sign-in prompt instead of an endless retry loop.
        clear_refresh_token()
        return False
