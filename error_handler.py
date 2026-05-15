"""
error_handler.py
用户友好的错误处理和异常提示模块
提供统一的错误消息格式和解决建议
"""

import json
import traceback
from typing import Any, Callable, Optional

import numpy as np
import streamlit as st

from logging_config import get_logger

logger = get_logger(__name__)


# ═══════════════════════════════════════════════════════════════════
#  错误消息和解决建议字典
# ═══════════════════════════════════════════════════════════════════

ERROR_SUGGESTIONS = {
    "json_decode_error": {
        "title": "JSON Format Error",
        "causes": [
            "Missing comma or quote",
            "Mismatched braces or brackets",
            "Single quotes used instead of double quotes",
        ],
        "suggestions": [
            "Validate the JSON syntax before running analysis.",
            "Wrap all strings in double quotes.",
            "Remove trailing commas after the final item.",
        ],
    },
    "connection_error": {
        "title": "Connection Failed",
        "causes": [
            "Internet connection interrupted",
            "External API unavailable",
            "Local Ollama service is not running",
        ],
        "suggestions": [
            "Check the network connection.",
            "Refresh the page and retry.",
            "If using Ollama, confirm localhost:11434 is reachable.",
            "Try another LLM provider such as Claude or DeepSeek.",
        ],
    },
    "insufficient_data": {
        "title": "Insufficient Data",
        "causes": [
            "Too little history, usually less than one year",
            "Too many ticker downloads failed",
            "Invalid ticker symbol",
        ],
        "suggestions": [
            "Increase the historical period, preferably to at least two years.",
            "Check ticker symbols for typos.",
            "Confirm network access is working.",
            "Use more liquid assets such as ETFs where possible.",
        ],
    },
    "linear_algebra_error": {
        "title": "Covariance Matrix Calculation Failed",
        "causes": [
            "Assets are perfectly or highly correlated",
            "Data contains NaN or infinite values",
            "Sample size is too small, causing a singular matrix",
        ],
        "suggestions": [
            "Remove overly correlated assets.",
            "Increase the historical data period.",
            "Inspect data quality and outliers.",
            "Try reducing the number of portfolio assets.",
        ],
    },
    "weight_error": {
        "title": "Weight Configuration Error",
        "causes": [
            "One or more weights are not numeric",
            "Weights do not sum to 1.0",
            "One or more weights are negative",
        ],
        "suggestions": [
            "Use positive numeric weights.",
            "Keep total weights close to 100%; the app can normalize small differences.",
            'Use JSON format: {"AAPL": 0.3, "GOOGL": 0.7}',
        ],
    },
    "invalid_ticker": {
        "title": "Invalid Ticker Symbol",
        "causes": [
            "Ticker contains unsupported characters",
            "Security does not exist or was delisted",
            "Ticker is misspelled",
        ],
        "suggestions": [
            "Check spelling and use uppercase symbols.",
            "Use valid exchange symbols.",
            "For crypto, use Yahoo-style symbols such as BTC-USD.",
            "Examples: AAPL, GOOGL, MSFT, TSLA.",
        ],
    },
    "timeout_error": {
        "title": "Request Timed Out",
        "causes": [
            "Network is slow",
            "Request is too large",
            "External API responded slowly",
        ],
        "suggestions": [
            "Reduce the number of tickers.",
            "Shorten the historical period.",
            "Retry later.",
            "Check network speed.",
        ],
    },
    "value_error": {
        "title": "Invalid Parameter",
        "causes": [
            "Parameter is outside the supported range",
            "Data type does not match the expected format",
        ],
        "suggestions": [
            "Check input ranges.",
            "Confirm date formats are valid.",
            "Use a positive integer for Monte Carlo simulations.",
        ],
    },
}


# ═══════════════════════════════════════════════════════════════════
#  通用错误处理函数
# ═══════════════════════════════════════════════════════════════════


