from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from structlog.types import Processor

_configured = False

LOG_DIR = Path("logs")
TRADING_LOG_FILE = LOG_DIR / "trading.log"
TRADING_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
TRADING_LOG_BACKUP_COUNT = 30


def configure_logging(
    level: str = "INFO",
    json_format: bool = False,
    log_file: str | None = None,
) -> None:
    global _configured
    if _configured:
        return

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    if json_format:
        renderer: Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty())

    json_renderer: Processor = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    console_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    json_formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            json_renderer,
        ],
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(console_formatter)
        root_logger.addHandler(file_handler)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    trading_handler = RotatingFileHandler(
        TRADING_LOG_FILE,
        maxBytes=TRADING_LOG_MAX_BYTES,
        backupCount=TRADING_LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    trading_handler.setFormatter(json_formatter)
    trading_handler.setLevel(logging.INFO)

    trading_logger = logging.getLogger("trading")
    trading_logger.addHandler(trading_handler)
    trading_logger.setLevel(logging.DEBUG)
    trading_logger.propagate = True

    _configured = True


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    if not _configured:
        configure_logging()
    return structlog.get_logger(name)


def get_trading_logger() -> structlog.stdlib.BoundLogger:
    if not _configured:
        configure_logging()
    return structlog.get_logger("trading")


def bind_context(**kwargs: object) -> None:
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()
