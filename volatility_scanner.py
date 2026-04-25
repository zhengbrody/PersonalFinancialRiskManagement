"""
volatility_scanner.py
Daily Post-Market Volatility Scanner v1.0
──────────────────────────────────────────────────────────
Scans S&P 500 movers, portfolio movers, IV rank/percentile,
market regime summary, and sector performance.

All data sourced via yfinance. Results cached for 1 hour in .cache/
to avoid hammering the API on repeated dashboard refreshes.

Dependencies: yfinance, numpy, pandas (all in requirements.txt)
"""

import hashlib
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional

import numpy as np
import pandas as pd
import yfinance as yf

from logging_config import get_logger

logger = get_logger(__name__)

# ══════════════════════════════════════════════════════════════
#  Constants
# ══════════════════════════════════════════════════════════════

CACHE_DIR = ".cache/volatility_scanner"
CACHE_MAX_AGE_SECONDS = 3600  # 1 hour

# Top ~100 most liquid S&P 500 stocks (by market cap / trading volume)
SP500_LIQUID_100 = [
    "AAPL",
    "MSFT",
    "NVDA",
    "GOOGL",
    "AMZN",
    "META",
    "TSLA",
    "BRK-B",
    "LLY",
    "AVGO",
    "JPM",
    "V",
    "UNH",
    "MA",
    "XOM",
    "JNJ",
    "COST",
    "HD",
    "PG",
    "ABBV",
    "MRK",
    "NFLX",
    "CRM",
    "AMD",
    "BAC",
    "CVX",
    "KO",
    "PEP",
    "WMT",
    "LIN",
    "ADBE",
    "TMO",
    "MCD",
    "CSCO",
    "ACN",
    "ABT",
    "ORCL",
    "DHR",
    "INTC",
    "QCOM",
    "CMCSA",
    "VZ",
    "TXN",
    "PM",
    "NEE",
    "LOW",
    "UNP",
    "RTX",
    "INTU",
    "AMGN",
    "MS",
    "GS",
    "HON",
    "T",
    "PFE",
    "BMY",
    "SCHW",
    "ISRG",
    "DE",
    "BLK",
    "GE",
    "C",
    "SYK",
    "ADP",
    "ELV",
    "AMAT",
    "GILD",
    "BKNG",
    "MDLZ",
    "ADI",
    "LRCX",
    "REGN",
    "CB",
    "VRTX",
    "MMC",
    "CI",
    "ZTS",
    "PYPL",
    "SO",
    "DUK",
    "CME",
    "CL",
    "SNPS",
    "CDNS",
    "MO",
    "EOG",
    "PGR",
    "WM",
    "SLB",
    "APD",
    "MCK",
    "USB",
    "FDX",
    "KLAC",
    "AJG",
    "PANW",
    "NOW",
    "ICE",
    "PLD",
    "ABNB",
    "MELI",
    "CRWD",
    "FTNT",
    "UBER",
    "COIN",
    "PLTR",
    "DASH",
    "ARM",
]

SECTOR_ETFS = {
    "Technology": "XLK",
    "Financials": "XLF",
    "Energy": "XLE",
    "Healthcare": "XLV",
    "Industrials": "XLI",
    "Communication Svcs": "XLC",
    "Consumer Disc": "XLY",
    "Consumer Staples": "XLP",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Materials": "XLB",
}


# ══════════════════════════════════════════════════════════════
#  File-based Cache
# ══════════════════════════════════════════════════════════════


def _ensure_cache_dir():
    """Create cache directory if it does not exist."""
    os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_key(func_name: str, args_repr: str) -> str:
    """Produce a deterministic filename-safe cache key."""
    raw = f"{func_name}:{args_repr}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return os.path.join(CACHE_DIR, f"{func_name}_{digest}.json")


def _read_cache(path: str) -> Optional[dict]:
    """Read cached result if the file exists and is younger than CACHE_MAX_AGE_SECONDS."""
    if not os.path.exists(path):
        return None
    try:
        mtime = os.path.getmtime(path)
        if time.time() - mtime > CACHE_MAX_AGE_SECONDS:
            return None
        with open(path, "r") as fh:
            return json.load(fh)
    except Exception:
        return None


