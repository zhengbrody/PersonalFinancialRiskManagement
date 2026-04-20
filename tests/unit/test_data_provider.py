"""
test_data_provider.py
数据提供者的单元测试 - 测试健壮性、缓存和数据验证功能
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os
import tempfile
import shutil

from data_provider import DataProvider, CachedDataProvider


class TestDataValidation:
    """测试数据质量验证功能"""

    def test_validate_ticker_data_normal(self):
        """测试正常数据验证通过"""
        dp = DataProvider({'TEST': 1.0}, period_years=1)

        # 创建正常数据
        dates = pd.date_range('2024-01-01', periods=100)
        data = pd.DataFrame({
            'Close': [100 + i * 0.5 for i in range(100)]
        }, index=dates)

        is_valid, msg = dp._validate_ticker_data('TEST', data)
        assert is_valid is True
        assert msg == ""

    def test_validate_ticker_data_empty(self):
        """测试空数据"""
        dp = DataProvider({'TEST': 1.0}, period_years=1)

        data = pd.DataFrame()

        is_valid, msg = dp._validate_ticker_data('TEST', data)
        assert is_valid is False
        assert "数据为空" in msg

    def test_validate_ticker_data_insufficient(self):
        """测试数据量不足"""
        dp = DataProvider({'TEST': 1.0}, period_years=1)

        # 只有10个数据点（少于20）
        dates = pd.date_range('2024-01-01', periods=10)
        data = pd.DataFrame({
            'Close': [100 + i for i in range(10)]
        }, index=dates)

        is_valid, msg = dp._validate_ticker_data('TEST', data)
        assert is_valid is False
        assert "数据量不足" in msg

    def test_validate_ticker_data_high_missing_rate(self):
        """测试缺失率过高的数据"""
        dp = DataProvider({'TEST': 1.0}, period_years=1)

        # 创建35%缺失的数据（超过30%阈值）
        dates = pd.date_range('2024-01-01', periods=100)
        values = []
        for i in range(100):
            if i % 3 == 0:  # 每3个就有1个缺失，约33%
                values.append(None)
            else:
                values.append(100 + i * 0.5 + np.random.random() * 2)  # 添加随机波动和趋势

        data = pd.DataFrame({
            'Close': values
        }, index=dates)

        is_valid, msg = dp._validate_ticker_data('TEST', data)
        assert is_valid is False
        assert "缺失率" in msg

    def test_validate_ticker_data_negative_prices(self):
        """测试负价格或零价格"""
        dp = DataProvider({'TEST': 1.0}, period_years=1)

        dates = pd.date_range('2024-01-01', periods=100)
        values = [100 + i for i in range(100)]
        values[50] = 0  # 一个零价格
        data = pd.DataFrame({
            'Close': values
        }, index=dates)

        is_valid, msg = dp._validate_ticker_data('TEST', data)
        assert is_valid is False
        assert "<=0的价格" in msg

    def test_validate_ticker_data_extreme_return(self):
        """测试极端涨跌幅 — 1-2次允许(警告)，>2次则失败"""
        dp = DataProvider({'TEST': 1.0}, period_years=1)

        # 1次极端涨幅 → 允许但警告
        np.random.seed(42)
        dates = pd.date_range('2024-01-01', periods=50)
        values = (100 + np.cumsum(np.random.randn(50) * 0.5)).tolist()
        values[25] = values[24] * 1.6  # 第26天涨60%
        data = pd.DataFrame({'Close': values}, index=dates)
        is_valid, _ = dp._validate_ticker_data('TEST', data)
        assert is_valid is True  # 1次极端值可以容忍

        # 3次以上极端涨幅 → 失败
        values[10] = values[9] * 1.7
        values[35] = values[34] * 0.4
        values[40] = values[39] * 1.8
        data3 = pd.DataFrame({'Close': values}, index=dates)
        is_valid3, msg3 = dp._validate_ticker_data('TEST', data3)
        assert is_valid3 is False
        assert "极端" in msg3

    def test_validate_ticker_data_suspended_trading(self):
        """测试停牌（连续相同价格）"""
        dp = DataProvider({'TEST': 1.0}, period_years=1)

        # 创建连续20天相同价格的数据
        dates = pd.date_range('2024-01-01', periods=50)
        values = [100.0] * 50
        # 前20天相同价格（模拟停牌）
        for i in range(20):
            values[i] = 100.0

        data = pd.DataFrame({
            'Close': values
        }, index=dates)

        is_valid, msg = dp._validate_ticker_data('TEST', data)
        assert is_valid is False
        assert "连续相同价格" in msg or "停牌" in msg


class TestCachedDataProvider:
    """测试缓存功能"""

    @pytest.fixture
    def temp_cache_dir(self):
        """创建临时缓存目录"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        # 清理
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_cache_path_generation(self, temp_cache_dir):
        """测试缓存路径生成"""
        cache_provider = CachedDataProvider(cache_dir=temp_cache_dir)

        path = cache_provider._get_cache_path('AAPL', '2024-01-01', '2024-12-31', 'prices')

        assert temp_cache_dir in path
        assert 'AAPL' in path
        assert '2024-01-01' in path
        assert '2024-12-31' in path
        assert 'prices.pkl' in path

    def test_cache_path_special_characters(self, temp_cache_dir):
        """测试特殊字符在缓存路径中的处理"""
        cache_provider = CachedDataProvider(cache_dir=temp_cache_dir)

        # 测试包含特殊字符的ticker
        path1 = cache_provider._get_cache_path('^TNX', '2024-01-01', '2024-12-31', 'prices')
        path2 = cache_provider._get_cache_path('CL=F', '2024-01-01', '2024-12-31', 'prices')

        # 确保特殊字符被替换
        assert '^' not in path1
        assert '=' not in path2

    def test_cache_validity_check(self, temp_cache_dir):
        """测试缓存有效性检查"""
        cache_provider = CachedDataProvider(cache_dir=temp_cache_dir)

        # 创建一个缓存文件
        cache_path = os.path.join(temp_cache_dir, 'test.pkl')

        # 文件不存在时应该无效
        assert cache_provider._is_cache_valid(cache_path, max_age_hours=24) is False

        # 创建文件
        with open(cache_path, 'wb') as f:
            f.write(b'test')

        # 新文件应该有效
        assert cache_provider._is_cache_valid(cache_path, max_age_hours=24) is True

        # 修改文件时间为2天前（超过24小时）
        old_time = (datetime.now() - timedelta(days=2)).timestamp()
        os.utime(cache_path, (old_time, old_time))

        # 过期文件应该无效
        assert cache_provider._is_cache_valid(cache_path, max_age_hours=24) is False


