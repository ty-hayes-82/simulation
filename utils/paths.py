from __future__ import annotations

from pathlib import Path


def get_repo_root(start: str | Path | None = None) -> Path:
    """Return the repository root by searching for a pyproject.toml upward.

    If not found, fall back to the parent of this file's parent directory.
    """
    current = Path(start) if start else Path(__file__).resolve()
    for path in [current, *current.parents]:
        candidate = path if path.is_dir() else path.parent
        if (candidate / "pyproject.toml").exists():
            return candidate
    # Fallback: utils/.. (project root)
    return Path(__file__).resolve().parents[1]


def resolve_course_dir(course_dir: str | Path) -> Path:
    """Resolve and validate a course directory path."""
    p = Path(course_dir)
    if not p.exists():
        raise FileNotFoundError(f"Course directory not found: {p}")
    return p



