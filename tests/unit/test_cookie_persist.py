"""Tests for browser-cookie auth persistence used across Stripe redirects."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock


def _install_fake_cookie_runtime(monkeypatch, cookie_manager):
    fake_st = SimpleNamespace(session_state={}, rerun=MagicMock())
    fake_stx = SimpleNamespace(CookieManager=MagicMock(return_value=cookie_manager))
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setitem(sys.modules, "extra_streamlit_components", fake_stx)
    return fake_st, fake_stx


def test_save_refresh_token_uses_long_lived_lax_secure_cookie(monkeypatch):
    cm = MagicMock()
    _install_fake_cookie_runtime(monkeypatch, cm)

    from libs.auth.cookie_persist import save_refresh_token

    before = datetime.now(timezone.utc)
    save_refresh_token("refresh-token")

    cm.set.assert_called_once()
    args, kwargs = cm.set.call_args
    assert args[:2] == ("mm_auth_v1", "refresh-token")
    assert kwargs["same_site"] == "lax"
    assert kwargs["secure"] is True
    assert 89 <= (kwargs["expires_at"] - before).days <= 90


def test_load_refresh_token_decodes_component_cookie(monkeypatch):
    cm = MagicMock()
    cm.get.return_value = "refresh%2Etoken%2Fwith%2Bchars"
    _install_fake_cookie_runtime(monkeypatch, cm)

    from libs.auth.cookie_persist import load_refresh_token

    assert load_refresh_token() == "refresh.token/with+chars"


def test_load_refresh_token_uses_http_cookie_header_before_component(monkeypatch):
    fake_st = SimpleNamespace(
        session_state={},
        context=SimpleNamespace(headers={"cookie": "other=1; mm_auth_v1=refresh%2Ftoken"}),
    )
    fake_stx = SimpleNamespace(CookieManager=MagicMock())
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    monkeypatch.setitem(sys.modules, "extra_streamlit_components", fake_stx)

    from libs.auth.cookie_persist import load_refresh_token

    assert load_refresh_token() == "refresh/token"
    fake_stx.CookieManager.assert_not_called()


def test_try_restore_session_hydrates_state_and_rotates_cookie(monkeypatch):
    cm = MagicMock()
    cm.get.return_value = "old-refresh"
    fake_st, _fake_stx = _install_fake_cookie_runtime(monkeypatch, cm)

    fake_user = MagicMock(
        id="user-1",
        email="user@example.com",
        user_metadata={"name": "User"},
        created_at="2026-01-01",
    )
    fake_session = MagicMock(access_token="new-access", refresh_token="new-refresh")
    fake_client = MagicMock()
    fake_client.auth.refresh_session.return_value = MagicMock(
        user=fake_user,
        session=fake_session,
    )
    monkeypatch.setattr("libs.auth.client.get_supabase", lambda: fake_client)

    from libs.auth.cookie_persist import try_restore_session

    assert try_restore_session() is True
    assert fake_st.session_state["_auth_user"]["email"] == "user@example.com"
    assert fake_st.session_state["_auth_access_token"] == "new-access"
    assert fake_st.session_state["_auth_refresh_token"] == "new-refresh"
    fake_client.auth.refresh_session.assert_called_once_with("old-refresh")
    cm.set.assert_called_once()
    assert cm.set.call_args.args[:2] == ("mm_auth_v1", "new-refresh")
