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


# The domain model (AssetPositionInput) only accepts these asset_type labels.
# Stored/legacy holdings may carry others ('equity', 'stock', 'etf', 'call'...),
# so unknowns normalise to 'public_security' rather than 500ing the score.
VALID_ASSET_TYPES = {"public_security", "cash", "crypto", "real_estate", "option"}


def normalize_asset_type(raw: object) -> str:
    """Map any stored/legacy asset_type label onto a domain-valid one."""
    s = str(raw or "").strip().lower()
    if s in VALID_ASSET_TYPES:
        return s
    if "crypto" in s:
        return "crypto"
    if "real" in s or "estate" in s or "reit" in s:
        return "real_estate"
    if "option" in s or s in {"call", "put"}:
        return "option"
    return "public_security"


def is_option_holding(h: object) -> bool:
    """True if a stored holding record is an option contract.

    THE one predicate. There were two and they disagreed: the risk path
    normalised the label (catching 'call' / 'put' / 'long_call'), while
    ``active_tickers`` compared the raw string to 'option' exactly. A holding
    stored as asset_type='call' was therefore correctly excluded from the price
    fetch but handed to the discovery adapters as an equity ticker -- and its
    key is a synthetic OCC symbol like AAPL260116C00150000, which no provider
    can resolve. /market/sentiment is credit-gated and caps the batch at 12, so
    that unresolvable row both cost the user credits and could push a real
    holding out of the batch.
    """
    raw = (h or {}).get("asset_type") if isinstance(h, dict) else None
    return normalize_asset_type(raw) == "option"


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
        return [str(t).upper() for t, h in holdings.items() if not is_option_holding(h)]
    except Exception as exc:  # noqa: BLE001
        _log.warning("active_tickers.failed err=%s", type(exc).__name__)
        return []
