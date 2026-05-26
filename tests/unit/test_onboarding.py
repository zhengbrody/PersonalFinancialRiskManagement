"""Tests for libs/auth/onboarding.py — new-user flow state machine.

We're not testing UI here (the Welcome page is a Streamlit script with
side effects); we're testing the pure-logic helpers the page calls.

Strategy: monkeypatch ``session.is_authenticated`` and
``portfolios.list_portfolios`` because that's the entire signal set.
``streamlit`` is stubbed so the module's lazy ``_ss()`` returns a fresh
session-state-like dict per test.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def onboarding(monkeypatch):
    """Reload ``libs.auth.onboarding`` against a stubbed streamlit and
    yield (module, fake_session_state). Each test gets a fresh state."""
    fake_state: dict = {}
    fake_st = MagicMock()
    fake_st.session_state = fake_state
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    # The module imports lazily, so just drop+reload to be safe.
    sys.modules.pop("libs.auth.onboarding", None)
    import importlib

    module = importlib.import_module("libs.auth.onboarding")
    return module, fake_state


# ── needs_onboarding ────────────────────────────────────────────────


def test_needs_onboarding_false_for_anonymous(onboarding, monkeypatch):
    module, _ = onboarding
    monkeypatch.setattr(module, "_is_authenticated", lambda: False)
    assert module.needs_onboarding() is False


def test_needs_onboarding_true_when_signed_in_no_portfolios(onboarding, monkeypatch):
    module, _ = onboarding
    monkeypatch.setattr(module, "_is_authenticated", lambda: True)
    monkeypatch.setattr(module, "_list_portfolios_safe", lambda: [])
    assert module.needs_onboarding() is True


def test_needs_onboarding_false_when_user_already_has_portfolios(onboarding, monkeypatch):
    module, _ = onboarding
    monkeypatch.setattr(module, "_is_authenticated", lambda: True)
    monkeypatch.setattr(
        module,
        "_list_portfolios_safe",
        lambda: [{"id": "abc", "name": "My port"}],
    )
    assert module.needs_onboarding() is False


def test_needs_onboarding_false_after_skip(onboarding, monkeypatch):
    """Once a user dismisses onboarding, we must NOT auto-route them
    back into it on every page nav within the same session."""
    module, state = onboarding
    monkeypatch.setattr(module, "_is_authenticated", lambda: True)
    monkeypatch.setattr(module, "_list_portfolios_safe", lambda: [])
    module.mark_skipped()
    assert state["_onboarding_skipped"] is True
    assert module.needs_onboarding() is False


def test_reset_skip_flag_re_enables_onboarding(onboarding, monkeypatch):
    """After they delete all portfolios + reset, onboarding should
    light up again (the "create your first portfolio" CTA is correct
    in this state)."""
    module, state = onboarding
    monkeypatch.setattr(module, "_is_authenticated", lambda: True)
    monkeypatch.setattr(module, "_list_portfolios_safe", lambda: [])
    module.mark_skipped()
    module.reset_skip_flag()
    assert "_onboarding_skipped" not in state
    assert module.needs_onboarding() is True


def test_list_portfolios_failure_is_treated_as_empty(onboarding, monkeypatch):
    """Network / RLS / missing migration must NOT raise into the
    Welcome page — degrade to 'no portfolios' silently."""
    module, _ = onboarding
    monkeypatch.setattr(module, "_is_authenticated", lambda: True)

    def _boom():
        raise RuntimeError("relation does not exist")

    # Patch the inner import path used by _list_portfolios_safe.
    monkeypatch.setattr(
        "libs.auth.portfolios.list_portfolios",
        _boom,
    )
    # _list_portfolios_safe catches the error and returns [].
    assert module._list_portfolios_safe() == []
    assert module.needs_onboarding() is True


# ── set/get_user_risk_preference ────────────────────────────────────


def test_risk_preference_defaults_to_three(onboarding):
    module, _ = onboarding
    assert module.get_user_risk_preference() == 3


def test_set_risk_preference_persists_in_session(onboarding):
    module, state = onboarding
    module.set_user_risk_preference(4)
    assert state["_user_risk_preference"] == 4
    assert module.get_user_risk_preference() == 4


def test_set_risk_preference_clamps_below_one(onboarding):
    module, _ = onboarding
    module.set_user_risk_preference(-3)
    assert module.get_user_risk_preference() == 1


def test_set_risk_preference_clamps_above_five(onboarding):
    module, _ = onboarding
    module.set_user_risk_preference(99)
    assert module.get_user_risk_preference() == 5


def test_set_risk_preference_handles_non_numeric(onboarding):
    """Form callbacks can hand us '' / None; we fall to default (3)."""
    module, _ = onboarding
    module.set_user_risk_preference("notanumber")  # type: ignore[arg-type]
    assert module.get_user_risk_preference() == 3


def test_risk_preference_durable_write_failures_dont_raise(onboarding, monkeypatch):
    """If we can't write the metadata into the default portfolio
    (e.g. user has no default yet), the session value still takes."""
    module, state = onboarding
    monkeypatch.setattr(
        "libs.auth.portfolios.get_default_portfolio",
        lambda: None,
    )
    module.set_user_risk_preference(5)
    assert state["_user_risk_preference"] == 5


def test_get_risk_preference_reads_from_default_portfolio_when_session_empty(
    onboarding, monkeypatch
):
    module, state = onboarding
    # Session is empty.
    state.clear()
    fake_port = {
        "id": "p1",
        "holdings": {"__meta_risk_preference": 4, "SPY": {"shares": 10}},
    }
    monkeypatch.setattr(
        "libs.auth.portfolios.get_default_portfolio",
        lambda: fake_port,
    )
    assert module.get_user_risk_preference() == 4
    # And once read, it should be hydrated into session_state too.
    assert state["_user_risk_preference"] == 4


def test_get_risk_preference_clamps_loaded_value(onboarding, monkeypatch):
    """A corrupt holdings.__meta_risk_preference (e.g. 9999) must not
    leak into the UI as an out-of-range slider value."""
    module, _ = onboarding
    fake_port = {"id": "p1", "holdings": {"__meta_risk_preference": 9999}}
    monkeypatch.setattr(
        "libs.auth.portfolios.get_default_portfolio",
        lambda: fake_port,
    )
    assert module.get_user_risk_preference() == 5


# ── safety: mark_skipped / reset don't crash without streamlit ─────


def test_mark_skipped_handles_session_state_isolation(onboarding):
    module, state = onboarding
    assert "_onboarding_skipped" not in state
    module.mark_skipped()
    assert state["_onboarding_skipped"] is True
    # Idempotent — calling twice is fine.
    module.mark_skipped()
    assert state["_onboarding_skipped"] is True


def test_get_when_default_portfolio_throws(onboarding, monkeypatch):
    """Even if the get_default_portfolio() call raises, we default to 3."""
    module, _ = onboarding

    def _explode():
        raise RuntimeError("postgrest 500")

    monkeypatch.setattr(
        "libs.auth.portfolios.get_default_portfolio",
        _explode,
    )
    assert module.get_user_risk_preference() == 3


# ── _list_portfolios_safe shape sanity ──────────────────────────────


def test_list_portfolios_safe_returns_list_not_none(onboarding, monkeypatch):
    """The downstream consumer does len() on the result — it MUST be
    iterable, never None."""
    module, _ = onboarding
    monkeypatch.setattr("libs.auth.portfolios.list_portfolios", lambda: None)
    assert module._list_portfolios_safe() == []


def test_list_portfolios_safe_short_circuits_on_normal_data(onboarding, monkeypatch):
    module, _ = onboarding
    fake = [{"id": "p1"}, {"id": "p2"}]
    monkeypatch.setattr("libs.auth.portfolios.list_portfolios", lambda: fake)
    out = module._list_portfolios_safe()
    assert isinstance(out, list)
    assert len(out) == 2


# Imported just to ensure the symbol stays exposed (other modules
# import it directly). Detects accidental rename.
def test_public_api_surface(onboarding):
    module, _ = onboarding
    assert hasattr(module, "needs_onboarding")
    assert hasattr(module, "mark_skipped")
    assert hasattr(module, "reset_skip_flag")
    assert hasattr(module, "set_user_risk_preference")
    assert hasattr(module, "get_user_risk_preference")
    # Avoid an unused-import warning in linters.
    _ = SimpleNamespace
