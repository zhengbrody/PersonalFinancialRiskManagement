"""Smart-money (SEC 13F) adapter.

A thin, fail-soft wrapper over the legacy ``institutional_tracker`` module
(imported verbatim, like the other backend adapters). SEC EDGAR scans are slow
on a cold cache (10–20s) and occasionally flaky, so every call fails soft to an
empty/neutral result rather than 500-ing the page. The legacy module already
disk-caches 24h; a short in-process TTL on the per-portfolio signal scan shields
EDGAR from refresh storms.
"""

from __future__ import annotations

import logging
import time
from typing import Any

_logger = logging.getLogger(__name__)

# Signals for a given ticker set move only when a new 13F is filed (quarterly),
# so a few hours of server-side staleness is invisible and keeps EDGAR calm.
_CACHE_TTL_SECONDS = 6 * 60 * 60
_cache: dict[str, tuple[float, Any]] = {}


def reset_cache() -> None:
    """Test hook — drop the in-process cache."""
    _cache.clear()


def _safe(label: str, fn, default):
    try:
        return fn()
    except Exception as exc:  # pragma: no cover - SEC/network variability
        _logger.warning("institutions.%s.failed err=%s", label, type(exc).__name__)
        return default


def smart_money_signals(tickers: list[str]) -> list[dict]:
    """Institutional-conviction signals for a ticker list. Cached + fail-soft."""
    tickers = [t.upper() for t in (tickers or []) if t]
    if not tickers:
        return []
    key = "signals:" + "_".join(sorted(set(tickers)))
    hit = _cache.get(key)
    if hit is not None and hit[0] > time.monotonic():
        return hit[1]

    from institutional_tracker import get_smart_money_signals

    signals = _safe("smart_money", lambda: get_smart_money_signals(tickers), []) or []
    _cache[key] = (time.monotonic() + _CACHE_TTL_SECONDS, signals)
    return signals


def top_institutions() -> list[dict]:
    """The ~30 most-watched 13F filers (fast, in-memory). Fail-soft to []."""
    from institutional_tracker import get_top_institutions

    return _safe("top", get_top_institutions, []) or []


def institution_detail(cik: str) -> dict:
    """A fund's top holdings + QoQ position changes. Cached + fail-soft.

    Returns ``{cik, name, holdings: [...], changes: {...}}``; any leg that fails
    degrades to empty rather than erroring the page.
    """
    cik = (cik or "").strip()
    if not cik:
        return {"cik": "", "name": None, "holdings": [], "changes": {}}
    key = f"detail:{cik}"
    hit = _cache.get(key)
    if hit is not None and hit[0] > time.monotonic():
        return hit[1]

    from institutional_tracker import (
        get_institution_name,
        get_institutional_changes,
        summarize_top_holdings,
    )

    out = {
        "cik": cik,
        "name": _safe("name", lambda: get_institution_name(cik), None),
        "holdings": _safe("holdings", lambda: summarize_top_holdings(cik, 20), []) or [],
        "changes": _safe("changes", lambda: get_institutional_changes(cik), {}) or {},
    }
    _cache[key] = (time.monotonic() + _CACHE_TTL_SECONDS, out)
    return out
