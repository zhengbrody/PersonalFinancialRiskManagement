"""Tests for shared UI helpers — focused on the rendered markup
contract so the SaaS pages don't accidentally drift into inconsistent
empty states.

We patch ``streamlit`` with a ``MagicMock`` (same pattern as
``test_shared_sidebar.py``) so the helpers can be imported and exercised
without a real ScriptRunContext.
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def components_module(monkeypatch):
    """Reload ``ui.components`` against a mocked Streamlit module.

    Reload (not just patch) so module-level imports of ``streamlit`` see
    the mock — otherwise ``st.markdown`` etc. would still be the real
    Streamlit functions and would raise outside a script run.
    """
    fake_st = MagicMock()
    fake_st.session_state = {}
    fake_st.secrets.get.return_value = ""
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    sys.modules.pop("ui.components", None)
    module = importlib.import_module("ui.components")
    return module, fake_st


# ── render_empty_state ───────────────────────────────────────────────


def test_render_empty_state_emits_title_and_description(components_module):
    module, fake_st = components_module

    module.render_empty_state(
        title="No analysis yet",
        description="Run analysis to populate this page.",
    )

    fake_st.markdown.assert_called_once()
    html = fake_st.markdown.call_args.args[0]
    # Both pieces of copy must end up in the rendered HTML so users see
    # the headline and the supporting sentence.
    assert "No analysis yet" in html
    assert "Run analysis to populate this page." in html
    # No action hint passed → the divider/hint chunk must not appear.
    assert "border-top:" not in html
    # Helper renders single-line HTML on purpose; markdown's 4-space
    # code-block trap bites if any line starts with indentation.
    assert fake_st.markdown.call_args.kwargs.get("unsafe_allow_html") is True


def test_render_empty_state_includes_action_hint_when_provided(components_module):
    module, fake_st = components_module

    module.render_empty_state(
        title="Empty",
        description="Body copy.",
        action_hint="Takes ~5 seconds.",
    )

    html = fake_st.markdown.call_args.args[0]
    assert "Takes ~5 seconds." in html
    assert "border-top:" in html  # the divider above the hint row


# ── render_analysis_required ─────────────────────────────────────────


def test_render_analysis_required_personalises_title_and_describes(components_module):
    module, fake_st = components_module

    module.render_analysis_required(
        "Risk",
        "VaR, drawdown and stress tests live here.",
    )

    # Outer card uses render_empty_state, which calls st.markdown ONCE.
    fake_st.markdown.assert_called_once()
    html = fake_st.markdown.call_args.args[0]
    assert "No analysis yet for Risk" in html
    assert "VaR, drawdown and stress tests live here." in html
    # CTA copy must mention the sidebar's actual button label so the
    # user can find it without poking around.
    assert "Refresh &amp; Run Analysis" in html or "Refresh & Run Analysis" in html


def test_render_analysis_required_emits_page_link_to_dashboard(components_module):
    module, fake_st = components_module

    module.render_analysis_required(
        "Overview",
        "Hero KPIs and charts here.",
    )

    # The "Go to Dashboard" page link is the recovery action — without
    # it the user is stuck on an empty page wondering what to click.
    fake_st.page_link.assert_called_once()
    args, kwargs = fake_st.page_link.call_args
    assert args[0] == "app.py"
    assert "Dashboard" in kwargs.get("label", "")


def test_render_analysis_required_swallows_page_link_failures(components_module):
    """Older Streamlit versions lack ``st.page_link``; the helper must
    still render the dark card and not raise."""
    module, fake_st = components_module
    fake_st.page_link.side_effect = AttributeError("page_link unavailable")

    module.render_analysis_required("Portfolio Actions", "Optimizer lives here.")

    fake_st.markdown.assert_called_once()  # the card still rendered
