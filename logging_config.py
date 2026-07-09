"""
Structured logging configuration
Uses structlog to provide JSON-formatted logs
"""

import logging
import logging.handlers
from pathlib import Path
from typing import Optional

import structlog

# Log directory
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


def configure_standard_logging():
    """Configure the standard library logging as structlog's backend"""

    # Create the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # Clear existing handlers
    root_logger.handlers.clear()

    # Console handler (used during development)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler (JSON format, auto-rotating)
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "app.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"  # 10MB
    )
    file_handler.setLevel(logging.INFO)

    # JSON formatter (uses python-json-logger)
    from pythonjsonlogger import jsonlogger

    json_formatter = jsonlogger.JsonFormatter("%(asctime)s %(name)s %(levelname)s %(message)s")
    file_handler.setFormatter(json_formatter)
    root_logger.addHandler(file_handler)


def configure_structlog():
    """Configure the structlog processor chain"""

    structlog.configure(
        processors=[
            # Add the logger name
            structlog.stdlib.add_log_level,
            # Add a timestamp
            structlog.processors.TimeStamper(fmt="iso"),
            # Add the call site (file:line number)
            structlog.processors.CallsiteParameterAdder(
                parameters=[
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.LINENO,
                ]
            ),
            # Format exceptions
            structlog.processors.format_exc_info,
            # Render as JSON
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def setup_logging():
    """Set up the logging system in one call"""
    configure_standard_logging()
    configure_structlog()


def get_logger(name: Optional[str] = None):
    """Get a structlog logger"""
    return structlog.get_logger(name)
