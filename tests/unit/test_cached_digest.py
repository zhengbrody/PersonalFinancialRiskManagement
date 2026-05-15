"""Tests for app.cached_digest() and app.invalidate_digest_cache().

Goal: prove the session-state digest cache:
  - caches across reruns (same fingerprint = no second LLM call)
  - invalidates when the input fingerprint changes
  - invalidates wholesale when invalidate_digest_cache() is called (after a
    fresh "Run Analysis")

NOTE: app.py runs `st.set_page_config(...)` at import time. We install a
MagicMock `streamlit` BEFORE importing app inside each test, so that call
is a no-op MagicMock invocation. We import `app` inside test bodies (not
at module top) for the same reason.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

# ── Test scaffolding ─────────────────────────────────────────────


class _FakeSessionState(dict):
    """Streamlit's session_state allows BOTH `["k"]` and `.k` access."""

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
    """Provide a fake `streamlit` module with a dict-style session_state.

    session_state must support both subscript (`st.session_state["k"]`) and
    attribute (`st.session_state.k`) access — app.py uses both at top level.
    """
    fake_st = MagicMock()
    fake_st.session_state = _FakeSessionState()
    fake_st.secrets.get.return_value = ""
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)
    return fake_st


@pytest.fixture
def app_module(fake_streamlit):
    """Import `app` AFTER streamlit is monkeypatched.

    We force-reimport so the module's bound `st` is our fake mock; otherwise
    a prior test that imported app with real streamlit would leak.
    """
    # Drop any cached `app` so the next import binds to our fake `st`.
    sys.modules.pop("app", None)
    import app  # noqa: E402

    return app


# ── 1. First call: empty cache → LLM is invoked, result stored ──


def test_first_call_invokes_llm_and_stores_result(fake_streamlit, app_module):
    with patch.object(app_module, "call_llm", return_value="MOCK_LLM_OUTPUT") as mock_llm:
        result = app_module.cached_digest("overview", prompt="hello", invalidate_on=("w",))

    assert result == "MOCK_LLM_OUTPUT"
    assert mock_llm.call_count == 1

    # Compute the expected slot the same way the SUT does.
    expected_fp = hash(("overview", "w"))
    expected_slot = f"_llm_cache::overview::{expected_fp}"
    assert expected_slot in fake_streamlit.session_state
    assert fake_streamlit.session_state[expected_slot] == "MOCK_LLM_OUTPUT"
    assert expected_slot in fake_streamlit.session_state["_llm_cache_keys"]


# ── 2. Second call, same fingerprint: cache hit, no second LLM call ──


def test_second_call_same_fingerprint_skips_llm(fake_streamlit, app_module):
    with patch.object(app_module, "call_llm", return_value="MOCK_LLM_OUTPUT") as mock_llm:
        first = app_module.cached_digest("overview", prompt="hi", invalidate_on=("w",))
        second = app_module.cached_digest("overview", prompt="hi", invalidate_on=("w",))

    assert first == second == "MOCK_LLM_OUTPUT"
    assert mock_llm.call_count == 1  # second call hit the cache


# ── 3. Different invalidate_on → different fingerprint → new LLM call ──


def test_changing_invalidate_on_triggers_new_call(fake_streamlit, app_module):
    with patch.object(app_module, "call_llm", side_effect=["FIRST", "SECOND"]) as mock_llm:
        out_a = app_module.cached_digest("overview", prompt="p", invalidate_on=("a",))
        out_b = app_module.cached_digest("overview", prompt="p", invalidate_on=("b",))

    assert out_a == "FIRST"
    assert out_b == "SECOND"
    assert mock_llm.call_count == 2

    # Both slots should be tracked in the registry.
    registry = fake_streamlit.session_state["_llm_cache_keys"]
    assert len(registry) == 2
    slot_a = f"_llm_cache::overview::{hash(('overview', 'a'))}"
    slot_b = f"_llm_cache::overview::{hash(('overview', 'b'))}"
    assert slot_a in registry
    assert slot_b in registry