def _write_cache(path: str, data: dict):
    """Persist result to cache file."""
    _ensure_cache_dir()
    try:
        with open(path, "w") as fh:
            json.dump(data, fh, default=str)
    except Exception as exc:
        logger.warning("cache_write_failed", path=path, error=str(exc))


# ══════════════════════════════════════════════════════════════
#  Internal helpers
# ══════════════════════════════════════════════════════════════


def _safe_float(val) -> Optional[float]:
    """Convert a value to float, returning None on failure."""
    try:
        result = float(val)
        if np.isnan(result) or np.isinf(result):
            return None
        return result
    except (TypeError, ValueError):
        return None


def _fetch_ticker_day_data(ticker: str) -> Optional[Dict]:
    """
    Fetch the most recent trading day's OHLCV plus 30-day average volume
    for a single ticker.

    Returns a dict with fields needed by the mover-scan, or None on error.
    """
    try:
        tk = yf.Ticker(ticker)
        info = tk.info or {}

        # 5d history gives us today's bar plus a few prior bars for prev close
        hist = tk.history(period="5d")
        # Drop rows where Close is NaN (e.g. today's bar before market close)
        hist = hist.dropna(subset=["Close"])
        if hist.empty or len(hist) < 2:
            return None

        today = hist.iloc[-1]
        prev = hist.iloc[-2]

        close = _safe_float(today.get("Close"))
        prev_close = _safe_float(prev.get("Close"))
        volume = _safe_float(today.get("Volume"))
        if close is None or prev_close is None or prev_close == 0:
            return None

        change_pct = round((close - prev_close) / prev_close * 100, 2)

        # 30-day average volume from info (faster than downloading 30d hist)
        avg_volume = _safe_float(info.get("averageDailyVolume10Day")) or _safe_float(
            info.get("averageVolume")
        )
        avg_volume_ratio = None
        if avg_volume and avg_volume > 0 and volume:
            avg_volume_ratio = round(volume / avg_volume, 2)

        name = info.get("shortName") or info.get("longName") or ticker

        return {
            "ticker": ticker,
            "name": name,
            "change_pct": change_pct,
            "close": round(close, 2),
            "volume": int(volume) if volume else None,
            "avg_volume_ratio": avg_volume_ratio,
        }
    except Exception as exc:
        logger.warning("fetch_ticker_failed", ticker=ticker, error=str(exc))
        return None


def _batch_fetch_movers(tickers: List[str], max_workers: int = 10) -> List[Dict]:
    """Fetch day data for a list of tickers in parallel."""
    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_ticker_day_data, t): t for t in tickers}
        for future in as_completed(futures):
            data = future.result()
            if data is not None:
                results.append(data)
    return results


# ══════════════════════════════════════════════════════════════
#  1. S&P 500 Mover Scan
# ══════════════════════════════════════════════════════════════


def scan_sp500_movers(top_n: int = 20) -> Dict:
    """
    Scan the top ~100 most-liquid S&P 500 stocks and return today's
    biggest gainers, losers, and unusual-volume names.

    Parameters
    ----------
    top_n : int
        Number of entries to return in each of top_gainers / top_losers.

    Returns
    -------
    dict
        {
            "top_gainers":    [{ticker, name, change_pct, close, volume, avg_volume_ratio}, ...],
            "top_losers":     [{...}, ...],
            "highest_volume": [{...}, ...],   # avg_volume_ratio > 2.0
            "scan_date":      "YYYY-MM-DD",
        }
    """
    cache_path = _cache_key("scan_sp500_movers", str(top_n))
    cached = _read_cache(cache_path)
    if cached is not None:
        logger.info("scan_sp500_movers_cache_hit")
        return cached

    logger.info("scan_sp500_movers_start", n_tickers=len(SP500_LIQUID_100), top_n=top_n)
    all_data = _batch_fetch_movers(SP500_LIQUID_100)

    # Sort for gainers (desc) and losers (asc)
    sorted_by_change = sorted(all_data, key=lambda d: d["change_pct"], reverse=True)
    top_gainers = sorted_by_change[:top_n]
    top_losers = sorted_by_change[-top_n:][::-1]  # worst first

    # Unusual volume: avg_volume_ratio > 2.0
    highest_volume = sorted(
        [d for d in all_data if d.get("avg_volume_ratio") and d["avg_volume_ratio"] > 2.0],
        key=lambda d: d["avg_volume_ratio"],
        reverse=True,
    )

    result = {
        "top_gainers": top_gainers,
        "top_losers": top_losers,
        "highest_volume": highest_volume,
        "scan_date": datetime.now().strftime("%Y-%m-%d"),
    }

    _write_cache(cache_path, result)
    logger.info(
        "scan_sp500_movers_done",
        gainers=len(top_gainers),
        losers=len(top_losers),
        unusual_vol=len(highest_volume),
    )
    return result


