"""
data_provider.py
数据下载与预处理模块
"""

import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, Optional


class DataProvider:
    """负责从 Yahoo Finance 下载行情数据并进行预处理。"""

    def __init__(
        self,
        weights: Dict[str, float],
        period_years: int = 2,
        end_date: Optional[str] = None,
    ):
        self.weights = weights
        self.tickers = list(weights.keys())
        self.period_years = period_years
        self.end_date = (
            pd.Timestamp(end_date) if end_date else pd.Timestamp.today().normalize()
        )
        self.start_date = self.end_date - timedelta(days=365 * period_years)

        self._prices: Optional[pd.DataFrame] = None
        self._returns: Optional[pd.DataFrame] = None

    # ── 数据下载 ──────────────────────────────────────────────
    def fetch_prices(self) -> pd.DataFrame:
        """下载调整后收盘价，返回 DataFrame (date × ticker)。"""
        if self._prices is not None:
            return self._prices

        raw = yf.download(
            self.tickers,
            start=self.start_date.strftime("%Y-%m-%d"),
            end=self.end_date.strftime("%Y-%m-%d"),
            auto_adjust=True,
            progress=False,
        )

        # yfinance 返回格式因 ticker 数量而异
        if isinstance(raw.columns, pd.MultiIndex):
            prices = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw
            # Flatten if still MultiIndex
            if isinstance(prices.columns, pd.MultiIndex):
                prices = prices.droplevel(0, axis=1)
        else:
            prices = raw[["Close"]].rename(columns={"Close": self.tickers[0]})

        prices = prices[self.tickers].dropna()
        self._prices = prices
        return self._prices

    # ── 日收益率 ─────────────────────────────────────────────
    def get_daily_returns(self) -> pd.DataFrame:
        """计算对数日收益率。"""
        if self._returns is not None:
            return self._returns
        prices = self.fetch_prices()
        self._returns = np.log(prices / prices.shift(1)).dropna()
        return self._returns

    # ── 组合累计收益 ─────────────────────────────────────────
    def get_portfolio_cumulative_returns(self) -> pd.Series:
        """按权重加权，返回组合的累计净值曲线。"""
        ret = self.get_daily_returns()
        w = np.array([self.weights[t] for t in ret.columns])
        port_ret = ret.dot(w)
        cum = (1 + port_ret).cumprod()
        cum.name = "Portfolio"
        return cum

    # ── 权重向量 (与 returns 列对齐) ────────────────────────
    def get_weight_array(self) -> np.ndarray:
        ret = self.get_daily_returns()
        return np.array([self.weights[t] for t in ret.columns])
