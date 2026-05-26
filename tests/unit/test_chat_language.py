"""Tests for the floating chat language-matching contract + suggested
prompt chips.

The chat prompt MUST tell the LLM to answer in the user's input
language. We test the SYSTEM_PROMPT template + the _detect helper +
the per-page suggestion router — these together are what makes
"用中文" Just Work without a visible language selector.
"""

from __future__ import annotations

import importlib
import sys
from unittest.mock import MagicMock


def _load_chat_module(monkeypatch):
    """Reload ``ui.floating_chat`` against a mocked ``streamlit``.

    The module touches ``st.dialog`` at import time, so we need a fake
    streamlit installed before we can import it cleanly. Same pattern
    as test_shared_sidebar.py.
    """
    fake_st = MagicMock()
    fake_st.session_state = {}
    fake_st.secrets.get.return_value = ""
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    sys.modules.pop("ui.floating_chat", None)
    module = importlib.import_module("ui.floating_chat")
    return module, fake_st


def test_system_prompt_contains_language_rule(monkeypatch):
    module, _ = _load_chat_module(monkeypatch)
    prompt = module._SYSTEM_PROMPT
    # Must instruct the model in plain English to follow the user's
    # latest message language. We don't pin the exact wording (allow
    # the team to refine copy) but we DO require these load-bearing
    # tokens to be present.
    lower = prompt.lower()
    assert "{language}" in prompt, "Language placeholder must remain for format()"
    assert "answer" in lower or "respond" in lower
    assert "language" in lower
    assert "user" in lower
    assert "latest" in lower or "user's" in lower


def test_detect_language_picks_chinese_for_cjk_input(monkeypatch):
    module, _ = _load_chat_module(monkeypatch)
    lang = module._detect_response_language("帮我分析一下持仓风险")
    assert "chinese" in lang.lower()


def test_detect_language_defaults_to_english(monkeypatch):
    module, _ = _load_chat_module(monkeypatch)
    lang = module._detect_response_language("Where is my biggest risk?")
    assert lang.lower() == "english"


def test_detect_language_handles_empty_input(monkeypatch):
    module, _ = _load_chat_module(monkeypatch)
    # No crash, default to English.
    lang = module._detect_response_language("")
    assert lang.lower() == "english"


# ── Suggestion chips ────────────────────────────────────────────────


def test_resolve_page_suggestions_overview(monkeypatch):
    module, fake_st = _load_chat_module(monkeypatch)
    fake_st.session_state["_active_page"] = "overview"
    suggestions = module._resolve_page_suggestions()
    assert any(
        "changed" in s.lower() for s in suggestions
    ), "Overview chip set must include the 'what changed since last run' nudge."
    assert any("risk" in s.lower() for s in suggestions)


def test_resolve_page_suggestions_risk(monkeypatch):
    module, fake_st = _load_chat_module(monkeypatch)
    fake_st.session_state["_active_page"] = "risk"
    suggestions = module._resolve_page_suggestions()
    assert any("margin" in s.lower() for s in suggestions)


def test_resolve_page_suggestions_ticker_research(monkeypatch):
    module, fake_st = _load_chat_module(monkeypatch)
    fake_st.session_state["_active_page"] = "ticker_research"
    suggestions = module._resolve_page_suggestions()
    # Ticker-research chips should be about the single name being viewed.
    assert any("ticker" in s.lower() or "concentration" in s.lower() for s in suggestions)


def test_resolve_page_suggestions_falls_back_to_default(monkeypatch):
    module, fake_st = _load_chat_module(monkeypatch)
    fake_st.session_state.pop("_active_page", None)
    suggestions = module._resolve_page_suggestions()
    # When no page hint is set we get the original generic list, which
    # has at least one VaR-themed prompt.
    assert any("var" in s.lower() for s in suggestions)


def test_per_page_chip_sets_are_distinct(monkeypatch):
    """Sanity: we shouldn't ship the same chips for every page."""
    module, _ = _load_chat_module(monkeypatch)
    overview = set(module._PAGE_SUGGESTION_PROMPTS["overview"])
    risk = set(module._PAGE_SUGGESTION_PROMPTS["risk"])
    actions = set(module._PAGE_SUGGESTION_PROMPTS["portfolio_actions"])
    research = set(module._PAGE_SUGGESTION_PROMPTS["ticker_research"])
    # Each page set should contribute at least one chip not shared with
    # the others — otherwise the per-page UX is a lie.
    assert overview - (risk | actions | research)
    assert risk - (overview | actions | research)
    assert actions - (overview | risk | research)
    assert research - (overview | risk | actions)
