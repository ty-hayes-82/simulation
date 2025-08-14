from __future__ import annotations

import logging
from typing import Optional


def init_logging(level: str = "INFO", log_file: Optional[str] = None) -> None:
    """Initialize root logging configuration.

    Parameters
    ----------
    level: str
        Logging level name, e.g. "DEBUG", "INFO", "WARNING", "ERROR".
    log_file: Optional[str]
        If provided, logs will be written to this file in addition to the console.
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    
    # Create handlers: one for console, one for file if specified
    handlers = [logging.StreamHandler()]
    if log_file:
        file_handler = logging.FileHandler(log_file, mode='w')
        file_handler.setLevel(numeric_level)
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        file_handler.setFormatter(formatter)
        handlers.append(file_handler)

    # Configure a simple, structured-friendly format without emojis
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=handlers,
    )


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a module-specific logger. Ensure logging is initialized upstream."""
    return logging.getLogger(name if name else __name__)


