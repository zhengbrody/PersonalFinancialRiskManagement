"""Raw market-history fetch for the regime pipeline (free yfinance).

All symbols are free + have deep history, so the training set is reproducible.
`spy` + `vix` are required; the rest are optional (a missing series just yields
NaN features downstream). Fail-soft: a dead/throttled ticker is skipped, never
raised. The fetcher is injectable so tests run offline.
"""

from __future__ import annotations

import logging
import time
import warnings
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

_log = logging.getLogger(__name__)

# Internal key -> yfinance symbol.
SYMBOLS: dict[str, str] = {
    "spy": "SPY",
    "qqq": "QQQ",
    "vix": "^VIX",
    "vix3m": "^VIX3M",
    "tnx": "^TNX",  # 10-year Treasury yield
    "irx": "^IRX",  # 13-week T-bill yield (3m)
}
REQUIRED = ("spy", "vix")


def _yf_close(symbol: str, start: str) -> Optional[pd.Series]:
    """Free-yfinance Close series since ``start``; None on any failure."""
    try:
        import yfinance as yf

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = yf.download(symbol, start=start, auto_adjust=True, progress=False)
        if df is None or getattr(df, "empty", True):
            return None
        if isinstance(df.columns, pd.MultiIndex):
            close = df["Close"]
            close = close.iloc[:, 0] if hasattr(close, "iloc") and close.ndim > 1 else close
        else:
            close = df["Close"] if "Close" in df.columns else df.iloc[:, 0]
        return close.dropna()
    except Exception as exc:  # noqa: BLE001 - fail-soft, optional sources may 404/throttle
        _log.warning("ml.data.fetch_failed symbol=%s err=%s", symbol, type(exc).__name__)
        return None


def fetch_history(
    *,
    years: float = 15.0,
    fetcher: Callable[[str, str], Optional[pd.Series]] = _yf_close,
    cache_dir: Optional[str] = None,
) -> dict[str, pd.Series]:
    """Return {key: Close series} for the SYMBOLS, going back ``years``.

    Raises only if a REQUIRED series (spy/vix) is unavailable; optional series
    that fail are simply omitted (their features become NaN). ``fetcher`` is
    injectable for offline tests.

    ``cache_dir`` (training-side reproducibility): when set, a pickled raw
    snapshot is read if present — a rerun against the same snapshot reproduces
    metrics BIT-FOR-BIT (live yfinance moves daily; the snapshot pins the
    data). On a miss the live fetch runs and the snapshot is written. Stdlib
    pickle by design: exact round-trip, zero extra deps; the file is our own
    artifact, never untrusted input."""
    if cache_dir is not None:
        cached = _cache_path(cache_dir, years)
        if cached.exists():
            raw = pd.read_pickle(cached)
            # A snapshot bypasses the live fetch, NOT the contract: required
            # series must still be present, and a schema drift (SYMBOLS grew
            # since the pickle) deserves a loud warning, not silent NaN.
            missing_required = [k for k in REQUIRED if k not in raw]
            if missing_required:
                raise ValueError(
                    f"cached snapshot {cached} is missing required series "
                    f"{missing_required} — delete it to refetch"
                )
            if set(raw) != set(SYMBOLS):
                _log.warning(
                    "ml.data.cache_schema_drift path=%s missing=%s",
                    cached,
                    sorted(set(SYMBOLS) - set(raw)),
                )
            spy = raw.get("spy")
            end = str(spy.index[-1].date()) if spy is not None and len(spy) else "?"
            _log.info(
                "ml.data.cache_hit path=%s keys=%s data_end=%s "
                "(snapshots never expire — delete the file to refresh)",
                cached,
                sorted(raw),
                end,
            )
            return raw

    start = (datetime.now() - timedelta(days=int(365 * years) + 30)).strftime("%Y-%m-%d")
    out: dict[str, pd.Series] = {}
    for key, symbol in SYMBOLS.items():
        series = fetcher(symbol, start)
        if series is not None and len(series) > 0:
            out[key] = series.astype(float)
    missing_required = [k for k in REQUIRED if k not in out]
    if missing_required:
        raise ValueError(f"required market history unavailable: {missing_required}")

    if cache_dir is not None:
        cached = _cache_path(cache_dir, years)
        cached.parent.mkdir(parents=True, exist_ok=True)
        pd.to_pickle(out, cached)
        _log.info("ml.data.cache_written path=%s", cached)
    return out


def _cache_path(cache_dir: str, years: float) -> Path:
    return Path(cache_dir) / f"raw_history_{years:g}y.pkl"


# ── serving-side shared raw cache ─────────────────────────────────────
# ml_regime + ml_health both need the same frame; without this each kept its
# own cold cache → two full 6-symbol yfinance bursts per TTL from the prod IP.
# One raw fetch now serves every consumer within the TTL — which requires both
# callers to request the SAME window, so SERVE_YEARS is the single source (a
# divergence here would silently split the cache key and revert to two bursts).
# ~1.75y warms the longest feature window (SMA200 + 252d rollups) with margin;
# only the latest row is predicted on, so more would be wasted bytes.
SERVE_YEARS = 1.75
SERVE_CACHE_TTL = 600.0
_serve_cache: dict[str, tuple[float, dict[str, pd.Series]]] = {}


def reset_serve_cache() -> None:
    _serve_cache.clear()


def fetch_history_cached(
    *,
    years: float,
    fetcher: Optional[Callable[[str, str], Optional[pd.Series]]] = None,
    ttl: float = SERVE_CACHE_TTL,
) -> dict[str, pd.Series]:
    """`fetch_history` behind a process-wide TTL cache, shared across services.

    Only the DEFAULT fetcher is cached — an injected fetcher (tests) bypasses
    the cache entirely so offline fixtures stay deterministic."""
    if fetcher is not None:
        return fetch_history(years=years, fetcher=fetcher)
    key = f"{years:g}"
    now = time.monotonic()
    hit = _serve_cache.get(key)
    if hit is not None and hit[0] > now:
        return hit[1]
    raw = fetch_history(years=years, fetcher=_yf_close)
    _serve_cache[key] = (now + ttl, raw)
    return raw


def data_coverage(raw: dict[str, pd.Series]) -> dict:
    """Compact provenance: which sources resolved + the SPY history span."""
    spy = raw.get("spy")
    return {
        "sources_present": sorted(raw.keys()),
        "sources_missing": sorted(set(SYMBOLS) - set(raw.keys())),
        "spy_start": str(spy.index[0].date()) if spy is not None and len(spy) else None,
        "spy_end": str(spy.index[-1].date()) if spy is not None and len(spy) else None,
        "observations": int(len(spy)) if spy is not None else 0,
    }
