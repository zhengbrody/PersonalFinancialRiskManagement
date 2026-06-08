"""Macro data orchestrator — FRED + US Treasury, both completely free.

Why these two:

* **FRED (Federal Reserve Bank of St. Louis)** — every US macro series
  worth showing (DFF, CPIAUCSL, UNRATE, GDP, …). The public CSV
  download endpoint requires no API key and has no rate limit we've
  ever hit at retail scale. Costs us nothing and never expires.

* **US Treasury daily yield curve** — the canonical risk-free curve.
  FMP's premium tier was charging for this; the Treasury publishes
  the same CSV for free.

Two helpers, mirrored on the existing ``market_data`` shape:

* ``get_fred_series(series_id, days)`` — last N days of one series.
* ``get_yield_curve()`` — latest full curve (1M … 30Y).

Both calls go through a small in-process LRU + 1h TTL cache. Macro
series update daily (FRED) or daily (Treasury), so a 1h TTL is plenty
without giving up freshness. The cache also protects us if either
upstream goes down briefly — stale-but-recent is much better than 500.
"""

from __future__ import annotations

import io
import logging
import re
import time
from dataclasses import dataclass
from typing import Iterable, Optional

import pandas as pd
import requests

_logger = logging.getLogger(__name__)

# ── tunables ───────────────────────────────────────────────────────

# HTTP timeout — FRED is consistently <1s. Treasury.gov measured at
# 8-9s from EC2 us-east-1 during Phase 5 staging (the upstream itself
# is slow, not the network path). 20s gives a comfortable margin while
# still failing fast if the upstream is truly down. Per the cache
# layer above, a successful response stays warm for 1h, so this
# timeout only bites on cache misses.
_HTTP_TIMEOUT = 20

# 1h is a sweet spot: FRED publishes once per business day, the Treasury
# curve updates once per day. Within an hour we're guaranteed identical
# data; the cache just dampens the load.
_CACHE_TTL_SECONDS = 60 * 60
CACHE_TTL_SECONDS = _CACHE_TTL_SECONDS

# FRED series ID format — uppercase letters, digits, underscore, dot.
# Examples: DFF, CPIAUCSL, GDPC1, T10Y2Y, UNRATE.
_SERIES_ID_RE = re.compile(r"^[A-Z0-9._]{1,40}$")

# Lock down what we accept — the public list of FRED series is huge,
# but for the dashboard we only need a handful. Constraining the
# whitelist server-side stops a misconfigured client (or scraper)
# from turning our backend into a free FRED proxy.
ALLOWED_FRED_SERIES: dict[str, str] = {
    "DFF": "Federal Funds Effective Rate (daily)",
    "DGS10": "10-Year Treasury Constant Maturity Rate (daily)",
    "CPIAUCSL": "Consumer Price Index — All Urban Consumers (monthly)",
    "UNRATE": "Civilian Unemployment Rate (monthly)",
    "T10Y2Y": "10Y minus 2Y Treasury spread (daily)",
    "VIXCLS": "CBOE Volatility Index — VIX (daily)",
}


# ── result shapes ──────────────────────────────────────────────────


@dataclass(frozen=True)
class SeriesPoint:
    """One observation of a FRED series."""

    date: str  # ISO YYYY-MM-DD
    value: float


@dataclass(frozen=True)
class SeriesResult:
    """Latest window of a FRED series + the human-readable label."""

    series_id: str
    label: str
    latest_value: Optional[float]
    latest_date: Optional[str]
    points: list[SeriesPoint]


@dataclass(frozen=True)
class YieldCurvePoint:
    """One tenor on the Treasury yield curve."""

    tenor: str  # e.g. "1M", "3M", "2Y", "10Y"
    yield_pct: float


@dataclass(frozen=True)
class YieldCurveResult:
    as_of: str
    points: list[YieldCurvePoint]


# ── internal cache ─────────────────────────────────────────────────


@dataclass
class _CacheEntry:
    value: object
    expires_at: float


_cache: dict[str, _CacheEntry] = {}


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry is None or entry.expires_at < time.monotonic():
        return None
    return entry.value


def _cache_set(key: str, value: object) -> None:
    _cache[key] = _CacheEntry(value=value, expires_at=time.monotonic() + _CACHE_TTL_SECONDS)


def reset_cache() -> None:
    """Test/maintenance escape hatch; not used by routes."""
    _cache.clear()


# ── HTTP plumbing ──────────────────────────────────────────────────


def _http_get(url: str) -> str:
    """Plain GET → text, no retry. FRED + Treasury are CDNs with
    high availability; if they fail, surface fast rather than block.

    Separated so tests can monkeypatch this single function instead
    of monkeypatching ``requests`` globally."""
    from . import metrics

    # FRED vs Treasury, derived from the host so both upstreams count separately.
    provider = "treasury" if "treasury" in url.lower() else "fred"
    try:
        resp = requests.get(
            url,
            timeout=_HTTP_TIMEOUT,
            headers={
                # Identify ourselves so upstream operators can contact
                # if a usage pattern looks abusive. Both endpoints are
                # public and don't gate by UA.
                "User-Agent": "MindMarketBackend/1.0 (contact@mindmarket.app)"
            },
        )
        resp.raise_for_status()
    except Exception:
        metrics.record_provider(provider, "error")
        raise
    metrics.record_provider(provider, "ok")
    return resp.text


