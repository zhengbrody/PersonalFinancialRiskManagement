"""
结构化日志配置
使用structlog提供JSON格式的日志
"""
import logging
import logging.handlers
import os
import structlog
from pathlib import Path

# 日志目录
LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)


def configure_standard_logging():
    """配置标准库logging作为structlog的后端"""

    # 创建根logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    # 清除现有handlers
    root_logger.handlers.clear()

    # Console handler（开发时使用）
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler（JSON格式，自动滚动）
    file_handler = logging.handlers.RotatingFileHandler(
        LOG_DIR / "app.log",
        maxBytes=10 * 1024 * 1024,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setLevel(logging.INFO)

    # JSON formatter（使用python-json-logger）
    from pythonjsonlogger import jsonlogger
    json_formatter = jsonlogger.JsonFormatter(
        '%(asctime)s %(name)s %(levelname)s %(message)s'
    )
    file_handler.setFormatter(json_formatter)
    root_logger.addHandler(file_handler)


def configure_structlog():
    """配置structlog处理器链"""

    structlog.configure(
        processors=[
            # 添加logger名称
            structlog.stdlib.add_log_level,
            # 添加时间戳
            structlog.processors.TimeStamper(fmt="iso"),
            # 添加调用位置（文件:行号）
            structlog.processors.CallsiteParameterAdder(
                parameters=[
                    structlog.processors.CallsiteParameter.FILENAME,
                    structlog.processors.CallsiteParameter.LINENO,
                ]
            ),
            # 格式化异常
            structlog.processors.format_exc_info,
            # 使用JSON渲染
            structlog.processors.JSONRenderer()
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def setup_logging():
    """一键设置日志系统"""
    configure_standard_logging()
    configure_structlog()


def get_logger(name: str = None):
    """获取structlog logger"""
    return structlog.get_logger(name)
