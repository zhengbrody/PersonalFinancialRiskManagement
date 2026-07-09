"""
Tests for the logging system
"""

import json
import logging
from pathlib import Path

import pytest

from logging_config import get_logger, setup_logging


@pytest.fixture(scope="module")
def setup_test_logging():
    """Set up logging at the start of the tests"""
    setup_logging()
    yield
    # No cleanup needed after tests (the log file can be kept)


def test_logging_setup(setup_test_logging):
    """Test that logging is configured successfully"""
    logger = get_logger("test")

    # Should not raise
    logger.info("test_message", key="value")


def test_logger_creation():
    """Test that multiple loggers can be created"""
    logger1 = get_logger("test.module1")
    logger2 = get_logger("test.module2")

    logger1.info("message_from_module1", module="module1")
    logger2.info("message_from_module2", module="module2")


def test_log_levels(setup_test_logging):
    """Test the different log levels"""
    logger = get_logger("test.levels")

    logger.debug("debug_message", level="debug")
    logger.info("info_message", level="info")
    logger.warning("warning_message", level="warning")
    logger.error("error_message", level="error")


def test_log_with_context(setup_test_logging):
    """Test that logs include context information"""
    logger = get_logger("test.context")

    logger.info(
        "test_event", ticker="AAPL", price=150.0, volume=1000000, metadata={"source": "test"}
    )


def test_json_log_format(setup_test_logging):
    """Test that logs are in JSON format"""
    logger = get_logger("test.json")

    logger.info("test_event", ticker="AAPL", price=150.0)

    # Read the last line of the log file
    log_file = Path("logs/app.log")
    assert log_file.exists(), "Log file should exist"

    with open(log_file, "r") as f:
        lines = f.readlines()
        if len(lines) > 0:
            last_line = lines[-1]

            # Verify it is valid JSON
            log_entry = json.loads(last_line)
            assert "message" in log_entry or "event" in log_entry


def test_log_rotation_config():
    """Test the log rotation configuration"""
    # Verify a RotatingFileHandler is configured
    root_logger = logging.getLogger()
    handlers = [
        h for h in root_logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]

    assert len(handlers) > 0, "Should have at least one RotatingFileHandler"
    assert handlers[0].maxBytes == 10 * 1024 * 1024, "Max bytes should be 10MB"
    assert handlers[0].backupCount == 5, "Backup count should be 5"


def test_log_directory_creation():
    """Test that the log directory is created automatically"""
    log_dir = Path("logs")
    assert log_dir.exists(), "Log directory should be created automatically"
    assert log_dir.is_dir(), "logs should be a directory"


def test_exception_logging(setup_test_logging):
    """Test exception logging"""
    logger = get_logger("test.exception")

    try:
        raise ValueError("Test exception for logging")
    except ValueError as e:
        logger.error("exception_occurred", error=str(e), exc_info=True)


def test_performance_metrics(setup_test_logging):
    """Test performance-metrics logging"""
    logger = get_logger("test.performance")

    import time

    start = time.time()
    time.sleep(0.01)  # Simulate an operation
    duration_ms = (time.time() - start) * 1000

    logger.info("operation.complete", operation="test_operation", duration_ms=round(duration_ms, 2))


def test_multiple_fields(setup_test_logging):
    """Test multi-field logging"""
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
