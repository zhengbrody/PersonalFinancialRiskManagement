"""Market-regime snapshot — VIX, Fear & Greed, and yield-curve status.

A thin adapter over the legacy ``market_intelligence`` module (imported
verbatim, same way the backend reuses ``risk_engine`` / ``engine.quant``).

Each leg is fetched independently and **fails soft to ``None``** so one
dead upstream (e.g. the CNN Fear & Greed JSON, or a yfinance hiccup on
VIX) never blanks the entire panel. A short in-process TTL cache shields
the upstreams from dashboard-refresh storms; the underlying functions
cache too, so this is belt-and-braces.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

_logger = logging.getLogger(__name__)

# Regime data moves slowly (VIX/F&G update intraday at most); 5 min of
# server-side staleness is invisible to users and cheap on the upstreams.
_CACHE_TTL_SECONDS = 300
_cache: dict[str, tuple[float, "RegimeSnapshot"]] = {}


@dataclass(frozen=True)
class VixState:
    current: Optional[float]
    change: Optional[float]  # day-over-day fractional return (0.01 = +1%)
    level: Optional[str]


@dataclass(frozen=True)
class FearGreedState:
    score: Optional[float]
    rating: Optional[str]


@dataclass(frozen=True)
class YieldCurveState:
    status: Optional[str]
    spread_3m_10y: Optional[float]
    inverted: Optional[bool]


@dataclass(frozen=True)
class RegimeSnapshot:
    vix: VixState
    fear_greed: FearGreedState
    yield_curve: YieldCurveState


def reset_cache() -> None:
    """Test hook — drop the in-process cache."""
    _cache.clear()


def _safe(label: str, fn):
    """Run an upstream fetch, swallowing failure to ``None`` and logging."""
    try:
        return fn()
    except Exception as exc:  # pragma: no cover - upstream variability
        _logger.warning("regime.%s.fetch_failed err=%s", label, type(exc).__name__)
        return None


def _vix() -> VixState:
    from market_intelligence import get_vix_current

    data = _safe("vix", get_vix_current) or {}
    cur = data.get("current")
    chg = data.get("change")
    return VixState(
        current=float(cur) if cur is not None else None,
        change=float(chg) if chg is not None else None,
        level=data.get("level") or None,
    )


def _fear_greed() -> FearGreedState:
    from market_intelligence import fetch_fear_greed

    data = _safe("fear_greed", fetch_fear_greed) or {}
    score = data.get("score")
    return FearGreedState(
        score=float(score) if score is not None else None,
        # ``rating_display`` is the title-cased label ("Extreme Fear"); fall
        # back to the raw rating.
        rating=data.get("rating_display") or data.get("rating") or None,
    )


def _yield_curve() -> YieldCurveState:
    from market_intelligence import fetch_yield_curve

    result = _safe("yield_curve", fetch_yield_curve)
    if not result:
        return YieldCurveState(status=None, spread_3m_10y=None, inverted=None)
    # fetch_yield_curve returns (DataFrame, analysis_dict).
    _, analysis = result
    analysis = analysis or {}
    spread = analysis.get("3M-10Y Spread")
    spread_f = float(spread) if spread is not None else None
    return YieldCurveState(
        status=analysis.get("curve_status") or None,
        spread_3m_10y=spread_f,
        # A negative 3M→10Y spread is an inverted curve (recession signal).
        inverted=(spread_f < 0) if spread_f is not None else None,
    )


def get_market_regime(*, force_refresh: bool = False) -> RegimeSnapshot:
    """Return the current market-regime snapshot (VIX / F&G / yield curve).

    Cached for ``_CACHE_TTL_SECONDS``. Each leg degrades to ``None`` on
    upstream failure rather than raising — the caller always gets a
    well-formed snapshot it can render partially.
    """
    key = "regime"
    if not force_refresh:
        hit = _cache.get(key)
        if hit is not None and hit[0] > time.monotonic():
            return hit[1]

    snapshot = RegimeSnapshot(
        vix=_vix(),
        fear_greed=_fear_greed(),
        yield_curve=_yield_curve(),
    )
    _cache[key] = (time.monotonic() + _CACHE_TTL_SECONDS, snapshot)
    return snapshot
