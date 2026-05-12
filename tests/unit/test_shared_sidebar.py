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
