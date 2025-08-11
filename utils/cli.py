from __future__ import annotations

from argparse import ArgumentParser
from typing import List


def add_log_level_argument(parser: ArgumentParser) -> None:
    """Add a standard --log-level flag to an ArgumentParser."""
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level (default: INFO)",
    )


def add_course_dir_argument(
    parser: ArgumentParser, default: str = "courses/pinetree_country_club"
) -> None:
    """Add a standard --course-dir flag to an ArgumentParser."""
    parser.add_argument(
        "--course-dir",
        default=default,
        help="Course directory containing data files",
    )


def parse_csv_list(value: str | None) -> List[str]:
    """Parse a comma-separated list string into a list of trimmed items."""
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]