# ══════════════════════════════════════════════════════════════
#  2. Portfolio Mover Scan
# ══════════════════════════════════════════════════════════════


def scan_portfolio_movers(tickers: List[str], top_n: int = 10) -> Dict:
    """
    Same output format as scan_sp500_movers but limited to a user-supplied
    list of portfolio holdings.

    Parameters
    ----------
    tickers : list[str]
        Ticker symbols to scan.
    top_n : int
        Max entries per category.

    Returns
    -------
    dict
        {top_gainers, top_losers, highest_volume, scan_date}
    """
    tickers_key = ",".join(sorted(tickers))
    cache_path = _cache_key("scan_portfolio_movers", f"{tickers_key}_{top_n}")
    cached = _read_cache(cache_path)
    if cached is not None:
        logger.info("scan_portfolio_movers_cache_hit")
        return cached

    logger.info("scan_portfolio_movers_start", n_tickers=len(tickers), top_n=top_n)
    all_data = _batch_fetch_movers(tickers)

    sorted_by_change = sorted(all_data, key=lambda d: d["change_pct"], reverse=True)
    top_gainers = sorted_by_change[:top_n]
    top_losers = sorted_by_change[-top_n:][::-1]

    highest_volume = sorted(
        [d for d in all_data if d.get("avg_volume_ratio") and d["avg_volume_ratio"] > 2.0],
        key=lambda d: d["avg_volume_ratio"],
        reverse=True,
    )

    result = {
        "top_gainers": top_gainers,
        "top_losers": top_losers,
        "highest_volume": highest_volume,
        "scan_date": datetime.now().strftime("%Y-%m-%d"),
    }

    _write_cache(cache_path, result)
    logger.info("scan_portfolio_movers_done", n_results=len(all_data))
    return result


# ══════════════════════════════════════════════════════════════
#  3. IV Movers (IV Rank & IV Percentile)
# ══════════════════════════════════════════════════════════════


