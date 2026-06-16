"""Macro news — a fail-soft adapter over ``market_intelligence.get_all_macro_news``.

The upstream aggregator combines multiple RSS publishers plus Yahoo Finance
market headlines. This service normalizes each item and also surfaces a compact
``sources`` list so the UI can show that the news rail is not a single-provider
Yahoo feed. Short in-proc TTL; never raises.
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from ..schemas.provenance import SourceProvenance

_logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 15 * 60
_cache: dict[str, tuple[float, dict]] = {}


def reset_cache() -> None:
    _cache.clear()


def _provider_id(source: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", source.strip().lower()).strip("_")
    return f"rss_{slug or 'macro'}"


def _source_provenance(items: list[dict]) -> list[SourceProvenance]:
    seen: dict[str, SourceProvenance] = {}
    for item in items:
        source = str(item.get("source") or "").strip()
        if not source:
            continue
        is_yahoo = source.lower().startswith("yahoo finance")
        provider = "yfinance" if is_yahoo else _provider_id(source)
        if provider in seen:
            continue
        seen[provider] = SourceProvenance(
            field="macro_news",
            provider=provider,
            label="Yahoo Finance" if is_yahoo else source,
            role="fallback" if is_yahoo else "primary",
            endpoint="market_intelligence.get_all_macro_news",
            freshness="15m cache",
            fallback_used=is_yahoo,
        )
    return list(seen.values())


def get_macro_news(max_items: int = 24) -> dict:
    """Latest macro headlines:
    ``{"items": [{source,title,link,published,summary}], "sources": [...]}``.
    Cached, fail-soft to empty lists."""
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

    payload = {"items": items, "sources": [s.model_dump() for s in _source_provenance(items)]}
    _cache[key] = (time.monotonic() + _CACHE_TTL_SECONDS, payload)
    return payload
