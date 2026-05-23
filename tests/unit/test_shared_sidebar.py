"""Regression tests for sidebar analysis routing."""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def sidebar_module(monkeypatch):
    fake_st = MagicMock()
    fake_st.session_state = {}
    fake_st.secrets.get.return_value = ""
    fake_st.switch_page = MagicMock()
    fake_st.rerun = MagicMock()

    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    sys.modules.pop("ui.shared_sidebar", None)

    module = importlib.import_module("ui.shared_sidebar")
    return module, fake_st


def test_queue_analysis_routes_to_dashboard(sidebar_module):
    module, fake_st = sidebar_module

    module._queue_analysis_and_route()

    assert fake_st.session_state["_run_trigger"] is True
    assert fake_st.session_state["_route_after_analysis"] == "pages/1_Overview.py"
    assert "_force_refresh" not in fake_st.session_state
    fake_st.switch_page.assert_called_once_with("app.py")
    fake_st.rerun.assert_not_called()


def test_queue_analysis_force_refresh_falls_back_to_rerun(sidebar_module):
    module, fake_st = sidebar_module
    fake_st.switch_page.side_effect = RuntimeError("route unavailable")

    module._queue_analysis_and_route(force_refresh=True)

    assert fake_st.session_state["_run_trigger"] is True
    assert fake_st.session_state["_route_after_analysis"] == "pages/1_Overview.py"
    assert fake_st.session_state["_force_refresh"] is True
    fake_st.switch_page.assert_called_once_with("app.py")
    fake_st.rerun.assert_called_once()


def test_public_navigation_includes_pricing(sidebar_module):
    module, _fake_st = sidebar_module

    nav_items = [item for _group, items in module._NAV_GROUPS for item in items]

    assert ("pages/11_Pricing.py", "Pricing") in nav_items


def test_public_navigation_keeps_auth_required_tools_clickable_until_login(sidebar_module):
    module, fake_st = sidebar_module

    module._render_custom_navigation()

    auth_calls = [
        call
        for call in fake_st.page_link.call_args_list
        if call.args and call.args[0] in module._AUTH_REQUIRED_NAV_PATHS
    ]
    disabled_paths = {call.args[0] for call in auth_calls if call.kwargs.get("disabled") is True}
    preview_paths = {call.args[0] for call in auth_calls if call.kwargs.get("help")}
    assert module._AUTH_REQUIRED_NAV_PATHS.isdisjoint(disabled_paths)
    assert module._AUTH_REQUIRED_NAV_PATHS.issubset(preview_paths)


def test_signed_in_navigation_unlocks_auth_required_tools(sidebar_module):
    module, fake_st = sidebar_module
    fake_st.session_state["_auth_user"] = {"id": "user-1", "email": "user@example.com"}

    module._render_custom_navigation()

    disabled_paths = {
        call.args[0]
        for call in fake_st.page_link.call_args_list
        if call.kwargs.get("disabled") is True
    }
    assert module._AUTH_REQUIRED_NAV_PATHS.isdisjoint(disabled_paths)