def _compute_near_atm_iv(ticker: str) -> Optional[Dict]:
    """
    For a single ticker, fetch near-ATM implied volatility from the
    nearest-expiry option chain, then compute IV Rank and IV Percentile
    using a 252-trading-day historical volatility proxy as the 52-week range.

    Returns
    -------
    dict or None
        {ticker, current_iv, iv_rank, iv_percentile, iv_change_1d}
    """
    try:
        tk = yf.Ticker(ticker)
        expirations = tk.options
        if not expirations:
            return None

        # Pick the nearest expiration that is at least 7 days out to avoid
        # weirdly compressed 0-DTE IVs.
        today = datetime.now().date()
        chosen_exp = None
        for exp_str in expirations:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            if (exp_date - today).days >= 7:
                chosen_exp = exp_str
                break
        if chosen_exp is None:
            chosen_exp = expirations[0]

        chain = tk.option_chain(chosen_exp)
        calls = chain.calls
        puts = chain.puts

        if calls.empty and puts.empty:
            return None

        # Current underlying price
        hist = tk.history(period="5d")
        hist = hist.dropna(subset=["Close"])
        if hist.empty:
            return None
        spot = float(hist["Close"].iloc[-1])

        # Find near-ATM: strike closest to spot
        all_strikes = pd.concat([calls[["strike"]], puts[["strike"]]]).drop_duplicates()
        atm_strike = all_strikes.iloc[(all_strikes["strike"] - spot).abs().argsort().iloc[0]][
            "strike"
        ]

        # Average the call and put ATM IV
        call_iv = calls.loc[calls["strike"] == atm_strike, "impliedVolatility"]
        put_iv = puts.loc[puts["strike"] == atm_strike, "impliedVolatility"]

        ivs = []
        if not call_iv.empty:
            v = _safe_float(call_iv.iloc[0])
            if v is not None:
                ivs.append(v)
        if not put_iv.empty:
            v = _safe_float(put_iv.iloc[0])
            if v is not None:
                ivs.append(v)

        if not ivs:
            return None

        current_iv = round(float(np.mean(ivs)) * 100, 2)  # as percentage

        # Approximate 52-week IV range using historical volatility of the
        # underlying (realized vol) as a stand-in.  We compute 30-day rolling
        # HV over the past year to get high / low / distribution.
        hist_1y = tk.history(period="1y")
        if hist_1y.empty or len(hist_1y) < 60:
            # Not enough data to compute rank; return current IV only
            return {
                "ticker": ticker,
                "current_iv": current_iv,
                "iv_rank": None,
                "iv_percentile": None,
                "iv_change_1d": None,
            }

        log_ret = np.log(hist_1y["Close"] / hist_1y["Close"].shift(1)).dropna()
        rolling_hv = log_ret.rolling(window=30).std() * np.sqrt(252) * 100
        rolling_hv = rolling_hv.dropna()

        if rolling_hv.empty:
            return {
                "ticker": ticker,
                "current_iv": current_iv,
                "iv_rank": None,
                "iv_percentile": None,
                "iv_change_1d": None,
            }

        hv_min = float(rolling_hv.min())
        hv_max = float(rolling_hv.max())

        # IV Rank = (current - 52w low) / (52w high - 52w low)
        if hv_max - hv_min > 0.01:
            iv_rank = round((current_iv - hv_min) / (hv_max - hv_min) * 100, 1)
            iv_rank = max(0.0, min(100.0, iv_rank))
        else:
            iv_rank = 50.0  # flat vol environment, default mid

        # IV Percentile = % of past observations below current IV
        iv_percentile = round(float((rolling_hv < current_iv).mean()) * 100, 1)

        # Approximate 1-day IV change: difference between today's ATM IV and
        # yesterday's closing HV (rough proxy)
        iv_change_1d = None
        if len(rolling_hv) >= 2:
            prev_hv = float(rolling_hv.iloc[-2])
            iv_change_1d = round(current_iv - prev_hv, 2)

        return {
            "ticker": ticker,
            "current_iv": current_iv,
            "iv_rank": iv_rank,
            "iv_percentile": iv_percentile,
            "iv_change_1d": iv_change_1d,
        }

    except Exception as exc:
        logger.warning("iv_computation_failed", ticker=ticker, error=str(exc))
        return None


def get_iv_movers(tickers: List[str]) -> List[Dict]:
    """
    For each ticker, compute current ATM implied volatility, IV Rank (0-100%),
    IV Percentile, and approximate 1-day IV change.

    IV Rank indicates where current IV sits within its 52-week range.
    IV Percentile indicates the percentage of days in the past year where
    IV was lower than today.

    Parameters
    ----------
    tickers : list[str]
        Ticker symbols to analyse.

    Returns
    -------
    list[dict]
        Each entry: {ticker, current_iv, iv_rank, iv_percentile, iv_change_1d}
        Tickers that fail are silently omitted.
    """
    tickers_key = ",".join(sorted(tickers))
    cache_path = _cache_key("get_iv_movers", tickers_key)
    cached = _read_cache(cache_path)
    if cached is not None:
        logger.info("get_iv_movers_cache_hit")
        return cached

    logger.info("get_iv_movers_start", n_tickers=len(tickers))
    results = []

    # Options data can be rate-limited; use moderate parallelism
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(_compute_near_atm_iv, t): t for t in tickers}
        for future in as_completed(futures):
            data = future.result()
            if data is not None:
                results.append(data)

    # Sort by IV rank descending (highest IV rank = most "elevated")
    results.sort(key=lambda d: d.get("iv_rank") or 0, reverse=True)

    _write_cache(cache_path, results)
    logger.info("get_iv_movers_done", n_results=len(results))
    return results


