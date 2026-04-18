"""
error_handler.py
用户友好的错误处理和异常提示模块
提供统一的错误消息格式和解决建议
"""

import json
import traceback
from typing import Optional, Callable, Any
import streamlit as st
import numpy as np
from logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════
#  错误消息和解决建议字典
# ═══════════════════════════════════════════════════════════════════

ERROR_SUGGESTIONS = {
    "json_decode_error": {
        "title": "JSON格式错误",
        "causes": [
            "缺少逗号或引号",
            "大括号不匹配",
            "使用了单引号而不是双引号",
        ],
        "suggestions": [
            "检查JSON格式（使用在线JSON验证工具）",
            "确保所有字符串用双引号括起来",
            "确保最后一个元素后没有逗号",
        ],
    },
    "connection_error": {
        "title": "网络连接失败",
        "causes": [
            "互联网连接中断",
            "API服务不可用",
            "Ollama本地服务未运行",
        ],
        "suggestions": [
            "检查网络连接",
            "尝试刷新页面重试",
            "如使用Ollama，请确保localhost:11434可访问",
            "尝试切换到其他LLM提供商（Claude/DeepSeek）",
        ],
    },
    "insufficient_data": {
        "title": "数据不足",
        "causes": [
            "样本量太少（少于1年数据）",
            "太多ticker数据获取失败",
            "股票代码无效",
        ],
        "suggestions": [
            "增加历史数据周期（建议≥2年）",
            "检查股票代码是否正确",
            "确保网络连接正常",
            "尝试使用更流动性的资产（如ETF）",
        ],
    },
    "linear_algebra_error": {
        "title": "协方差矩阵计算失败",
        "causes": [
            "资产完全相关（高度相关）",
            "数据中存在NaN或无穷大值",
            "样本量不足导致矩阵奇异",
        ],
        "suggestions": [
            "移除过度相关的资产对",
            "增加历史数据周期",
            "检查数据质量（可能存在异常值）",
            "尝试减少portfolio中的资产数量",
        ],
    },
    "weight_error": {
        "title": "权重配置错误",
        "causes": [
            "权重不是数字",
            "权重总和不等于1.0",
            "存在负权重",
        ],
        "suggestions": [
            "确保所有权重是正数",
            "权重总和应接近100%（会自动归一化）",
            "使用JSON格式: {\"AAPL\": 0.3, \"GOOGL\": 0.7}",
        ],
    },
    "invalid_ticker": {
        "title": "无效的股票代码",
        "causes": [
            "代码格式错误（包含特殊字符）",
            "股票不存在或已退市",
            "拼写错误",
        ],
        "suggestions": [
            "检查代码拼写（通常为大写字母）",
            "确保使用有效的交易所代码（AAPL不是aapl）",
            "对于加密货币，使用 BTC-USD 格式",
            "参考美股列表: AAPL, GOOGL, MSFT, TSLA等",
        ],
    },
    "timeout_error": {
        "title": "请求超时",
        "causes": [
            "网络速度慢",
            "下载的数据太多",
            "API响应缓慢",
        ],
        "suggestions": [
            "减少ticker数量",
            "减少历史数据周期",
            "稍后重试",
            "检查网络速度",
        ],
    },
    "value_error": {
        "title": "参数值错误",
        "causes": [
            "参数超出合理范围",
            "数据类型不匹配",
        ],
        "suggestions": [
            "检查输入参数范围",
            "确保日期格式正确",
            "确保蒙特卡洛模拟次数为正整数",
        ],
    },
}


# ═══════════════════════════════════════════════════════════════════
#  通用错误处理函数
# ═══════════════════════════════════════════════════════════════════

