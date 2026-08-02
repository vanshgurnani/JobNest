from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_LEVELS = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}

_CONSOLE_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
_FILE_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"

_configured = False


def _level(name: str | None) -> int:
    return LOG_LEVELS.get((name or os.getenv("LOG_LEVEL", "INFO")).upper(), logging.INFO)


def _add_console_handler(logger: logging.Logger) -> None:
    if any(isinstance(h, logging.StreamHandler) and not isinstance(h, RotatingFileHandler) for h in logger.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
    logger.addHandler(handler)


def _add_file_handler(logger: logging.Logger) -> None:
    log_file = os.getenv("LOG_FILE")
    if not log_file:
        return
    path = Path(log_file).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if any(getattr(h, "baseFilename", None) == str(path) for h in logger.handlers):
        return
    handler = RotatingFileHandler(str(path), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter(_FILE_FORMAT))
    logger.addHandler(handler)


def setup_logging(level: str | None = None, *, file: str | None = None) -> None:
    """Configure console (+ optional rotating file) logging for the whole app.

    Safe to call multiple times; only configures once per process.
    """
    global _configured
    if file:
        os.environ.setdefault("LOG_FILE", file)
    if _configured:
        logging.getLogger().setLevel(_level(level))
        return

    root = logging.getLogger()
    root.setLevel(_level(level))
    _add_console_handler(root)
    _add_file_handler(root)

    # Route noisy third-party loggers to WARNING unless DEBUG is requested
    if root.level > logging.DEBUG:
        for noisy in ("httpx", "httpcore", "urllib3", "asyncio", "uvicorn.access"):
            logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True
