"""Detect whether a freshly-signed-in user still needs the new-user
onboarding flow.

Source of truth (cheap, no extra schema)
----------------------------------------
A user "needs onboarding" iff they are signed in AND
``libs.auth.portfolios.list_portfolios()`` returns an empty list AND
they haven't explicitly skipped during this Streamlit session.

We deliberately avoid adding a column to ``profiles`` for two reasons:
  1. Migration churn for a single boolean isn't worth it; the
     existence-of-portfolio signal is already perfect.
  2. If the user later deletes all their portfolios, we *want* the
     onboarding banner to come back — the "create your first portfolio"
     UX is honestly the right CTA in both cases.

If the user dismisses onboarding for the current session (clicks Skip),
we set a session-state flag so the Login → Onboarding redirect doesn't
kick them back here on every page nav. The flag dies with the tab.

Public API
----------
- ``needs_onboarding()``: bool. Wraps the rules above.
- ``mark_skipped()``: persist the "don't redirect me again" flag in
  session_state.
- ``set_user_risk_preference(value)``: stash 1–5 risk preference. We
  also try to write it into the user's default portfolio's metadata
  jsonb so it survives a refresh, but we never fail the call if the
  write doesn't work — it's a UX convenience, not a billing decision.
- ``get_user_risk_preference()``: read it back. Defaults to 3.
"""

from __future__ import annotations

import logging
from typing import Any

_logger = logging.getLogger(__name__)

# Session-state keys. Prefix matches the rest of the auth layer.
_KEY_SKIPPED = "_onboarding_skipped"
_KEY_RISK_PREFERENCE = "_user_risk_preference"

_DEFAULT_RISK_PREFERENCE = 3


def _ss():
    """Lazy import of streamlit.session_state.

    Mirrors the pattern in libs/auth/session.py so this module stays
    importable from Lambda / CI without Streamlit running.
    """
    import streamlit as st

    return st.session_state


def _is_authenticated() -> bool:
    try:
        from .session import is_authenticated

        return bool(is_authenticated())
    except Exception:
        return False


def _list_portfolios_safe() -> list[dict[str, Any]]:
    """Catch every kind of failure (network / RLS / missing migration)
    and degrade to 'no portfolios'. The onboarding code path must never
    be the thing that errors out the page."""
    try:
        from .portfolios import list_portfolios

        return list_portfolios() or []
    except Exception as exc:
        _logger.warning("onboarding.list_portfolios_failed: %s", exc)
        return []


def needs_onboarding() -> bool:
    """Return True when the signed-in user has zero portfolios AND
    hasn't explicitly skipped this session."""
    if not _is_authenticated():
        return False
    if _ss().get(_KEY_SKIPPED):
        return False
    return len(_list_portfolios_safe()) == 0


def mark_skipped() -> None:
    """Persist the user's choice to skip onboarding for this session."""
    _ss()[_KEY_SKIPPED] = True


def reset_skip_flag() -> None:
    """Clear the skip flag — used after a successful portfolio create,
    so we don't keep redirecting them back here if they delete it later
    and want the guided flow again."""
    _ss().pop(_KEY_SKIPPED, None)


def set_user_risk_preference(value: int) -> None:
    """Store the user's chosen 1–5 risk preference.

    Persistence strategy is intentionally lightweight: store in
    session_state (always works) and *also* try to copy it into the
    default portfolio's metadata jsonb on best-effort. Writing it on
    the portfolio means a re-login picks it up; failing the write
    just means the user re-selects on the next session — not a bug,
    not a billing issue.
    """
    try:
        clean = int(value)
    except (TypeError, ValueError):
        clean = _DEFAULT_RISK_PREFERENCE
    clean = max(1, min(5, clean))
    _ss()[_KEY_RISK_PREFERENCE] = clean

    # Best-effort durable copy. Wrapped tightly — any failure must NOT
    # break the onboarding wizard.
    try:
        from .portfolios import get_default_portfolio, update_portfolio

        port = get_default_portfolio()
        if port and port.get("id"):
            holdings = dict(port.get("holdings") or {})
            holdings["__meta_risk_preference"] = clean
            update_portfolio(port["id"], holdings=holdings)
    except Exception as exc:
        _logger.info("onboarding.persist_risk_pref_skipped: %s", exc)


def get_user_risk_preference() -> int:
    """Return the user's preferred 1–5 risk slider. Looks at:
    1. session_state (set by set_user_risk_preference)
    2. default portfolio's holdings.__meta_risk_preference
    3. DEFAULT (3)
    """
    state = _ss()
    if _KEY_RISK_PREFERENCE in state:
        try:
            return int(state[_KEY_RISK_PREFERENCE])
        except (TypeError, ValueError):
            pass

    try:
        from .portfolios import get_default_portfolio

        port = get_default_portfolio()
        if port:
            holdings = port.get("holdings") or {}
            if isinstance(holdings, dict):
                stored = holdings.get("__meta_risk_preference")
                if stored is not None:
                    state[_KEY_RISK_PREFERENCE] = max(1, min(5, int(stored)))
                    return state[_KEY_RISK_PREFERENCE]
    except Exception:
        pass

    return _DEFAULT_RISK_PREFERENCE
