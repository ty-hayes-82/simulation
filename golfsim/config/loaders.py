from __future__ import annotations

import json
from pathlib import Path
from typing import Union

from .models import SimulationConfig, TeeTimesConfig


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


