"""Unified, source-labeled news for a ticker.

Combines FMP stock news + company press releases (primary) with a deterministic
SEC EDGAR filings link, deduplicated by URL/title and classified by type
(``news`` | ``press_release`` | ``earnings_transcript`` | ``filing`` | ``macro``).
Each item carries its provider source label; callers (Research, Copilot) only
ever see these normalized items, never raw provider JSON.

Fail-soft: with no FMP key the service still returns the deterministic SEC
filings link, so the news rail is never empty. Fetchers are injectable so the
classification/dedup logic is unit-testable without the network.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Callable, Optional

from ..schemas.provenance import SourceProvenance
from .providers import fmp_provider
from .providers import registry as reg

# news item types
NEWS = "news"
PRESS_RELEASE = "press_release"
EARNINGS_TRANSCRIPT = "earnings_transcript"
FILING = "filing"
MACRO = "macro"


def _norm_url(url: Optional[str]) -> str:
    if not url:
        return ""
    u = re.sub(r"[?#].*$", "", url.strip().lower()).rstrip("/")
    return re.sub(r"^https?://(www\.)?", "", u)


def _hash_key(title: str, url: Optional[str]) -> str:
    basis = _norm_url(url) or re.sub(r"\s+", " ", (title or "").strip().lower())
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()


def _item(
    *,
    title: str,
    url: Optional[str],
    item_type: str,
    source: str,
    site: Optional[str] = None,
    published: Optional[str] = None,
    snippet: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "url": url,
        "type": item_type,
        "source": source,
        "source_label": reg.label(source),
        "site": site,
        "published": published,
        "snippet": snippet,
    }


def _dedupe(items: list[dict]) -> list[dict]:
    """Drop duplicates by URL (else title) hash, keeping the first seen. FMP and
    a press wire often carry the same story — show it once."""
    seen: set[str] = set()
    out: list[dict] = []
    for it in items:
        key = _hash_key(it.get("title", ""), it.get("url"))
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def sec_filings_item(ticker: str) -> dict[str, Any]:
    """Deterministic SEC EDGAR full-text-search link for the ticker's filings —
    always available (no key), so the news rail always has at least one source."""
    tk = ticker.upper()
    url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&ticker={tk}&type=&dateb=&owner=include&count=40"
    return _item(
        title=f"{tk} — SEC filings (EDGAR)",
        url=url,
        item_type=FILING,
        source=reg.SEC,
        site="SEC EDGAR",
    )


def get_ticker_news(
    ticker: str,
    *,
    limit: int = 12,
    news_fn: Callable = fmp_provider.get_news,
    press_fn: Callable = fmp_provider.get_press_releases,
) -> dict[str, Any]:
    """Unified news for one ticker: FMP news + press releases + a SEC filings
    link, deduped + classified + source-labeled. Returns
    ``{items, sources, warnings}`` (JSON-safe)."""
    tk = ticker.upper()
    items: list[dict] = []
    warnings: list[str] = []
    sources: list[SourceProvenance] = []

    news = news_fn(tk, limit=limit)
    if news.ok:
        items += [
            _item(
                title=n.title,
                url=n.url,
                item_type=NEWS,
                source=reg.FMP,
                site=n.site,
                published=n.published,
                snippet=n.snippet,
            )
            for n in news.data
        ]
        sources.append(reg.build_provenance("news", reg.FMP, as_of=news.as_of))
    else:
        warnings += list(news.warnings)

    press = press_fn(tk, limit=max(4, limit // 2))
    if press.ok:
        items += [
            _item(
                title=n.title,
                url=n.url,
                item_type=PRESS_RELEASE,
                source=reg.FMP,
                site=n.site,
                published=n.published,
                snippet=n.snippet,
            )
            for n in press.data
        ]
        sources.append(reg.build_provenance("press_releases", reg.FMP, as_of=press.as_of))

    # Deterministic SEC filings entry — always present.
    items.append(sec_filings_item(tk))
    sources.append(reg.build_provenance("filings", reg.SEC, freshness="link"))

    items = _dedupe(items)
    # Newest first; entries without a date sink to the bottom.
    items.sort(key=lambda it: it.get("published") or "", reverse=True)

    return {
        "items": items[:limit],
        "sources": [s.model_dump() for s in sources],
        "warnings": sorted(set(warnings)),
    }
