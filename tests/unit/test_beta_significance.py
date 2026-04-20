"""
test_beta_significance.py
测试多因子Beta统计显著性检验功能
"""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

from risk_engine import RiskEngine
from data_provider import DataProvider


# ══════════════════════════════════════════════════════════════
#  测试 _compute_beta_with_significance 方法
# ══════════════════════════════════════════════════════════════

def test_beta_significance_highly_correlated():
    """测试高度相关数据（beta应该显著）"""
    # 创建完全相关的数据（beta=1.5, 低噪声）
    np.random.seed(42)
    n_samples = 252
    X = np.random.randn(n_samples)
    y = 1.5 * X + np.random.randn(n_samples) * 0.05  # beta=1.5, 低噪声

    # 创建mock的DataProvider和RiskEngine
    mock_dp = Mock(spec=DataProvider)
    engine = RiskEngine(mock_dp)

    # 调用统计显著性方法
    stats = engine._compute_beta_with_significance(y, X)

    # 验证结果
    assert 1.4 < stats['beta'] < 1.6, f"Beta应该接近1.5，实际: {stats['beta']}"
    assert stats['p_value'] < 0.001, f"p值应该非常小（高度显著），实际: {stats['p_value']}"
    assert stats['is_significant'] == True, "beta应该显著"
    assert stats['r_squared'] > 0.9, f"R²应该很高，实际: {stats['r_squared']}"
    assert not np.isnan(stats['t_stat']), "t统计量不应该是NaN"
    assert not np.isnan(stats['std_error']), "标准误不应该是NaN"


def test_beta_significance_no_correlation():
    """测试无相关数据（beta应该不显著）"""
    # 创建完全独立的随机数据
    np.random.seed(42)
    n_samples = 252
    X = np.random.randn(n_samples)
    y = np.random.randn(n_samples)  # 完全独立

    mock_dp = Mock(spec=DataProvider)
    engine = RiskEngine(mock_dp)

    stats = engine._compute_beta_with_significance(y, X)

    # 验证结果
    assert stats['p_value'] > 0.05, f"p值应该大于0.05（不显著），实际: {stats['p_value']}"
    assert stats['is_significant'] == False, "beta不应该显著"
    assert stats['r_squared'] < 0.1, f"R²应该很低，实际: {stats['r_squared']}"


def test_beta_significance_small_sample():
    """测试小样本（可能不显著，取决于噪声）"""
    np.random.seed(42)
    n_samples = 30  # 只有30个样本
    X = np.random.randn(n_samples)
    y = 0.8 * X + np.random.randn(n_samples) * 0.5  # beta=0.8, 中等噪声

    mock_dp = Mock(spec=DataProvider)
    engine = RiskEngine(mock_dp)

    stats = engine._compute_beta_with_significance(y, X)

    # 小样本应该仍然能返回合理结果
    assert 'beta' in stats
    assert 'p_value' in stats
    assert 't_stat' in stats
    assert not np.isnan(stats['beta'])
    assert 0 <= stats['p_value'] <= 1 or np.isnan(stats['p_value'])


def test_beta_significance_negative_beta():
    """测试负beta系数"""
    np.random.seed(42)
    n_samples = 252
    X = np.random.randn(n_samples)
    y = -1.2 * X + np.random.randn(n_samples) * 0.1  # 负beta，低噪声

    mock_dp = Mock(spec=DataProvider)
    engine = RiskEngine(mock_dp)

    stats = engine._compute_beta_with_significance(y, X)

    # 验证结果
    assert -1.3 < stats['beta'] < -1.1, f"Beta应该接近-1.2，实际: {stats['beta']}"
    assert stats['p_value'] < 0.001, "负beta也应该显著"
    assert stats['is_significant'] == True
    assert stats['t_stat'] < 0, "负beta的t统计量应该为负"


def test_beta_significance_edge_cases():
    """测试边界情况"""
    mock_dp = Mock(spec=DataProvider)
    engine = RiskEngine(mock_dp)

    # 测试1: 常数数组（无变化）
    X_const = np.ones(100)
    y_const = np.random.randn(100)

    stats_const = engine._compute_beta_with_significance(y_const, X_const)

    # 应该返回NaN或接近零（因为X无变化，X'X矩阵奇异）
    # 在实际情况中，lstsq会尝试处理，可能返回很小的值或NaN
    assert np.isnan(stats_const['beta']) or abs(stats_const['beta']) < 1.0

    # 测试2: 包含NaN的数据
    X_nan = np.array([1, 2, np.nan, 4, 5])
    y_nan = np.array([2, 4, 6, 8, 10])

    # 这应该能处理或返回合理的错误
    try:
        stats_nan = engine._compute_beta_with_significance(y_nan, X_nan)
        # 如果没有报错，检查结果
        assert 'beta' in stats_nan
    except (ValueError, np.linalg.LinAlgError):
        # 允许抛出异常
        pass


# ══════════════════════════════════════════════════════════════
#  测试 _compute_multi_factor_betas 方法（集成测试）
# ══════════════════════════════════════════════════════════════