def show_error(
    error: Exception,
    title: str = "发生错误",
    error_type: Optional[str] = None,
    show_technical_details: bool = True,
) -> None:
    """
    显示用户友好的错误信息

    Args:
        error: 异常对象
        title: 错误标题
        error_type: 错误类型（用于查找建议）
        show_technical_details: 是否显示技术细节
    """
    st.error(f"❌ {title}")

    # 获取错误消息
    error_message = str(error)
    st.markdown(f"**错误**: {error_message}")

    # 查找相关建议
    suggestions_dict = ERROR_SUGGESTIONS.get(error_type or "value_error", {})

    if suggestions_dict:
        with st.expander("📋 可能的原因和解决方案"):
            if suggestions_dict.get("causes"):
                st.markdown("**可能的原因：**")
                for cause in suggestions_dict["causes"]:
                    st.markdown(f"- {cause}")

            if suggestions_dict.get("suggestions"):
                st.markdown("**建议的解决方案：**")
                for suggestion in suggestions_dict["suggestions"]:
                    st.markdown(f"- {suggestion}")

    # 显示技术细节（可选）
    if show_technical_details:
        with st.expander("🔧 技术细节（开发者）"):
            st.code(traceback.format_exc(), language="python")
            logger.error(
                "ui.error",
                error_type=type(error).__name__,
                error=error_message,
                exc_info=True,
            )


def show_warning(
    message: str,
    title: str = "警告",
    suggestions: Optional[list[str]] = None,
) -> None:
    """
    显示警告信息和建议

    Args:
        message: 警告消息
        title: 警告标题
        suggestions: 解决建议列表
    """
    st.warning(f"⚠️ {title}")
    st.markdown(message)

    if suggestions:
        st.markdown("**建议：**")
        for suggestion in suggestions:
            st.markdown(f"- {suggestion}")


def show_success(message: str, title: str = "成功") -> None:
    """显示成功消息"""
    st.success(f"✓ {title}")
    st.markdown(message)


# ═══════════════════════════════════════════════════════════════════
#  特定错误处理函数
# ═══════════════════════════════════════════════════════════════════

def handle_json_error(error: json.JSONDecodeError, json_string: str) -> None:
    """处理JSON解析错误"""
    st.error("❌ JSON格式错误")
    st.markdown(f"**错误位置**: 第 {error.lineno} 行，第 {error.colno} 列")
    st.markdown(f"**错误信息**: {error.msg}")

    # 显示错误位置附近的代码
    lines = json_string.split('\n')
    if error.lineno and error.lineno <= len(lines):
        st.markdown("**错误附近的代码:**")
        start = max(0, error.lineno - 3)
        end = min(len(lines), error.lineno + 2)
        for i in range(start, end):
            marker = ">>> " if i == error.lineno - 1 else "    "
            st.code(f"{marker}{lines[i]}")

    with st.expander("📋 可能的原因和解决方案"):
        st.markdown("**常见JSON错误：**")
        st.markdown("""
        - 字符串必须用双引号（"），不能用单引号（'）
        - 最后一个元素后面不能有逗号
        - 大括号和方括号必须成对出现
        - 数字不能有引号（数字直接写，如 1, 3.14，不是 "1", "3.14"）
        """)

    logger.warning("ui.json_parse_error", lineno=error.lineno, colno=error.colno)


def handle_weight_error(weights: dict, total: float) -> None:
    """处理权重验证错误"""
    st.warning("⚠️ 权重配置问题")
    st.markdown(f"**权重总和**: {total:.2%} (应为100%)")
    st.markdown("**已自动归一化为100%**")

    # 显示归一化后的权重
    normalized = {k: round(v/total * 100, 2) for k, v in weights.items()}
    st.markdown("**归一化后的权重:**")
    for ticker, pct in sorted(normalized.items(), key=lambda x: x[1], reverse=True):
        st.markdown(f"- {ticker}: {pct}%")


def handle_data_loading_error(
    ticker: Optional[str] = None,
    reason: Optional[str] = None,
    failed_tickers: Optional[list[tuple[str, str]]] = None,
) -> None:
    """处理数据加载错误"""
    if ticker:
        st.warning(f"⚠️ 无法下载 {ticker} 的数据")
        if reason:
            st.markdown(f"**原因**: {reason}")

    if failed_tickers:
        st.warning(f"⚠️ 无法下载 {len(failed_tickers)} 个ticker的数据")
        with st.expander("查看失败详情"):
            for tk, rsn in failed_tickers:
                st.markdown(f"- **{tk}**: {rsn}")
        st.info("💡 分析将使用成功下载的ticker继续")


