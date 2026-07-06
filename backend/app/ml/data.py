"""Raw market-history fetch for the regime pipeline (free yfinance).

All symbols are free + have deep history, so the training set is reproducible.
`spy` + `vix` are required; the rest are optional (a missing series just yields
NaN features downstream). Fail-soft: a dead/throttled ticker is skipped, never
raised. The fetcher is injectable so tests run offline.
"""

from __future__ import annotations

import logging
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
            _log.info("ml.data.cache_hit path=%s keys=%s", cached, sorted(raw))
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
