import numpy as np
import pandas as pd
import pytest


@pytest.fixture
def sample_returns():
    """生成示例收益率数据（3个资产，252天）"""
    np.random.seed(42)
    dates = pd.date_range("2022-01-01", periods=252)
    data = {
        "NVDA": np.random.randn(252) * 0.02,
        "SPY": np.random.randn(252) * 0.01,
        "GLD": np.random.randn(252) * 0.008,
    }
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def sample_weights():
    """示例权重"""
    return {"NVDA": 0.5, "SPY": 0.3, "GLD": 0.2}
