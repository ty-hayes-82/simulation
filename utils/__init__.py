"""Utility package for shared helpers used by CLI scripts and libraries."""

from .encoding import setup_encoding  # re-export for convenience
from .cli import add_log_level_argument, add_course_dir_argument, parse_csv_list
from .paths import get_repo_root, resolve_course_dir
from .io import write_json, read_json, write_table_csv

__all__ = [
    "setup_encoding",
    "add_log_level_argument",
    "add_course_dir_argument",
    "parse_csv_list",
    "get_repo_root",
    "resolve_course_dir",
    "write_json",
    "read_json",
    "write_table_csv",
]


