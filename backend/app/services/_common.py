"""Small shared helpers for the fail-soft service adapters.

``safe`` is the run-an-upstream-fetch-swallowing-failure wrapper that the
``market_*`` / ``institutions`` adapters all use; ``active_tickers`` is the
fail-soft "tickers in the caller's active portfolio" resolver shared by the
discovery routers (institutions, market sentiment) that want ``[]`` on an empty
or unavailable portfolio rather than a 422.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

_log = logging.getLogger(__name__)


def safe(label: str, fn: Callable[[], Any], default: Any = None) -> Any:
    """Run ``fn``; on any exception log at warning and return ``default``."""
    try:
        return fn()
    except Exception as exc:  # pragma: no cover - upstream variability
        _log.warning("%s.failed err=%s", label, type(exc).__name__)
        return default


def active_tickers(access_token: str | None) -> list[str]:
    """Upper-cased tickers in the caller's active portfolio, fail-soft to ``[]``
    (discovery surfaces never block on an empty/unavailable portfolio)."""
    try:
        from libs.auth.active_portfolio import get_active_holdings

        holdings = get_active_holdings(access_token=access_token) or {}
        return [str(t).upper() for t in holdings.keys()]
    except Exception as exc:  # noqa: BLE001
        _log.warning("active_tickers.failed err=%s", type(exc).__name__)
        return []
