from __future__ import annotations

from typing import Tuple


def parse_hhmm(hhmm: str) -> Tuple[int, int]:
    """Parse a HH:MM string into (hour, minute). Returns (0, 0) on error."""
    try:
        parts = hhmm.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        return hour, minute
    except Exception:
        return 0, 0


def seconds_since_7am(hhmm: str) -> int:
    """Convert a HH:MM string to seconds since 7 AM baseline."""
    hour, minute = parse_hhmm(hhmm)
    return max(0, (hour - 7) * 3600 + minute * 60)


def format_time_from_baseline(seconds: int) -> str:
    """Format seconds since 7 AM into HH:MM string."""
    total = max(0, int(seconds))
    hh = 7 + (total // 3600)
    mm = (total % 3600) // 60
    return f"{hh:02d}:{mm:02d}"


