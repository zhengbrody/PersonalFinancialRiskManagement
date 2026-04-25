"""
测试日志系统
"""

import json
import logging
from pathlib import Path

import pytest

from logging_config import get_logger, setup_logging


@pytest.fixture(scope="module")
def setup_test_logging():
    """在测试开始时设置日志"""
    setup_logging()
    yield
    # 测试后清理不需要（日志文件可以保留）


def test_logging_setup(setup_test_logging):
    """测试日志配置成功"""
    logger = get_logger("test")

    # 应该不抛异常
    logger.info("test_message", key="value")


def test_logger_creation():
    """测试可以创建多个logger"""
    logger1 = get_logger("test.module1")
    logger2 = get_logger("test.module2")

    logger1.info("message_from_module1", module="module1")
    logger2.info("message_from_module2", module="module2")


def test_log_levels(setup_test_logging):
    """测试不同日志级别"""
    logger = get_logger("test.levels")

    logger.debug("debug_message", level="debug")
    logger.info("info_message", level="info")
    logger.warning("warning_message", level="warning")
    logger.error("error_message", level="error")


def test_log_with_context(setup_test_logging):
    """测试日志包含上下文信息"""
    logger = get_logger("test.context")

    logger.info(
        "test_event", ticker="AAPL", price=150.0, volume=1000000, metadata={"source": "test"}
    )


def test_json_log_format(setup_test_logging):
    """测试日志是JSON格式"""
    logger = get_logger("test.json")

    logger.info("test_event", ticker="AAPL", price=150.0)

    # 读取日志文件最后一行
    log_file = Path("logs/app.log")
    assert log_file.exists(), "Log file should exist"

    with open(log_file, "r") as f:
        lines = f.readlines()
        if len(lines) > 0:
            last_line = lines[-1]

            # 验证是有效的JSON
            log_entry = json.loads(last_line)
            assert "message" in log_entry or "event" in log_entry


def test_log_rotation_config():
    """测试日志滚动配置"""
    # 验证配置了RotatingFileHandler
    root_logger = logging.getLogger()
    handlers = [
        h for h in root_logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]

    assert len(handlers) > 0, "Should have at least one RotatingFileHandler"
    assert handlers[0].maxBytes == 10 * 1024 * 1024, "Max bytes should be 10MB"
    assert handlers[0].backupCount == 5, "Backup count should be 5"


def test_log_directory_creation():
    """测试日志目录自动创建"""
    log_dir = Path("logs")
    assert log_dir.exists(), "Log directory should be created automatically"
    assert log_dir.is_dir(), "logs should be a directory"


def test_exception_logging(setup_test_logging):
    """测试异常日志记录"""
    logger = get_logger("test.exception")

    try:
        raise ValueError("Test exception for logging")
    except ValueError as e:
        logger.error("exception_occurred", error=str(e), exc_info=True)


def test_performance_metrics(setup_test_logging):
    """测试性能指标日志"""
    logger = get_logger("test.performance")

    import time

    start = time.time()
    time.sleep(0.01)  # 模拟操作
    duration_ms = (time.time() - start) * 1000

    logger.info("operation.complete", operation="test_operation", duration_ms=round(duration_ms, 2))


def test_multiple_fields(setup_test_logging):
    """测试多字段日志"""
    logger = get_logger("test.multifield")

    logger.info(
        "data.fetch.complete",
        ticker="NVDA",
        rows=500,
        start_date="2023-01-01",
        end_date="2024-12-31",
        cached=True,
        duration_ms=123.45,
    )
