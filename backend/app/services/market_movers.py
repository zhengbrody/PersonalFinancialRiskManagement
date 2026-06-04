"""Market movers + sector performance — a fail-soft adapter over the legacy
``volatility_scanner`` module (free yfinance data).

Both legs fail soft to empty so one dead upstream never blanks the panel, and a
short in-process TTL shields yfinance from refresh storms (the legacy module
already disk-caches 1h).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

_logger = logging.getLogger(__name__)

# Movers update intraday; ~10 min staleness is invisible and cheap on yfinance.
_CACHE_TTL_SECONDS = 600
_cache: dict[str, tuple[float, "MoversSnapshot"]] = {}


@dataclass(frozen=True)
class SectorRow:
    sector: str
    ticker: str
    change_pct: Optional[float]
    ytd_return: Optional[float]


@dataclass(frozen=True)
class MoverRow:
    ticker: str
    name: str
    change_pct: Optional[float]
    close: Optional[float]
    avg_volume_ratio: Optional[float]


@dataclass(frozen=True)
class MoversSnapshot:
    scan_date: Optional[str]
    sectors: list[SectorRow] = field(default_factory=list)
    top_gainers: list[MoverRow] = field(default_factory=list)
    top_losers: list[MoverRow] = field(default_factory=list)
    unusual_volume: list[MoverRow] = field(default_factory=list)


def reset_cache() -> None:
    _cache.clear()


def _safe(label: str, fn, default):
    try:
        return fn()
    except Exception as exc:  # pragma: no cover - upstream variability
        _logger.warning("movers.%s.failed err=%s", label, type(exc).__name__)
        return default


def _f(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _mover(d: dict) -> MoverRow:
    return MoverRow(
        ticker=str(d.get("ticker", "")),
        name=str(d.get("name", "") or ""),
        change_pct=_f(d.get("change_pct")),
        close=_f(d.get("close")),
        avg_volume_ratio=_f(d.get("avg_volume_ratio")),
    )


def get_movers(*, top_n: int = 8) -> MoversSnapshot:
    """Sector performance + top gainers/losers/unusual-volume. Cached, fail-soft."""
    key = f"movers:{top_n}"
    hit = _cache.get(key)
    if hit is not None and hit[0] > time.monotonic():
        return hit[1]

    from volatility_scanner import get_sector_performance, scan_sp500_movers

    sectors_raw = _safe("sectors", get_sector_performance, []) or []
    movers_raw = _safe("movers", lambda: scan_sp500_movers(top_n), {}) or {}

    snapshot = MoversSnapshot(
        scan_date=movers_raw.get("scan_date"),
        sectors=[
            SectorRow(
                sector=str(s.get("sector", "")),
                ticker=str(s.get("ticker", "")),
                change_pct=_f(s.get("change_pct")),
                ytd_return=_f(s.get("ytd_return")),
            )
            for s in sectors_raw
        ],
        top_gainers=[_mover(d) for d in movers_raw.get("top_gainers", [])],
        top_losers=[_mover(d) for d in movers_raw.get("top_losers", [])],
        # legacy key is "highest_volume" — surfaced as "unusual_volume".
        unusual_volume=[_mover(d) for d in movers_raw.get("highest_volume", [])],
    )
    _cache[key] = (time.monotonic() + _CACHE_TTL_SECONDS, snapshot)
    return snapshot