def handle_risk_calculation_error(error: Exception) -> None:
    """处理风险计算错误"""
    error_str = str(error).lower()

    if "singular" in error_str or "linalg" in error_str:
        show_error(
            error,
            title="协方差矩阵计算失败",
            error_type="linear_algebra_error",
        )
    elif "insufficient" in error_str or "data" in error_str:
        show_error(
            error,
            title="数据不足",
            error_type="insufficient_data",
        )
    else:
        show_error(
            error,
            title="风险计算失败",
        )


def validate_weights(weights: dict) -> tuple[bool, Optional[dict], Optional[str]]:
    """
    验证权重配置

    Returns:
        (is_valid, normalized_weights, error_message)
    """
    try:
        # 检查是否为空
        if not weights:
            return False, None, "权重配置为空"

        # 检查所有值都是数字
        for ticker, weight in weights.items():
            if not isinstance(weight, (int, float)):
                return False, None, f"{ticker} 的权重不是数字: {weight}"
            if weight < 0:
                return False, None, f"{ticker} 的权重为负数: {weight}"

        # 计算总和
        total = sum(weights.values())

        # 检查总和是否接近1.0
        if abs(total - 1.0) > 0.01:  # 允许1%的误差
            # 自动归一化
            normalized = {k: v / total for k, v in weights.items()}
            return True, normalized, f"权重已自动归一化（原总和: {total:.2%}）"

        return True, weights, None

    except Exception as e:
        return False, None, f"权重验证失败: {str(e)}"


def validate_tickers(tickers: list[str]) -> tuple[bool, list[str], list[str]]:
    """
    验证ticker格式

    Returns:
        (all_valid, valid_tickers, invalid_tickers)
    """
    valid = []
    invalid = []

    for ticker in tickers:
        # 允许的字符：字母、数字、"-"（对于crypto）、"="（对于某些特殊ticker）
        if all(c.isalnum() or c in "-=" for c in ticker):
            valid.append(ticker)
        else:
            invalid.append(ticker)

    return len(invalid) == 0, valid, invalid


def safe_operation(
    func: Callable,
    *args,
    operation_name: str = "操作",
    show_spinner: bool = True,
    spinner_text: str = "处理中...",
    **kwargs
) -> Optional[Any]:
    """
    安全执行操作，自动处理异常

    Args:
        func: 要执行的函数
        operation_name: 操作名称（用于错误消息）
        show_spinner: 是否显示spinner
        spinner_text: spinner文本

    Returns:
        函数的返回值，或None（如果出错）
    """
    try:
        if show_spinner:
            with st.spinner(spinner_text):
                return func(*args, **kwargs)
        else:
            return func(*args, **kwargs)

    except json.JSONDecodeError as e:
        handle_json_error(e, kwargs.get("json_string", ""))
        logger.error(f"{operation_name}_json_error", exc_info=True)
        return None

    except ConnectionError as e:
        show_error(
            e,
            title="网络连接失败",
            error_type="connection_error",
        )
        logger.error(f"{operation_name}_connection_error", exc_info=True)
        return None

    except ValueError as e:
        show_error(
            e,
            title="参数值错误",
            error_type="value_error",
        )
        logger.error(f"{operation_name}_value_error", exc_info=True)
        return None

    except np.linalg.LinAlgError as e:
        handle_risk_calculation_error(e)
        logger.error(f"{operation_name}_linalg_error", exc_info=True)
        return None

    except TimeoutError as e:
        show_error(
            e,
            title="请求超时",
            error_type="timeout_error",
        )
        logger.error(f"{operation_name}_timeout", exc_info=True)
        return None

    except Exception as e:
        show_error(
            e,
            title=f"{operation_name}失败",
        )
        logger.error(f"{operation_name}_error", exc_info=True)
        return None
