"""Macro news — a fail-soft adapter over ``market_intelligence.get_all_macro_news``
(free RSS + yfinance market news). Short in-proc TTL; never raises.
"""

from __future__ import annotations

import logging
import time
from typing import Any

_logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 15 * 60
_cache: dict[str, tuple[float, list[dict]]] = {}


def reset_cache() -> None:
    _cache.clear()


def get_macro_news(max_items: int = 24) -> list[dict]:
    """Latest macro headlines: ``[{source, title, link, published, summary}]``.
    Cached, fail-soft to ``[]``."""
    key = f"news:{max_items}"
    hit = _cache.get(key)
    if hit is not None and hit[0] > time.monotonic():
        return hit[1]

    items: list[dict] = []
    try:
        from market_intelligence import get_all_macro_news

        raw: list[dict[str, Any]] = get_all_macro_news(max_items=max_items) or []
        for it in raw:
            title = str(it.get("title") or "").strip()
            if not title:
                continue
            items.append(
                {
                    "source": str(it.get("source") or "") or None,
                    "title": title,
                    "link": str(it.get("link") or "") or None,
                    "published": str(it.get("published") or "") or None,
                    "summary": str(it.get("summary") or "") or None,
                }
            )
    except Exception as exc:  # pragma: no cover - RSS/network variability
        _logger.warning("news.fetch_failed err=%s", type(exc).__name__)
        items = []

    _cache[key] = (time.monotonic() + _CACHE_TTL_SECONDS, items)
    return items