# ══════════════════════════════════════════════════════════════
#  4. Market Regime Summary
# ══════════════════════════════════════════════════════════════


def get_market_regime_summary() -> Dict:
    """
    Quick-look market overview: VIX, S&P 500 return, 10Y yield,
    USD index, and a put/call ratio approximation from SPY options volume.

    Returns
    -------
    dict
        {
            "vix_level":        float,
            "vix_change":       float,   # daily change in VIX points
            "sp500_return_pct": float,   # S&P 500 daily return %
            "tnx_yield":        float,   # 10Y Treasury yield %
            "tnx_change":       float,   # daily change in yield points
            "usd_index":        float,   # DX-Y.NYB level
            "usd_change_pct":   float,
            "put_call_ratio":   float or None,
            "regime_label":     str,     # "Low Vol" / "Normal" / "Elevated" / "High Vol"
            "scan_date":        str,
        }
    """
    cache_path = _cache_key("get_market_regime_summary", "")
    cached = _read_cache(cache_path)
    if cached is not None:
        logger.info("market_regime_cache_hit")
        return cached

    logger.info("market_regime_start")
    result: Dict = {"scan_date": datetime.now().strftime("%Y-%m-%d")}

    # --- VIX ---
    try:
        vix = yf.Ticker("^VIX")
        vix_hist = vix.history(period="5d").dropna(subset=["Close"])
        if not vix_hist.empty and len(vix_hist) >= 2:
            result["vix_level"] = round(float(vix_hist["Close"].iloc[-1]), 2)
            result["vix_change"] = round(
                float(vix_hist["Close"].iloc[-1] - vix_hist["Close"].iloc[-2]), 2
            )
        else:
            result["vix_level"] = None
            result["vix_change"] = None
    except Exception as exc:
        logger.warning("vix_fetch_failed", error=str(exc))
        result["vix_level"] = None
        result["vix_change"] = None

    # --- S&P 500 daily return ---
    try:
        spy = yf.Ticker("^GSPC")
        spy_hist = spy.history(period="5d").dropna(subset=["Close"])
        if not spy_hist.empty and len(spy_hist) >= 2:
            today_close = float(spy_hist["Close"].iloc[-1])
            prev_close = float(spy_hist["Close"].iloc[-2])
            result["sp500_return_pct"] = round((today_close - prev_close) / prev_close * 100, 2)
        else:
            result["sp500_return_pct"] = None
    except Exception as exc:
        logger.warning("sp500_fetch_failed", error=str(exc))
        result["sp500_return_pct"] = None

    # --- 10Y Treasury yield ---
    try:
        tnx = yf.Ticker("^TNX")
        tnx_hist = tnx.history(period="5d").dropna(subset=["Close"])
        if not tnx_hist.empty and len(tnx_hist) >= 2:
            result["tnx_yield"] = round(float(tnx_hist["Close"].iloc[-1]), 3)
            result["tnx_change"] = round(
                float(tnx_hist["Close"].iloc[-1] - tnx_hist["Close"].iloc[-2]), 3
            )
        else:
            result["tnx_yield"] = None
            result["tnx_change"] = None
    except Exception as exc:
        logger.warning("tnx_fetch_failed", error=str(exc))
        result["tnx_yield"] = None
        result["tnx_change"] = None

    # --- USD Index ---
    try:
        dx = yf.Ticker("DX-Y.NYB")
        dx_hist = dx.history(period="5d").dropna(subset=["Close"])
        if not dx_hist.empty and len(dx_hist) >= 2:
            dx_close = float(dx_hist["Close"].iloc[-1])
            dx_prev = float(dx_hist["Close"].iloc[-2])
            result["usd_index"] = round(dx_close, 2)
            result["usd_change_pct"] = round((dx_close - dx_prev) / dx_prev * 100, 2)
        else:
            result["usd_index"] = None
            result["usd_change_pct"] = None
    except Exception as exc:
        logger.warning("usd_index_fetch_failed", error=str(exc))
        result["usd_index"] = None
        result["usd_change_pct"] = None

    # --- Put/Call ratio from SPY options ---
    try:
        spy_tk = yf.Ticker("SPY")
        expirations = spy_tk.options
        if expirations:
            # Pick the nearest expiration
            chain = spy_tk.option_chain(expirations[0])
            total_put_vol = chain.puts["volume"].sum() if "volume" in chain.puts.columns else 0
            total_call_vol = chain.calls["volume"].sum() if "volume" in chain.calls.columns else 0
            if total_call_vol > 0:
                result["put_call_ratio"] = round(float(total_put_vol / total_call_vol), 2)
            else:
                result["put_call_ratio"] = None
        else:
            result["put_call_ratio"] = None
    except Exception as exc:
        logger.warning("put_call_ratio_failed", error=str(exc))
        result["put_call_ratio"] = None

    # --- Regime label ---
    vix = result.get("vix_level")
    if vix is not None:
        if vix < 15:
            result["regime_label"] = "Low Vol"
        elif vix < 20:
            result["regime_label"] = "Normal"
        elif vix < 30:
            result["regime_label"] = "Elevated"
        else:
            result["regime_label"] = "High Vol"
    else:
        result["regime_label"] = "Unknown"

    _write_cache(cache_path, result)
    logger.info("market_regime_done", regime=result.get("regime_label"))
    return result


