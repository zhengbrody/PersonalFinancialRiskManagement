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
    fake_streamlit.secrets.get.side_effect = lambda k, d="": "https://from-secrets" if k == "SUPABASE_URL" else "secret-key"
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


def test_sign_up_returns_user(fake_streamlit, supabase_env):
    fake_user = MagicMock(id="new-user", email="new@x.com", user_metadata={}, created_at="2026-01-01")
    fake_resp = MagicMock(user=fake_user)
    fake_client = MagicMock()
    fake_client.auth.sign_up.return_value = fake_resp

    with patch("supabase.create_client", return_value=fake_client):
        from libs.auth import session as auth_session
        user = auth_session.sign_up_with_password("new@x.com", "pw12345678")

    assert user["id"] == "new-user"
    # NB: sign-up does NOT auto-login (Supabase typically requires email confirm)
    assert "_auth_user" not in fake_streamlit.session_state
