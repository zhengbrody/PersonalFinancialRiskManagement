"""Market-wide regime detail (bull / bear / transition) for the /markets page.

Thin adapter over the legacy ``regime_detector`` (imported verbatim, like the
other services). ``regime_detector.get_regime_summary()`` is self-contained —
it fetches ~2y of SPY + VIX (yfinance, 4h JSON cache) and runs the composite
GMM/vol/trend detector. We add a short in-process TTL cache and **fail soft**:
any upstream failure yields an empty snapshot so the panel renders "—" rather
than 500-ing. NOT a build-time cost — the fetch is a cached runtime call.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

_logger = logging.getLogger(__name__)

_CACHE_TTL_SECONDS = 600  # 10 min; the underlying fetch already caches 4h
_HISTORY_MAX_POINTS = 252  # ~1 trading year of the regime ribbon
_cache: dict[str, tuple[float, "RegimeDetail"]] = {}


@dataclass(frozen=True)
class RegimeHistoryPoint:
    date: str
    regime: str


@dataclass(frozen=True)
class RegimeDetail:
    current_regime: Optional[str] = None
    confidence: Optional[float] = None
    regime_since_date: Optional[str] = None
    vix_regime: Optional[str] = None
    trend_regime: Optional[str] = None
    vol_regime: Optional[str] = None
    history: list[RegimeHistoryPoint] = field(default_factory=list)


def reset_cache() -> None:
    """Test hook — drop the in-process cache."""
    _cache.clear()


def _serialize_history(hist) -> list[RegimeHistoryPoint]:
    """``historical_regimes`` DataFrame → compact [{date, regime}] (last N).

    The per-date composite label lives in the ``composite_signal`` column;
    the date is the index (DatetimeIndex) or a ``date`` column. Anything
    unparseable is skipped — never raise."""
    points: list[RegimeHistoryPoint] = []
    try:
        if hist is None or getattr(hist, "empty", True):
            return []
        df = hist.tail(_HISTORY_MAX_POINTS)
        regime_col = "composite_signal" if "composite_signal" in df.columns else None
        has_date_col = "date" in df.columns
        for idx, row in df.iterrows():
            label = row.get(regime_col) if regime_col else None
            if label is None:
                continue
            raw_date = row.get("date") if has_date_col else idx
            try:
                iso = raw_date.date().isoformat()
            except AttributeError:
                iso = str(raw_date)[:10]
            points.append(RegimeHistoryPoint(date=iso, regime=str(label)))
    except Exception as exc:  # pragma: no cover - defensive
        _logger.warning("regime_detail.history_serialize_failed err=%s", type(exc).__name__)
        return []
    return points


def get_regime_detail(*, force_refresh: bool = False) -> RegimeDetail:
    """Current market regime + ~1y history. Cached; fails soft to an empty
    snapshot (every field nullable) so the caller always renders cleanly."""
    key = "regime_detail"
    if not force_refresh:
        hit = _cache.get(key)
        if hit is not None and hit[0] > time.monotonic():
            return hit[1]

    try:
        from regime_detector import get_regime_summary

        data = get_regime_summary() or {}
    except Exception as exc:  # pragma: no cover - upstream variability
        _logger.warning("regime_detail.fetch_failed err=%s", type(exc).__name__)
        data = {}

    def _clean(v):
        # "Unknown" is the engine's no-data sentinel — surface as None.
        return None if v in (None, "Unknown") else v

    conf = data.get("confidence")
    detail = RegimeDetail(
        current_regime=_clean(data.get("current_regime")),
        confidence=float(conf) if isinstance(conf, (int, float)) else None,
        regime_since_date=data.get("regime_since_date") or None,
        vix_regime=_clean(data.get("vix_regime")),
        trend_regime=_clean(data.get("trend_regime")),
        vol_regime=_clean(data.get("vol_regime")),
        history=_serialize_history(data.get("historical_regimes")),
    )
    _cache[key] = (time.monotonic() + _CACHE_TTL_SECONDS, detail)
    return detail
