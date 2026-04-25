"""
test_error_handling.py
错误处理模块的单元测试
测试JSON解析、权重验证、ticker验证等
"""

import json

import pytest

from error_handler import (
    validate_tickers,
    validate_weights,
)


class TestWeightValidation:
    """权重验证测试"""

    def test_valid_weights(self):
        """测试有效的权重"""
        weights = {"AAPL": 0.3, "GOOGL": 0.7}
        is_valid, result, msg = validate_weights(weights)
        assert is_valid
        assert result == weights
        assert msg is None

    def test_weights_need_normalization(self):
        """测试需要归一化的权重"""
        weights = {"AAPL": 1.0, "GOOGL": 1.0}  # 总和=2
        is_valid, result, msg = validate_weights(weights)
        assert is_valid
        assert result is not None
        assert abs(sum(result.values()) - 1.0) < 0.001
        assert msg is not None

    def test_empty_weights(self):
        """测试空权重字典"""
        weights = {}
        is_valid, result, msg = validate_weights(weights)
        assert not is_valid
        assert result is None
        assert msg is not None

    def test_negative_weight(self):
        """测试负权重"""
        weights = {"AAPL": -0.5, "GOOGL": 1.5}
        is_valid, result, msg = validate_weights(weights)
        assert not is_valid
        assert msg is not None

    def test_non_numeric_weight(self):
        """测试非数字权重"""
        weights = {"AAPL": "0.5", "GOOGL": 0.5}
        is_valid, result, msg = validate_weights(weights)
        assert not is_valid
        assert msg is not None

    def test_weight_tolerance(self):
        """测试权重容差（1%误差内）"""
        # 0.99总和会被自动归一化
        weights = {"AAPL": 0.495, "GOOGL": 0.495}
        is_valid, result, msg = validate_weights(weights)
        assert is_valid
        # 应该被归一化
        assert result is not None
        assert abs(sum(result.values()) - 1.0) < 0.001

    def test_weight_outside_tolerance(self):
        """测试超出容差范围的权重"""
        # 0.95总和超过1%误差
        weights = {"AAPL": 0.47, "GOOGL": 0.48}
        is_valid, result, msg = validate_weights(weights)
        assert is_valid
        assert abs(sum(result.values()) - 1.0) < 0.001
        assert msg is not None


class TestTickerValidation:
    """Ticker验证测试"""

    def test_valid_tickers(self):
        """测试有效的ticker"""
        tickers = ["AAPL", "GOOGL", "MSFT", "BTC-USD"]
        all_valid, valid, invalid = validate_tickers(tickers)
        assert all_valid
        assert valid == tickers
        assert len(invalid) == 0

    def test_invalid_ticker_special_char(self):
        """测试包含特殊字符的ticker"""
        tickers = ["A@PL", "GOOGL"]
        all_valid, valid, invalid = validate_tickers(tickers)
        assert not all_valid
        assert "A@PL" in invalid
        assert "GOOGL" in valid

    def test_mixed_valid_invalid_tickers(self):
        """测试混合的有效和无效ticker"""
        tickers = ["AAPL", "GOOGL#", "MSFT", "BTC/USD"]
        all_valid, valid, invalid = validate_tickers(tickers)
        assert not all_valid
        assert "AAPL" in valid
        assert "MSFT" in valid
        assert "GOOGL#" in invalid
        assert "BTC/USD" in invalid

    def test_ticker_with_hyphen(self):
        """测试包含连字符的ticker（如加密货币）"""
        tickers = ["BTC-USD", "ETH-USD", "MSFT"]
        all_valid, valid, invalid = validate_tickers(tickers)
        assert all_valid
        assert tickers == valid

    def test_empty_ticker_list(self):
        """测试空ticker列表"""
        tickers = []
        all_valid, valid, invalid = validate_tickers(tickers)
        assert all_valid
        assert valid == []
        assert invalid == []

    def test_ticker_with_equals(self):
        """测试包含等号的ticker"""
        # 某些特殊符号ticker可能包含=
        tickers = ["TICKER=F", "AAPL"]
        all_valid, valid, invalid = validate_tickers(tickers)
        assert all_valid
        assert "TICKER=F" in valid
        assert "AAPL" in valid


class TestJSONParsing:
    """JSON解析测试"""

    def test_valid_json(self):
        """测试有效的JSON"""
        json_str = '{"AAPL": 0.5, "GOOGL": 0.5}'
        try:
            result = json.loads(json_str)
            assert result == {"AAPL": 0.5, "GOOGL": 0.5}
        except json.JSONDecodeError:
            pytest.fail("应该能成功解析有效的JSON")

    def test_invalid_json_missing_closing_brace(self):
        """测试缺少右大括号的JSON"""
        json_str = '{"AAPL": 0.5, "GOOGL": 0.5'
        with pytest.raises(json.JSONDecodeError):
            json.loads(json_str)

    def test_invalid_json_single_quotes(self):
        """测试使用单引号的JSON"""
        json_str = "{'AAPL': 0.5, 'GOOGL': 0.5}"
        with pytest.raises(json.JSONDecodeError):
            json.loads(json_str)

    def test_invalid_json_trailing_comma(self):
        """测试尾部逗号"""
        json_str = '{"AAPL": 0.5, "GOOGL": 0.5,}'
        with pytest.raises(json.JSONDecodeError):
            json.loads(json_str)

    def test_json_with_comments(self):
        """测试包含注释的JSON"""
        json_str = '{"AAPL": 0.5, // comment\n"GOOGL": 0.5}'
        with pytest.raises(json.JSONDecodeError):
            json.loads(json_str)

    def test_json_array_instead_of_object(self):
        """测试数组而不是对象"""
        json_str = "[0.5, 0.5]"
        try:
            result = json.loads(json_str)
            # JSON有效，但不是字典，应该在其他地方处理
            assert isinstance(result, list)
        except json.JSONDecodeError:
            pytest.fail("有效的JSON数组解析应该成功")


