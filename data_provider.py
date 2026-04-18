"""
data_provider.py
数据下载与预处理模块 v2.2
──────────────────────────────────────────────────────────
新增：宏观因子下载（^TNX / DX-Y.NYB / CL=F）· 成交量下载
v2.2: 健壮的数据管道 - 缓存机制 + 数据质量验证 + 错误处理
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import os
import pickle
import warnings
import time

from logging_config import get_logger

logger = get_logger(__name__)


class CachedDataProvider:
    """带缓存的数据提供者 - 避免重复下载，提升性能和可靠性"""

    def __init__(self, cache_dir: str = ".cache/market_data"):
        self.cache_dir = cache_dir
        os.makedirs(cache_dir, exist_ok=True)

    def _get_cache_path(self, ticker: str, start: str, end: str, data_type: str = "prices") -> str:
        """生成缓存文件路径"""
        safe_ticker = ticker.replace("/", "_").replace("^", "").replace("=", "")
        return os.path.join(
            self.cache_dir,
            f"{safe_ticker}_{start}_{end}_{data_type}.pkl"
        )

    def _is_cache_valid(self, cache_path: str, max_age_hours: int = 24) -> bool:
        """检查缓存是否有效（未过期）"""
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
        max_age_hours: int = 24
    ) -> Optional[pd.DataFrame]:
        """
        带缓存的数据获取

        Args:
            ticker: 股票代码
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            force_refresh: 强制刷新（忽略缓存）
            data_type: 数据类型 (prices/volume)
            max_age_hours: 缓存有效期（小时）

        Returns:
            DataFrame 或 None（如果下载失败）
        """
        cache_path = self._get_cache_path(ticker, start_date, end_date, data_type)
        start_time = time.time()

        # 尝试从缓存加载
        if not force_refresh and self._is_cache_valid(cache_path, max_age_hours):
            try:
                with open(cache_path, 'rb') as f:
                    data = pickle.load(f)
                duration_ms = (time.time() - start_time) * 1000
                logger.info(
                    "data.cache.hit",
                    ticker=ticker,
                    data_type=data_type,
                    rows=len(data),
                    duration_ms=round(duration_ms, 2)
                )
                return data
            except Exception as e:
                logger.warning(
                    "data.cache.load_failed",
                    ticker=ticker,
                    error=str(e)
                )
                warnings.warn(f"缓存加载失败 ({ticker}): {e}，重新下载")

        # 从网络下载
        try:
            download_start = time.time()
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                data = yf.download(
                    ticker,
                    start=start_date,
                    end=end_date,
                    auto_adjust=True,
                    progress=False
                )
            download_duration = (time.time() - download_start) * 1000

            if data.empty:
                logger.warning(
                    "data.download.empty",
                    ticker=ticker,
                    data_type=data_type
                )
                # 如果网络下载为空，尝试使用过期缓存
                if os.path.exists(cache_path):
                    warnings.warn(f"下载数据为空 ({ticker})，使用过期缓存")
                    with open(cache_path, 'rb') as f:
                        return pickle.load(f)
                return None

            # 保存到缓存
            try:
                with open(cache_path, 'wb') as f:
                    pickle.dump(data, f)
            except Exception as e:
                logger.warning(
                    "data.cache.save_failed",
                    ticker=ticker,
                    error=str(e)
                )
                warnings.warn(f"缓存保存失败 ({ticker}): {e}")

            total_duration = (time.time() - start_time) * 1000
            logger.info(
                "data.download.success",
                ticker=ticker,
                data_type=data_type,
                rows=len(data),
                download_duration_ms=round(download_duration, 2),
                total_duration_ms=round(total_duration, 2),
                cached=True
            )
            return data

        except Exception as e:
            logger.error(
                "data.download.failed",
                ticker=ticker,
                data_type=data_type,
                error=str(e)
            )
            # 如果网络失败，尝试使用过期缓存
            if os.path.exists(cache_path):
                warnings.warn(f"网络下载失败 ({ticker}): {e}，使用过期缓存")
                try:
                    with open(cache_path, 'rb') as f:
                        return pickle.load(f)
                except Exception as cache_error:
                    warnings.warn(f"过期缓存也加载失败: {cache_error}")
            return None


class DataProvider:
    """负责从 Yahoo Finance 下载行情数据并进行预处理。

    Note on batch efficiency: yf.download() already handles multiple tickers
    in a single HTTP batch request internally, so no additional ThreadPoolExecutor
    concurrency is needed for price/volume downloads in this class.
    """

    # 宏观因子 ticker → 可读名
    MACRO_FACTOR_TICKERS = {
        "^TNX":     "US10Y Rate",     # 10 年美债收益率 — 利率因子
        "DX-Y.NYB": "USD Index",      # 美元指数 — 汇率因子
        "CL=F":     "Crude Oil",      # WTI 原油期货 — 通胀因子
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
                         用于流动性风险计算；可选。
        """
        self.weights = weights
        self.tickers = list(weights.keys())
        self.period_years = period_years
        self.end_date = (
            pd.Timestamp(end_date) if end_date else pd.Timestamp.today().normalize()
        )
        self.start_date = self.end_date - timedelta(days=365 * period_years)
        self.holdings = holdings  # optional, for liquidity calc

        # 缓存
        self._prices: Optional[pd.DataFrame] = None
        self._returns: Optional[pd.DataFrame] = None
        self._macro_prices: Optional[pd.DataFrame] = None
        self._macro_returns: Optional[pd.DataFrame] = None
        self._volume_30d: Optional[pd.DataFrame] = None

        # 初始化缓存提供者
        self._cache_provider = CachedDataProvider()

        # 失败记录
        self._failed_tickers: List[Tuple[str, str]] = []

    # ══════════════════════════════════════════════════════════
    #  数据质量验证与清洗
    # ══════════════════════════════════════════════════════════

    @staticmethod
    def _detect_currency_mixing(prices: pd.DataFrame, tickers: List[str]) -> Tuple[bool, str]:
        """
        检测投资组合中是否混合了不同货币的资产

        Args:
            prices: 价格DataFrame
            tickers: ticker列表

        Returns:
            (has_mixing, warning_message)
        """
        # 常见的非美元资产后缀
        foreign_indicators = {
            '.L': 'GBP (伦敦)',
            '.T': 'JPY (东京)',
            '.TO': 'CAD (多伦多)',
            '.HK': 'HKD (香港)',
            '.SS': 'CNY (上海)',
            '.SZ': 'CNY (深圳)',
            '.AX': 'AUD (澳洲)',
            '.PA': 'EUR (巴黎)',
            '.DE': 'EUR (德国)',
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
                detected_currencies[ticker] = 'USD'

        # 检查是否有多种货币
        unique_currencies = set(detected_currencies.values())
        if len(unique_currencies) > 1:
            currency_list = ', '.join(f"{t}({c})" for t, c in detected_currencies.items())
            return True, f"检测到混合货币: {currency_list}。VaR计算可能不准确。"

        return False, ""

    @staticmethod
    def _winsorize_returns(returns: pd.Series, lower_pct: float = 0.01, upper_pct: float = 0.99) -> pd.Series:
        """
        Winsorization: 将极端值裁剪到百分位数阈值

        Args:
            returns: 收益率序列
            lower_pct: 下界百分位数 (默认1%)
            upper_pct: 上界百分位数 (默认99%)

        Returns:
            清洗后的收益率序列
        """
        if len(returns) < 10:
            return returns

        valid_returns = returns.dropna()
        if len(valid_returns) == 0:
            return returns

        lower_bound = valid_returns.quantile(lower_pct)
        upper_bound = valid_returns.quantile(upper_pct)

        # 裁剪到阈值
        clipped = returns.clip(lower=lower_bound, upper=upper_bound)

        # 记录被裁剪的数量
        n_clipped = ((returns < lower_bound) | (returns > upper_bound)).sum()
        if n_clipped > 0:
            logger.info(
                "data.winsorization.applied",
                n_clipped=n_clipped,
                lower_bound=round(lower_bound, 4),
                upper_bound=round(upper_bound, 4)
            )

        return clipped

    @staticmethod
    def _detect_gaps(data: pd.Series, max_gap_days: int = 5) -> List[Tuple[pd.Timestamp, pd.Timestamp, int]]:
        """
        检测数据中的缺口（连续缺失）

        Args:
            data: 价格或收益率序列
            max_gap_days: 最大允许缺口天数

        Returns:
            缺口列表 [(start_date, end_date, gap_days), ...]
        """
        if data.index.freq is None:
            # 推断频率
            try:
                inferred_freq = pd.infer_freq(data.index[:20])
                if inferred_freq is None:
                    return []
            except Exception:
                return []

        # 找到所有缺失值的位置
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
    def _smart_fill_gaps(data: pd.Series, method: str = 'auto') -> pd.Series:
        """
        智能填充数据缺口

        Args:
            data: 带缺失值的序列
            method: 填充方法
                - 'auto': 小缺口用线性插值，大缺口用前向填充
                - 'ffill': 前向填充
                - 'interpolate': 线性插值

        Returns:
            填充后的序列
        """
        if data.isnull().sum() == 0:
            return data

        if method == 'ffill':
            return data.ffill()
        elif method == 'interpolate':
            return data.interpolate(method='linear', limit_direction='both')
        elif method == 'auto':
            # 对小缺口（<=3天）用插值，大缺口用前向填充
            filled = data.copy()

            # 先前向填充
            filled = filled.ffill()

            # 找连续缺失<=3的区间用插值
            missing_runs = (filled.isnull().astype(int).groupby(
                filled.notnull().astype(int).cumsum()
            ).cumsum())

            small_gaps = missing_runs <= 3
            filled[small_gaps] = data[small_gaps].interpolate(method='linear')

            # 最后再填充剩余的
            filled = filled.ffill().bfill()

            return filled
        else:
            raise ValueError(f"Unknown fill method: {method}")

    def _validate_ticker_data(self, ticker: str, data: pd.DataFrame) -> Tuple[bool, str]:
        """
        验证ticker数据质量

        Returns:
            (is_valid, error_message)
        """
        if data is None or data.empty:
            return False, "数据为空"

        # 获取 Close 列（如果是 MultiIndex）
        if isinstance(data.columns, pd.MultiIndex):
            if 'Close' in data.columns.get_level_values(0):
                close_data = data['Close']
                # 如果还是DataFrame，取第一列
                if isinstance(close_data, pd.DataFrame):
                    close_data = close_data.iloc[:, 0]
            else:
                close_data = data.iloc[:, 0] if len(data.columns) > 0 else data
        else:
            if 'Close' in data.columns:
                close_data = data['Close']
            else:
                close_data = data.iloc[:, 0] if len(data.columns) > 0 else data

        # 确保是Series
        if isinstance(close_data, pd.DataFrame):
            close_data = close_data.iloc[:, 0]

        # 检查1: 数据量不足
        if len(close_data) < 20:  # 至少20个交易日
            return False, f"数据量不足({len(close_data)}天)"

        # 检查2: 缺失率
        missing_pct = close_data.isnull().sum() / len(close_data)
        if missing_pct > 0.3:
            return False, f"缺失率{missing_pct:.1%}超过30%"

        # 检查3: 价格<=0
        valid_prices = close_data.dropna()
        if len(valid_prices) > 0 and (valid_prices <= 0).any():
            return False, "存在<=0的价格"

        # 检查4: 极端单日涨跌幅 (可能是股票分拆/合并)
        if len(valid_prices) > 1:
            returns = valid_prices.pct_change().dropna()
            if len(returns) > 0:
                extreme_count = (abs(returns) > 0.5).sum()
                if extreme_count > 0:
                    # 允许1-2次极端值（可能是真实的市场事件）
                    if extreme_count > 2:
                        return False, f"存在{extreme_count}次极端单日涨跌幅(>50%)"
                    else:
                        logger.warning(
                            "data.validation.extreme_returns",
                            ticker=ticker,
                            extreme_count=extreme_count,
                            max_return=round(returns.abs().max(), 3)
                        )

        # 检查5: 连续相同价格(停牌) - 放宽标准，因为某些资产可能正常停滞
        if len(valid_prices) > 10:
            price_changes = valid_prices.diff().fillna(0)
            consecutive_zeros = (price_changes == 0).rolling(window=15).sum().max()
            if consecutive_zeros >= 15:  # 连续15天相同价格
                return False, f"存在{int(consecutive_zeros)}天连续相同价格(可能停牌)"

        # 检查6: 检测大缺口
        gaps = self._detect_gaps(close_data, max_gap_days=5)
        if gaps:
            total_gap_days = sum(g[2] for g in gaps)
            if total_gap_days > 20:  # 累计缺口超过20天
                return False, f"数据缺口过多: {len(gaps)}个缺口, 累计{total_gap_days}天"
            else:
                logger.info(
                    "data.validation.gaps_detected",
                    ticker=ticker,
                    n_gaps=len(gaps),
                    total_gap_days=total_gap_days
                )

        # 检查7: 价格波动性异常（可能是数据错误）
        if len(valid_prices) > 30:
            returns = valid_prices.pct_change().dropna()
            if len(returns) > 0:
                volatility = returns.std()
                # 年化波动率 > 200% 非常异常
                if volatility * np.sqrt(252) > 2.0:
                    logger.warning(
                        "data.validation.extreme_volatility",
                        ticker=ticker,
                        annual_vol=round(volatility * np.sqrt(252), 2)
                    )

        return True, ""

    def get_failed_tickers(self) -> List[Tuple[str, str]]:
        """返回下载失败的ticker列表及失败原因"""
        return self._failed_tickers.copy()

    # ══════════════════════════════════════════════════════════
    #  资产价格 & 收益率（改进版：健壮的批量下载）
    # ══════════════════════════════════════════════════════════
    def fetch_prices(self, force_refresh: bool = False) -> pd.DataFrame:
        """
        下载调整后收盘价，返回 DataFrame (date × ticker)。
        健壮版本：单个ticker失败不影响其他，支持缓存和数据验证。

        Args:
            force_refresh: 强制刷新数据（忽略缓存）

        Returns:
            DataFrame: 成功下载的ticker的价格数据
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
            end_date=end_str
        )
        batch_start_time = time.time()

        print(f"\n{'='*60}")
        print(f"数据下载开始: {len(self.tickers)} 个ticker")
        print(f"时间范围: {start_str} 至 {end_str}")
        print(f"{'='*60}")

        for ticker in self.tickers:
            try:
                # 使用缓存下载
                data = self._cache_provider.fetch_with_cache(
                    ticker,
                    start_str,
                    end_str,
                    force_refresh=force_refresh,
                    data_type="prices"
                )

                if data is None:
                    self._failed_tickers.append((ticker, "下载返回空数据"))
                    print(f"  ✗ {ticker}: 下载失败（空数据）")
                    continue

                # 数据验证
                is_valid, error_msg = self._validate_ticker_data(ticker, data)
                if not is_valid:
                    self._failed_tickers.append((ticker, error_msg))
                    logger.warning(
                        "data.fetch_prices.validation_failed",
                        ticker=ticker,
                        error=error_msg
                    )
                    print(f"  ✗ {ticker}: 验证失败 - {error_msg}")
                    continue

                # 提取 Close 价格
                if isinstance(data.columns, pd.MultiIndex):
                    if 'Close' in data.columns.get_level_values(0):
                        close = data['Close']
                        if isinstance(close, pd.DataFrame):
                            close = close.iloc[:, 0]
                    else:
                        close = data.iloc[:, 0]
                else:
                    if 'Close' in data.columns:
                        close = data['Close']
                    else:
                        close = data.iloc[:, 0] if len(data.columns) > 0 else data

                successful_prices[ticker] = close
                print(f"  ✓ {ticker}: 成功 ({len(close)} 个数据点)")

            except Exception as e:
                self._failed_tickers.append((ticker, f"异常: {str(e)}"))
                print(f"  ✗ {ticker}: 异常 - {str(e)}")
                continue

        # 报告结果
        batch_duration = (time.time() - batch_start_time) * 1000
        logger.info(
            "data.fetch_prices.complete",
            successful=len(successful_prices),
            failed=len(self._failed_tickers),
            total=len(self.tickers),
            duration_ms=round(batch_duration, 2)
        )

        print(f"\n{'='*60}")
        print(f"数据下载完成:")
        print(f"  成功: {len(successful_prices)}/{len(self.tickers)}")
        print(f"  失败: {len(self._failed_tickers)}")

        if self._failed_tickers:
            print(f"\n失败详情:")
            for ticker, error in self._failed_tickers:
                logger.warning(
                    "data.fetch_prices.ticker_failed",
                    ticker=ticker,
                    error=error
                )
                print(f"  - {ticker}: {error}")

        print(f"{'='*60}\n")

        if not successful_prices:
            logger.error(
                "data.fetch_prices.all_failed",
                ticker_count=len(self.tickers)
            )
            raise ValueError(
                "所有ticker数据获取失败！请检查:\n"
                "  1. 网络连接\n"
                "  2. 股票代码是否正确\n"
                "  3. 日期范围是否有效"
            )

        # 合并为 DataFrame
        self._prices = pd.DataFrame(successful_prices)

        # 检测货币混合
        has_mixing, currency_warning = self._detect_currency_mixing(
            self._prices,
            list(successful_prices.keys())
        )
        if has_mixing:
            logger.warning("data.currency_mixing", message=currency_warning)
            print(f"\n⚠️  货币警告: {currency_warning}")

        # 智能填充缺口（使用前向填充+插值处理节假日差异和小缺口）
        for col in self._prices.columns:
            self._prices[col] = self._smart_fill_gaps(self._prices[col], method='auto')

        # 移除仍有缺失的行
        self._prices = self._prices.dropna()

        return self._prices

    def get_daily_returns(self, winsorize: bool = False) -> pd.DataFrame:
        """
        计算对数日收益率

        Args:
            winsorize: 是否应用Winsorization处理极端值 (默认False)

        Returns:
            DataFrame: 日收益率 (date × ticker)
        """
        if self._returns is not None:
            return self._returns

        prices = self.fetch_prices()
        returns = np.log(prices / prices.shift(1)).dropna()

        if winsorize:
            # 对每个ticker应用winsorization
            for col in returns.columns:
                returns[col] = self._winsorize_returns(returns[col])
            logger.info("data.returns.winsorized", ticker_count=len(returns.columns))

        self._returns = returns
        return self._returns

    def get_portfolio_cumulative_returns(self) -> pd.Series:
        """按权重加权，返回组合的累计净值曲线。"""
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
    #  便捷属性访问器
    # ══════════════════════════════════════════════════════════
    @property
    def prices(self) -> pd.DataFrame:
        """便捷访问: 获取价格数据"""
        return self.fetch_prices()

    @property
    def returns(self) -> pd.DataFrame:
        """便捷访问: 获取收益率数据"""
        return self.get_daily_returns()

    # ══════════════════════════════════════════════════════════
    #  宏观因子数据（改进版：健壮下载）
    # ══════════════════════════════════════════════════════════
    def fetch_macro_prices(self, force_refresh: bool = False) -> pd.DataFrame:
        """
        下载宏观因子价格：
          ^TNX   — 10 年美债收益率 (利率因子)
          DX-Y.NYB — 美元指数 (汇率因子)
          CL=F   — WTI 原油期货 (通胀因子)

        返回 DataFrame, columns 为可读名 ("US10Y Rate", "USD Index", "Crude Oil")
        健壮版本：支持缓存和部分失败
        """
        if self._macro_prices is not None and not force_refresh:
            return self._macro_prices

        macro_tickers = list(self.MACRO_FACTOR_TICKERS.keys())
        start_str = self.start_date.strftime("%Y-%m-%d")
        end_str = self.end_date.strftime("%Y-%m-%d")

        logger.info(
            "data.fetch_macro.start",
            macro_tickers=macro_tickers,
            force_refresh=force_refresh
        )
        start_time = time.time()

        successful_data = {}
        failed_macro = []

        for ticker in macro_tickers:
            try:
                data = self._cache_provider.fetch_with_cache(
                    ticker,
                    start_str,
                    end_str,
                    force_refresh=force_refresh,
                    data_type="macro"
                )

                if data is None or data.empty:
                    failed_macro.append((ticker, "下载返回空数据"))
                    continue

                # 提取 Close 价格
                if isinstance(data.columns, pd.MultiIndex):
                    if 'Close' in data.columns.get_level_values(0):
                        close = data['Close']
                        if isinstance(close, pd.DataFrame):
                            close = close.iloc[:, 0]
                    else:
                        close = data.iloc[:, 0]
                else:
                    if 'Close' in data.columns:
                        close = data['Close']
                    else:
                        close = data.iloc[:, 0] if len(data.columns) > 0 else data

                # 使用可读名称
                readable_name = self.MACRO_FACTOR_TICKERS[ticker]
                successful_data[readable_name] = close

            except Exception as e:
                failed_macro.append((ticker, str(e)))
                continue

        duration_ms = (time.time() - start_time) * 1000

        if failed_macro:
            for ticker, error in failed_macro:
                logger.warning(
                    "data.fetch_macro.ticker_failed",
                    ticker=ticker,
                    error=error
                )
            warnings.warn(f"宏观因子部分下载失败: {failed_macro}")

        if not successful_data:
            # 如果全部失败，返回空 DataFrame 而不是抛出异常
            logger.warning(
                "data.fetch_macro.all_failed",
                duration_ms=round(duration_ms, 2)
            )
            warnings.warn("所有宏观因子下载失败，返回空数据")
            self._macro_prices = pd.DataFrame()
            return self._macro_prices

        # 合并数据并前向填充
        self._macro_prices = pd.DataFrame(successful_data)
        self._macro_prices = self._macro_prices.ffill().dropna(how='all')

        logger.info(
            "data.fetch_macro.complete",
            successful=len(successful_data),
            failed=len(failed_macro),
            duration_ms=round(duration_ms, 2)
        )

        return self._macro_prices

    def get_macro_returns(self) -> pd.DataFrame:
        """宏观因子的对数日收益率。"""
        if self._macro_returns is not None:
            return self._macro_returns
        prices = self.fetch_macro_prices()
        self._macro_returns = np.log(prices / prices.shift(1)).dropna()
        return self._macro_returns

    # ══════════════════════════════════════════════════════════
    #  成交量数据（30 日）（改进版：健壮下载）
    # ══════════════════════════════════════════════════════════
    def fetch_volume_30d(self, force_refresh: bool = False) -> pd.DataFrame:
        """
        下载各持仓资产最近 30 个交易日的日成交量。
        返回 DataFrame (date × ticker)，只包含 volume 不为 0 的 ticker。
        加密货币（ticker 含 "-USD"）也能从 Yahoo Finance 获取成交量。
        健壮版本：支持缓存和部分失败
        """
        if self._volume_30d is not None and not force_refresh:
            return self._volume_30d

        # 下载最近 45 天数据以确保有 30 个交易日
        end = self.end_date
        start = end - timedelta(days=45)
        start_str = start.strftime("%Y-%m-%d")
        end_str = end.strftime("%Y-%m-%d")

        successful_volumes = {}
        failed_volumes = []

        for ticker in self.tickers:
            try:
                data = self._cache_provider.fetch_with_cache(
                    ticker,
                    start_str,
                    end_str,
                    force_refresh=force_refresh,
                    data_type="volume",
                    max_age_hours=6  # 成交量数据更频繁更新
                )

                if data is None or data.empty:
                    failed_volumes.append((ticker, "下载返回空数据"))
                    continue

                # 提取 Volume 列
                if isinstance(data.columns, pd.MultiIndex):
                    if 'Volume' in data.columns.get_level_values(0):
                        volume = data['Volume']
                        if isinstance(volume, pd.DataFrame):
                            volume = volume.iloc[:, 0]
                    else:
                        # 没有 Volume 列，跳过
                        continue
                else:
                    if 'Volume' in data.columns:
                        volume = data['Volume']
                    else:
                        # 没有 Volume 列，跳过
                        continue

                # 清理无效值
                volume = volume.replace([np.inf, -np.inf], np.nan).fillna(0)

                # 只保留最近30个交易日
                volume = volume.tail(30)

                if len(volume) > 0:
                    successful_volumes[ticker] = volume

            except Exception as e:
                failed_volumes.append((ticker, str(e)))
                continue

        if failed_volumes and len(failed_volumes) > len(self.tickers) * 0.3:
            # 如果超过30%失败，发出警告
            warnings.warn(f"成交量数据部分下载失败 ({len(failed_volumes)}/{len(self.tickers)})")

        if not successful_volumes:
            # 返回空 DataFrame 而不是抛出异常
            self._volume_30d = pd.DataFrame()
            return self._volume_30d

        # 合并数据
        self._volume_30d = pd.DataFrame(successful_volumes)
        return self._volume_30d

    def get_adv_30d(self) -> pd.Series:
        """
        30 日平均日成交量 (Average Daily Volume)。
        返回 Series: ticker → ADV (shares)。
        """
        vol = self.fetch_volume_30d().replace([np.inf, -np.inf], np.nan).fillna(0)
        # 使用中位数降低停牌缺口和单日异常放量对 ADV 的扭曲。
        adv = vol.median()
        adv.name = "ADV_30d"
        return adv
