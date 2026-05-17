"""Tests for app.call_llm()'s default system prompt baseline.

The goal of P1's prompt refactor is to make AI answers grounded and
structured. The DEFAULT system prompt (used when a caller passes
``system=""``) must:

  1. Enforce grounding rules so the LLM doesn't invent prices, VaR, etc.
  2. Stay out of the way when the caller passes their own system prompt
     (per-page digests already set tailored prompts and shouldn't get
     our defaults appended to them).

NB on import: app.py runs ``st.set_page_config(...)`` at import time.
We install a MagicMock ``streamlit`` BEFORE importing ``app`` inside
each test so that call is a no-op.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest


class _FakeSessionState(dict):
    """Streamlit session_state supports both subscript and attribute access."""

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as e:
            raise AttributeError(item) from e

    def __setattr__(self, key, value):
        self[key] = value

    def __delattr__(self, key):
        try:
            del self[key]
        except KeyError as e:
            raise AttributeError(key) from e


@pytest.fixture
def fake_streamlit(monkeypatch):
    fake_st = MagicMock()
    fake_st.session_state = _FakeSessionState()
    fake_st.secrets.get.return_value = ""
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    return fake_st


@pytest.fixture
def app_module(fake_streamlit, monkeypatch):
    # Admin mode skips the quota gate so call_llm can exercise the
    # provider call path without standing up a billing fixture.
    monkeypatch.setenv("MINDMARKET_ADMIN_MODE", "true")
    sys.modules.pop("app", None)
    import app  # noqa: E402

    return app


class _CapturingClient:
    """Anthropic client stand-in that records the kwargs of .messages.create."""

    last_call_kwargs: dict | None = None

    class _Messages:
        def create(self, **kwargs):
            _CapturingClient.last_call_kwargs = kwargs
            # Mirror anthropic.types.Message shape just enough for call_llm.
            content = MagicMock()
            content.text = "ok"
            resp = MagicMock()
            resp.content = [content]
            resp.usage = MagicMock(input_tokens=10, output_tokens=5)
            return resp

    def __init__(self, *args, **kwargs):
        self.messages = self._Messages()


def _install_fake_anthropic(monkeypatch):
    fake_anthropic = MagicMock()
    fake_anthropic.Anthropic = _CapturingClient
    monkeypatch.setitem(sys.modules, "anthropic", fake_anthropic)
    _CapturingClient.last_call_kwargs = None


# ---------------------------------------------------------------------------
# Default system prompt content
# ---------------------------------------------------------------------------


def test_default_system_prompt_includes_grounding_rules(fake_streamlit, app_module, monkeypatch):
    """When ``system=""``, the baseline grounding rules must reach the model."""
    _install_fake_anthropic(monkeypatch)
    fake_streamlit.session_state["_model_provider"] = "Anthropic Claude"
    fake_streamlit.session_state["_api_key_input"] = "sk-ant-fake"

    out = app_module.call_llm("hello", system="", max_tokens=200)

    assert out == "ok"
    assert _CapturingClient.last_call_kwargs is not None
    system_arg = _CapturingClient.last_call_kwargs.get("system", "")
    # The two contractual phrases the refactor introduced.
    assert "NEVER invent" in system_arg
    assert "data not available" in system_arg
    # The structured-output skeleton the rules describe.
    assert "Assessment" in system_arg
    assert "Evidence" in system_arg
    assert "Risks" in system_arg
    assert "Actions" in system_arg


def test_explicit_system_prompt_is_not_overridden(fake_streamlit, app_module, monkeypatch):
    """A caller-supplied system prompt must pass through verbatim — the
    page-level digests rely on their own tailored instructions and would
    contradict themselves if we appended the default grounding rules."""
    _install_fake_anthropic(monkeypatch)
    fake_streamlit.session_state["_model_provider"] = "Anthropic Claude"
    fake_streamlit.session_state["_api_key_input"] = "sk-ant-fake"

    custom = "my custom prompt — answer in Klingon"
    out = app_module.call_llm("hello", system=custom, max_tokens=200)

    assert out == "ok"
    system_arg = _CapturingClient.last_call_kwargs.get("system", "")
    # The caller's exact string is preserved at the start of the prompt.
    assert system_arg.startswith(custom)
    # And the default grounding rules are NOT injected on top of it.
    assert "NEVER invent" not in system_arg
    # (call_llm DOES append a one-line "Write the entire answer in English"
    # nudge when the custom prompt doesn't mention a language — that's
    # existing pre-refactor behavior and out of scope here. We only assert
    # that the heavy grounding ruleset doesn't leak in.)
