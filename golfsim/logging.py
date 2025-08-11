from __future__ import annotations

import logging
from typing import Optional


def init_logging(level: str = "INFO") -> None:
    """Initialize root logging configuration.

    Parameters
    ----------
    level: str
        Logging level name, e.g. "DEBUG", "INFO", "WARNING", "ERROR".
    """
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    # Configure a simple, structured-friendly format without emojis
    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Return a module-specific logger. Ensure logging is initialized upstream."""
    return logging.getLogger(name if name else __name__)


