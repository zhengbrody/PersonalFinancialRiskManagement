"""Tests for libs/auth/session.py — no real Supabase, all mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from libs.auth import client as auth_client

# ── Test scaffolding ────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_supabase_singleton():
    """Each test starts without a cached client."""
    auth_client.reset_client_cache()
    yield
    auth_client.reset_client_cache()


@pytest.fixture
def fake_streamlit(monkeypatch):
    """Provide a fake `streamlit` module with a dict-style session_state."""
    fake_st = MagicMock()
    fake_st.session_state = {}
    fake_st.secrets.get.return_value = ""

    import sys

    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    return fake_st


@pytest.fixture
def supabase_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "test-anon-key")


# ── client.get_supabase ─────────────────────────────────────────


def test_get_supabase_raises_when_unconfigured(fake_streamlit, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_ANON_KEY", raising=False)
    with pytest.raises(auth_client.AuthError, match="not configured"):
        auth_client.get_supabase()


def test_get_supabase_caches_singleton(fake_streamlit, supabase_env):
    fake_client = MagicMock()
    with patch("supabase.create_client", return_value=fake_client) as mock_create:
        a = auth_client.get_supabase()
        b = auth_client.get_supabase()
    assert a is b is fake_client
    assert mock_create.call_count == 1


def test_env_beats_streamlit_secrets(fake_streamlit, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://from-env.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "env-key")
    fake_streamlit.secrets.get.side_effect = lambda k, d="": (
        "https://from-secrets" if k == "SUPABASE_URL" else "secret-key"
    )
    with patch("supabase.create_client") as mock_create:
        auth_client.get_supabase()
    args = mock_create.call_args[0]
    assert args[0] == "https://from-env.supabase.co"
    assert args[1] == "env-key"


# ── session.sign_in_with_password ───────────────────────────────


def test_sign_in_stores_user_and_tokens(fake_streamlit, supabase_env):
    fake_user = MagicMock(id="user-123", email="x@y.com", user_metadata={}, created_at="2026-01-01")
    fake_session = MagicMock(access_token="JWT-acc", refresh_token="JWT-ref")
    fake_resp = MagicMock(user=fake_user, session=fake_session)

    fake_client = MagicMock()
    fake_client.auth.sign_in_with_password.return_value = fake_resp

    with patch("supabase.create_client", return_value=fake_client):
        from libs.auth import session as auth_session

        user = auth_session.sign_in_with_password("x@y.com", "pw12345678")

    assert user["email"] == "x@y.com"
    assert user["id"] == "user-123"
    assert fake_streamlit.session_state["_auth_user"]["email"] == "x@y.com"
    assert fake_streamlit.session_state["_auth_access_token"] == "JWT-acc"
    assert fake_streamlit.session_state["_auth_refresh_token"] == "JWT-ref"


def test_sign_in_failure_raises_authError(fake_streamlit, supabase_env):
    fake_client = MagicMock()
    err = Exception("Invalid login credentials")
    err.message = "Invalid login credentials"
    fake_client.auth.sign_in_with_password.side_effect = err

    with patch("supabase.create_client", return_value=fake_client):
        from libs.auth import session as auth_session

        with pytest.raises(auth_client.AuthError, match="Invalid login credentials"):
            auth_session.sign_in_with_password("x@y.com", "wrong")


def test_sign_out_clears_session(fake_streamlit, supabase_env):
    fake_streamlit.session_state["_auth_user"] = {"id": "u", "email": "e"}
    fake_streamlit.session_state["_auth_access_token"] = "t"
    fake_streamlit.session_state["_auth_refresh_token"] = "r"

    fake_client = MagicMock()
    with patch("supabase.create_client", return_value=fake_client):
        from libs.auth import session as auth_session

        auth_session.sign_out()

    for k in ("_auth_user", "_auth_access_token", "_auth_refresh_token"):
        assert k not in fake_streamlit.session_state
    fake_client.auth.sign_out.assert_called_once()


def test_is_authenticated_reflects_session(fake_streamlit):
    from libs.auth import session as auth_session

    assert auth_session.is_authenticated() is False
    fake_streamlit.session_state["_auth_user"] = {"id": "u", "email": "e"}
    assert auth_session.is_authenticated() is True


def test_sign_up_returns_user_pending_confirmation(fake_streamlit, supabase_env):
    """Project has Confirm Email = ON: Supabase returns user but no session."""
    fake_user = MagicMock(
        id="new-user", email="new@x.com", user_metadata={}, created_at="2026-01-01"
    )
    fake_resp = MagicMock(user=fake_user, session=None)
    fake_client = MagicMock()
    fake_client.auth.sign_up.return_value = fake_resp

    with patch("supabase.create_client", return_value=fake_client):
        from libs.auth import session as auth_session

        user = auth_session.sign_up_with_password("new@x.com", "pw12345678")

    assert user["id"] == "new-user"
    assert user["email_confirmed"] is False
    # Pending confirmation → no auto-login
    assert "_auth_user" not in fake_streamlit.session_state


def test_sign_up_auto_logs_in_when_confirm_email_disabled(fake_streamlit, supabase_env):
    """Project has Confirm Email = OFF: Supabase returns a session, and we
    write tokens to session_state so the user can immediately use the app."""
    fake_user = MagicMock(
        id="auto-user", email="a@b.com", user_metadata={}, created_at="2026-01-01"
    )
    fake_session = MagicMock(access_token="acc", refresh_token="ref")
    fake_resp = MagicMock(user=fake_user, session=fake_session)
    fake_client = MagicMock()
    fake_client.auth.sign_up.return_value = fake_resp

    with patch("supabase.create_client", return_value=fake_client):
        from libs.auth import session as auth_session

        user = auth_session.sign_up_with_password("a@b.com", "pw12345678")

    assert user["email_confirmed"] is True
    assert fake_streamlit.session_state["_auth_user"]["id"] == "auto-user"
    assert fake_streamlit.session_state["_auth_access_token"] == "acc"


def test_resend_confirmation_invokes_supabase(fake_streamlit, supabase_env):
    fake_client = MagicMock()
    with patch("supabase.create_client", return_value=fake_client):
        from libs.auth import session as auth_session

        auth_session.resend_confirmation_email("user@x.com")

    fake_client.auth.resend.assert_called_once_with({"type": "signup", "email": "user@x.com"})


def test_resend_confirmation_surfaces_auth_error(fake_streamlit, supabase_env):
    fake_client = MagicMock()
    fake_client.auth.resend.side_effect = Exception("Rate limit exceeded")
    with patch("supabase.create_client", return_value=fake_client):
        from libs.auth import session as auth_session

        with pytest.raises(auth_client.AuthError, match="Rate limit"):
            auth_session.resend_confirmation_email("user@x.com")


# ── OAuth helpers ───────────────────────────────────────────────


def test_sign_in_with_oauth_returns_authorization_url(fake_streamlit, supabase_env):
    fake_client = MagicMock()
    fake_client.auth.sign_in_with_oauth.return_value = MagicMock(
        url="https://accounts.google.com/o/oauth2/auth?..."
    )

    with patch("supabase.create_client", return_value=fake_client):
        from libs.auth import session as auth_session

        url = auth_session.sign_in_with_oauth("google", redirect_to="https://mindmarket.app")

    assert url.startswith("https://accounts.google.com/")
    fake_client.auth.sign_in_with_oauth.assert_called_once_with(
        {"provider": "google", "options": {"redirect_to": "https://mindmarket.app"}}
    )


def test_sign_in_with_oauth_raises_when_no_url_returned(fake_streamlit, supabase_env):
    fake_client = MagicMock()
    fake_client.auth.sign_in_with_oauth.return_value = MagicMock(url=None)

    with patch("supabase.create_client", return_value=fake_client):
        from libs.auth import session as auth_session

        with pytest.raises(auth_client.AuthError, match="authorization URL"):
            auth_session.sign_in_with_oauth("google")


def test_complete_oauth_with_code_writes_session(fake_streamlit, supabase_env):
    """PKCE callback: ?code=X → exchange for session → store tokens."""
    fake_user = MagicMock(
        id="g-user", email="g@x.com", user_metadata={"provider": "google"}, created_at="x"
    )
    fake_session = MagicMock(access_token="acc-pkce", refresh_token="ref-pkce")
    fake_client = MagicMock()
    fake_client.auth.exchange_code_for_session.return_value = MagicMock(
        user=fake_user, session=fake_session
    )

    with patch("supabase.create_client", return_value=fake_client):
        from libs.auth import session as auth_session

        user = auth_session.complete_oauth_with_code("supabase-auth-code-xyz")

    assert user["id"] == "g-user"
    assert fake_streamlit.session_state["_auth_user"]["email"] == "g@x.com"
    assert fake_streamlit.session_state["_auth_access_token"] == "acc-pkce"
    assert fake_streamlit.session_state["_auth_refresh_token"] == "ref-pkce"
    fake_client.auth.exchange_code_for_session.assert_called_once_with(
        {"auth_code": "supabase-auth-code-xyz"}
    )


def test_complete_oauth_with_code_rejects_empty(fake_streamlit, supabase_env):
    from libs.auth import session as auth_session

    with pytest.raises(auth_client.AuthError, match="Missing OAuth code"):
        auth_session.complete_oauth_with_code("")


def test_complete_oauth_with_code_surfaces_exchange_error(fake_streamlit, supabase_env):
    fake_client = MagicMock()
    fake_client.auth.exchange_code_for_session.side_effect = Exception("invalid_grant")

    with patch("supabase.create_client", return_value=fake_client):
        from libs.auth import session as auth_session

        with pytest.raises(auth_client.AuthError, match="invalid_grant"):
            auth_session.complete_oauth_with_code("xyz")


def test_complete_oauth_with_code_handles_missing_session(fake_streamlit, supabase_env):
    fake_client = MagicMock()
    fake_client.auth.exchange_code_for_session.return_value = MagicMock(user=None, session=None)

    with patch("supabase.create_client", return_value=fake_client):
        from libs.auth import session as auth_session

        with pytest.raises(auth_client.AuthError, match="no session"):
            auth_session.complete_oauth_with_code("xyz")


def test_hydrate_session_from_tokens_writes_state(fake_streamlit, supabase_env):
    """OAuth callback path: set_session validates the tokens server-side
    and we mirror them into st.session_state so subsequent requests are
    authed just like a password sign-in."""
    fake_user = MagicMock(
        id="g-user", email="g@x.com", user_metadata={"provider": "google"}, created_at="x"
    )
    fake_client = MagicMock()
    fake_client.auth.set_session.return_value = MagicMock(user=fake_user)

    with patch("supabase.create_client", return_value=fake_client):
        from libs.auth import session as auth_session

        user = auth_session.hydrate_session_from_tokens(
            access_token="acc-jwt", refresh_token="ref-jwt"
        )

    assert user["id"] == "g-user"
    assert fake_streamlit.session_state["_auth_user"]["email"] == "g@x.com"
    assert fake_streamlit.session_state["_auth_access_token"] == "acc-jwt"
    assert fake_streamlit.session_state["_auth_refresh_token"] == "ref-jwt"
    fake_client.auth.set_session.assert_called_once_with("acc-jwt", "ref-jwt")


def test_hydrate_session_from_tokens_rejects_empty_tokens(fake_streamlit, supabase_env):
    from libs.auth import session as auth_session

    with pytest.raises(auth_client.AuthError, match="Missing"):
        auth_session.hydrate_session_from_tokens(access_token="", refresh_token="r")


def test_hydrate_session_from_tokens_surfaces_set_session_error(fake_streamlit, supabase_env):
    fake_client = MagicMock()
    fake_client.auth.set_session.side_effect = Exception("invalid_grant")

    with patch("supabase.create_client", return_value=fake_client):
        from libs.auth import session as auth_session

        with pytest.raises(auth_client.AuthError, match="invalid_grant"):
            auth_session.hydrate_session_from_tokens("a", "b")


def _make_jwt(exp_unix: int) -> str:
    """Build a minimal unsigned JWT with the given exp claim."""
    import base64
    import json

    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp_unix}).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}."


def test_access_token_refreshes_when_near_expiry(fake_streamlit, supabase_env):
    """JWT within the refresh buffer triggers refresh_session()."""
    import time as _t

    stale = _make_jwt(int(_t.time()) + 30)  # 30s left, under the 60s buffer
    fresh = _make_jwt(int(_t.time()) + 3600)

    fake_streamlit.session_state["_auth_user"] = {"id": "u", "email": "e"}
    fake_streamlit.session_state["_auth_access_token"] = stale
    fake_streamlit.session_state["_auth_refresh_token"] = "old-refresh"

    fake_client = MagicMock()
    fake_client.auth.refresh_session.return_value = MagicMock(
        session=MagicMock(access_token=fresh, refresh_token="new-refresh"),
    )

    with patch("supabase.create_client", return_value=fake_client):
        from libs.auth import session as auth_session

        token = auth_session.access_token()

    assert token == fresh
    assert fake_streamlit.session_state["_auth_refresh_token"] == "new-refresh"
    fake_client.auth.refresh_session.assert_called_once_with("old-refresh")


def test_access_token_skips_refresh_when_far_from_expiry(fake_streamlit, supabase_env):
    """Token with plenty of lifetime left should NOT trigger a refresh round-trip."""
    import time as _t

    fresh = _make_jwt(int(_t.time()) + 3600)
    fake_streamlit.session_state["_auth_user"] = {"id": "u", "email": "e"}
    fake_streamlit.session_state["_auth_access_token"] = fresh
    fake_streamlit.session_state["_auth_refresh_token"] = "r"

    fake_client = MagicMock()
    with patch("supabase.create_client", return_value=fake_client):
        from libs.auth import session as auth_session

        token = auth_session.access_token()

    assert token == fresh
    fake_client.auth.refresh_session.assert_not_called()


def test_access_token_swallows_refresh_failure(fake_streamlit, supabase_env):
    """If refresh_session raises, fall back to the stale token rather than crash."""
    import time as _t

    stale = _make_jwt(int(_t.time()) + 5)
    fake_streamlit.session_state["_auth_user"] = {"id": "u", "email": "e"}
    fake_streamlit.session_state["_auth_access_token"] = stale
    fake_streamlit.session_state["_auth_refresh_token"] = "r"

    fake_client = MagicMock()
    fake_client.auth.refresh_session.side_effect = Exception("network")
    with patch("supabase.create_client", return_value=fake_client):
        from libs.auth import session as auth_session

        token = auth_session.access_token()

    # Stale token is returned; downstream 401 will surface, but we don't crash.
    assert token == stale