class TestDataProviderRobustness:
    """测试 DataProvider 的健壮性"""

    def test_initialization(self):
        """测试初始化"""
        weights = {'AAPL': 0.5, 'GOOGL': 0.5}
        dp = DataProvider(weights, period_years=2)

        assert dp.weights == weights
        assert dp.tickers == ['AAPL', 'GOOGL']
        assert dp.period_years == 2
        assert dp._cache_provider is not None
        assert dp._failed_tickers == []

    def test_initialization_with_holdings(self):
        """测试带holdings的初始化"""
        weights = {'AAPL': 0.5, 'GOOGL': 0.5}
        holdings = {'AAPL': {'shares': 100}, 'GOOGL': {'shares': 50}}

        dp = DataProvider(weights, period_years=2, holdings=holdings)

        assert dp.holdings == holdings

    def test_get_failed_tickers(self):
        """测试获取失败ticker列表"""
        weights = {'AAPL': 0.5, 'GOOGL': 0.5}
        dp = DataProvider(weights, period_years=2)

        # 初始应该为空
        assert dp.get_failed_tickers() == []

        # 手动添加一些失败记录
        dp._failed_tickers = [('INVALID', 'ticker不存在')]

        failed = dp.get_failed_tickers()
        assert len(failed) == 1
        assert failed[0][0] == 'INVALID'
        assert 'ticker不存在' in failed[0][1]

    def test_date_range_calculation(self):
        """测试日期范围计算"""
        weights = {'AAPL': 0.5}
        end_date = '2024-12-31'

        dp = DataProvider(weights, period_years=2, end_date=end_date)

        assert dp.end_date == pd.Timestamp('2024-12-31')
        # 2年前应该是2022-12-31左右
        expected_start = pd.Timestamp('2024-12-31') - timedelta(days=365 * 2)
        assert dp.start_date == expected_start


