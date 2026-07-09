"""
data_provider.py
Market-data download and preprocessing module v2.2
──────────────────────────────────────────────────────────
New: macro-factor download (^TNX / DX-Y.NYB / CL=F) · volume download
v2.2: robust data pipeline - caching + data-quality validation + error handling
"""

import os
import pickle
import time
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf

from logging_config import get_logger

logger = get_logger(__name__)


class CachedDataProvider:
    """Cached data provider - avoids redundant downloads, improving performance and reliability"""

    def __init__(self, cache_dir: str = ".cache/market_data"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def _get_cache_path(self, ticker: str, start: str, end: str, data_type: str = "prices") -> str:
        """Build the cache file path"""
        safe_ticker = ticker.replace("/", "_").replace("^", "").replace("=", "")
        return os.path.join(self.cache_dir, f"{safe_ticker}_{start}_{end}_{data_type}.pkl")

    def _is_cache_valid(self, cache_path: str, max_age_hours: int = 24) -> bool:
        """Check whether the cache is valid (not expired)"""
        if not os.path.exists(cache_path):
            return False

        file_time = datetime.fromtimestamp(os.path.getmtime(cache_path))
        age = datetime.now() - file_time

        return age < timedelta(hours=max_age_hours)

    def fetch_with_cache(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
        force_refresh: bool = False,
        data_type: str = "prices",
        max_age_hours: int = 24,
    ) -> Optional[pd.DataFrame]:
        """
        Cached data fetch

        Args:
            ticker: stock symbol
            start_date: start date (YYYY-MM-DD)
            end_date: end date (YYYY-MM-DD)
            force_refresh: force refresh (ignore cache)
            data_type: data type (prices/volume)
            max_age_hours: cache validity period (hours)

        Returns:
            DataFrame, or None (if the download fails)
        """
        cache_path = self._get_cache_path(ticker, start_date, end_date, data_type)
        start_time = time.time()

        # Try loading from cache
        if not force_refresh and self._is_cache_valid(cache_path, max_age_hours):
            try:
                with open(cache_path, "rb") as f:
                    data = pickle.load(f)
                duration_ms = (time.time() - start_time) * 1000
                logger.info(
                    "data.cache.hit",
                    ticker=ticker,
                    data_type=data_type,
                    rows=len(data),
                    duration_ms=round(duration_ms, 2),
                )
                return data
            except Exception as e:
                logger.warning("data.cache.load_failed", ticker=ticker, error=str(e))
                warnings.warn(f"Cache load failed ({ticker}): {e}, re-downloading")

        # Download from the network
        try:
            download_start = time.time()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                data = yf.download(
                    ticker, start=start_date, end=end_date, auto_adjust=True, progress=False
                )
            download_duration = (time.time() - download_start) * 1000

            if data.empty:
                logger.warning("data.download.empty", ticker=ticker, data_type=data_type)
                # If the network download is empty, fall back to the stale cache
                if os.path.exists(cache_path):
                    warnings.warn(f"Downloaded data empty ({ticker}), using stale cache")
                    with open(cache_path, "rb") as f:
                        return pickle.load(f)
                return None

            # Save to cache
            try:
                with open(cache_path, "wb") as f:
                    pickle.dump(data, f)
            except Exception as e:
                logger.warning("data.cache.save_failed", ticker=ticker, error=str(e))
                warnings.warn(f"Cache save failed ({ticker}): {e}")

            total_duration = (time.time() - start_time) * 1000
            logger.info(
                "data.download.success",
                ticker=ticker,
                data_type=data_type,
                rows=len(data),
                download_duration_ms=round(download_duration, 2),
                total_duration_ms=round(total_duration, 2),
                cached=True,
            )
            return data

        except Exception as e:
            logger.error("data.download.failed", ticker=ticker, data_type=data_type, error=str(e))
            # If the network fails, fall back to the stale cache
            if os.path.exists(cache_path):
                warnings.warn(f"Network download failed ({ticker}): {e}, using stale cache")
                try:
                    with open(cache_path, "rb") as f:
                        return pickle.load(f)
                except Exception as cache_error:
                    warnings.warn(f"Stale cache also failed to load: {cache_error}")
            return None


class DataProvider:
    """Downloads market data from Yahoo Finance and preprocesses it.

    Note on batch efficiency: yf.download() already handles multiple tickers
    in a single HTTP batch request internally, so no additional ThreadPoolExecutor
    concurrency is needed for price/volume downloads in this class.
    """

    # Macro factor ticker → readable name
    MACRO_FACTOR_TICKERS = {
        "^TNX": "US10Y Rate",  # 10-year Treasury yield — rate factor
        "DX-Y.NYB": "USD Index",  # US dollar index — FX factor
        "CL=F": "Crude Oil",  # WTI crude futures — inflation factor
    }

    def __init__(
        self,
        weights: Dict[str, float],
        period_years: int = 2,
        end_date: Optional[str] = None,
        holdings: Optional[Dict[str, dict]] = None,
    ):
        """
        Parameters
        ----------
        weights : dict   ticker → portfolio weight (0-1)
        holdings : dict  ticker → {"shares": float}  (from portfolio_config)
                         Used for liquidity-risk calculation; optional.
        """
        self.weights = weights
        self.tickers = list(weights.keys())
        self.period_years = period_years
        self.end_date = pd.Timestamp(end_date) if end_date else pd.Timestamp.today().normalize()
        self.start_date = self.end_date - timedelta(days=365 * period_years)
        self.holdings = holdings  # optional, for liquidity calc

        # Caches
        self._prices: Optional[pd.DataFrame] = None
        self._returns: Optional[pd.DataFrame] = None
        self._macro_prices: Optional[pd.DataFrame] = None
        self._macro_returns: Optional[pd.DataFrame] = None
        self._volume_30d: Optional[pd.DataFrame] = None
        # Instance-level memo for benchmark + risk-free fetches. These
        # were uncached and got called 2-3 times per engine.run() — once
        # for single-factor beta (SPY), once for multi-factor (SPY+QQQ+
        # GLD+TLT), and once for risk-free (^IRX). That was 3-6s of
        # redundant yfinance downloads per Run Analysis. With the
        # DataProvider itself cached via @st.cache_resource(ttl=24h),
        # these memos persist for the same window.
        self._benchmark_returns_cache: dict[tuple, pd.DataFrame] = {}
        self._risk_free_rate_cached: Optional[float] = None

        # Initialize the cache provider
        self._cache_provider = CachedDataProvider()

        # Failure records
        self._failed_tickers: List[Tuple[str, str]] = []

    # ══════════════════════════════════════════════════════════
    #  Data-quality validation and cleaning
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _detect_currency_mixing(prices: pd.DataFrame, tickers: List[str]) -> Tuple[bool, str]:
        """
        Detect whether the portfolio mixes assets denominated in different currencies

        Args:
            prices: price DataFrame
            tickers: list of tickers

        Returns:
            (has_mixing, warning_message)
        """
        # Common non-USD asset suffixes
        foreign_indicators = {
            ".L": "GBP (London)",
            ".T": "JPY (Tokyo)",
            ".TO": "CAD (Toronto)",
            ".HK": "HKD (Hong Kong)",
            ".SS": "CNY (Shanghai)",
            ".SZ": "CNY (Shenzhen)",
            ".AX": "AUD (Australia)",
            ".PA": "EUR (Paris)",
            ".DE": "EUR (Germany)",
        }

        detected_currencies = {}
        for ticker in tickers:
            is_foreign = False
            for suffix, currency in foreign_indicators.items():
                if ticker.endswith(suffix):
                    detected_currencies[ticker] = currency
                    is_foreign = True
                    break
            if not is_foreign:
                detected_currencies[ticker] = "USD"

        # Check whether multiple currencies are present
        unique_currencies = set(detected_currencies.values())
        if len(unique_currencies) > 1:
            currency_list = ", ".join(f"{t}({c})" for t, c in detected_currencies.items())
            return True, f"Mixed currencies detected: {currency_list}. VaR may be inaccurate."

        return False, ""

    @staticmethod
    def _winsorize_returns(
        returns: pd.Series, lower_pct: float = 0.01, upper_pct: float = 0.99
    ) -> pd.Series:
        """
        Winsorization: clip extreme values to percentile thresholds

        Args:
            returns: return series
            lower_pct: lower percentile bound (default 1%)
            upper_pct: upper percentile bound (default 99%)

        Returns:
            cleaned return series
        """
        if len(returns) < 10:
            return returns

        valid_returns = returns.dropna()
        if len(valid_returns) == 0:
            return returns

        lower_bound = valid_returns.quantile(lower_pct)
        upper_bound = valid_returns.quantile(upper_pct)

        # Clip to the thresholds
        clipped = returns.clip(lower=lower_bound, upper=upper_bound)

        # Record how many were clipped
        n_clipped = ((returns < lower_bound) | (returns > upper_bound)).sum()
        if n_clipped > 0:
            logger.info(
                "data.winsorization.applied",
                n_clipped=n_clipped,
                lower_bound=round(lower_bound, 4),
                upper_bound=round(upper_bound, 4),
            )

        return clipped

    @staticmethod
    def _detect_gaps(
        data: pd.Series, max_gap_days: int = 5
    ) -> List[Tuple[pd.Timestamp, pd.Timestamp, int]]:
        """
        Detect gaps in the data (consecutive missing values)

        Args:
            data: price or return series
            max_gap_days: maximum allowed gap length in days

        Returns:
            list of gaps [(start_date, end_date, gap_days), ...]
        """
        if data.index.freq is None:
            # Infer the frequency
            try:
                inferred_freq = pd.infer_freq(data.index[:20])
                if inferred_freq is None:
                    return []
            except Exception:
                return []

        # Find the positions of all missing values
        missing_mask = data.isnull()
        gaps = []

        in_gap = False
        gap_start = None
        gap_length = 0

        for date, is_missing in missing_mask.items():
            if is_missing:
                if not in_gap:
                    gap_start = date
                    gap_length = 1
                    in_gap = True
                else:
                    gap_length += 1
            else:
                if in_gap and gap_length > max_gap_days:
                    gaps.append((gap_start, date, gap_length))
                in_gap = False
                gap_length = 0

        return gaps

    @staticmethod
    def _smart_fill_gaps(data: pd.Series, method: str = "auto") -> pd.Series:
        """
        Smart-fill data gaps

        Args:
            data: series with missing values
            method: fill method
                - 'auto': linear interpolation for small gaps, forward-fill for large gaps
                - 'ffill': forward-fill
                - 'interpolate': linear interpolation

        Returns:
            filled series
        """
        if data.isnull().sum() == 0:
            return data

        if method == "ffill":
            return data.ffill()
        elif method == "interpolate":
            return data.interpolate(method="linear", limit_direction="both")
        elif method == "auto":
            # Interpolate small gaps (<=3 days); forward-fill large gaps
            filled = data.copy()

            # Forward-fill first
            filled = filled.ffill()

            # Interpolate runs with <=3 consecutive missing values
            missing_runs = (
                filled.isnull().astype(int).groupby(filled.notnull().astype(int).cumsum()).cumsum()
            )

            small_gaps = missing_runs <= 3
            filled[small_gaps] = data[small_gaps].interpolate(method="linear")

            # Finally fill any remaining values
            filled = filled.ffill().bfill()

            return filled
        else:
            raise ValueError(f"Unknown fill method: {method}")

    def _validate_ticker_data(self, ticker: str, data: pd.DataFrame) -> Tuple[bool, str]:
        """
        Validate ticker data quality

        Returns:
            (is_valid, error_message)
        """
        if data is None or data.empty:
            return False, "Data is empty"

        # Get the Close column (if it is a MultiIndex)
        if isinstance(data.columns, pd.MultiIndex):
            if "Close" in data.columns.get_level_values(0):
                close_data = data["Close"]
                # If it is still a DataFrame, take the first column
                if isinstance(close_data, pd.DataFrame):
                    close_data = close_data.iloc[:, 0]
            else:
                close_data = data.iloc[:, 0] if len(data.columns) > 0 else data
        else:
            if "Close" in data.columns:
                close_data = data["Close"]
            else:
                close_data = data.iloc[:, 0] if len(data.columns) > 0 else data

        # Ensure it is a Series
        if isinstance(close_data, pd.DataFrame):
            close_data = close_data.iloc[:, 0]

        # Check 1: insufficient data
        if len(close_data) < 20:  # at least 20 trading days
            return False, f"Insufficient data ({len(close_data)} days)"

        # Check 2: missing rate
        missing_pct = close_data.isnull().sum() / len(close_data)
        if missing_pct > 0.3:
            return False, f"Missing rate {missing_pct:.1%} exceeds 30%"

        # Check 3: price <= 0
        valid_prices = close_data.dropna()
        if len(valid_prices) > 0 and (valid_prices <= 0).any():
            return False, "Contains prices <= 0"

        # Check 4: extreme single-day move (possibly a stock split/merger)
        if len(valid_prices) > 1:
            returns = valid_prices.pct_change().dropna()
            if len(returns) > 0:
                extreme_count = (abs(returns) > 0.5).sum()
                if extreme_count > 0:
                    # Allow 1-2 extreme values (may be genuine market events)
                    if extreme_count > 2:
                        return False, f"Contains {extreme_count} extreme single-day moves (>50%)"
                    else:
                        logger.warning(
                            "data.validation.extreme_returns",
                            ticker=ticker,
                            extreme_count=extreme_count,
                            max_return=round(returns.abs().max(), 3),
                        )

        # Check 5: consecutive identical prices (suspended trading) - relaxed threshold, since some assets may legitimately stall
        if len(valid_prices) > 10:
            price_changes = valid_prices.diff().fillna(0)
            consecutive_zeros = (price_changes == 0).rolling(window=15).sum().max()
            if consecutive_zeros >= 15:  # 15 consecutive days of identical prices
                return (
                    False,
                    f"Contains {int(consecutive_zeros)} days of consecutive identical prices (possibly halted)",
                )

        # Check 6: detect large gaps
        gaps = self._detect_gaps(close_data, max_gap_days=5)
        if gaps:
            total_gap_days = sum(g[2] for g in gaps)
            if total_gap_days > 20:  # cumulative gap exceeds 20 days
                return False, f"Too many data gaps: {len(gaps)} gaps, {total_gap_days} days total"
            else:
                logger.info(
                    "data.validation.gaps_detected",
                    ticker=ticker,
                    n_gaps=len(gaps),
                    total_gap_days=total_gap_days,
                )

        # Check 7: abnormal price volatility (may be a data error)
        if len(valid_prices) > 30:
            returns = valid_prices.pct_change().dropna()
            if len(returns) > 0:
                volatility = returns.std()
                # Annualized volatility > 200% is highly abnormal
                if volatility * np.sqrt(252) > 2.0:
                    logger.warning(
                        "data.validation.extreme_volatility",
                        ticker=ticker,
                        annual_vol=round(volatility * np.sqrt(252), 2),
                    )

        return True, ""

    def get_failed_tickers(self) -> List[Tuple[str, str]]:
        """Return the list of tickers that failed to download along with the failure reasons"""
        return self._failed_tickers.copy()

    # ══════════════════════════════════════════════════════════
    #  Asset prices & returns (improved: robust batch download)
    # ══════════════════════════════════════════════════════════
    def fetch_prices(self, force_refresh: bool = False) -> pd.DataFrame:
        """
        Download adjusted close prices; returns a DataFrame (date × ticker).
        Robust version: a single ticker's failure doesn't affect the others; supports caching and data validation.

        Args:
            force_refresh: force-refresh the data (ignore cache)

        Returns:
            DataFrame: price data for the tickers that downloaded successfully
        """
        if self._prices is not None and not force_refresh:
            return self._prices

        start_str = self.start_date.strftime("%Y-%m-%d")
        end_str = self.end_date.strftime("%Y-%m-%d")

        successful_prices = {}
        self._failed_tickers = []

        logger.info(
            "data.fetch_prices.start",
            tickers=self.tickers,
            ticker_count=len(self.tickers),
            force_refresh=force_refresh,
            period_years=self.period_years,
            start_date=start_str,
            end_date=end_str,
        )
        batch_start_time = time.time()

        print(f"\n{'='*60}")
        print(f"Data download started: {len(self.tickers)} tickers")
        print(f"Date range: {start_str} to {end_str}")
        print(f"{'='*60}")

        # Parallel fetch — yfinance is I/O bound and the per-ticker cache
        # check + HTTP roundtrip dominates. Serial loop was ~1-2s/ticker
        # for ~30 holdings on cache miss; a 6-worker pool brings cold
        # start from ~45s to ~8-10s. We cap workers to avoid hammering
        # yfinance (which is unofficially rate-limited).
        max_workers = min(8, max(1, len(self.tickers)))

        def _fetch_one(ticker: str):
            """Returns (ticker, close_series, error_or_None)."""
            try:
                data = self._cache_provider.fetch_with_cache(
                    ticker,
                    start_str,
                    end_str,
                    force_refresh=force_refresh,
                    data_type="prices",
                )
                if data is None:
                    return ticker, None, "empty download data"

                is_valid, error_msg = self._validate_ticker_data(ticker, data)
                if not is_valid:
                    return ticker, None, error_msg

                if isinstance(data.columns, pd.MultiIndex):
                    if "Close" in data.columns.get_level_values(0):
                        close = data["Close"]
                        if isinstance(close, pd.DataFrame):
                            close = close.iloc[:, 0]
                    else:
                        close = data.iloc[:, 0]
                else:
                    if "Close" in data.columns:
                        close = data["Close"]
                    else:
                        close = data.iloc[:, 0] if len(data.columns) > 0 else data

                return ticker, close, None
            except Exception as e:
                return ticker, None, f"Exception: {str(e)}"

        # Preserve deterministic per-ticker logging order by collecting
        # results in submission order. ThreadPoolExecutor.map() guarantees
        # the same ordering as the input iterable.
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            results = list(pool.map(_fetch_one, self.tickers))

        for ticker, close, error in results:
            if error is not None:
                self._failed_tickers.append((ticker, error))
                if error.startswith("Exception:"):
                    print(f"  ✗ {ticker}: {error}")
                elif error == "empty download data":
                    print(f"  ✗ {ticker}: download failed (empty data)")
                else:
                    logger.warning(
                        "data.fetch_prices.validation_failed",
                        ticker=ticker,
                        error=error,
                    )
                    print(f"  ✗ {ticker}: validation failed - {error}")
                continue
            successful_prices[ticker] = close
            print(f"  ✓ {ticker}: success ({len(close)} data points)")

        # Report the results
        batch_duration = (time.time() - batch_start_time) * 1000
        logger.info(
            "data.fetch_prices.complete",
            successful=len(successful_prices),
            failed=len(self._failed_tickers),
            total=len(self.tickers),
            duration_ms=round(batch_duration, 2),
        )

        print(f"\n{'='*60}")
        print("Data download complete:")
        print(f"  Success: {len(successful_prices)}/{len(self.tickers)}")
        print(f"  Failed: {len(self._failed_tickers)}")

        if self._failed_tickers:
            print("\nFailure details:")
            for ticker, error in self._failed_tickers:
                logger.warning("data.fetch_prices.ticker_failed", ticker=ticker, error=error)
                print(f"  - {ticker}: {error}")

        print(f"{'='*60}\n")

        if not successful_prices:
            logger.error("data.fetch_prices.all_failed", ticker_count=len(self.tickers))
            raise ValueError(
                "Failed to fetch data for all tickers! Please check:\n"
                "  1. Network connection\n"
                "  2. Whether the ticker symbols are correct\n"
                "  3. Whether the date range is valid"
            )

        # Merge into a DataFrame
        self._prices = pd.DataFrame(successful_prices)

        # Detect currency mixing
        has_mixing, currency_warning = self._detect_currency_mixing(
            self._prices, list(successful_prices.keys())
        )
        if has_mixing:
            logger.warning("data.currency_mixing", message=currency_warning)
            print(f"\n⚠️  Currency warning: {currency_warning}")

        # Smart-fill gaps (forward-fill + interpolation to handle holiday differences and small gaps)
        for col in self._prices.columns:
            self._prices[col] = self._smart_fill_gaps(self._prices[col], method="auto")

        # Drop rows that still have missing values
        self._prices = self._prices.dropna()

        return self._prices

    def get_daily_returns(self, winsorize: bool = False) -> pd.DataFrame:
        """
        Compute simple daily returns (simple/arithmetic returns).

        Project-wide convention: SIMPLE returns, (P_t / P_{t-1}) - 1.
        Rationale: retail UX familiarity, backtest_engine uses simple, and
        (1+r).cumprod() compounding stays correct across risk_engine /
        performance_attribution / drawdown.

        Args:
            winsorize: whether to apply Winsorization to handle extreme values (default False)

        Returns:
            DataFrame: simple daily returns (date × ticker)
        """
        if self._returns is not None:
            return self._returns

        prices = self.fetch_prices()
        returns = prices.pct_change().dropna()

        if winsorize:
            # Apply winsorization to each ticker
            for col in returns.columns:
                returns[col] = self._winsorize_returns(returns[col])
            logger.info("data.returns.winsorized", ticker_count=len(returns.columns))

        self._returns = returns
        return self._returns

    def get_portfolio_cumulative_returns(self) -> pd.Series:
        """Weight by portfolio weights and return the portfolio's cumulative net-value curve."""
        ret = self.get_daily_returns()
        w = np.array([self.weights[t] for t in ret.columns])
        port_ret = ret.dot(w)
        cum = (1 + port_ret).cumprod()
        cum.name = "Portfolio"
        return cum

    def get_weight_array(self) -> np.ndarray:
        ret = self.get_daily_returns()
        return np.array([self.weights[t] for t in ret.columns])

    # ══════════════════════════════════════════════════════════
    #  Convenience property accessors
    # ══════════════════════════════════════════════════════════
    @property
    def prices(self) -> pd.DataFrame:
        """Convenience accessor: get price data"""
        return self.fetch_prices()

    @property
    def returns(self) -> pd.DataFrame:
        """Convenience accessor: get return data"""
        return self.get_daily_returns()

    # ══════════════════════════════════════════════════════════
    #  Macro-factor data (improved: robust download)
    # ══════════════════════════════════════════════════════════
    def fetch_macro_prices(self, force_refresh: bool = False) -> pd.DataFrame:
        """
        Download macro-factor prices:
          ^TNX   — 10-year Treasury yield (rate factor)
          DX-Y.NYB — US dollar index (FX factor)
          CL=F   — WTI crude futures (inflation factor)

        Returns a DataFrame whose columns are readable names ("US10Y Rate", "USD Index", "Crude Oil")
        Robust version: supports caching and partial failure
        """
        if self._macro_prices is not None and not force_refresh:
            return self._macro_prices

        macro_tickers = list(self.MACRO_FACTOR_TICKERS.keys())
        start_str = self.start_date.strftime("%Y-%m-%d")
        end_str = self.end_date.strftime("%Y-%m-%d")

        logger.info(
            "data.fetch_macro.start", macro_tickers=macro_tickers, force_refresh=force_refresh
        )
        start_time = time.time()

        successful_data = {}
        failed_macro = []

        def _fetch_one_macro(ticker: str):
            """Parallel worker — returns (ticker, close_series, error_or_None)."""
            try:
                data = self._cache_provider.fetch_with_cache(
                    ticker, start_str, end_str, force_refresh=force_refresh, data_type="macro"
                )

                if data is None or data.empty:
                    return ticker, None, "empty download data"

                # Extract Close.
                if isinstance(data.columns, pd.MultiIndex):
                    if "Close" in data.columns.get_level_values(0):
                        close = data["Close"]
                        if isinstance(close, pd.DataFrame):
                            close = close.iloc[:, 0]
                    else:
                        close = data.iloc[:, 0]
                else:
                    if "Close" in data.columns:
                        close = data["Close"]
                    else:
                        close = data.iloc[:, 0] if len(data.columns) > 0 else data

                return ticker, close, None
            except Exception as e:
                return ticker, None, str(e)

        # Parallel: each macro ticker is an independent HTTP/cache call.
        # Serial was ~3-6s on cache miss; max_workers=3 brings it to ~1-2s.
        with ThreadPoolExecutor(max_workers=max(1, len(macro_tickers))) as pool:
            macro_results = list(pool.map(_fetch_one_macro, macro_tickers))

        for ticker, close, error in macro_results:
            if error is not None:
                failed_macro.append((ticker, error))
                continue
            readable_name = self.MACRO_FACTOR_TICKERS[ticker]
            successful_data[readable_name] = close

        duration_ms = (time.time() - start_time) * 1000

        if failed_macro:
            for ticker, error in failed_macro:
                logger.warning("data.fetch_macro.ticker_failed", ticker=ticker, error=error)
            warnings.warn(f"Some macro factors failed to download: {failed_macro}")

        if not successful_data:
            # If all fail, return an empty DataFrame instead of raising
            logger.warning("data.fetch_macro.all_failed", duration_ms=round(duration_ms, 2))
            warnings.warn("All macro factors failed to download, returning empty data")
            self._macro_prices = pd.DataFrame()
            return self._macro_prices

        # Merge the data and forward-fill
        self._macro_prices = pd.DataFrame(successful_data)
        self._macro_prices = self._macro_prices.ffill().dropna(how="all")

        logger.info(
            "data.fetch_macro.complete",
            successful=len(successful_data),
            failed=len(failed_macro),
            duration_ms=round(duration_ms, 2),
        )

        return self._macro_prices

    def get_macro_returns(self) -> pd.DataFrame:
        """Simple daily returns for the macro factors (project-wide convention)."""
        if self._macro_returns is not None:
            return self._macro_returns
        prices = self.fetch_macro_prices()
        self._macro_returns = prices.pct_change().dropna()
        return self._macro_returns

    # ══════════════════════════════════════════════════════════
    #  Benchmark / factor / risk-free providers (replace direct
    #  yfinance calls from risk_engine so the engine stays pure)
    # ══════════════════════════════════════════════════════════

    def get_benchmark_returns(
        self,
        benchmarks: list,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Fetch simple daily returns for one or more benchmark/factor tickers.
        Returns an empty DataFrame (columns = benchmarks) on full failure.

        Used by RiskEngine for single-factor and multi-factor beta fits.
        Aligned to project's SIMPLE-return convention.

        Memoized on the DataProvider instance — `engine.run()` calls
        this twice (single-factor SPY, then 4-factor SPY+QQQ+GLD+TLT),
        and previously each call did a fresh yfinance HTTP roundtrip.
        With the cache, the second call (and any subsequent re-runs)
        return instantly.
        """
        if not benchmarks:
            return pd.DataFrame()

        # Cache key includes the benchmark set + window so different
        # callers don't share each other's data.
        cache_key = (tuple(sorted(benchmarks)), start, end)
        cached = self._benchmark_returns_cache.get(cache_key)
        if cached is not None:
            return cached.copy()

        start_str = start or (
            self.end_date - timedelta(days=int(self.period_years * 365) + 10)
        ).strftime("%Y-%m-%d")
        end_str = end or self.end_date.strftime("%Y-%m-%d")

        try:
            raw = yf.download(
                benchmarks,
                start=start_str,
                end=end_str,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
        except Exception as exc:
            logger.warning(
                "data.benchmark.download_failed", benchmarks=list(benchmarks), error=str(exc)
            )
            return pd.DataFrame(columns=benchmarks)

        if raw is None or raw.empty:
            return pd.DataFrame(columns=benchmarks)

        # Normalize to a flat DataFrame of Close prices
        if isinstance(raw.columns, pd.MultiIndex):
            if "Close" in raw.columns.get_level_values(0):
                close = raw["Close"]
            elif "Adj Close" in raw.columns.get_level_values(0):
                close = raw["Adj Close"]
            else:
                return pd.DataFrame(columns=benchmarks)
        else:
            # Single-ticker request: columns are fields
            if "Close" in raw.columns:
                close = raw[["Close"]].rename(columns={"Close": benchmarks[0]})
            else:
                return pd.DataFrame(columns=benchmarks)

        close = close.ffill().dropna(how="all")
        if close.empty:
            return pd.DataFrame(columns=benchmarks)

        result = close.pct_change().dropna(how="all")
        self._benchmark_returns_cache[cache_key] = result
        return result.copy()

    def get_risk_free_rate(self, fallback: float = 0.045) -> float:
        """
        Fetch latest 13-week Treasury yield (^IRX, in %) and convert to decimal.
        Returns the supplied fallback on any failure so callers never crash.

        Memoized — `engine.run()` calls this once per analysis but with
        the DataProvider cached for 24h, repeat Run Analysis clicks were
        re-downloading ^IRX every time. Cache lives on the instance.
        """
        if self._risk_free_rate_cached is not None:
            return self._risk_free_rate_cached
        try:
            raw = yf.download("^IRX", period="5d", auto_adjust=True, progress=False, threads=False)
        except Exception as exc:
            logger.warning("data.risk_free.download_failed", error=str(exc))
            return fallback

        if raw is None or raw.empty:
            return fallback
        try:
            if isinstance(raw.columns, pd.MultiIndex):
                close = (
                    raw["Close"]["^IRX"]
                    if "^IRX" in raw["Close"].columns
                    else raw["Close"].iloc[:, 0]
                )
            else:
                close = raw["Close"] if "Close" in raw.columns else raw.iloc[:, 0]
            latest = float(close.dropna().iloc[-1])
            # ^IRX is quoted in percent; convert to decimal. Sanity-clip to [0, 0.20].
            rate = max(0.0, min(0.20, latest / 100.0))
            self._risk_free_rate_cached = rate
            return rate
        except Exception as exc:
            logger.warning("data.risk_free.parse_failed", error=str(exc))
            return fallback

    def get_historical_scenario_prices(
        self,
        tickers: list,
        start: str,
        end: str,
    ) -> Optional[pd.DataFrame]:
        """
        Fetch close prices for a historical backtest scenario window.
        Returns None (not an empty DF) on full failure so callers can
        distinguish "no data" from "zero-length window".
        """
        if not tickers:
            return None
        try:
            raw = yf.download(
                tickers,
                start=start,
                end=end,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
        except Exception as exc:
            logger.warning(
                "data.scenario.download_failed",
                tickers=list(tickers),
                start=start,
                end=end,
                error=str(exc),
            )
            return None

        if raw is None or raw.empty:
            return None

        if isinstance(raw.columns, pd.MultiIndex):
            if "Close" in raw.columns.get_level_values(0):
                return raw["Close"].ffill().dropna(how="all")
            if "Adj Close" in raw.columns.get_level_values(0):
                return raw["Adj Close"].ffill().dropna(how="all")
            return None
        # Single ticker path
        if "Close" in raw.columns:
            return raw[["Close"]].rename(columns={"Close": tickers[0]}).ffill()
        return None

    # ══════════════════════════════════════════════════════════
    #  Volume data (30-day) (improved: robust download)
    # ══════════════════════════════════════════════════════════
    def fetch_volume_30d(self, force_refresh: bool = False) -> pd.DataFrame:
        """
        Download each holding's daily volume over the last 30 trading days.
        Returns a DataFrame (date × ticker) containing only tickers whose volume is non-zero.
        Cryptocurrencies (tickers containing "-USD") also expose volume via Yahoo Finance.
        Robust version: supports caching and partial failure
        """
        if self._volume_30d is not None and not force_refresh:
            return self._volume_30d

        # Download the last 45 days to ensure 30 trading days are available
        end = self.end_date
        start = end - timedelta(days=45)
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")

        successful_volumes = {}
        failed_volumes = []

        def _fetch_one_volume(ticker: str):
            """Parallel worker — returns (ticker, volume_series, error_or_None).

            The 30-day tail trim happens here in the worker so the main
            thread just collects pre-cleaned series.
            """
            try:
                data = self._cache_provider.fetch_with_cache(
                    ticker,
                    start_str,
                    end_str,
                    force_refresh=force_refresh,
                    data_type="volume",
                    max_age_hours=6,  # volume refreshes more frequently
                )

                if data is None or data.empty:
                    return ticker, None, "empty download data"

                # Extract Volume column. Yahoo's MultiIndex shape can be
                # ("Volume", ticker) or just "Volume" for single ticker.
                if isinstance(data.columns, pd.MultiIndex):
                    if "Volume" in data.columns.get_level_values(0):
                        volume = data["Volume"]
                        if isinstance(volume, pd.DataFrame):
                            volume = volume.iloc[:, 0]
                    else:
                        return ticker, None, "no_volume_column"
                else:
                    if "Volume" in data.columns:
                        volume = data["Volume"]
                    else:
                        return ticker, None, "no_volume_column"

                volume = volume.replace([np.inf, -np.inf], np.nan).fillna(0)
                volume = volume.tail(30)
                if len(volume) == 0:
                    return ticker, None, "empty_after_tail"
                return ticker, volume, None
            except Exception as e:
                return ticker, None, str(e)

        # Parallel: per-ticker volume fetch is I/O-bound. For 30 tickers
        # serial = ~15-30s on cold cache (this dominated the user-visible
        # "30-60s" spinner during Run Analysis). 8 workers in parallel
        # brings it to ~3-5s. Matches the same throttling pattern used
        # in fetch_prices to avoid hammering Yahoo's rate limits.
        max_workers = min(8, max(1, len(self.tickers)))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            results = list(pool.map(_fetch_one_volume, self.tickers))

        for ticker, volume, error in results:
            if error is not None:
                # "no_volume_column" / "empty_after_tail" are silent
                # skips (the ticker simply doesn't have volume data);
                # network/exception errors are reported.
                if error not in ("no_volume_column", "empty_after_tail"):
                    failed_volumes.append((ticker, error))
                continue
            successful_volumes[ticker] = volume

        if failed_volumes and len(failed_volumes) > len(self.tickers) * 0.3:
            warnings.warn(
                f"Some volume data failed to download ({len(failed_volumes)}/{len(self.tickers)})"
            )

        if not successful_volumes:
            # Return an empty DataFrame instead of raising
            self._volume_30d = pd.DataFrame()
            return self._volume_30d

        # Merge the data
        self._volume_30d = pd.DataFrame(successful_volumes)
        return self._volume_30d

    def get_adv_30d(self) -> pd.Series:
        """
        30-day Average Daily Volume (ADV).
        Returns a Series: ticker → ADV (shares).
        """
        vol = self.fetch_volume_30d().replace([np.inf, -np.inf], np.nan).fillna(0)
        # Use the median to reduce distortion of ADV from suspension gaps and single-day volume spikes.
        adv = vol.median()
        adv.name = "ADV_30d"
        return adv
