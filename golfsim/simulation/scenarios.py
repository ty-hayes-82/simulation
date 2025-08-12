from __future__ import annotations

from typing import Dict, List

from ..config.loaders import load_tee_times_config
from ..logging import get_logger
from ..utils.time import seconds_since_7am


logger = get_logger(__name__)


def build_groups_interval(count: int, first_tee_s: int, interval_min: float, default_group_size: int = 4) -> List[Dict]:
    groups: List[Dict] = []
    for i in range(count):
        groups.append(
            {
                "group_id": i + 1,
                "tee_time_s": int(first_tee_s + i * int(interval_min * 60)),
                "num_golfers": default_group_size,
            }
        )
    return groups


def build_groups_from_scenario(course_dir: str, scenario_key: str, default_group_size: int = 4) -> List[Dict]:
    """Build golfer groups using a named scenario from tee_times_config.json.

    - Interprets `hourly_golfers` counts as number of golfers in that hour
    - Creates groups of size `default_group_size` (last group may be smaller)
    - Distributes groups evenly across each hour block
    """
    if not scenario_key or scenario_key.lower() in {"none", "manual"}:
        return []

    try:
        config = load_tee_times_config(course_dir)
    except FileNotFoundError:
        logger.warning("tee_times_config.json not found; falling back to manual args")
        return []

    scenarios = config.scenarios or {}
    if scenario_key not in scenarios:
        logger.warning("tee-scenario '%s' not found; falling back to manual args", scenario_key)
        return []

    scenario = scenarios[scenario_key]
    hourly: Dict[str, int] = scenario.get("hourly_golfers", {})
    if not hourly:
        logger.warning("tee-scenario '%s' missing 'hourly_golfers'; falling back to manual args", scenario_key)
        return []

    groups: List[Dict] = []
    group_id = 1

    # Sort hour keys like "07:00", "08:00" ...
    for hour_label, golfers in sorted(hourly.items(), key=lambda kv: seconds_since_7am(kv[0])):
        golfers_int = int(golfers or 0)
        if golfers_int <= 0:
            continue

        # Number of groups for this hour
        groups_this_hour = (golfers_int + default_group_size - 1) // default_group_size
        if groups_this_hour <= 0:
            continue

        base_s = seconds_since_7am(hour_label)
        # Evenly distribute within the hour
        interval_seconds = int(3600 / groups_this_hour)

        remaining_golfers = golfers_int
        for i in range(groups_this_hour):
            size = min(default_group_size, remaining_golfers)
            if size <= 0:
                break
            tee_time_s = base_s + i * interval_seconds
            groups.append(
                {
                    "group_id": group_id,
                    "tee_time_s": int(tee_time_s),
                    "num_golfers": int(size),
                }
            )
            group_id += 1
            remaining_golfers -= size

    # Renumber group ids to be consecutive
    for i, g in enumerate(groups, 1):
        g["group_id"] = i

    return groups