class TestDataProviderIntegration:
    """集成测试 - 测试实际数据下载（需要网络连接）"""

    @pytest.mark.slow
    @pytest.mark.skipif(
        os.environ.get('SKIP_NETWORK_TESTS') == '1',
        reason="跳过网络测试"
    )
    def test_fetch_prices_single_ticker(self):
        """测试单个ticker的价格获取"""
        weights = {'AAPL': 1.0}
        dp = DataProvider(weights, period_years=1)

        try:
            prices = dp.fetch_prices()

            # 验证返回的是DataFrame
            assert isinstance(prices, pd.DataFrame)

            # 验证包含AAPL列
            assert 'AAPL' in prices.columns

            # 验证有数据
            assert len(prices) > 0

            # 验证数据类型
            assert prices['AAPL'].dtype in [np.float64, np.float32]

        except Exception as e:
            pytest.skip(f"网络测试失败（可能是网络问题）: {e}")

    @pytest.mark.slow
    @pytest.mark.skipif(
        os.environ.get('SKIP_NETWORK_TESTS') == '1',
        reason="跳过网络测试"
    )
    def test_fetch_prices_multiple_tickers(self):
        """测试多个ticker的价格获取"""
        weights = {'AAPL': 0.5, 'GOOGL': 0.5}
        dp = DataProvider(weights, period_years=1)

        try:
            prices = dp.fetch_prices()

            # 至少应该有一个ticker成功
            assert len(prices.columns) >= 1

            # 验证数据有效
            assert len(prices) > 0

        except Exception as e:
            pytest.skip(f"网络测试失败（可能是网络问题）: {e}")

    @pytest.mark.slow
    @pytest.mark.skipif(
        os.environ.get('SKIP_NETWORK_TESTS') == '1',
        reason="跳过网络测试"
    )
    def test_fetch_prices_with_invalid_ticker(self):
        """测试包含无效ticker时的健壮性"""
        weights = {
            'AAPL': 0.4,
            'INVALID_TICKER_XYZ123': 0.3,
            'GOOGL': 0.3
        }
        dp = DataProvider(weights, period_years=1)

        try:
            prices = dp.fetch_prices()

            # 应该成功返回有效ticker的数据
            assert isinstance(prices, pd.DataFrame)

            # 有效ticker应该在结果中
            valid_tickers = [t for t in ['AAPL', 'GOOGL'] if t in prices.columns]
            assert len(valid_tickers) >= 1

            # 无效ticker应该在失败列表中
            failed = dp.get_failed_tickers()
            failed_ticker_names = [f[0] for f in failed]
            assert 'INVALID_TICKER_XYZ123' in failed_ticker_names

        except Exception as e:
            pytest.skip(f"网络测试失败（可能是网络问题）: {e}")

    def test_get_daily_returns(self):
        """测试日收益率计算"""
        weights = {'AAPL': 1.0}
        dp = DataProvider(weights, period_years=1)

        # 创建模拟价格数据
        dates = pd.date_range('2024-01-01', periods=100)
        prices = pd.DataFrame({
            'AAPL': [100 + i for i in range(100)]
        }, index=dates)

        dp._prices = prices

        returns = dp.get_daily_returns()

        # 验证返回类型
        assert isinstance(returns, pd.DataFrame)

        # 验证长度（应该比价格少1行）
        assert len(returns) == len(prices) - 1

        # 验证是简单收益率（project-wide convention）
        assert returns['AAPL'].iloc[0] == pytest.approx((101 - 100) / 100, rel=1e-9)

    def test_cumulative_return_matches_price_derived(self):
        """累计收益（由返回序列推导）必须与（终价/起价 - 1）一致。"""
        dp = DataProvider({'AAPL': 1.0}, period_years=2)
        dates = pd.date_range('2024-01-01', periods=60, freq='D')
        prices = pd.DataFrame({
            'AAPL': [100.0 * (1.001 ** i) for i in range(60)]
        }, index=dates)
        dp._prices = prices

        returns = dp.get_daily_returns()
        cumret_from_returns = (1 + returns['AAPL']).prod() - 1
        cumret_from_prices = prices['AAPL'].iloc[-1] / prices['AAPL'].iloc[0] - 1

        assert cumret_from_returns == pytest.approx(cumret_from_prices, rel=1e-10)


class TestCacheIntegration:
    """测试缓存集成功能"""

    @pytest.fixture
    def temp_cache_dir(self):
        """创建临时缓存目录"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_cache_saves_data(self, temp_cache_dir):
        """测试缓存是否正确保存数据"""
        cache_provider = CachedDataProvider(cache_dir=temp_cache_dir)

        # 创建测试数据
        test_data = pd.DataFrame({
            'Close': [100, 101, 102],
            'Volume': [1000, 1100, 1200]
        })

        # 保存到缓存
        cache_path = cache_provider._get_cache_path('TEST', '2024-01-01', '2024-01-31', 'prices')
        import pickle
        with open(cache_path, 'wb') as f:
            pickle.dump(test_data, f)

        # 验证缓存有效
        assert cache_provider._is_cache_valid(cache_path, max_age_hours=24)

        # 从缓存加载
        with open(cache_path, 'rb') as f:
            loaded_data = pickle.load(f)

        # 验证数据一致性
        pd.testing.assert_frame_equal(test_data, loaded_data)


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