# ══════════════════════════════════════════════════════════════
#  5. Sector Performance
# ══════════════════════════════════════════════════════════════


def _fetch_sector_etf(sector: str, ticker: str) -> Optional[Dict]:
    """Fetch daily and YTD performance for a single sector ETF."""
    try:
        tk = yf.Ticker(ticker)

        # Daily change from 5d history
        hist = tk.history(period="5d")
        # Drop rows where Close is NaN (e.g. today's bar before market close)
        hist = hist.dropna(subset=["Close"])
        if hist.empty or len(hist) < 2:
            return None

        today_close = float(hist["Close"].iloc[-1])
        prev_close = float(hist["Close"].iloc[-2])
        change_pct = round((today_close - prev_close) / prev_close * 100, 2)

        # YTD return: fetch from Jan 1 of current year
        year_start = datetime(datetime.now().year, 1, 1).strftime("%Y-%m-%d")
        ytd_hist = tk.history(start=year_start)
        ytd_hist = ytd_hist.dropna(subset=["Close"])
        ytd_return = None
        if not ytd_hist.empty and len(ytd_hist) >= 2:
            first_close = float(ytd_hist["Close"].iloc[0])
            if first_close > 0:
                ytd_return = round((today_close - first_close) / first_close * 100, 2)

        return {
            "sector": sector,
            "ticker": ticker,
            "change_pct": change_pct,
            "ytd_return": ytd_return,
        }

    except Exception as exc:
        logger.warning("sector_etf_fetch_failed", sector=sector, ticker=ticker, error=str(exc))
        return None


def get_sector_performance() -> List[Dict]:
    """
    Fetch daily and YTD performance for each SPDR sector ETF.

    Returns
    -------
    list[dict]
        Each entry: {sector, ticker, change_pct, ytd_return}
        Sorted by today's change_pct descending.
    """
    cache_path = _cache_key("get_sector_performance", "")
    cached = _read_cache(cache_path)
    if cached is not None:
        logger.info("sector_performance_cache_hit")
        return cached

    logger.info("sector_performance_start")
    results = []

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {
            pool.submit(_fetch_sector_etf, sector, ticker): sector
            for sector, ticker in SECTOR_ETFS.items()
        }
        for future in as_completed(futures):
            data = future.result()
            if data is not None:
                results.append(data)

    # Sort by daily change descending
    results.sort(key=lambda d: d["change_pct"], reverse=True)

    _write_cache(cache_path, results)
    logger.info("sector_performance_done", n_sectors=len(results))
    return results


