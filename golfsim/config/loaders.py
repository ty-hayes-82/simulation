from __future__ import annotations

import json
from pathlib import Path
from typing import Union, List, Dict

from .models import SimulationConfig, TeeTimesConfig
from ..logging import get_logger

logger = get_logger(__name__)


def load_simulation_config(course_dir: Union[str, Path]) -> SimulationConfig:
    course_path = Path(course_dir)
    candidates = [
        course_path / "config" / "simulation_config.json",
        course_path / "simulation_config.json",
    ]
    for path in candidates:
        if path.exists():
            data = json.loads(path.read_text())
            return SimulationConfig.from_dict(data)
    raise FileNotFoundError(f"simulation_config.json not found in {course_dir}")


def load_tee_times_config(course_dir: Union[str, Path]) -> TeeTimesConfig:
    course_path = Path(course_dir)
    candidates = [
        course_path / "config" / "tee_times_config.json",
        course_path / "tee_times_config.json",
    ]
    for path in candidates:
        if path.exists():
            data = json.loads(path.read_text())
            return TeeTimesConfig.from_dict(data)
    raise FileNotFoundError(f"tee_times_config.json not found in {course_dir}")


def parse_hhmm_to_seconds_since_7am(hhmm: str) -> int:
    """Parse HH:MM format to seconds since 7 AM."""
    try:
        hh, mm = hhmm.split(":")
        return (int(hh) - 7) * 3600 + int(mm) * 60
    except Exception:
        return 0


def parse_tee_time_to_seconds_since_7am(tee_time: str) -> int:
    """Parse tee time strings like '7:45 AM', '1:06 PM' to seconds since 7 AM."""
    try:
        # Handle AM/PM format
        if 'PM' in tee_time.upper():
            time_part = tee_time.upper().replace('PM', '').strip()
            hh, mm = time_part.split(':')
            hour = int(hh)
            if hour != 12:  # 12 PM stays 12, 1 PM becomes 13, etc.
                hour += 12
            return (hour - 7) * 3600 + int(mm) * 60
        elif 'AM' in tee_time.upper():
            time_part = tee_time.upper().replace('AM', '').strip()
            hh, mm = time_part.split(':')
            hour = int(hh)
            if hour == 12:  # 12 AM becomes 0
                hour = 0
            return (hour - 7) * 3600 + int(mm) * 60
        else:
            # Fallback to HH:MM format
            return parse_hhmm_to_seconds_since_7am(tee_time)
    except Exception:
        return 0


def build_groups_from_scenario(course_dir: str, scenario_key: str, default_group_size: int = 4) -> List[Dict]:
    """Build golfer groups using a named scenario from tee_times_config.json.

    Supports two formats:
    1. Legacy: `hourly_golfers` counts as number of golfers in that hour
    2. New: `detailed_tee_times` with exact tee times and golfer counts
    
    For detailed tee times, creates groups exactly as specified.
    For hourly distribution, creates groups of size `default_group_size` (last group may be smaller).
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
        # Attempt alias resolution from tee_times_config.json top-level "aliases"
        try:
            course_path = Path(course_dir)
            candidates = [
                course_path / "config" / "tee_times_config.json",
                course_path / "tee_times_config.json",
            ]
            alias_target = None
            for p in candidates:
                if p.exists():
                    raw = json.loads(p.read_text())
                    aliases = raw.get("aliases", {}) if isinstance(raw, dict) else {}
                    if isinstance(aliases, dict):
                        alias_target = aliases.get(scenario_key)
                    break
            if alias_target and alias_target in scenarios:
                logger.info("Resolved tee-scenario alias '%s' -> '%s'", scenario_key, alias_target)
                scenario_key = alias_target
            else:
                logger.warning("tee-scenario '%s' not found; falling back to manual args", scenario_key)
                return []
        except Exception:
            logger.warning("tee-scenario '%s' not found; falling back to manual args", scenario_key)
            return []

    scenario = scenarios[scenario_key]
    
    # Check for detailed tee times first (new format)
    detailed_tee_times = scenario.get("detailed_tee_times", [])
    if detailed_tee_times:
        logger.info("Using detailed tee times from scenario '%s'", scenario_key)
        groups: List[Dict] = []
        group_id = 1
        
        for tee_time_entry in detailed_tee_times:
            tee_time = tee_time_entry.get("tee_time", "")
            num_golfers = int(tee_time_entry.get("number_of_golfers", 0))
            
            if not tee_time or num_golfers <= 0:
                continue
                
            tee_time_s = parse_tee_time_to_seconds_since_7am(tee_time)
            if tee_time_s < 0:  # Skip times before 7 AM
                continue
                
            groups.append({
                "group_id": group_id,
                "tee_time_s": tee_time_s,
                "num_golfers": num_golfers,
            })
            group_id += 1
        
        return groups
    
    # Fallback to legacy hourly_golfers format
    hourly: Dict[str, int] = scenario.get("hourly_golfers", {})
    if not hourly:
        logger.warning("tee-scenario '%s' missing both 'detailed_tee_times' and 'hourly_golfers'; falling back to manual args", scenario_key)
        return []

    logger.info("Using hourly golfer distribution from scenario '%s'", scenario_key)
    groups: List[Dict] = []
    group_id = 1

    # Sort hour keys like "07:00", "08:00" ...
    for hour_label, golfers in sorted(hourly.items(), key=lambda kv: parse_hhmm_to_seconds_since_7am(kv[0])):
        golfers_int = int(golfers or 0)
        if golfers_int <= 0:
            continue

        # Number of groups for this hour
        groups_this_hour = (golfers_int + default_group_size - 1) // default_group_size
        if groups_this_hour <= 0:
            continue

        base_s = parse_hhmm_to_seconds_since_7am(hour_label)
        # Evenly distribute within the hour
        interval_seconds = int(3600 / groups_this_hour)

        remaining_golfers = golfers_int
        for i in range(groups_this_hour):
            # Assign group size. Last group may be smaller
            size = min(default_group_size, remaining_golfers)
            if size <= 0:
                break
            tee_time_s = base_s + i * interval_seconds
            groups.append({
                "group_id": group_id,
                "tee_time_s": int(tee_time_s),
                "num_golfers": int(size),
            })
            group_id += 1
            remaining_golfers -= size

    return groups


def build_groups_interval(count: int, first_tee_s: int, interval_min: float) -> List[Dict]:
    """Build groups with regular intervals."""
    groups: List[Dict] = []
    for i in range(count):
        groups.append({
            "group_id": i + 1,
            "tee_time_s": int(first_tee_s + i * int(interval_min * 60)),
            "num_golfers": 4,
        })
    return groups


