"""Small shared helpers for the fail-soft service adapters.

``safe`` is the run-an-upstream-fetch-swallowing-failure wrapper that the
``market_*`` / ``institutions`` adapters all use; ``active_tickers`` is the
fail-soft "tickers in the caller's active portfolio" resolver shared by the
discovery routers (institutions, market sentiment) that want ``[]`` on an empty
or unavailable portfolio rather than a 422; ``snapshot_to_mapping`` is the ONE
place a provider snapshot (pydantic model / dataclass / Mapping) becomes a
plain dict.
"""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)


def iso_now() -> str:
    """Current UTC instant as an ISO-8601 string (shared ``generated_at`` stamp)."""
    return datetime.now(timezone.utc).isoformat()


def safe(label: str, fn: Callable[[], Any], default: Any = None) -> Any:
    """Run ``fn``; on any exception log at warning and return ``default``."""
    try:
        return fn()
    except Exception as exc:  # pragma: no cover - upstream variability
        _log.warning("%s.failed err=%s", label, type(exc).__name__)
        return default


def snapshot_to_mapping(obj: object) -> Optional[dict[str, Any]]:
    """Normalize a provider snapshot/state into a plain ``dict``.

    Handles every shape the service layer legitimately returns — pydantic
    models (``model_dump()``), dataclasses (``dataclasses.asdict``, which is
    recursive so nested states like ``VixState`` become plain dicts too), and
    Mappings. ``None`` passes through as ``None``. Any OTHER shape logs a
    structured warning and returns ``None`` so callers degrade to missing
    evidence / an empty payload instead of a 500 — a deliberate type dispatch,
    not a blanket ``except`` that could mask real programming errors.

    THE single home for this conversion (production bug: the Copilot
    macro_rates branch and the MCP ``get_macro_context`` tool each hand-rolled
    ``dict(snap)`` on ``market_regime.RegimeSnapshot`` — a frozen dataclass —
    and 500'd; tests masked it with dict-shaped fixtures).
    """
    if obj is None:
        return None
    dump = getattr(obj, "model_dump", None)
    if callable(dump):
        return dump()
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, Mapping):
        return dict(obj)
    _log.warning("snapshot_to_mapping.unsupported_type type=%s", type(obj).__name__)
    return None


def active_tickers(access_token: str | None) -> list[str]:
    """Upper-cased tickers in the caller's active portfolio, fail-soft to ``[]``
    (discovery surfaces never block on an empty/unavailable portfolio)."""
    try:
        from libs.auth.active_portfolio import get_active_holdings

        holdings = get_active_holdings(access_token=access_token) or {}
        # Skip option contracts: their synthetic OCC keys aren't real symbols,
        # so the discovery adapters (sentiment, 13F) would only fail-soft on them.
        return [
            str(t).upper()
            for t, h in holdings.items()
            if str((h or {}).get("asset_type") if isinstance(h, dict) else "").lower() != "option"
        ]
    except Exception as exc:  # noqa: BLE001
        _log.warning("active_tickers.failed err=%s", type(exc).__name__)
        return []
