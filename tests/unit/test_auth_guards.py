"""Tests for Streamlit auth guards."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def guards_module(monkeypatch):
    fake_st = MagicMock()
    fake_st.session_state = {}
    fake_st.stop.side_effect = RuntimeError("streamlit stopped")
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    sys.modules.pop("libs.auth.guards", None)
    module = importlib.import_module("libs.auth.guards")
    return module, fake_st


def test_require_auth_page_stops_for_anonymous_user(guards_module):
    module, fake_st = guards_module

    with pytest.raises(RuntimeError, match="streamlit stopped"):
        module.require_auth_page("Ticker Research")

    fake_st.warning.assert_called_once_with("Sign in to access Ticker Research.")
    fake_st.page_link.assert_called_once_with("pages/0_Login.py", label="Go to Login")
    fake_st.stop.assert_called_once()


def test_require_auth_page_allows_signed_in_user(guards_module):
    module, fake_st = guards_module
    fake_st.session_state["_auth_user"] = {"id": "user-1", "email": "user@example.com"}

    module.require_auth_page("Ticker Research")

    fake_st.warning.assert_not_called()
    fake_st.page_link.assert_not_called()
    fake_st.stop.assert_not_called()
