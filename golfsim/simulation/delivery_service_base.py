from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import simpy

from ..config.loaders import load_simulation_config
from ..logging import get_logger
from .. import utils


logger = get_logger(__name__)


@dataclass
class DeliveryOrder:
    order_id: Optional[str]
    golfer_group_id: int
    golfer_id: str
    order_time_s: float
    hole_num: int
    order_placed_time: Optional[float] = None
    prep_started_time: Optional[float] = None
    prep_completed_time: Optional[float] = None
    delivery_started_time: Optional[float] = None
    delivered_time: Optional[float] = None
    total_completion_time_s: float = 0.0
    queue_delay_s: float = 0.0
    status: str = "pending"  # pending, processed, failed
    failure_reason: Optional[str] = None
    tee_time_s: float = 0.0


@dataclass
class BaseDeliveryService:
    env: simpy.Environment
    course_dir: str
    runner_speed_mps: float = 2.68
    prep_time_min: int = 10
    activity_log: List[Dict] = field(default_factory=list)
    delivery_stats: List[Dict] = field(default_factory=list)
    failed_orders: List[DeliveryOrder] = field(default_factory=list)

    # Derived config fields
    clubhouse_coords: Optional[Tuple[float, float]] = None
    service_open_s: int = 0
    service_close_s: int = 0
    # Precomputed distances from clubhouse to each hole (meters)
    hole_distance_m: Optional[Dict[int, float]] = None
    # NEW: Precomputed travel times from clubhouse to each node
    node_travel_times: Optional[List[Dict[str, float]]] = None
    # Configured queue timeout: orders not dispatched within this window fail
    queue_timeout_s: int = 3600

    def __post_init__(self) -> None:
        self.prep_time_s = self.prep_time_min * 60
        self._load_course_config()
        self._load_node_travel_times()  # New method to load node travel times
        if not hasattr(self, "groups"):  # For SingleRunner, start process here
            self.env.process(self._delivery_service_process())

    def _load_course_config(self) -> None:
        """Loads course-specific config, including clubhouse coords and service hours."""
        sim_cfg = load_simulation_config(self.course_dir)
        self.clubhouse_coords = sim_cfg.clubhouse
        try:
            self.queue_timeout_s = max(60, int(getattr(sim_cfg, "minutes_for_delivery_order_failure", 60)) * 60)
        except Exception:
            self.queue_timeout_s = 3600
        if getattr(sim_cfg, "service_hours", None) is not None:
            open_time = f"{int(sim_cfg.service_hours.start_hour):02d}:00"
            close_time = f"{int(sim_cfg.service_hours.end_hour):02d}:00"
        else:
            open_time = "07:00"
            close_time = "18:00"
        self.service_open_s = utils.time_str_to_seconds(open_time)
        self.service_close_s = utils.time_str_to_seconds(close_time)
        logger.info(
            "Delivery service hours: %s - %s (%.1fh - %.1fh)",
            open_time,
            close_time,
            self.service_open_s / 3600,
            self.service_close_s / 3600,
        )
        # Try to load realistic distances per hole
        self._load_travel_distances()

    def _load_node_travel_times(self) -> None:
        """Load pre-computed travel times from clubhouse to each node."""
        try:
            import json
            travel_times_path = Path(self.course_dir) / "node_travel_times.json"
            if travel_times_path.exists():
                data = json.loads(travel_times_path.read_text(encoding="utf-8"))
                self.node_travel_times = data.get("travel_times", [])
                if self.node_travel_times:
                    logger.info("Loaded travel times for %d nodes.", len(self.node_travel_times))
            else:
                self.node_travel_times = None
                logger.warning("node_travel_times.json not found. Delivery calculations will use less accurate heuristics.")
        except Exception as e:
            logger.error("Failed to load or parse node_travel_times.json: %s", e)
            self.node_travel_times = None

    def _load_travel_distances(self) -> None:
        """Load clubhouse→hole distances from travel_times.json if available.

        Falls back to None if not present; downstream logic will use heuristics.
        """
        try:
            import json
            course_path = Path(self.course_dir)
            candidates = [
                course_path / "travel_times.json",
                course_path / "travel_times_simple.json",
            ]
            chosen = next((p for p in candidates if p.exists()), None)
            if not chosen:
                self.hole_distance_m = None
                return
            data = json.loads(chosen.read_text(encoding="utf-8"))
            holes = data.get("holes", [])
            mapping: Dict[int, float] = {}
            for h in holes:
                hole_num = int(h.get("hole", 0))
                tt = (
                    h.get("travel_times", {})
                    .get("golf_cart", {})
                    .get("to_target", {})
                )
                dist = tt.get("distance_m")
                if hole_num and isinstance(dist, (int, float)):
                    mapping[hole_num] = float(dist)
            self.hole_distance_m = mapping if mapping else None
            if self.hole_distance_m:
                logger.info("Loaded travel distances for %d holes from %s", len(self.hole_distance_m), chosen.name)
            else:
                logger.warning("travel_times file present but no usable distances found: %s", chosen)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to load travel distances: %s", e)
            self.hole_distance_m = None

    def is_service_open(self) -> bool:
        return self.service_open_s <= self.env.now <= self.service_close_s

    def log_activity(self, activity_type: str, description: str, order_id: Optional[str] = None, location: Optional[str] = None, orders_in_queue: Optional[int] = None, runner_id: Optional[str] = None) -> None:
        current_time_min = self.env.now / 60
        hours = int(current_time_min // 60) + 7
        minutes = int(current_time_min % 60)
        time_str = f"{hours:02d}:{minutes:02d}"
        
        # Determine location from subclass-specific attributes if not provided
        if location is None:
            if hasattr(self, "runner_location"): # SingleRunner
                location = self.runner_location
            # For MultiRunner, location seems to be passed explicitly with runner context
            else:
                location = "clubhouse"

        entry = {
            "timestamp_s": self.env.now,
            "time_str": time_str,
            "activity_type": activity_type,
            "description": description,
            "order_id": order_id,
            "location": location,
        }
        if orders_in_queue is not None:
            entry["orders_in_queue"] = int(orders_in_queue)
        if runner_id is not None:
            entry["runner_id"] = runner_id
        self.activity_log.append(entry)

    def _calculate_delivery_details(self, hole_num: int, node_idx: Optional[int] = None) -> Tuple[float, float]:
        # Prefer precise, node-based travel times if available
        if node_idx is not None and self.node_travel_times and 0 <= node_idx < len(self.node_travel_times):
            node_data = self.node_travel_times[node_idx]
            return node_data.get("distance_m", 0.0), node_data.get("time_s", 0.0)

        # Second, prefer realistic distances from travel_times.json (legacy)
        if self.hole_distance_m and hole_num in self.hole_distance_m:
            distance_m = float(self.hole_distance_m[hole_num])
            travel_time_s = distance_m / max(self.runner_speed_mps, 0.1)
            return distance_m, travel_time_s

        # Fallback heuristic distances if no travel time files are found
        heuristic_distance_by_hole = [
            0, 400, 600, 800, 1000, 1200, 1400, 1600, 1800, 2000,
            1800, 1600, 1400, 1200, 1000, 800, 600, 400, 200,
        ]
        if 1 <= hole_num <= 18:
            distance_m = float(heuristic_distance_by_hole[hole_num])
        else:
            distance_m = 1000.0
        travel_time_s = distance_m / max(self.runner_speed_mps, 0.1)
        return distance_m, travel_time_s

    def _calculate_return_time(self, runner_location: str) -> float:
        if runner_location == "clubhouse":
            return 0.0
        # Parse last hole from runner_location and mirror outbound time
        try:
            if runner_location.startswith("hole_"):
                hole_num = int(runner_location.split("_")[1])
                distance_m, time_s = self._calculate_delivery_details(hole_num)
                return float(time_s)
        except Exception:
            pass
        # Fallback constant
        return 8 * 60.0
