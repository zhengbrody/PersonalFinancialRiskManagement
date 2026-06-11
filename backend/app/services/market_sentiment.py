"""Per-holding AI sentiment — a non-Streamlit reimplementation of the legacy
``app.score_sentiment_ollama`` flow (the legacy one is Streamlit-coupled).

For each ticker we pull a few recent headlines (free yfinance) and ask the LLM
for a structured ``{score, label, narrative}`` over them. The LLM only
summarises the supplied headlines — it is told not to invent facts. With no LLM
key (``llm_callable is None``) every ticker degrades to a deterministic neutral
placeholder so the page still renders. Scoring runs in a small thread pool and
is cached per ticker-set.

LLM-boundary note: the 0-100 sentiment score is the model CLASSIFYING the
supplied headlines (rank/summarize — allowed), not a financial metric it
computed. It must never feed risk math; the UI labels it ``ai_generated``
and shows the headline basis. If sentiment ever becomes an input to scoring,
it needs a deterministic floor first (see risk_explain / build_verdict).
"""

from __future__ import annotations

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Optional

_logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 30 * 60
_cache: dict[str, tuple[float, list[dict]]] = {}

# Bound cost + latency: never score more than this many holdings per call.
_MAX_TICKERS = 12
_MAX_HEADLINES = 6
_MAX_WORKERS = 5

_SYSTEM = (
    "You are a markets analyst. Given a few recent news headlines about one "
    "stock, judge the near-term RETAIL sentiment they convey. Do not invent "
    "facts beyond the headlines. Return JSON ONLY, no fences:\n"
    '{"score": <0-100 int, 0=very bearish 50=neutral 100=very bullish>, '
    '"label": "Bearish|Neutral|Bullish", "narrative": "<one short sentence>"}'
)

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def reset_cache() -> None:
    _cache.clear()


def _neutral(ticker: str, n_headlines: int, reason: str) -> dict:
    return {
        "ticker": ticker,
        "score": 50,
        "label": "Neutral",
        "narrative": reason,
        "headline_count": n_headlines,
    }


def _fetch_headlines(ticker: str) -> list[str]:
    """Recent headlines for a ticker via free yfinance. Fail-soft to []."""
    try:
        import yfinance as yf

        raw = getattr(yf.Ticker(ticker), "news", None) or []
        titles: list[str] = []
        for item in raw[:_MAX_HEADLINES]:
            # yfinance shapes vary: {title:...} or {content:{title:...}}.
            title = item.get("title") or (item.get("content") or {}).get("title")
            if title:
                titles.append(str(title))
        return titles
    except Exception as exc:  # pragma: no cover - network variability
        _logger.warning("sentiment.headlines_failed ticker=%s err=%s", ticker, type(exc).__name__)
        return []


def _score_one(ticker: str, llm_callable: Optional[Callable]) -> dict:
    headlines = _fetch_headlines(ticker)
    if not headlines:
        return _neutral(ticker, 0, "No recent headlines found.")
    if llm_callable is None:
        return _neutral(ticker, len(headlines), "AI scoring unavailable — headlines only.")

    prompt = f"Ticker: {ticker}\nRecent headlines:\n" + "\n".join(f"- {h}" for h in headlines)
    try:
        raw = llm_callable(prompt=prompt, system=_SYSTEM, max_tokens=200, temperature=0.2)
    except Exception as exc:  # noqa: BLE001
        _logger.warning("sentiment.llm_failed ticker=%s err=%s", ticker, type(exc).__name__)
        return _neutral(ticker, len(headlines), "AI scoring failed — headlines only.")

    parsed = _parse(raw or "")
    if not parsed:
        return _neutral(ticker, len(headlines), "Could not parse the AI verdict.")
    score = parsed.get("score")
    try:
        score = max(0, min(100, int(round(float(score)))))
    except (TypeError, ValueError):
        score = 50
    label = str(parsed.get("label") or "").strip() or _label_from_score(score)
    return {
        "ticker": ticker,
        "score": score,
        "label": label,
        "narrative": str(parsed.get("narrative") or "").strip(),
        "headline_count": len(headlines),
    }


def _label_from_score(score: int) -> str:
    if score >= 60:
        return "Bullish"
    if score <= 40:
        return "Bearish"
    return "Neutral"


def _parse(raw: str) -> Optional[dict]:
    raw = raw.strip()
    for candidate in (raw, _re_first(raw)):
        if not candidate:
            continue
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except Exception:  # noqa: BLE001
            continue
    return None


def _re_first(text: str) -> Optional[str]:
    m = _JSON_RE.search(text)
    return m.group(0) if m else None


def score_portfolio_sentiment(
    tickers: list[str], *, llm_callable: Optional[Callable] = None
) -> list[dict]:
    """Per-ticker sentiment, parallelised + cached. Order follows ``tickers``."""
    tickers = [t.upper() for t in (tickers or []) if t][:_MAX_TICKERS]
    if not tickers:
        return []

    # Cache key folds in whether a model is available (None → neutral path).
    key = ("llm:" if llm_callable else "none:") + "_".join(sorted(set(tickers)))
    hit = _cache.get(key)
    if hit is not None and hit[0] > time.monotonic():
        return hit[1]

    with ThreadPoolExecutor(max_workers=_MAX_WORKERS) as pool:
        results = list(pool.map(lambda t: _score_one(t, llm_callable), tickers))

    _cache[key] = (time.monotonic() + _CACHE_TTL_SECONDS, results)
    return results
