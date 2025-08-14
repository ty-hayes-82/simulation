from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import simpy

from ..config.loaders import load_simulation_config
from ..logging import get_logger
from ..io.results import SimulationResult


logger = get_logger(__name__)


@dataclass
class DeliveryOrder:
    order_id: str | None
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


@dataclass
class SingleRunnerDeliveryService:
    env: simpy.Environment
    course_dir: str
    runner_speed_mps: float = 2.68
    prep_time_min: int = 10
    activity_log: List[Dict] = field(default_factory=list)
    order_queue: List[DeliveryOrder] = field(default_factory=list)
    delivery_stats: List[Dict] = field(default_factory=list)
    failed_orders: List[DeliveryOrder] = field(default_factory=list)

    # Internal runtime state
    runner_busy: bool = False
    runner_location: str = "clubhouse"

    # Derived config fields
    clubhouse_coords: Tuple[float, float] | None = None
    service_open_s: int = 0
    service_close_s: int = 0
    # Precomputed distances from clubhouse to each hole (meters)
    hole_distance_m: Dict[int, float] | None = None

    def __post_init__(self) -> None:
        self.prep_time_s = self.prep_time_min * 60
        self._load_course_config()
        self.env.process(self._delivery_service_process())

    def _load_course_config(self) -> None:
        sim_cfg = load_simulation_config(self.course_dir)
        self.clubhouse_coords = sim_cfg.clubhouse
        if getattr(sim_cfg, "service_hours", None) is not None:
            open_time = f"{int(sim_cfg.service_hours.start_hour):02d}:00"
            close_time = f"{int(sim_cfg.service_hours.end_hour):02d}:00"
        else:
            open_time = "07:00"
            close_time = "18:00"
        self.service_open_s = self._time_str_to_seconds(open_time)
        self.service_close_s = self._time_str_to_seconds(close_time)
        logger.info(
            "Delivery service hours: %s - %s (%.1fh - %.1fh)",
            open_time,
            close_time,
            self.service_open_s / 3600,
            self.service_close_s / 3600,
        )
        # Try to load realistic distances per hole
        self._load_travel_distances()

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

    @staticmethod
    def _time_str_to_seconds(time_str: str) -> int:
        hour, minute = map(int, time_str.split(":"))
        return (hour - 7) * 3600 + minute * 60

    def is_service_open(self) -> bool:
        return self.service_open_s <= self.env.now <= self.service_close_s

    def log_activity(self, activity_type: str, description: str, order_id: str | None = None, location: Optional[str] = None) -> None:
        current_time_min = self.env.now / 60
        hours = int(current_time_min // 60) + 7
        minutes = int(current_time_min % 60)
        time_str = f"{hours:02d}:{minutes:02d}"
        self.activity_log.append(
            {
                "timestamp_s": self.env.now,
                "time_str": time_str,
                "activity_type": activity_type,
                "description": description,
                "order_id": order_id,
                "location": location or self.runner_location,
            }
        )

    def place_order(self, order: DeliveryOrder) -> None:
        order.order_placed_time = self.env.now
        self.order_queue.append(order)
        queue_size = len(self.order_queue)
        if queue_size == 1:
            self.log_activity(
                "order_received",
                f"New order from Group {order.golfer_group_id} on Hole {order.hole_num} - Processing immediately",
                order.order_id,
                "clubhouse",
            )
        else:
            self.log_activity(
                "order_queued",
                f"New order from Group {order.golfer_group_id} on Hole {order.hole_num} - Added to queue (position {queue_size})",
                order.order_id,
                "clubhouse",
            )

    def _delivery_service_process(self):  # simpy process
        if self.env.now < self.service_open_s:
            wait_time = self.service_open_s - self.env.now
            self.log_activity("service_closed", f"Delivery service closed. Waiting {wait_time/60:.0f} minutes until opening", None, "clubhouse")
            yield self.env.timeout(wait_time)
            self.log_activity("service_opened", "Delivery service opened for business", None, "clubhouse")

        while True:
            if self.env.now > self.service_close_s:
                self.log_activity("service_closed", "Delivery service closed for the day. Remaining orders left unprocessed", None, "clubhouse")
                for remaining in self.order_queue:
                    remaining.status = "failed"
                    remaining.failure_reason = "Service closed before order could be processed"
                    self.failed_orders.append(remaining)
                self.order_queue.clear()
                break

            if self.order_queue and not self.runner_busy:
                order = self.order_queue.pop(0)
                placed_time = order.order_placed_time if order.order_placed_time is not None else self.env.now
                if (self.env.now - placed_time) > 3600:
                    order.status = "failed"
                    order.failure_reason = "Exceeded 1-hour queue time before processing"
                    self.failed_orders.append(order)
                    self.log_activity("order_failed", f"Order {order.order_id} failed. Waited over 1 hour in queue.", order.order_id)
                    continue
                yield self.env.process(self._process_single_order(order))
            else:
                yield self.env.timeout(30)

    def _process_single_order(self, order: DeliveryOrder):  # simpy process
        self.runner_busy = True
        placed_time = order.order_placed_time if order.order_placed_time is not None else self.env.now
        order.queue_delay_s = self.env.now - placed_time
        self.log_activity(
            "processing_start",
            f"Started processing Order {order.order_id} for Group {order.golfer_group_id} (waited {order.queue_delay_s/60:.1f} min in queue)",
            order.order_id,
        )

        if self.runner_location != "clubhouse":
            return_time = self._calculate_return_time()
            self.log_activity("returning", f"Returning to clubhouse from {self.runner_location} ({return_time/60:.1f} min)", order.order_id, self.runner_location)
            yield self.env.timeout(return_time)
            self.runner_location = "clubhouse"
            self.log_activity("arrived_clubhouse", f"Arrived back at clubhouse to prepare Order {order.order_id}", order.order_id, "clubhouse")

        order.prep_started_time = self.env.now
        self.log_activity("prep_start", f"Started food preparation for Order {order.order_id} (Hole {order.hole_num})", order.order_id, "clubhouse")
        yield self.env.timeout(self.prep_time_s)
        order.prep_completed_time = self.env.now
        self.log_activity("prep_complete", f"Completed food preparation for Order {order.order_id} ({self.prep_time_s/60:.0f} min)", order.order_id, "clubhouse")

        delivery_distance_m, delivery_time_s = self._calculate_delivery_details(order.hole_num)
        order.delivery_started_time = self.env.now
        self.log_activity("delivery_start", f"Departing clubhouse to deliver Order {order.order_id} to Hole {order.hole_num} ({delivery_distance_m:.0f}m, {delivery_time_s/60:.1f} min)", order.order_id, "clubhouse")
        yield self.env.timeout(delivery_time_s)
        order.delivered_time = self.env.now
        self.runner_location = f"hole_{order.hole_num}"

        placed_time = order.order_placed_time if order.order_placed_time is not None else order.delivered_time
        order.total_completion_time_s = order.delivered_time - placed_time
        return_time_s = self._calculate_return_time()
        total_drive_time_s = delivery_time_s + return_time_s
        self.log_activity("delivery_complete", f"Delivered Order {order.order_id} to Group {order.golfer_group_id} at Hole {order.hole_num} (Total completion: {order.total_completion_time_s/60:.1f} min)", order.order_id, f"hole_{order.hole_num}")

        order.status = "processed"
        self.delivery_stats.append(
            {
                "order_id": order.order_id,
                "golfer_group_id": order.golfer_group_id,
                "hole_num": order.hole_num,
                "order_time_s": order.order_time_s,
                "queue_delay_s": order.queue_delay_s,
                "prep_time_s": self.prep_time_s,
                "delivery_time_s": delivery_time_s,
                "return_time_s": return_time_s,
                "total_drive_time_s": total_drive_time_s,
                "delivery_distance_m": delivery_distance_m,
                "total_completion_time_s": order.total_completion_time_s,
                "delivered_at_time_s": order.delivered_time,
            }
        )

        if self.order_queue:
            next_order = self.order_queue[0]
            self.log_activity("queue_status", f"{len(self.order_queue)} orders waiting. Next: Order {next_order.order_id} for Group {next_order.golfer_group_id} on Hole {next_order.hole_num}", None, f"hole_{order.hole_num}")
        else:
            self.log_activity("idle", f"No orders in queue. Runner waiting at Hole {order.hole_num}", None, f"hole_{order.hole_num}")

        self.runner_busy = False

    def _calculate_return_time(self) -> float:
        if self.runner_location == "clubhouse":
            return 0.0
        # Parse last hole from runner_location and mirror outbound time
        try:
            if self.runner_location.startswith("hole_"):
                hole_num = int(self.runner_location.split("_")[1])
                distance_m, time_s = self._calculate_delivery_details(hole_num)
                return float(time_s)
        except Exception:
            pass
        # Fallback constant
        return 8 * 60.0

    def _calculate_delivery_details(self, hole_num: int) -> Tuple[float, float]:
        # Prefer realistic distances from travel_times.json
        if self.hole_distance_m and hole_num in self.hole_distance_m:
            distance_m = float(self.hole_distance_m[hole_num])
            travel_time_s = distance_m / max(self.runner_speed_mps, 0.1)
            return distance_m, travel_time_s

        # Fallback heuristic distances
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


@dataclass
class MultiRunnerDeliveryService:
    env: simpy.Environment
    course_dir: str
    num_runners: int = 2
    runner_speed_mps: float = 2.68
    prep_time_min: int = 10
    activity_log: List[Dict] = field(default_factory=list)
    delivery_stats: List[Dict] = field(default_factory=list)
    failed_orders: List[DeliveryOrder] = field(default_factory=list)

    # Shared queue implemented using a SimPy Store for concurrency
    order_store: Optional[simpy.Store] = None

    # Derived/config fields
    clubhouse_coords: Tuple[float, float] | None = None
    service_open_s: int = 0
    service_close_s: int = 0
    hole_distance_m: Dict[int, float] | None = None

    # Internal per-runner state
    runner_locations: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.prep_time_s = int(self.prep_time_min) * 60
        self._load_course_config()
        self.order_store = simpy.Store(self.env)
        # Initialize runner locations to clubhouse
        self.runner_locations = ["clubhouse" for _ in range(int(self.num_runners))]
        # Start runner processes
        for idx in range(int(self.num_runners)):
            self.env.process(self._runner_loop(idx))

    def _load_course_config(self) -> None:
        sim_cfg = load_simulation_config(self.course_dir)
        self.clubhouse_coords = sim_cfg.clubhouse
        if getattr(sim_cfg, "service_hours", None) is not None:
            open_time = f"{int(sim_cfg.service_hours.start_hour):02d}:00"
            close_time = f"{int(sim_cfg.service_hours.end_hour):02d}:00"
        else:
            open_time = "07:00"
            close_time = "18:00"
        self.service_open_s = self._time_str_to_seconds(open_time)
        self.service_close_s = self._time_str_to_seconds(close_time)
        logger.info(
            "Delivery service hours: %s - %s (%.1fh - %.1fh)",
            open_time,
            close_time,
            self.service_open_s / 3600,
            self.service_close_s / 3600,
        )
        self._load_travel_distances()

    def _load_travel_distances(self) -> None:
        try:
            import json
            course_path = Path(self.course_dir)
            candidates = [course_path / "travel_times.json", course_path / "travel_times_simple.json"]
            chosen = next((p for p in candidates if p.exists()), None)
            if not chosen:
                self.hole_distance_m = None
                return
            data = json.loads(chosen.read_text(encoding="utf-8"))
            holes = data.get("holes", [])
            mapping: Dict[int, float] = {}
            for h in holes:
                hole_num = int(h.get("hole", 0))
                tt = h.get("travel_times", {}).get("golf_cart", {}).get("to_target", {})
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

    @staticmethod
    def _time_str_to_seconds(time_str: str) -> int:
        hour, minute = map(int, time_str.split(":"))
        return (hour - 7) * 3600 + minute * 60

    def log_activity(self, activity_type: str, description: str, runner_id: Optional[str] = None, order_id: str | None = None, location: Optional[str] = None) -> None:
        current_time_min = self.env.now / 60
        hours = int(current_time_min // 60) + 7
        minutes = int(current_time_min % 60)
        time_str = f"{hours:02d}:{minutes:02d}"
        self.activity_log.append(
            {
                "timestamp_s": self.env.now,
                "time_str": time_str,
                "activity_type": activity_type,
                "description": description,
                "runner_id": runner_id,
                "order_id": order_id,
                "location": location,
            }
        )

    def place_order(self, order: DeliveryOrder) -> None:
        order.order_placed_time = self.env.now
        # Note: store.put returns an event; we don't need to wait on it here
        self.order_store.put(order)
        self.log_activity(
            "order_received",
            f"New order from Group {order.golfer_group_id} on Hole {order.hole_num}",
            runner_id=None,
            order_id=order.order_id,
            location="clubhouse",
        )

    def _runner_loop(self, runner_index: int):  # simpy process
        runner_label = f"runner_{runner_index + 1}"
        # Wait until service opens
        if self.env.now < self.service_open_s:
            wait_time = self.service_open_s - self.env.now
            self.log_activity("service_closed", f"{runner_label} waiting {wait_time/60:.0f} minutes until opening", runner_id=runner_label, location="clubhouse")
            yield self.env.timeout(wait_time)
            self.log_activity("service_opened", f"{runner_label} started shift", runner_id=runner_label, location="clubhouse")

        while True:
            # Stop condition: after close and queue empty
            if self.env.now > self.service_close_s and len(self.order_store.items) == 0:
                self.log_activity("service_closed", f"{runner_label} shift ended", runner_id=runner_label, location=self.runner_locations[runner_index])
                break

            # Fetch next order or wait briefly
            evt = self.order_store.get()
            timeout_evt = self.env.timeout(30)
            res = yield evt | timeout_evt
            if timeout_evt in res:
                continue
            order: DeliveryOrder = res[evt]

            # Discard orders that waited too long in the queue
            placed_time = order.order_placed_time if order.order_placed_time is not None else self.env.now
            if (self.env.now - placed_time) > 3600:
                order.status = "failed"
                order.failure_reason = "Exceeded 1-hour queue time before processing"
                self.failed_orders.append(order)
                self.log_activity("order_failed", f"{runner_label} dropping Order {order.order_id} after >1h wait", runner_id=runner_label, order_id=order.order_id, location=self.runner_locations[runner_index])
                continue

            # Process the order
            yield self.env.process(self._process_single_order(order, runner_index, runner_label))

    def _process_single_order(self, order: DeliveryOrder, runner_index: int, runner_label: str):  # simpy process
        # If not at clubhouse, return first
        if self.runner_locations[runner_index] != "clubhouse":
            return_time = self._calculate_return_time(self.runner_locations[runner_index])
            self.log_activity("returning", f"{runner_label} returning to clubhouse from {self.runner_locations[runner_index]} ({return_time/60:.1f} min)", runner_id=runner_label, order_id=order.order_id, location=self.runner_locations[runner_index])
            yield self.env.timeout(return_time)
            self.runner_locations[runner_index] = "clubhouse"
            self.log_activity("arrived_clubhouse", f"{runner_label} arrived at clubhouse to prepare Order {order.order_id}", runner_id=runner_label, order_id=order.order_id, location="clubhouse")

        order.queue_delay_s = self.env.now - (order.order_placed_time or self.env.now)
        order.prep_started_time = self.env.now
        self.log_activity("prep_start", f"{runner_label} started prep for Order {order.order_id} (Hole {order.hole_num})", runner_id=runner_label, order_id=order.order_id, location="clubhouse")
        yield self.env.timeout(self.prep_time_s)
        order.prep_completed_time = self.env.now
        self.log_activity("prep_complete", f"{runner_label} completed prep for Order {order.order_id}", runner_id=runner_label, order_id=order.order_id, location="clubhouse")

        delivery_distance_m, delivery_time_s = self._calculate_delivery_details(order.hole_num)
        order.delivery_started_time = self.env.now
        self.log_activity("delivery_start", f"{runner_label} departing to Hole {order.hole_num} ({delivery_distance_m:.0f}m, {delivery_time_s/60:.1f} min)", runner_id=runner_label, order_id=order.order_id, location="clubhouse")
        yield self.env.timeout(delivery_time_s)
        order.delivered_time = self.env.now
        self.runner_locations[runner_index] = f"hole_{order.hole_num}"

        placed_time = order.order_placed_time if order.order_placed_time is not None else order.delivered_time
        order.total_completion_time_s = order.delivered_time - placed_time
        return_time_s = self._calculate_return_time(self.runner_locations[runner_index])
        total_drive_time_s = delivery_time_s + return_time_s
        self.log_activity("delivery_complete", f"{runner_label} delivered Order {order.order_id} to Hole {order.hole_num} (Total completion: {order.total_completion_time_s/60:.1f} min)", runner_id=runner_label, order_id=order.order_id, location=self.runner_locations[runner_index])

        order.status = "processed"
        self.delivery_stats.append(
            {
                "order_id": order.order_id,
                "golfer_group_id": order.golfer_group_id,
                "hole_num": order.hole_num,
                "order_time_s": order.order_time_s,
                "queue_delay_s": order.queue_delay_s,
                "prep_time_s": self.prep_time_s,
                "delivery_time_s": delivery_time_s,
                "return_time_s": return_time_s,
                "total_drive_time_s": total_drive_time_s,
                "delivery_distance_m": delivery_distance_m,
                "total_completion_time_s": order.total_completion_time_s,
                "delivered_at_time_s": order.delivered_time,
                "runner_id": runner_label,
            }
        )

    def _calculate_return_time(self, runner_location: str) -> float:
        if runner_location == "clubhouse":
            return 0.0
        try:
            if runner_location.startswith("hole_"):
                hole_num = int(runner_location.split("_")[1])
                _, time_s = self._calculate_delivery_details(hole_num)
                return float(time_s)
        except Exception:
            pass
        return 8 * 60.0

    def _calculate_delivery_details(self, hole_num: int) -> Tuple[float, float]:
        if self.hole_distance_m and hole_num in self.hole_distance_m:
            distance_m = float(self.hole_distance_m[hole_num])
            travel_time_s = distance_m / max(self.runner_speed_mps, 0.1)
            return distance_m, travel_time_s
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

def simulate_golfer_orders(groups: List[Dict], order_probability_per_9_holes: float) -> List[DeliveryOrder]:
    """Generate delivery orders on a per-group, per-9-holes basis.

    Semantics:
    - Each group has up to two independent chances to place an order: once on the front nine (holes 1–9)
      and once on the back nine (holes 10–18).
    - The probability for each nine is `order_probability_per_9_holes`.
    - Order times are aligned to a random hole within the corresponding nine using ~12 min/hole pacing.
    - Number of golfers in a group is ignored for order generation.
    """
    import random

    orders: List[DeliveryOrder] = []
    minutes_per_hole = 12

    for group in groups:
        group_id = group["group_id"]
        tee_time_s = group["tee_time_s"]

        # Front nine (holes 1..9)
        if random.random() < order_probability_per_9_holes:
            hole_front = int(random.randint(1, 9))
            order_time_front_s = tee_time_s + (hole_front - 1) * minutes_per_hole * 60
            orders.append(
                DeliveryOrder(
                    order_id=None,
                    golfer_group_id=group_id,
                    golfer_id=f"G{group_id}",
                    order_time_s=order_time_front_s,
                    hole_num=hole_front,
                )
            )

        # Back nine (holes 10..18)
        if random.random() < order_probability_per_9_holes:
            hole_back = int(random.randint(10, 18))
            order_time_back_s = tee_time_s + (hole_back - 1) * minutes_per_hole * 60
            orders.append(
                DeliveryOrder(
                    order_id=None,
                    golfer_group_id=group_id,
                    golfer_id=f"G{group_id}",
                    order_time_s=order_time_back_s,
                    hole_num=hole_back,
                )
            )

    orders.sort(key=lambda x: x.order_time_s)
    for i, order in enumerate(orders, 1):
        order.order_id = f"{i:03d}"
    return orders


# Optional service: Beverage cart GPS tracking (moved from CLI script)
@dataclass
class BeverageCartService:
    env: simpy.Environment
    course_dir: str
    cart_id: str = "bev_cart_1"
    track_coordinates: bool = True
    starting_hole: int = 18  # New parameter for custom starting hole

    coordinates: List[Dict] = field(default_factory=list)
    activity_log: List[Dict] = field(default_factory=list)

    clubhouse_coords: Tuple[float, float] | None = None
    service_start_s: int = 0
    service_end_s: int = 0
    bev_cart_18_holes_minutes: int = 180

    def __post_init__(self) -> None:
        self._load_course_config()
        if self.track_coordinates:
            self.env.process(self.beverage_cart_process())

    def _load_course_config(self) -> None:
        sim_cfg = load_simulation_config(self.course_dir)
        self.clubhouse_coords = sim_cfg.clubhouse
        # Read configured 18-hole loop durations
        try:
            minutes = int(getattr(sim_cfg, "bev_cart_18_holes_minutes", 180))
            self.bev_cart_18_holes_minutes = max(1, minutes)
        except Exception:
            self.bev_cart_18_holes_minutes = 180
        # Service hours for beverage cart (prefer config, else defaults)
        if getattr(sim_cfg, "bev_cart_hours", None) is not None:
            start_time = f"{int(sim_cfg.bev_cart_hours.start_hour):02d}:00"
            end_time = f"{int(sim_cfg.bev_cart_hours.end_hour):02d}:00"
        else:
            start_time = "09:00"
            end_time = "17:00"
        self.service_start_s = self._time_str_to_seconds(start_time)
        self.service_end_s = self._time_str_to_seconds(end_time)
        logger.info(
            "Beverage cart service hours: %s - %s (%.1fh - %.1fh)",
            start_time,
            end_time,
            self.service_start_s / 3600,
            self.service_end_s / 3600,
        )
        logger.info("Beverage cart 18-hole circuit time: %d minutes", self.bev_cart_18_holes_minutes)

    # -------------------- Loop points utilities --------------------
    def _build_hole_sequence(self, minutes_per_loop: int) -> List[int]:
        """Build hole sequence based on starting hole.
        
        Cart 1 (starting_hole=18): 18→17→16→...→1 (standard reverse)
        Cart 2 (starting_hole=9): 9→8→7→...→1→18→17→...→10→9 (start at 9, complete full circuit)
        """
        minutes_per_hole_in_loop = minutes_per_loop / 18.0
        hole_sequence: List[int] = []
        
        if self.starting_hole == 18:
            # Standard reverse route: 18→1
            for hole_num in range(18, 0, -1):  # 18..1
                hole_minutes = int(minutes_per_hole_in_loop)
                hole_sequence.extend([hole_num] * hole_minutes)
        elif self.starting_hole == 9:
            # Cart 2 route: 9→8→7→6→5→4→3→2→1→18→17→16→15→14→13→12→11→10→9
            # Start at 9, go down to 1, then 18 down to 10, then back to 9
            sequence = list(range(9, 0, -1)) + list(range(18, 9, -1))  # [9,8,7,6,5,4,3,2,1,18,17,16,15,14,13,12,11,10]
            for hole_num in sequence:
                hole_minutes = int(minutes_per_hole_in_loop)
                hole_sequence.extend([hole_num] * hole_minutes)
        else:
            # Default to standard reverse for other starting holes
            for hole_num in range(18, 0, -1):
                hole_minutes = int(minutes_per_hole_in_loop)
                hole_sequence.extend([hole_num] * hole_minutes)
        
        # Ensure we have exactly minutes_per_loop minutes
        while len(hole_sequence) < minutes_per_loop:
            hole_sequence.append(hole_sequence[-1] if hole_sequence else 1)
        hole_sequence = hole_sequence[:minutes_per_loop]
        
        return hole_sequence
    
    @staticmethod
    def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
        import math
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return 6371000.0 * c

    def _flatten_holes_linestrings(self) -> list[tuple[float, float]]:
        """Concatenate holes 1..18 LineStrings into a single coordinate list (lon, lat)."""
        import json
        from shapely.geometry import LineString

        holes_path = Path(self.course_dir) / "geojson" / "holes.geojson"
        if not holes_path.exists():
            return []
        data = json.loads(holes_path.read_text(encoding="utf-8"))
        feats = data.get("features", [])

        def _ref(props):
            v = props.get("ref") or props.get("hole")
            try:
                return int(v)
            except Exception:
                return 10**9

        feats.sort(key=lambda f: _ref(f.get("properties", {})))
        coords: list[tuple[float, float]] = []
        for f in feats:
            geom = f.get("geometry", {})
            if geom.get("type") != "LineString":
                continue
            for lon, lat in geom.get("coordinates", []):
                coords.append((float(lon), float(lat)))
        # Close loop by returning to start
        if len(coords) > 1:
            coords.append(coords[0])
        # Deduplicate consecutive duplicates
        dedup: list[tuple[float, float]] = []
        last: tuple[float, float] | None = None
        for pt in coords:
            if last is None or (pt[0] != last[0] or pt[1] != last[1]):
                dedup.append(pt)
                last = pt
        return dedup

    def _resample_uniform(self, coords: list[tuple[float, float]], num_points: int) -> list[tuple[float, float]]:
        if num_points <= 0 or len(coords) < 2:
            return list(coords)
        # cumulative distances
        cum = [0.0]
        total = 0.0
        for i in range(1, len(coords)):
            d = self._haversine_m(*coords[i - 1], *coords[i])
            total += d
            cum.append(total)
        if total <= 0:
            return [coords[0]] * num_points
        step = total / max(num_points - 1, 1)
        targets = [i * step for i in range(num_points)]
        res: list[tuple[float, float]] = []
        j = 0
        for t in targets:
            while j < len(cum) - 1 and cum[j + 1] < t:
                j += 1
            if j >= len(cum) - 1:
                res.append(coords[-1])
                continue
            seg = max(cum[j + 1] - cum[j], 1e-9)
            frac = (t - cum[j]) / seg
            lon = coords[j][0] + frac * (coords[j + 1][0] - coords[j][0])
            lat = coords[j][1] + frac * (coords[j + 1][1] - coords[j][1])
            res.append((lon, lat))
        return res

    def _load_or_build_loop_points(self) -> list[tuple[float, float]]:
        """Load loop points from outputs if present; otherwise build from holes.

        Uses bev_cart_18_holes_minutes to determine per-loop minutes when building.
        """
        # Prefer prebuilt points
        prebuilt = Path("outputs") / "holes_path" / "holes_path_points.json"
        if prebuilt.exists():
            try:
                import json
                data = json.loads(prebuilt.read_text(encoding="utf-8"))
                coords = data.get("coordinates", [])
                pts = [(float(lon), float(lat)) for lon, lat in coords]
                if len(pts) >= 2:
                    logger.info("Loaded %d loop points from %s", len(pts), prebuilt)
                    return pts
            except Exception:
                pass

        # Build from holes with configured minutes per loop
        minutes = int(self.bev_cart_18_holes_minutes)
        base = self._flatten_holes_linestrings()
        if len(base) < 2:
            logger.warning("Could not build holes path; falling back to clubhouse point only")
            return []
        pts = self._resample_uniform(base, max(2, minutes))
        logger.info("Built %d loop points from holes.geojson (%d min per loop)", len(pts), self.bev_cart_18_holes_minutes)
        return pts

    @staticmethod
    def _time_str_to_seconds(time_str: str) -> int:
        hour, minute = map(int, time_str.split(":"))
        return (hour - 7) * 3600 + minute * 60

    def log_activity(self, activity_type: str, description: str, location: Optional[str] = None) -> None:
        current_time_min = self.env.now / 60
        hours = int(current_time_min // 60) + 7
        minutes = int(current_time_min % 60)
        time_str = f"{hours:02d}:{minutes:02d}"
        self.activity_log.append(
            {
                "timestamp_s": self.env.now,
                "time_str": time_str,
                "activity_type": activity_type,
                "description": description,
                "cart_id": self.cart_id,
                "location": location,
            }
        )

    def beverage_cart_process(self):  # simpy process
        # Wait until service starts
        if self.env.now < self.service_start_s:
            wait_time = self.service_start_s - self.env.now
            self.log_activity("service_closed", f"Beverage cart waiting {wait_time/60:.0f} minutes until service starts")
            yield self.env.timeout(wait_time)
            self.log_activity("service_opened", "Beverage cart service started")

        # Load loop points and generate GPS coordinates from 09:00 to 17:00
        try:
            loop_points = self._load_or_build_loop_points()

            # Load hole lines (optional; current_hole will be time-based for 18→1 traversal)
            import json
            from shapely.geometry import LineString, Point

            hole_lines: dict[int, LineString] = {}
            holes_file = Path(self.course_dir) / "geojson" / "holes.geojson"
            if holes_file.exists():
                holes_data = json.loads(holes_file.read_text(encoding="utf-8"))
                for feature in holes_data.get("features", []):
                    props = feature.get("properties", {})
                    raw_num = props.get("hole", props.get("ref"))
                    try:
                        hole_num = int(raw_num) if raw_num is not None else None
                    except (TypeError, ValueError):
                        hole_num = None
                    if hole_num and feature.get("geometry", {}).get("type") == "LineString":
                        coords = feature["geometry"]["coordinates"]
                        hole_lines[hole_num] = LineString(coords)

            def nearest_hole(lon: float, lat: float) -> int | None:
                # Retained for potential diagnostics; not used for assignment
                if not hole_lines:
                    return None
                pt = Point(lon, lat)
                best_hole, best_dist = None, float("inf")
                for h, line in hole_lines.items():
                    d = line.distance(pt)
                    if d < best_dist:
                        best_dist = d
                        best_hole = h
                return best_hole

            import math
            # Build timestamps at 60s from start to end (inclusive)
            timestamps = list(range(int(self.service_start_s), int(self.service_end_s) + 1, 60))

            # Start at clubhouse at opening and label as starting on the configured hole
            club_lon, club_lat = self.clubhouse_coords or (0.0, 0.0)
            if timestamps:
                self.coordinates.append(
                    {
                        "latitude": float(club_lat),
                        "longitude": float(club_lon),
                        "timestamp": int(timestamps[0]),
                        "type": "bev_cart",
                        "current_hole": self.starting_hole,
                    }
                )

            # If we have loop points, follow them minute-by-minute after opening
            if loop_points:
                points = loop_points
                num_points = len(points)
                minutes_per_loop = max(1, int(self.bev_cart_18_holes_minutes))
                # Traverse the loop in reverse so the cart goes 18→1
                rotated = list(reversed(points))

                # Build hole sequence based on starting hole
                hole_sequence = self._build_hole_sequence(minutes_per_loop)

                # Advance through the loop so one full loop takes minutes_per_loop minutes,
                # even if we have a different number of prebuilt points
                step_per_minute = num_points / float(minutes_per_loop)
                
                # Adjust starting position based on starting hole
                if self.starting_hole == 9:
                    # Cart 2 starts at hole 9, which is roughly halfway through the course
                    # Start at roughly the middle of the loop
                    pos = num_points * 0.5
                else:
                    # Cart 1 starts at the beginning (hole 18)
                    pos = 0.0
                for i, t in enumerate(timestamps[1:]):
                    idx0 = int(math.floor(pos)) % num_points
                    idx1 = (idx0 + 1) % num_points
                    frac = pos - math.floor(pos)
                    lon = rotated[idx0][0] + frac * (rotated[idx1][0] - rotated[idx0][0])
                    lat = rotated[idx0][1] + frac * (rotated[idx1][1] - rotated[idx0][1])

                    minutes_into_loop = i % minutes_per_loop
                    current_hole = hole_sequence[minutes_into_loop]
                    
                    self.coordinates.append(
                        {
                            "latitude": float(lat),
                            "longitude": float(lon),
                            "timestamp": int(t),
                            "type": "bev_cart",
                            "current_hole": current_hole,
                        }
                    )
                    pos += step_per_minute

            self.log_activity(
                "coordinates_generated",
                f"Generated {len(self.coordinates)} GPS coordinates for beverage cart route using loop points",
            )
            logger.info("Generated %d beverage cart GPS coordinates (start %s, end %s)", len(self.coordinates), self.service_start_s, self.service_end_s)
        except Exception as e:  # noqa: BLE001
            self.log_activity("coordinates_error", f"Error generating beverage cart coordinates: {str(e)}")
            logger.error("Error generating beverage cart coordinates: %s", e)

        # Continue running until service ends
        while self.env.now <= self.service_end_s:
            yield self.env.timeout(60)

        self.log_activity("service_closed", "Beverage cart service ended for the day")



def run_multi_golfer_simulation(
    course_dir: str,
    groups: List[Dict[str, Any]],
    order_probability_per_9_holes: float = 0.3,
    prep_time_min: int = 10,
    runner_speed_mps: float = 6.0,
    env: Optional[simpy.Environment] = None,
    output_dir: Optional[str] = None,
    create_visualization: bool = True,
) -> Dict[str, Any]:
    """
    Run a simple multi-golfer simulation using a single runner queue.

    Parameters
    ----------
    course_dir: str
        Path to course directory with config files.
    groups: list of dict
        Each group: {"group_id": int, "tee_time_s": int, "num_golfers": int}
    order_probability_per_9_holes: float
        Probability (0..1) of an order per golfer per 9 holes.
    prep_time_min: int
        Food preparation time per order in minutes.
    runner_speed_mps: float
        Runner speed in meters per second.
    env: simpy.Environment | None
        Optional external environment for composition/testing.
    output_dir: str | None
        Directory to save visualization PNG. If None, no visualization created.
    create_visualization: bool
        Whether to create delivery visualization PNG map.

    Returns
    -------
    dict
        Summary including orders, activity log, and delivery stats.
    """
    simulation_env = env or simpy.Environment()

    service = SingleRunnerDeliveryService(
        env=simulation_env,
        course_dir=course_dir,
        runner_speed_mps=runner_speed_mps,
        prep_time_min=prep_time_min,
    )

    # Generate synthetic orders based on groups and probabilities
    orders = simulate_golfer_orders(groups, order_probability_per_9_holes)

    def order_arrival_process():  # simpy process
        last_time = simulation_env.now
        for order in orders:
            target_time = max(order.order_time_s, service.service_open_s)
            if target_time > last_time:
                yield simulation_env.timeout(target_time - last_time)
            service.place_order(order)
            last_time = target_time

    simulation_env.process(order_arrival_process())

    # Run until close of service or until queue drains after closing
    run_until = max(service.service_close_s + 1, max((o.order_time_s for o in orders), default=0) + 4 * 3600)
    simulation_env.run(until=run_until)

    # Summarize results
    results: Dict[str, Any] = {
        "success": True,
        "simulation_type": "multi_golfer_single_runner",
        "orders": [
            {
                "order_id": o.order_id,
                "golfer_group_id": o.golfer_group_id,
                "golfer_id": o.golfer_id,
                "hole_num": o.hole_num,
                "order_time_s": o.order_time_s,
                "status": o.status,
                "total_completion_time_s": o.total_completion_time_s,
            }
            for o in orders
        ],
        "delivery_stats": service.delivery_stats,
        "failed_orders": [
            {
                "order_id": o.order_id,
                "reason": o.failure_reason,
            }
            for o in service.failed_orders
        ],
        "activity_log": service.activity_log,
        "metadata": {
            "prep_time_min": prep_time_min,
            "runner_speed_mps": runner_speed_mps,
            "num_groups": len(groups),
            "course_dir": str(course_dir),
        },
    }

    # Compute simple aggregates
    if service.delivery_stats:
        total_order_time = sum(d.get("total_completion_time_s", 0.0) for d in service.delivery_stats)
        avg_order_time = total_order_time / max(len(service.delivery_stats), 1)
        total_distance = sum(d.get("delivery_distance_m", 0.0) for d in service.delivery_stats)
        avg_distance = total_distance / max(len(service.delivery_stats), 1)
        results["aggregate_metrics"] = {
            "average_order_time_s": avg_order_time,
            "total_delivery_distance_m": total_distance,
            "average_delivery_distance_m": avg_distance,
            "orders_processed": len(service.delivery_stats),
            "orders_failed": len(service.failed_orders),
        }
    else:
        results["aggregate_metrics"] = {
            "average_order_time_s": 0.0,
            "total_delivery_distance_m": 0.0,
            "average_delivery_distance_m": 0.0,
            "orders_processed": 0,
            "orders_failed": len(service.failed_orders),
        }

    # Create visualization if requested and we have orders
    if create_visualization and output_dir and results["orders"]:
        try:
            from ..viz.matplotlib_viz import render_delivery_plot, render_individual_delivery_plots
            from ..viz.matplotlib_viz import load_course_geospatial_data
            import networkx as nx
            
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            
            # Load course data for visualization
            sim_cfg = load_simulation_config(course_dir)
            clubhouse_coords = sim_cfg.clubhouse
            course_data = load_course_geospatial_data(course_dir)
            
            # Try to load cart graph
            cart_graph = None
            cart_graph_path = Path(course_dir) / "pkl" / "cart_graph.pkl"
            if cart_graph_path.exists():
                import pickle
                with open(cart_graph_path, "rb") as f:
                    cart_graph = pickle.load(f)
            
            # Create main visualization (all orders together)
            viz_path = output_path / "delivery_orders_map.png"
            render_delivery_plot(
                results=results,
                course_data=course_data,
                clubhouse_coords=clubhouse_coords,
                cart_graph=cart_graph,
                save_path=viz_path,
                style="detailed"
            )
            
            logger.info("Created delivery visualization: %s", viz_path)
            results["visualization_path"] = str(viz_path)
            
            # Create individual delivery visualizations
            individual_paths = render_individual_delivery_plots(
                results=results,
                course_data=course_data,
                clubhouse_coords=clubhouse_coords,
                cart_graph=cart_graph,
                output_dir=output_path,
                filename_prefix="delivery_order",
                style="detailed"
            )
            
            if individual_paths:
                logger.info("Created %d individual delivery visualizations", len(individual_paths))
                results["individual_visualization_paths"] = [str(p) for p in individual_paths]
            
        except Exception as e:
            logger.warning("Failed to create visualization: %s", e)
            results["visualization_error"] = str(e)

    return results