@pytest.mark.integration
def test_multi_factor_betas_with_significance():
    """集成测试：多因子beta计算及显著性检验。
    Benchmark data now flows through DataProvider.get_benchmark_returns,
    not yfinance directly, so we stub the provider method."""
    # 创建模拟数据
    dates = pd.date_range('2023-01-01', periods=252, freq='D')

    # 模拟资产收益率
    np.random.seed(42)
    asset_returns = pd.DataFrame({
        'AAPL': np.random.randn(252) * 0.02,
        'TSLA': np.random.randn(252) * 0.03,
    }, index=dates)

    # 模拟因子收益率（SPY, QQQ 等） — 直接提供 simple return 级别
    np.random.seed(7)
    factor_ret = pd.DataFrame({
        'SPY': np.random.randn(252) * 0.01,
        'QQQ': np.random.randn(252) * 0.015,
        'GLD': np.random.randn(252) * 0.008,
        'TLT': np.random.randn(252) * 0.01,
        'IWM': np.random.randn(252) * 0.012,
        'VTV': np.random.randn(252) * 0.009,
    }, index=dates)

    # Mock DataProvider: benchmark returns are now provider-sourced
    mock_dp = Mock(spec=DataProvider)
    mock_dp.start_date = dates[0]
    mock_dp.end_date = dates[-1]
    mock_dp.get_benchmark_returns.return_value = factor_ret
    mock_dp.get_risk_free_rate.return_value = 0.045

    engine = RiskEngine(mock_dp)

    # 调用多因子 beta 计算
    result = engine._compute_multi_factor_betas(asset_returns)

    # 验证返回结构
    assert 'betas' in result, "应该返回betas"
    assert 'significance' in result, "应该返回significance"

    betas_df = result['betas']
    sig_df = result['significance']

    # 验证betas DataFrame
    assert isinstance(betas_df, pd.DataFrame)
    assert not betas_df.empty
    assert 'AAPL' in betas_df.index
    assert 'TSLA' in betas_df.index

    # 验证significance DataFrame
    assert isinstance(sig_df, pd.DataFrame)
    assert not sig_df.empty
    assert 'Ticker' in sig_df.columns
    assert 'Factor' in sig_df.columns
    assert 'Beta' in sig_df.columns
    assert 't_stat' in sig_df.columns
    assert 'p_value' in sig_df.columns
    assert 'is_significant' in sig_df.columns
    assert 'r_squared' in sig_df.columns

    # 检查每个资产都有6个因子的统计信息
    for ticker in ['AAPL', 'TSLA']:
        ticker_data = sig_df[sig_df['Ticker'] == ticker]
        assert len(ticker_data) == 6, f"{ticker}应该有6个因子"

        # 检查所有必要字段都存在且格式正确
        for _, row in ticker_data.iterrows():
            assert 'Beta' in row
            assert 't_stat' in row
            assert 'p_value' in row
            assert isinstance(row['is_significant'], (bool, np.bool_))


# ══════════════════════════════════════════════════════════════
#  性能测试
# ══════════════════════════════════════════════════════════════

def test_beta_significance_performance():
    """测试统计检验的性能（应该很快）"""
    import time

    np.random.seed(42)
    n_samples = 252
    X = np.random.randn(n_samples)
    y = 1.5 * X + np.random.randn(n_samples) * 0.1

    mock_dp = Mock(spec=DataProvider)
    engine = RiskEngine(mock_dp)

    # 执行100次，测量时间
    start = time.time()
    for _ in range(100):
        stats = engine._compute_beta_with_significance(y, X)
    elapsed = time.time() - start

    # 100次应该在1秒内完成
    assert elapsed < 1.0, f"100次beta计算耗时{elapsed:.2f}秒，太慢了"


# ══════════════════════════════════════════════════════════════
#  文档测试（确保返回结构符合文档）
# ══════════════════════════════════════════════════════════════

def test_beta_significance_return_structure():
    """测试返回字典的结构符合文档说明"""
    np.random.seed(42)
    n_samples = 252
    X = np.random.randn(n_samples)
    y = 1.5 * X + np.random.randn(n_samples) * 0.1

    mock_dp = Mock(spec=DataProvider)
    engine = RiskEngine(mock_dp)

    stats = engine._compute_beta_with_significance(y, X)

    # 验证所有必需字段都存在
    required_fields = ['beta', 'intercept', 't_stat', 'p_value',
                      'is_significant', 'r_squared', 'std_error']

    for field in required_fields:
        assert field in stats, f"缺少必需字段: {field}"

    # 验证类型
    assert isinstance(stats['beta'], (float, np.floating))
    assert isinstance(stats['intercept'], (float, np.floating))
    assert isinstance(stats['t_stat'], (float, np.floating))
    assert isinstance(stats['p_value'], (float, np.floating))
    assert isinstance(stats['is_significant'], (bool, np.bool_))
    assert isinstance(stats['r_squared'], (float, np.floating))
    assert isinstance(stats['std_error'], (float, np.floating))

    # 验证合理范围
    assert 0 <= stats['r_squared'] <= 1, f"R²应该在[0,1]之间，实际: {stats['r_squared']}"
    assert 0 <= stats['p_value'] <= 1 or np.isnan(stats['p_value']), \
        f"p值应该在[0,1]之间，实际: {stats['p_value']}"
    assert stats['std_error'] >= 0 or np.isnan(stats['std_error']), \
        f"标准误应该非负，实际: {stats['std_error']}"


if __name__ == "__main__":
    # 运行基本测试
    print("Running basic beta significance tests...")

    print("\n1. Testing highly correlated data...")
    test_beta_significance_highly_correlated()
    print("✓ Passed")

    print("\n2. Testing no correlation...")
    test_beta_significance_no_correlation()
    print("✓ Passed")

    print("\n3. Testing negative beta...")
    test_beta_significance_negative_beta()
    print("✓ Passed")

    print("\n4. Testing return structure...")
    test_beta_significance_return_structure()
    print("✓ Passed")

    print("\n5. Testing performance...")
    test_beta_significance_performance()
    print("✓ Passed")

    print("\n✅ All basic tests passed!")