class TestErrorScenarios:
    """错误场景测试"""

    def test_all_invalid_tickers(self):
        """测试所有ticker都无效"""
        tickers = ["A@B@C", "D#E#F", "G$H$I"]
        all_valid, valid, invalid = validate_tickers(tickers)
        assert not all_valid
        assert len(valid) == 0
        assert len(invalid) == 3

    def test_weights_with_zero_total(self):
        """测试权重总和为0"""
        weights = {"AAPL": 0.0, "GOOGL": 0.0}
        is_valid, result, msg = validate_weights(weights)
        # 总和为0会导致除以0，应该验证失败
        assert not is_valid or msg is not None

    def test_very_large_number_of_tickers(self):
        """测试大量ticker"""
        tickers = [f"TICK{i:04d}" for i in range(1000)]
        all_valid, valid, invalid = validate_tickers(tickers)
        assert all_valid
        assert len(valid) == 1000
        assert len(invalid) == 0

    def test_mixed_case_tickers(self):
        """测试混合大小写ticker"""
        tickers = ["aapl", "GOOGL", "MsFt"]
        all_valid, valid, invalid = validate_tickers(tickers)
        # 应该接受所有字母组合
        assert all_valid

    def test_complex_weight_normalization(self):
        """测试复杂的权重归一化"""
        weights = {
            "AAPL": 0.1,
            "GOOGL": 0.2,
            "MSFT": 0.3,
            "TSLA": 0.25,
            "AMZN": 0.2,  # 总和=1.15
        }
        is_valid, result, msg = validate_weights(weights)
        assert is_valid
        assert result is not None
        # 验证归一化后权重之和为1.0
        assert abs(sum(result.values()) - 1.0) < 0.0001
        # 权重比例应该保持
        assert result["AAPL"] < result["GOOGL"] < result["MSFT"]


class TestErrorMessages:
    """错误消息测试"""

    def test_json_error_with_line_info(self):
        """测试JSON错误是否包含行号信息"""
        json_str = '{"AAPL": 0.5, "GOOGL": 0.5'
        try:
            json.loads(json_str)
        except json.JSONDecodeError as e:
            # 错误对象应该包含行号和列号
            assert hasattr(e, "lineno")
            assert hasattr(e, "colno")
            assert hasattr(e, "msg")

    def test_weight_validation_message_detail(self):
        """测试权重验证错误消息的详细程度"""
        weights = {"AAPL": "invalid"}
        is_valid, result, msg = validate_weights(weights)
        assert not is_valid
        assert msg is not None
        # 错误消息应该包含问题的ticker
        assert "AAPL" in msg or "权重" in msg


# 集成测试
class TestIntegration:
    """集成测试"""

    def test_full_validation_pipeline(self):
        """测试完整的验证流程"""
        # 模拟用户输入
        json_input = '{"AAPL": 0.5, "GOOGL": 0.5}'

        # 第1步：解析JSON
        try:
            weights = json.loads(json_input)
        except json.JSONDecodeError:
            pytest.fail("应该能解析有效的JSON")

        # 第2步：验证权重
        is_valid_w, normalized_w, msg_w = validate_weights(weights)
        assert is_valid_w

        # 第3步：验证ticker
        is_valid_t, valid_tickers, invalid_tickers = validate_tickers(list(normalized_w.keys()))
        assert is_valid_t
        assert len(invalid_tickers) == 0

    def test_invalid_input_early_exit(self):
        """测试无效输入是否在早期阶段被捕获"""
        # 无效的JSON应该在第1步被捕获
        json_input = '{"AAPL": 0.5, invalid}'

        with pytest.raises(json.JSONDecodeError):
            json.loads(json_input)

    def test_graceful_degradation(self):
        """测试部分失败是否优雅降级"""
        # 某些ticker无效，但其他有效
        json_input = '{"AAPL": 0.3, "INVALID@TICKER": 0.3, "GOOGL": 0.4}'
        weights = json.loads(json_input)

        # 权重应该有效
        is_valid_w, _, _ = validate_weights(weights)
        assert is_valid_w

        # 但ticker有无效的
        is_valid_t, valid_t, invalid_t = validate_tickers(list(weights.keys()))
        assert not is_valid_t
        assert len(valid_t) == 2
        assert len(invalid_t) == 1