# ── 4. Different `key` → different slot ──


def test_different_key_uses_different_slot(fake_streamlit, app_module):
    with patch.object(app_module, "call_llm", side_effect=["O", "R"]) as mock_llm:
        app_module.cached_digest("overview", prompt="p", invalidate_on=("x",))
        app_module.cached_digest("risk", prompt="p", invalidate_on=("x",))

    assert mock_llm.call_count == 2
    slot_overview = f"_llm_cache::overview::{hash(('overview', 'x'))}"
    slot_risk = f"_llm_cache::risk::{hash(('risk', 'x'))}"
    assert slot_overview != slot_risk
    assert fake_streamlit.session_state[slot_overview] == "O"
    assert fake_streamlit.session_state[slot_risk] == "R"
    registry = fake_streamlit.session_state["_llm_cache_keys"]
    assert slot_overview in registry
    assert slot_risk in registry


# ── 5. invalidate_digest_cache() wipes everything ──


def test_invalidate_digest_cache_drops_all_slots(fake_streamlit, app_module):
    with patch.object(app_module, "call_llm", side_effect=["A", "B", "C"]):
        app_module.cached_digest("k1", prompt="p", invalidate_on=("x",))
        app_module.cached_digest("k2", prompt="p", invalidate_on=("x",))
        app_module.cached_digest("k3", prompt="p", invalidate_on=("x",))

    # Sanity: 3 slots tracked + populated.
    assert len(fake_streamlit.session_state["_llm_cache_keys"]) == 3
    tracked = set(fake_streamlit.session_state["_llm_cache_keys"])
    for slot in tracked:
        assert slot in fake_streamlit.session_state

    app_module.invalidate_digest_cache()

    # All slots gone; registry emptied (popped from session_state).
    for slot in tracked:
        assert slot not in fake_streamlit.session_state
    assert "_llm_cache_keys" not in fake_streamlit.session_state


# ── 6. invalidate_digest_cache() on a fresh session is a safe no-op ──


def test_invalidate_when_no_cache_is_safe(fake_streamlit, app_module):
    # Empty session_state — no _llm_cache_keys key at all.
    assert "_llm_cache_keys" not in fake_streamlit.session_state
    # Must not raise.
    app_module.invalidate_digest_cache()
    assert "_llm_cache_keys" not in fake_streamlit.session_state


# ── 7. invalidate does NOT touch unrelated session_state keys ──


def test_invalidate_doesnt_drop_unrelated_session_state(fake_streamlit, app_module):
    fake_streamlit.session_state["weights"] = {"AAPL": 0.5, "MSFT": 0.5}
    fake_streamlit.session_state["analysis_ready"] = True
    fake_streamlit.session_state["_lang"] = "en"

    with patch.object(app_module, "call_llm", return_value="X"):
        app_module.cached_digest("overview", prompt="p", invalidate_on=("w",))

    # Cache was populated.
    assert any(k.startswith("_llm_cache::") for k in fake_streamlit.session_state)

    app_module.invalidate_digest_cache()

    # Unrelated keys preserved.
    assert fake_streamlit.session_state["weights"] == {"AAPL": 0.5, "MSFT": 0.5}
    assert fake_streamlit.session_state["analysis_ready"] is True
    assert fake_streamlit.session_state["_lang"] == "en"
    # Cache slots gone.
    assert not any(k.startswith("_llm_cache::") for k in fake_streamlit.session_state)


# ── 8. call_llm is invoked with the exact args we passed in ──


def test_call_llm_receives_correct_arguments(fake_streamlit, app_module):
    with patch.object(app_module, "call_llm", return_value="OUT") as mock_llm:
        app_module.cached_digest(
            "k",
            prompt="P",
            system="S",
            max_tokens=123,
            temperature=0.5,
            invalidate_on=("x",),
        )

    mock_llm.assert_called_once_with("P", system="S", max_tokens=123, temperature=0.5)