# ── FRED ───────────────────────────────────────────────────────────


def _validate_series_id(series_id: str) -> str:
    s = (series_id or "").strip().upper()
    if not _SERIES_ID_RE.match(s):
        raise ValueError(f"Invalid FRED series id: {series_id!r}")
    if s not in ALLOWED_FRED_SERIES:
        raise ValueError(
            f"Series {s} is not on the allow-list. Add it to "
            "ALLOWED_FRED_SERIES if it belongs in the dashboard."
        )
    return s


def get_fred_series(series_id: str, *, days: int = 365) -> SeriesResult:
    """Return the trailing window of a FRED series.

    ``days`` clamps to a reasonable max so a buggy caller can't ask
    for "all history since 1947". Window is approximate — FRED
    publishes weekdays only for daily series; we send back whatever
    they return.
    """
    sid = _validate_series_id(series_id)
    window = max(30, min(days, 365 * 10))
    cache_key = f"fred::{sid}::{window}"
    cached = _cache_get(cache_key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    start = (pd.Timestamp.today().normalize() - pd.Timedelta(days=window)).strftime("%Y-%m-%d")
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={start}"
    text = _http_get(url)

    df = pd.read_csv(io.StringIO(text))
    if df.empty or df.shape[1] < 2:
        result = SeriesResult(
            series_id=sid,
            label=ALLOWED_FRED_SERIES[sid],
            latest_value=None,
            latest_date=None,
            points=[],
        )
        _cache_set(cache_key, result)
        return result

    # FRED uses "." as a sentinel for "no value reported"; coerce to NaN
    # and drop. Older FRED CSVs also use lower-case column names.
    date_col = df.columns[0]
    val_col = df.columns[1]
    df[val_col] = pd.to_numeric(df[val_col], errors="coerce")
    df = df.dropna(subset=[val_col]).copy()

    points: list[SeriesPoint] = []
    for _, row in df.iterrows():
        try:
            d = pd.Timestamp(row[date_col]).strftime("%Y-%m-%d")
            v = float(row[val_col])
        except Exception:
            continue
        points.append(SeriesPoint(date=d, value=v))

    latest_value = points[-1].value if points else None
    latest_date = points[-1].date if points else None
    result = SeriesResult(
        series_id=sid,
        label=ALLOWED_FRED_SERIES[sid],
        latest_value=latest_value,
        latest_date=latest_date,
        points=points,
    )
    _cache_set(cache_key, result)
    return result


def get_fred_series_batch(series_ids: Iterable[str], *, days: int = 365) -> list[SeriesResult]:
    """Convenience: pull several series, dedup + validate first."""
    seen: set[str] = set()
    out: list[SeriesResult] = []
    for raw in series_ids:
        sid = _validate_series_id(raw)
        if sid in seen:
            continue
        seen.add(sid)
        try:
            out.append(get_fred_series(sid, days=days))
        except Exception as exc:
            _logger.warning("macro.fred.series_failed sid=%s err=%s", sid, exc)
    return out


# ── Treasury yield curve ───────────────────────────────────────────


# Treasury's CSV uses verbose column labels; map them to compact tenors
# the frontend wants.
_TENOR_MAP: dict[str, str] = {
    "1 Mo": "1M",
    "2 Mo": "2M",
    "3 Mo": "3M",
    "4 Mo": "4M",
    "6 Mo": "6M",
    "1 Yr": "1Y",
    "2 Yr": "2Y",
    "3 Yr": "3Y",
    "5 Yr": "5Y",
    "7 Yr": "7Y",
    "10 Yr": "10Y",
    "20 Yr": "20Y",
    "30 Yr": "30Y",
}


def get_yield_curve(*, force_refresh: bool = False) -> YieldCurveResult:
    """Return today's (or the most recent published) Treasury curve.

    The Treasury publishes the CSV per calendar year. We pull the
    current year's file and use the most recent row.
    """
    year = pd.Timestamp.today().year
    cache_key = f"treasury::yc::{year}"
    if not force_refresh:
        cached = _cache_get(cache_key)
        if cached is not None:
            return cached  # type: ignore[return-value]

    url = (
        "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
        f"daily-treasury-rates.csv/{year}/all?"
        "type=daily_treasury_yield_curve"
        f"&field_tdr_date_value={year}&page&_format=csv"
    )
    text = _http_get(url)
    df = pd.read_csv(io.StringIO(text))

    if df.empty:
        result = YieldCurveResult(as_of="", points=[])
        _cache_set(cache_key, result)
        return result

    # Treasury CSV is newest-row-first; pick the head.
    row = df.iloc[0]
    as_of_raw = str(row["Date"])
    try:
        as_of = pd.Timestamp(as_of_raw).strftime("%Y-%m-%d")
    except Exception:
        as_of = as_of_raw

    points: list[YieldCurvePoint] = []
    for col, tenor in _TENOR_MAP.items():
        if col not in row:
            continue
        try:
            v = float(row[col])
        except (TypeError, ValueError):
            continue
        if pd.isna(v):
            continue
        points.append(YieldCurvePoint(tenor=tenor, yield_pct=v))

    result = YieldCurveResult(as_of=as_of, points=points)
    _cache_set(cache_key, result)
    return result