# ══════════════════════════════════════════════════════════════
#  Convenience: Full Dashboard Snapshot
# ══════════════════════════════════════════════════════════════


def get_dashboard_snapshot(
    portfolio_tickers: Optional[List[str]] = None,
    sp500_top_n: int = 20,
) -> Dict:
    """
    Convenience function that runs all scans and returns a single dict
    suitable for rendering on a dashboard.

    Parameters
    ----------
    portfolio_tickers : list[str] or None
        If provided, also run a portfolio-specific scan.
    sp500_top_n : int
        Number of top gainers / losers to include.

    Returns
    -------
    dict
        {
            "market_regime": {...},
            "sp500_movers":  {...},
            "sectors":       [...],
            "portfolio_movers": {...} or None,
            "iv_movers":     [...] or None,   # only if portfolio_tickers given
        }
    """
    logger.info("dashboard_snapshot_start")

    snapshot: Dict = {}

    # These can safely run in parallel via threads
    with ThreadPoolExecutor(max_workers=4) as pool:
        regime_future = pool.submit(get_market_regime_summary)
        sp500_future = pool.submit(scan_sp500_movers, sp500_top_n)
        sector_future = pool.submit(get_sector_performance)

        portfolio_future = None
        iv_future = None
        if portfolio_tickers:
            portfolio_future = pool.submit(scan_portfolio_movers, portfolio_tickers)
            iv_future = pool.submit(get_iv_movers, portfolio_tickers)

        snapshot["market_regime"] = regime_future.result()
        snapshot["sp500_movers"] = sp500_future.result()
        snapshot["sectors"] = sector_future.result()
        snapshot["portfolio_movers"] = portfolio_future.result() if portfolio_future else None
        snapshot["iv_movers"] = iv_future.result() if iv_future else None

    logger.info("dashboard_snapshot_done")
    return snapshot


# ══════════════════════════════════════════════════════════════
#  CLI entry point (for quick testing)
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import pprint

    print("=" * 60)
    print("  Volatility Scanner - Post-Market Dashboard")
    print("=" * 60)

    print("\
--- Market Regime ---")
    regime = get_market_regime_summary()
    pprint.pprint(regime)

    print("\
--- Sector Performance ---")
    sectors = get_sector_performance()
    for s in sectors:
        print(
            f"  {s['sector']:20s}  {s['ticker']}  {s['change_pct']:+.2f}%  YTD: {s.get('ytd_return', 'N/A')}"
        )

    print("\
--- S&P 500 Top Movers (top 5) ---")
    movers = scan_sp500_movers(top_n=5)
    print("Gainers:")
    for g in movers["top_gainers"]:
        print(
            f"  {g['ticker']:6s}  {g['change_pct']:+.2f}%  ${g['close']:.2f}  vol ratio: {g.get('avg_volume_ratio', 'N/A')}"
        )
    print("Losers:")
    for l in movers["top_losers"]:
        print(
            f"  {l['ticker']:6s}  {l['change_pct']:+.2f}%  ${l['close']:.2f}  vol ratio: {l.get('avg_volume_ratio', 'N/A')}"
        )

    print("\
--- IV Movers (sample) ---")
    iv_data = get_iv_movers(["AAPL", "TSLA", "NVDA", "META", "AMZN"])
    for iv in iv_data:
        print(
            f"  {iv['ticker']:6s}  IV: {iv['current_iv']:.1f}%  Rank: {iv.get('iv_rank', 'N/A')}  "
            f"Pctile: {iv.get('iv_percentile', 'N/A')}  1d chg: {iv.get('iv_change_1d', 'N/A')}"
        )

    print("\
Done.")
