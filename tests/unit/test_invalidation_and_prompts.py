"""Tests for the cross-cutting invariants set on 2026-05-26:

1. Editing a portfolio MUST invalidate every cache so subsequent
   features (Risk Analysis, AI Chat, action cards, deep equity
   analysis, page-level AI digests) immediately reflect the new
   state.
2. The analyst prompts MUST keep their missing-data protocol so
   "缺数据专业分析" works — the model anchors to sector norms and
   labels the gap, never says "insufficient data" as a cop-out.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

# ── invalidation helper (pages/0_Portfolios.py) ─────────────────────


@pytest.fixture
def fake_session_state(monkeypatch):
    """Pull pages/0_Portfolios._invalidate_analysis_cache out via
    a small importlib dance so it operates on our mocked
    session_state instead of a real Streamlit one."""
    state: dict = {}
    fake_st = MagicMock()
    fake_st.session_state = state
    fake_st.secrets.get.return_value = ""
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    # Load the page module's text and exec _just the helper_ in a
    # namespace that has our fake streamlit injected. We can't import
    # pages/0_Portfolios.py directly because it executes UI at top
    # level.
    import pathlib

    src = pathlib.Path("pages/0_Portfolios.py").read_text()

    # Extract the helper function source manually — keeps the test
    # robust if the page's top-level imports change.
    needle = "def _invalidate_analysis_cache"
    start = src.find(needle)
    assert start >= 0, "Helper not found; did the function get renamed?"
    # Find the next top-level def to bound the helper body.
    end = src.find("\ndef ", start + 1)
    assert end > start

    helper_src = src[start:end]

    # The helper references `from logging_config import get_logger`
    # inside a try/except, so we can run it bare. We DO need `st` and
    # access to session_state — both come via fake_st.
    namespace: dict = {"st": fake_st}
    exec(helper_src, namespace)
    invalidate = namespace["_invalidate_analysis_cache"]
    return invalidate, state, fake_st


def test_invalidate_sets_force_refresh(fake_session_state):
    invalidate, state, _ = fake_session_state
    invalidate()
    assert state["_force_refresh"] is True


def test_invalidate_pops_analysis_cache_keys(fake_session_state):
    invalidate, state, _ = fake_session_state
    state["_last_cache_key"] = ("old",)
    state["_last_analysis_ts"] = 12345
    state["_last_snapshot_cache_key"] = ("old_snap",)
    invalidate()
    assert "_last_cache_key" not in state
    assert "_last_analysis_ts" not in state
    assert "_last_snapshot_cache_key" not in state


def test_invalidate_clears_every_registered_llm_digest_slot(fake_session_state):
    """app.cached_digest() registers each cache slot in
    _llm_cache_keys. invalidation should drop the entry AND every
    slot it pointed to."""
    invalidate, state, _ = fake_session_state
    state["_llm_cache_keys"] = {"slot_a", "slot_b", "slot_c"}
    state["slot_a"] = "stale-content-a"
    state["slot_b"] = "stale-content-b"
    state["slot_c"] = "stale-content-c"
    state["unrelated_key"] = "keep-me"  # control: don't blow this up

    invalidate()
    assert "_llm_cache_keys" not in state
    assert "slot_a" not in state
    assert "slot_b" not in state
    assert "slot_c" not in state
    # Unrelated keys survive — invalidation is targeted, not nuclear.
    assert state["unrelated_key"] == "keep-me"


def test_invalidate_clears_risk_memory_derived_state(fake_session_state):
    invalidate, state, _ = fake_session_state
    state["_recent_action_cards"] = [{"title": "stale"}]
    state["_recent_snapshot_delta"] = {"has_prior": True}
    invalidate()
    assert "_recent_action_cards" not in state
    assert "_recent_snapshot_delta" not in state


def test_invalidate_clears_every_deep_equity_cache(fake_session_state):
    invalidate, state, _ = fake_session_state
    state["_deep_equity_AAPL"] = {"stale": True}
    state["_deep_equity_NVDA"] = {"stale": True}
    state["other_user_key"] = "preserve"
    invalidate()
    assert "_deep_equity_AAPL" not in state
    assert "_deep_equity_NVDA" not in state
    assert state["other_user_key"] == "preserve"


def test_invalidate_clears_chat_context_cache(fake_session_state):
    """User chat HISTORY is preserved; only derived per-turn context
    cache drops so the next chat turn rebuilds against the new
    portfolio."""
    invalidate, state, _ = fake_session_state
    state["_fc_messages"] = [{"role": "user", "content": "kept"}]
    state["_chat_context_cache"] = "stale context"
    state["_chat_last_portfolio_signature"] = "old-sig"
    invalidate()
    # Derived context dropped...
    assert "_chat_context_cache" not in state
    assert "_chat_last_portfolio_signature" not in state
    # ...but the user's actual message thread is sacred.
    assert state["_fc_messages"] == [{"role": "user", "content": "kept"}]


def test_invalidate_is_idempotent_on_empty_state(fake_session_state):
    """Calling on a freshly-loaded session must not raise."""
    invalidate, state, _ = fake_session_state
    invalidate()
    assert state["_force_refresh"] is True


# ── prompt guardrails (equity + chat) ───────────────────────────────


def test_equity_prompt_keeps_missing_data_protocol():
    """The 2026-05-26 product directive: missing data → still
    professional. Pin the load-bearing phrases."""
    from libs.analysis.equity_research import ANALYST_SYSTEM_PROMPT

    p = ANALYST_SYSTEM_PROMPT.lower()
    assert "missing data does not excuse silence" in p
    assert "anchoring to" in p or "anchor" in p
    # No-cop-out clause: forbid leading with "insufficient data".
    assert "never open with" in p
    assert "insufficient data" in p  # mentioned as a banned opener


def test_equity_prompt_still_forbids_fabricating_numbers():
    from libs.analysis.equity_research import ANALYST_SYSTEM_PROMPT

    p = ANALYST_SYSTEM_PROMPT.lower()
    assert "do not fabricate" in p or "do not invent" in p


def test_floating_chat_prompt_keeps_missing_data_protocol(monkeypatch):
    """The chat prompt is the user-visible AI surface; missing data
    has to be handled the same way.

    We use monkeypatch (not raw sys.modules surgery) so the mocked
    ``streamlit`` is rolled back when the test exits — otherwise it
    leaks into later tests in the suite (Stripe / 10y yield) that
    legitimately import streamlit.
    """
    import importlib

    fake_st = MagicMock()
    fake_st.session_state = {}
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    sys.modules.pop("ui.floating_chat", None)
    module = importlib.import_module("ui.floating_chat")
    p = module._SYSTEM_PROMPT.lower()
    assert "missing-data protocol" in p
    assert "never blank the answer" in p or "always produce a verdict" in p
    assert "anchoring to a sector" in p or "sector / market norm" in p
    # No-cop-out clause.
    assert "never open with" in p
    # Force a clean reload of ui.floating_chat after we restore the real
    # streamlit so subsequent tests aren't stuck with the MagicMock.
    sys.modules.pop("ui.floating_chat", None)


def test_portfolio_prompt_keeps_missing_data_protocol():
    from libs.analysis.portfolio_research import PORTFOLIO_ANALYST_PROMPT

    p = PORTFOLIO_ANALYST_PROMPT.lower()
    assert "missing-data protocol" in p
    assert "never blank" in p
    assert "anchoring to" in p