def show_error(
    error: Exception,
    title: str = "Error",
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
    st.markdown(f"**Error**: {error_message}")

    # 查找相关建议
    suggestions_dict = ERROR_SUGGESTIONS.get(error_type or "value_error", {})

    if suggestions_dict:
        with st.expander("📋 Possible Causes and Fixes"):
            if suggestions_dict.get("causes"):
                st.markdown("**Possible causes:**")
                for cause in suggestions_dict["causes"]:
                    st.markdown(f"- {cause}")

            if suggestions_dict.get("suggestions"):
                st.markdown("**Suggested fixes:**")
                for suggestion in suggestions_dict["suggestions"]:
                    st.markdown(f"- {suggestion}")

    # 显示技术细节（可选）
    if show_technical_details:
        with st.expander("🔧 Technical Details"):
            st.code(traceback.format_exc(), language="python")
            logger.error(
                "ui.error",
                error_type=type(error).__name__,
                error=error_message,
                exc_info=True,
            )


def show_warning(
    message: str,
    title: str = "Warning",
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
        st.markdown("**Suggestions:**")
        for suggestion in suggestions:
            st.markdown(f"- {suggestion}")


def show_success(message: str, title: str = "Success") -> None:
    """显示成功消息"""
    st.success(f"✓ {title}")
    st.markdown(message)


# ═══════════════════════════════════════════════════════════════════
#  特定错误处理函数
# ═══════════════════════════════════════════════════════════════════


def handle_json_error(error: json.JSONDecodeError, json_string: str) -> None:
    """处理JSON解析错误"""
    st.error("❌ JSON Format Error")
    st.markdown(f"**Location**: line {error.lineno}, column {error.colno}")
    st.markdown(f"**Message**: {error.msg}")

    # 显示错误位置附近的代码
    lines = json_string.split("\n")
    if error.lineno and error.lineno <= len(lines):
        st.markdown("**Nearby code:**")
        start = max(0, error.lineno - 3)
        end = min(len(lines), error.lineno + 2)
        for i in range(start, end):
            marker = ">>> " if i == error.lineno - 1 else "    "
            st.code(f"{marker}{lines[i]}")

    with st.expander("📋 Possible Causes and Fixes"):
        st.markdown("**Common JSON issues:**")
        st.markdown("""
        - Strings must use double quotes (`"`), not single quotes.
        - The final item must not have a trailing comma.
        - Braces and brackets must be balanced.
        - Numbers should not be quoted, for example `1` or `3.14`, not `"1"`.
        """)

    logger.warning("ui.json_parse_error", lineno=error.lineno, colno=error.colno)


def handle_weight_error(weights: dict, total: float) -> None:
    """处理权重验证错误"""
    st.warning("⚠️ Weight Configuration Issue")
    st.markdown(f"**Weight total**: {total:.2%} (expected 100%)")
    st.markdown("**Weights were automatically normalized to 100%.**")

    # 显示归一化后的权重
    normalized = {k: round(v / total * 100, 2) for k, v in weights.items()}
    st.markdown("**Normalized weights:**")
    for ticker, pct in sorted(normalized.items(), key=lambda x: x[1], reverse=True):
        st.markdown(f"- {ticker}: {pct}%")


def handle_data_loading_error(
    ticker: Optional[str] = None,
    reason: Optional[str] = None,
    failed_tickers: Optional[list[tuple[str, str]]] = None,
) -> None:
    """处理数据加载错误"""
    if ticker:
        st.warning(f"⚠️ Could not download data for {ticker}")
        if reason:
            st.markdown(f"**Reason**: {reason}")

    if failed_tickers:
        st.warning(f"⚠️ Could not download data for {len(failed_tickers)} ticker(s)")
        with st.expander("View Failure Details"):
            for tk, rsn in failed_tickers:
                st.markdown(f"- **{tk}**: {rsn}")
        st.info("Analysis will continue with successfully downloaded tickers.")


def handle_risk_calculation_error(error: Exception) -> None:
    """处理风险计算错误"""
    error_str = str(error).lower()

    if "singular" in error_str or "linalg" in error_str:
        show_error(
            error,
            title="Covariance Matrix Calculation Failed",
            error_type="linear_algebra_error",
        )
    elif "insufficient" in error_str or "data" in error_str:
        show_error(
            error,
            title="Insufficient Data",
            error_type="insufficient_data",
        )
    else:
        show_error(
            error,
            title="Risk Calculation Failed",
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
            return False, None, "Weight configuration is empty"

        # 检查所有值都是数字
        for ticker, weight in weights.items():
            if not isinstance(weight, (int, float)):
                return False, None, f"{ticker} weight is not numeric: {weight}"
            if weight < 0:
                return False, None, f"{ticker} weight is negative: {weight}"

        # 计算总和
        total = sum(weights.values())

        # 检查总和是否接近1.0
        if abs(total - 1.0) > 0.01:  # 允许1%的误差
            # 自动归一化
            normalized = {k: v / total for k, v in weights.items()}
            return (
                True,
                normalized,
                f"Weights automatically normalized (original total: {total:.2%})",
            )

        return True, weights, None

    except Exception as e:
        return False, None, f"Weight validation failed: {str(e)}"


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
    operation_name: str = "Operation",
    show_spinner: bool = True,
    spinner_text: str = "Processing...",
    **kwargs,
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
            title="Connection Failed",
            error_type="connection_error",
        )
        logger.error(f"{operation_name}_connection_error", exc_info=True)
        return None

    except ValueError as e:
        show_error(
            e,
            title="Invalid Parameter",
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
            title="Request Timed Out",
            error_type="timeout_error",
        )
        logger.error(f"{operation_name}_timeout", exc_info=True)
        return None

    except Exception as e:
        show_error(
            e,
            title=f"{operation_name} Failed",
        )
        logger.error(f"{operation_name}_error", exc_info=True)
        return None
