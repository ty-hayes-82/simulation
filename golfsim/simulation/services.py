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
    # Configured queue timeout: orders not dispatched within this window fail
    queue_timeout_s: int = 3600

    def __post_init__(self) -> None:
        self.prep_time_s = self.prep_time_min * 60
        self._load_course_config()
        self.env.process(self._delivery_service_process())

    def _load_course_config(self) -> None:
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

    def _prune_expired_orders(self) -> None:
        """Remove orders from queue that exceeded queue_timeout_s without dispatch."""
        if not self.order_queue:
            return
        kept: List[DeliveryOrder] = []
        for o in self.order_queue:
            placed = o.order_placed_time if o.order_placed_time is not None else self.env.now
            if (self.env.now - placed) >= self.queue_timeout_s:
                o.status = "failed"
                o.failure_reason = f"Not dispatched within {int(self.queue_timeout_s/60)} minutes"
                self.failed_orders.append(o)
                self.log_activity(
                    "order_failed_timeout",
                    f"Order {o.order_id} timed out in queue (>{int(self.queue_timeout_s/60)} min); removed from queue",
                    o.order_id,
                    "clubhouse",
                    orders_in_queue=len(self.order_queue),
                )
            else:
                kept.append(o)
        self.order_queue = kept

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

    def log_activity(self, activity_type: str, description: str, order_id: str | None = None, location: Optional[str] = None, orders_in_queue: Optional[int] = None) -> None:
        current_time_min = self.env.now / 60
        hours = int(current_time_min // 60) + 7
        minutes = int(current_time_min % 60)
        time_str = f"{hours:02d}:{minutes:02d}"
        entry = {
            "timestamp_s": self.env.now,
            "time_str": time_str,
            "activity_type": activity_type,
            "description": description,
            "order_id": order_id,
            "location": location or self.runner_location,
        }
        if orders_in_queue is not None:
            entry["orders_in_queue"] = int(orders_in_queue)
        self.activity_log.append(entry)

    def place_order(self, order: DeliveryOrder) -> None:
        order.order_placed_time = self.env.now
        # Queue length BEFORE appending this order
        prior_queue_len = len(self.order_queue)
        self.order_queue.append(order)
        queue_size = len(self.order_queue)
        if queue_size == 1:
            self.log_activity(
                "order_received",
                f"New order from Group {order.golfer_group_id} on Hole {order.hole_num} - Processing immediately",
                order.order_id,
                "clubhouse",
                orders_in_queue=prior_queue_len,
            )
        else:
            self.log_activity(
                "order_queued",
                f"New order from Group {order.golfer_group_id} on Hole {order.hole_num} - Added to queue (position {queue_size})",
                order.order_id,
                "clubhouse",
                orders_in_queue=prior_queue_len,
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

            # Periodically prune expired orders from the head/tail of the queue
            self._prune_expired_orders()

            if self.order_queue and not self.runner_busy:
                order = self.order_queue.pop(0)
                # Process order regardless of wait time - no SLA timeout during processing
                yield self.env.process(self._process_single_order(order))
            else:
                yield self.env.timeout(30)

    def _process_single_order(self, order: DeliveryOrder):  # simpy process
        self.runner_busy = True
        placed_time = order.order_placed_time if order.order_placed_time is not None else self.env.now
        # Fail immediately if order has already exceeded timeout before starting any work
        if (self.env.now - placed_time) >= self.queue_timeout_s:
            order.status = "failed"
            order.failure_reason = f"Not dispatched within {int(self.queue_timeout_s/60)} minutes"
            self.failed_orders.append(order)
            self.log_activity(
                "order_failed_timeout",
                f"Order {order.order_id} timed out before processing (>{int(self.queue_timeout_s/60)} min)",
                order.order_id,
                self.runner_location,
            )
            self.runner_busy = False
            return
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
        # Final pre-departure timeout check
        if (self.env.now - placed_time) >= self.queue_timeout_s:
            order.status = "failed"
            order.failure_reason = f"Not dispatched within {int(self.queue_timeout_s/60)} minutes"
            self.failed_orders.append(order)
            self.log_activity(
                "order_failed_timeout",
                f"Order {order.order_id} exceeded timeout before departure; discarding",
                order.order_id,
                "clubhouse",
            )
            self.runner_busy = False
            return
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
    # Optional: pass golfer groups so we can predict current hole at departure
    groups: Optional[List[Dict[str, Any]]] = None

    # Shared queue implemented using a SimPy Store for incoming orders
    order_store: Optional[simpy.Store] = None
    # Dedicated per-runner queues to enable deterministic assignment
    runner_stores: List[simpy.Store] = field(default_factory=list)

    # Derived/config fields
    clubhouse_coords: Tuple[float, float] | None = None
    service_open_s: int = 0
    service_close_s: int = 0
    hole_distance_m: Dict[int, float] | None = None
    # Configured queue timeout
    queue_timeout_s: int = 3600

    # Internal per-runner state
    runner_locations: List[str] = field(default_factory=list)
    runner_busy: List[bool] = field(default_factory=list)
    # Derived helpers for prediction
    _tee_time_by_group: Dict[int, int] = field(default_factory=dict)
    _nodes_per_hole: int = 12
    # Connected points from holes_connected and hole line geometries for prediction/mapping
    _loop_points: List[Tuple[float, float]] = field(default_factory=list)
    _loop_holes: List[Optional[int]] = field(default_factory=list)
    _hole_lines: Dict[int, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.prep_time_s = int(self.prep_time_min) * 60
        self._load_course_config()
        self.order_store = simpy.Store(self.env)
        # Initialize runner locations to clubhouse
        self.runner_locations = ["clubhouse" for _ in range(int(self.num_runners))]
        # Initialize busy flags and per-runner queues
        self.runner_busy = [False for _ in range(int(self.num_runners))]
        self.runner_stores = [simpy.Store(self.env) for _ in range(int(self.num_runners))]
        # Start runner processes
        for idx in range(int(self.num_runners)):
            self.env.process(self._runner_loop(idx))
        # Start dispatcher process to assign orders to runners with priority by index
        self.env.process(self._dispatch_loop())
        # Build lookup maps if groups provided
        try:
            if self.groups:
                self._tee_time_by_group = {
                    int(g.get("group_id")): int(g.get("tee_time_s", 0))
                    for g in self.groups
                    if g is not None and g.get("group_id") is not None
                }
        except Exception:
            self._tee_time_by_group = {}
        # Estimate nodes-per-hole from holes_connected.geojson (1 min per node pacing)
        try:
            import json as _json
            path = Path(self.course_dir) / "geojson" / "generated" / "holes_connected.geojson"
            total_nodes = 0
            if path.exists():
                gj = _json.loads(path.read_text(encoding="utf-8"))
                total_nodes = len([
                    f for f in (gj.get("features") or [])
                    if (f.get("geometry") or {}).get("type") == "Point"
                ])
            self._nodes_per_hole = max(1, int(round(float(total_nodes or (18 * 12)) / 18.0)))
        except Exception:
            self._nodes_per_hole = 12

        # Load holes_connected points (idx network) and hole line geometries for mapping and prediction
        try:
            self._loop_points, self._loop_holes = self._load_connected_points()
        except Exception:
            self._loop_points, self._loop_holes = [], []
        try:
            self._hole_lines = self._load_hole_lines()
        except Exception:
            self._hole_lines = {}

    def _dispatch_loop(self):  # simpy process
        """Assign incoming orders to available runners with deterministic tie-breaking.

        Rule: Among available runners, choose the lowest index first
        (e.g., if runner_2 and runner_3 are both available, pick runner_2).
        """
        while True:
            # Stop condition: after close and no pending orders and all runners idle
            if (
                self.env.now > self.service_close_s
                and len(self.order_store.items) == 0
                and all(not self.runner_stores[i].items for i in range(int(self.num_runners)))
            ):
                break

            # Wait briefly if no orders or no runner available
            if len(self.order_store.items) == 0 or not any(not b for b in self.runner_busy):
                yield self.env.timeout(5)
                continue

            # Pop next order and assign to the lowest-index available runner
            order: DeliveryOrder = yield self.order_store.get()
            try:
                runner_index = next(i for i, busy in enumerate(self.runner_busy) if not busy)
            except StopIteration:
                # No runner available after get (race). Requeue order and wait a bit
                self.order_store.items.insert(0, order)  # place back at front
                yield self.env.timeout(5)
                continue

            self.runner_busy[runner_index] = True
            runner_label = f"runner_{runner_index + 1}"
            self.log_activity(
                "order_assigned",
                f"Assigned Order {order.order_id} to {runner_label}",
                runner_id=runner_label,
                order_id=order.order_id,
                location=self.runner_locations[runner_index],
            )
            # Place order into the selected runner's personal queue
            self.runner_stores[runner_index].put(order)

    def _load_course_config(self) -> None:
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
        # Start background expiration sweeper
        self.env.process(self._expiration_sweeper())

    def _expiration_sweeper(self):  # simpy process
        """Periodically remove expired orders from shared and per-runner queues."""
        while True:
            # Stop sweeper after close and all queues empty
            if (
                self.env.now > self.service_close_s
                and len(self.order_store.items) == 0
                and all(not q.items for q in self.runner_stores)
            ):
                return
            # Sweep shared queue
            if self.order_store is not None and self.order_store.items:
                kept: List[DeliveryOrder] = []
                for o in list(self.order_store.items):
                    placed = o.order_placed_time if o.order_placed_time is not None else self.env.now
                    if (self.env.now - placed) >= self.queue_timeout_s:
                        o.status = "failed"
                        o.failure_reason = f"Not dispatched within {int(self.queue_timeout_s/60)} minutes"
                        self.failed_orders.append(o)
                        try:
                            self.order_store.items.remove(o)
                        except ValueError:
                            pass
                        self.log_activity(
                            "order_failed_timeout",
                            f"Order {o.order_id} timed out in dispatcher queue; removed",
                            runner_id=None,
                            order_id=o.order_id,
                            location="clubhouse",
                            orders_in_queue=len(self.order_store.items),
                        )
                    else:
                        kept.append(o)
            # Sweep per-runner queues
            for idx, q in enumerate(self.runner_stores):
                if not q.items:
                    continue
                for o in list(q.items):
                    placed = o.order_placed_time if o.order_placed_time is not None else self.env.now
                    if (self.env.now - placed) >= self.queue_timeout_s:
                        o.status = "failed"
                        o.failure_reason = f"Not dispatched within {int(self.queue_timeout_s/60)} minutes"
                        self.failed_orders.append(o)
                        try:
                            q.items.remove(o)
                        except ValueError:
                            pass
                        self.log_activity(
                            "order_failed_timeout",
                            f"Order {o.order_id} timed out before runner departure; removed from {f'runner_{idx+1}'} queue",
                            runner_id=f"runner_{idx+1}",
                            order_id=o.order_id,
                            location=self.runner_locations[idx],
                            orders_in_queue=len(q.items),
                        )
            # Sleep until next sweep
            yield self.env.timeout(30)

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

    def log_activity(self, activity_type: str, description: str, runner_id: Optional[str] = None, order_id: str | None = None, location: Optional[str] = None, orders_in_queue: Optional[int] = None) -> None:
        current_time_min = self.env.now / 60
        hours = int(current_time_min // 60) + 7
        minutes = int(current_time_min % 60)
        time_str = f"{hours:02d}:{minutes:02d}"
        entry = {
            "timestamp_s": self.env.now,
            "time_str": time_str,
            "activity_type": activity_type,
            "description": description,
            "runner_id": runner_id,
            "order_id": order_id,
            "location": location,
        }
        if orders_in_queue is not None:
            entry["orders_in_queue"] = int(orders_in_queue)
        self.activity_log.append(entry)

    def place_order(self, order: DeliveryOrder) -> None:
        order.order_placed_time = self.env.now
        # Capture queue length BEFORE placing this order
        try:
            prior_len = len(self.order_store.items)
        except Exception:
            prior_len = None
        # Note: store.put returns an event; we don't need to wait on it here
        self.order_store.put(order)
        self.log_activity(
            "order_received",
            f"New order from Group {order.golfer_group_id} on Hole {order.hole_num}",
            runner_id=None,
            order_id=order.order_id,
            location="clubhouse",
            orders_in_queue=prior_len,
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
            # Stop condition: after close and personal queue empty
            if self.env.now > self.service_close_s and len(self.runner_stores[runner_index].items) == 0:
                self.log_activity("service_closed", f"{runner_label} shift ended", runner_id=runner_label, location=self.runner_locations[runner_index])
                break

            # Wait for an order assigned to this runner
            order: DeliveryOrder = yield self.runner_stores[runner_index].get()

            # Process the order (timeout checks handled in processing)
            yield self.env.process(self._process_single_order(order, runner_index, runner_label))

    def _process_single_order(self, order: DeliveryOrder, runner_index: int, runner_label: str):  # simpy process
        # If not at clubhouse, return first
        placed_time = order.order_placed_time if order.order_placed_time is not None else self.env.now
        # Early timeout check before doing any work
        if (self.env.now - placed_time) >= self.queue_timeout_s:
            order.status = "failed"
            order.failure_reason = f"Not dispatched within {int(self.queue_timeout_s/60)} minutes"
            self.failed_orders.append(order)
            self.log_activity(
                "order_failed_timeout",
                f"{runner_label} received expired order {order.order_id}; discarding",
                runner_id=runner_label,
                order_id=order.order_id,
                location=self.runner_locations[runner_index],
            )
            self.runner_busy[runner_index] = False
            return
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

        # Predict an intercept hole considering prep time, runner travel time, and golfer progression
        target_hole = self._choose_intercept_hole(order)

        # Predict precise delivery coordinates using cart graph and hole lines
        predicted_coords: Optional[Tuple[float, float]] = None
        try:
            from .engine import predict_optimal_delivery_location, enhanced_delivery_routing
            predicted_coords = predict_optimal_delivery_location(
                order_hole=int(order.hole_num),
                prep_time_min=float(self.prep_time_s) / 60.0,
                travel_time_s=0.0,
                hole_lines=self._hole_lines,
                course_dir=self.course_dir,
                runner_speed_mps=float(self.runner_speed_mps),
                order_time_s=float(getattr(order, "order_time_s", self.env.now) or self.env.now),
                clubhouse_lonlat=self.clubhouse_coords,
            )
        except Exception:
            predicted_coords = None

        trip_to_golfer = None
        trip_back = None
        delivery_distance_m = 0.0
        delivery_time_s = 0.0
        delivered_hole_num = int(target_hole)
        try:
            if predicted_coords and predicted_coords[0] != 0 and predicted_coords[1] != 0:
                # Route to predicted coords using enhanced graph
                from .engine import enhanced_delivery_routing
                import pickle
                cart_graph = None
                try:
                    with open((Path(self.course_dir) / "pkl" / "cart_graph.pkl"), "rb") as f:
                        cart_graph = pickle.load(f)
                except Exception:
                    cart_graph = None
                if cart_graph is not None:
                    trip_to_golfer = enhanced_delivery_routing(
                        cart_graph, self.clubhouse_coords, predicted_coords, self.runner_speed_mps
                    )
                    trip_back = enhanced_delivery_routing(
                        cart_graph, predicted_coords, self.clubhouse_coords, self.runner_speed_mps
                    )
                    delivery_distance_m = float(trip_to_golfer.get("length_m", 0.0) + trip_back.get("length_m", 0.0))
                    delivery_time_s = float(trip_to_golfer.get("time_s", 0.0))
                    # Map predicted coords to nearest hole via holes_connected idx network
                    delivered_hole_num = self._nearest_hole_from_coords(predicted_coords[0], predicted_coords[1]) or delivered_hole_num
                else:
                    # Fallback to hole-based enhanced routing
                    delivery_route_data = self._calculate_enhanced_delivery_route(target_hole)
                    delivery_distance_m = delivery_route_data["delivery_distance_m"]
                    delivery_time_s = delivery_route_data["delivery_time_s"]
                    trip_to_golfer = delivery_route_data.get("trip_to_golfer")
                    trip_back = delivery_route_data.get("trip_back")
                    delivered_hole_num = int(target_hole)
            else:
                # Fallback when prediction not available
                delivery_route_data = self._calculate_enhanced_delivery_route(target_hole)
                delivery_distance_m = delivery_route_data["delivery_distance_m"]
                delivery_time_s = delivery_route_data["delivery_time_s"]
                trip_to_golfer = delivery_route_data.get("trip_to_golfer")
                trip_back = delivery_route_data.get("trip_back")
                delivered_hole_num = int(target_hole)
        except Exception:
            # As a last resort, fall back to simple delivery details
            distance_m, time_s = self._calculate_delivery_details(int(target_hole))
            delivery_distance_m = float(distance_m)
            delivery_time_s = float(time_s)
            delivered_hole_num = int(target_hole)
        
        # Final pre-departure timeout check
        if (self.env.now - placed_time) >= self.queue_timeout_s:
            order.status = "failed"
            order.failure_reason = f"Not dispatched within {int(self.queue_timeout_s/60)} minutes"
            self.failed_orders.append(order)
            self.log_activity(
                "order_failed_timeout",
                f"{runner_label} exceeded timeout before departure for Order {order.order_id}; discarding",
                runner_id=runner_label,
                order_id=order.order_id,
                location="clubhouse",
            )
            self.runner_busy[runner_index] = False
            return

        order.delivery_started_time = self.env.now
        self.log_activity("delivery_start", f"{runner_label} departing to Hole {delivered_hole_num} ({delivery_distance_m:.0f}m, {delivery_time_s/60:.1f} min)", runner_id=runner_label, order_id=order.order_id, location="clubhouse")
        yield self.env.timeout(delivery_time_s)
        order.delivered_time = self.env.now
        self.runner_locations[runner_index] = f"hole_{delivered_hole_num}"

        placed_time = order.order_placed_time if order.order_placed_time is not None else order.delivered_time
        order.total_completion_time_s = order.delivered_time - placed_time
        return_time_s = self._calculate_return_time(self.runner_locations[runner_index])
        total_drive_time_s = delivery_time_s + return_time_s
        self.log_activity("delivery_complete", f"{runner_label} delivered Order {order.order_id} to Hole {delivered_hole_num} (Total completion: {order.total_completion_time_s/60:.1f} min)", runner_id=runner_label, order_id=order.order_id, location=self.runner_locations[runner_index])

        # Immediately return to clubhouse after delivery so next order does not inherit the return as queue wait
        if return_time_s > 0:
            self.log_activity("returning", f"{runner_label} returning to clubhouse from {self.runner_locations[runner_index]} ({return_time_s/60:.1f} min)", runner_id=runner_label, order_id=order.order_id, location=self.runner_locations[runner_index])
            yield self.env.timeout(return_time_s)
            self.runner_locations[runner_index] = "clubhouse"
            self.log_activity("arrived_clubhouse", f"{runner_label} arrived at clubhouse after delivering Order {order.order_id}", runner_id=runner_label, order_id=order.order_id, location="clubhouse")
        order.status = "processed"
        delivery_stats_entry = {
            "order_id": order.order_id,
            "golfer_group_id": order.golfer_group_id,
            # Delivered hole (predicted at departure)
            "hole_num": int(delivered_hole_num),
            # Original placed hole for reference
            "placed_hole_num": int(order.hole_num),
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
        # Add routing data for visualization if available
        if trip_to_golfer:
            delivery_stats_entry["trip_to_golfer"] = trip_to_golfer
        if trip_back:
            delivery_stats_entry["trip_back"] = trip_back
        if predicted_coords:
            delivery_stats_entry["predicted_delivery_location"] = [float(predicted_coords[0]), float(predicted_coords[1])]
            
        self.delivery_stats.append(delivery_stats_entry)
        # Mark runner available for next assignment
        self.runner_busy[runner_index] = False

    def _choose_intercept_hole(self, order: DeliveryOrder) -> int:
        """
        Choose an intercept hole ahead of the golfer based on:
        - Current golfer progression from tee time (1 minute per node pacing)
        - Runner outbound travel time to each candidate hole
        - Aim to minimize the mismatch between runner arrival and golfer arrival at the hole

        Always clamps to at least the placed hole; favors arriving slightly before golfer.
        """
        placed_hole = int(getattr(order, "hole_num", 1) or 1)
        nodes_per_hole = max(1, int(self._nodes_per_hole))

        # Estimate golfer's current progress (in minutes) since tee at departure time
        current_delta_min = 0
        try:
            if self._tee_time_by_group:
                gtee = int(self._tee_time_by_group.get(int(order.golfer_group_id), 0))
                current_delta_min = max(0, int((self.env.now - gtee) // 60))
        except Exception:
            current_delta_min = 0

        # Start considering holes from the max of placed hole and current progress-derived hole
        progress_hole = 1 + int(current_delta_min // nodes_per_hole)
        start_hole = max(placed_hole, max(1, min(18, progress_hole)))

        best_hole = start_hole
        best_score = float("inf")

        for candidate in range(start_hole, 19):
            try:
                # Runner travel time to candidate hole (minutes)
                _, travel_time_s = self._calculate_delivery_details(candidate)
                runner_time_min = max(0.0, float(travel_time_s) / 60.0)

                # Golfer time remaining (minutes) until candidate hole from current progress
                golfer_arrival_min = (candidate - 1) * nodes_per_hole
                golfer_time_remaining_min = max(0, int(golfer_arrival_min - current_delta_min))

                # Penalize arriving after the golfer more heavily
                lateness = max(0.0, runner_time_min - float(golfer_time_remaining_min))
                earliness = max(0.0, float(golfer_time_remaining_min) - runner_time_min)
                # Weight late arrivals 3x compared to earliness
                score = (3.0 * lateness) + (1.0 * earliness)

                if score < best_score - 1e-6:
                    best_score = score
                    best_hole = candidate
            except Exception:
                continue

        # Ensure within [1, 18]
        return int(max(1, min(18, best_hole)))

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

    def _load_connected_points(self) -> tuple[List[Tuple[float, float]], List[Optional[int]]]:
        """Load per-minute loop points and hole labels from holes_connected.geojson for hole mapping."""
        import json
        coords: List[Tuple[float, float]] = []
        hole_nums: List[Optional[int]] = []
        path = Path(self.course_dir) / "geojson" / "generated" / "holes_connected.geojson"
        if not path.exists():
            return [], []
        data = json.loads(path.read_text(encoding="utf-8"))
        features = data.get("features", []) if isinstance(data, dict) else []
        for feat in features:
            if not isinstance(feat, dict):
                continue
            geom = feat.get("geometry") or {}
            if geom.get("type") != "Point":
                continue
            coords_xy = geom.get("coordinates") or []
            if not isinstance(coords_xy, (list, tuple)) or len(coords_xy) < 2:
                continue
            lon = float(coords_xy[0]); lat = float(coords_xy[1])
            props = feat.get("properties") or {}
            hn = props.get("hole_number") or props.get("hole") or props.get("hole_num") or props.get("current_hole")
            try:
                hole_num = int(hn) if hn is not None else None
            except Exception:
                hole_num = None
            coords.append((lon, lat))
            hole_nums.append(hole_num)
        return coords, hole_nums

    def _load_hole_lines(self) -> Dict[int, Any]:
        """Load hole LineString geometries keyed by hole number."""
        from ..viz.matplotlib_viz import load_course_geospatial_data
        hole_lines: Dict[int, Any] = {}
        course_data = load_course_geospatial_data(self.course_dir)
        holes_gdf = course_data.get("holes")
        if holes_gdf is None:
            return {}
        for _, hole in holes_gdf.iterrows():
            hole_ref = hole.get("ref", str(hole.name + 1))
            try:
                hole_id = int(hole_ref)
            except Exception:
                continue
            geom = hole.geometry
            if geom is not None:
                hole_lines[hole_id] = geom
        return hole_lines

    @staticmethod
    def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
        import math
        phi1 = math.radians(lat1); phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1); dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return 6371000.0 * c

    def _nearest_hole_from_coords(self, lon: float, lat: float) -> Optional[int]:
        """Map a coordinate to the nearest hole using holes_connected point index mapping.

        Falls back to simple vacancy if labels are missing.
        """
        if not self._loop_points:
            return None
        best_idx = -1
        best_d = float("inf")
        for idx, (px, py) in enumerate(self._loop_points):
            d = self._haversine_m(lon, lat, px, py)
            if d < best_d:
                best_d = d
                best_idx = idx
        if best_idx < 0:
            return None
        try:
            hn = self._loop_holes[best_idx] if best_idx < len(self._loop_holes) else None
            return int(hn) if hn is not None else None
        except Exception:
            return None

    def _calculate_enhanced_delivery_route(self, hole_num: int) -> Dict:
        """Calculate enhanced delivery route with actual path data for visualization."""
        try:
            # Load cart graph for enhanced routing
            import pickle
            from pathlib import Path
            from .engine import enhanced_delivery_routing
            
            cart_graph_path = Path(self.course_dir) / "pkl" / "cart_graph.pkl"
            if not cart_graph_path.exists():
                # Fall back to simple calculation if no cart graph
                distance_m, travel_time_s = self._calculate_delivery_details(hole_num)
                return {
                    "delivery_distance_m": distance_m,
                    "delivery_time_s": travel_time_s,
                }
            
            with open(cart_graph_path, 'rb') as f:
                cart_graph = pickle.load(f)
            
            # Get hole location for routing
            hole_location = self._get_hole_location(hole_num)
            if not hole_location:
                # Fall back to simple calculation if no hole location
                distance_m, travel_time_s = self._calculate_delivery_details(hole_num)
                return {
                    "delivery_distance_m": distance_m,
                    "delivery_time_s": travel_time_s,
                }
            
            # Calculate trip to golfer
            trip_to_golfer = enhanced_delivery_routing(
                cart_graph, self.clubhouse_coords, hole_location, self.runner_speed_mps
            )
            
            # Calculate return trip
            trip_back = enhanced_delivery_routing(
                cart_graph, hole_location, self.clubhouse_coords, self.runner_speed_mps
            )
            
            # Total delivery metrics
            total_distance_m = trip_to_golfer["length_m"] + trip_back["length_m"]
            total_time_s = trip_to_golfer["time_s"] + trip_back["time_s"]
            
            return {
                "delivery_distance_m": total_distance_m,
                "delivery_time_s": trip_to_golfer["time_s"],  # Only outbound time for simulation
                "trip_to_golfer": trip_to_golfer,
                "trip_back": trip_back,
            }
            
        except Exception as e:
            # Fail loudly: enhanced routing is required for delivery timing
            raise RuntimeError(f"Enhanced routing failed for hole {hole_num}: {e}")

    def _get_hole_location(self, hole_num: int) -> Optional[Tuple[float, float]]:
        """Get the coordinates for a hole based on course geospatial data."""
        try:
            from ..viz.matplotlib_viz import load_course_geospatial_data
            
            course_data = load_course_geospatial_data(self.course_dir)
            if 'holes' not in course_data:
                return None
                
            holes_gdf = course_data['holes']
            for _, hole in holes_gdf.iterrows():
                hole_ref = hole.get('ref', str(hole.name + 1))
                try:
                    hole_id = int(hole_ref)
                    if hole_id == hole_num:
                        if hole.geometry.geom_type == "LineString":
                            # Use midpoint of hole as delivery location
                            midpoint = hole.geometry.interpolate(0.5, normalized=True)
                            return (midpoint.x, midpoint.y)
                        elif hasattr(hole.geometry, 'centroid'):
                            return (hole.geometry.centroid.x, hole.geometry.centroid.y)
                except (ValueError, TypeError):
                    continue
            return None
            
        except Exception as e:
            logger.warning("Failed to get hole location for hole %d: %s", hole_num, e)
            return None

def simulate_golfer_orders(groups: List[Dict], order_probability_per_9_holes: float, rng_seed: Optional[int] = None, *, course_dir: Optional[str] = None) -> List[DeliveryOrder]:
    """Generate delivery orders on a per-group, per-9-holes basis.

    Semantics:
    - Each group has up to two independent chances to place an order: once on the front nine (holes 1–9)
      and once on the back nine (holes 10–18).
    - The probability for each nine is `order_probability_per_9_holes`.
    - Order times are aligned to a random hole within the corresponding nine using ~12 min/hole pacing.
    - Number of golfers in a group is ignored for order generation.
    
    Parameters:
    - rng_seed: Optional random seed for deterministic order generation (for exact replay)
    """
    import random
    
    # Seed the random number generator if provided
    if rng_seed is not None:
        random.seed(rng_seed)

    orders: List[DeliveryOrder] = []
    # Derive node-based pacing from holes_connected.geojson (1 min per node)
    try:
        from pathlib import Path
        import json as _json
        if course_dir:
            data = _json.loads((Path(course_dir) / "geojson" / "generated" / "holes_connected.geojson").read_text(encoding="utf-8"))
            total_nodes = len([f for f in (data.get("features") or []) if (f.get("geometry") or {}).get("type") == "Point"]) or 18 * 12
        else:
            total_nodes = 18 * 12
    except Exception:
        total_nodes = 18 * 12
    nodes_per_hole = max(1, int(round(float(total_nodes) / 18.0)))

    for group in groups:
        group_id = group["group_id"]
        tee_time_s = group["tee_time_s"]

        # Front nine (holes 1..9)
        if random.random() < order_probability_per_9_holes:
            hole_front = int(random.randint(1, 9))
            start_node = int(round((hole_front - 1) * nodes_per_hole))
            order_time_front_s = tee_time_s + start_node * 60
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
            start_node = int(round((hole_back - 1) * nodes_per_hole))
            order_time_back_s = tee_time_s + start_node * 60
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
    # Deprecated: timing now derived from node-per-minute pacing
    bev_cart_18_holes_minutes: int = 180

    def __post_init__(self) -> None:
        self._load_course_config()
        if self.track_coordinates:
            self.env.process(self.beverage_cart_process())

    def _load_course_config(self) -> None:
        sim_cfg = load_simulation_config(self.course_dir)
        self.clubhouse_coords = sim_cfg.clubhouse
        # Deprecated: ignore bev_cart_18_holes_minutes; pacing is one node per minute backward
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
        # Deprecated informational log removed (fixed node pacing)

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

    def _load_connected_points(self) -> tuple[list[tuple[float, float]], list[int | None]]:
        """Load per-minute loop points from holes_connected.geojson.

        Returns:
            (coords_lonlat, hole_numbers)
        """
        import json
        # Local imports to avoid module-level dependency cycles
        try:
            from golfsim.simulation.crossings import load_holes_geojson, locate_hole_for_point  # type: ignore
        except Exception:
            load_holes_geojson = None  # type: ignore
            locate_hole_for_point = None  # type: ignore
        coords: list[tuple[float, float]] = []
        hole_nums: list[int | None] = []
        path = Path(self.course_dir) / "geojson" / "generated" / "holes_connected.geojson"
        if not path.exists():
            return [], []
        data = json.loads(path.read_text(encoding="utf-8"))
        features = data.get("features", []) if isinstance(data, dict) else []
        # Optional hole polygons for labeling when Point properties absent
        holes_fc = None
        try:
            if load_holes_geojson is not None:
                holes_path = Path(self.course_dir) / "geojson" / "generated" / "holes_geofenced.geojson"
                if holes_path.exists():
                    holes_fc = load_holes_geojson(str(holes_path))
        except Exception:
            holes_fc = None

        # Use Point features only (no LineString resampling) and use embedded hole labels or polygon fallback
        for feat in features:
            if not isinstance(feat, dict):
                continue
            geom = feat.get("geometry") or {}
            if geom.get("type") != "Point":
                continue
            coords_xy = geom.get("coordinates") or []
            if not isinstance(coords_xy, (list, tuple)) or len(coords_xy) < 2:
                continue
            lon = float(coords_xy[0])
            lat = float(coords_xy[1])
            props = feat.get("properties") or {}
            hn = (
                props.get("hole_number")
                or props.get("hole")
                or props.get("hole_num")
                or props.get("current_hole")
            )
            hole_num = None
            try:
                hole_num = int(hn) if hn is not None else None
            except Exception:
                hole_num = None
            if hole_num is None and holes_fc is not None and locate_hole_for_point is not None:
                try:
                    hole_num = locate_hole_for_point(lon=lon, lat=lat, holes=holes_fc)
                except Exception:
                    hole_num = None
            coords.append((lon, lat))
            hole_nums.append(hole_num)
        return coords, hole_nums

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

    def _load_or_build_loop_points(self) -> tuple[list[tuple[float, float]], list[int | None]]:
        """Load per-minute loop points and hole labels from holes_connected.geojson."""
        coords, holes = self._load_connected_points()
        if coords:
            logger.info("Loaded %d loop points from holes_connected.geojson", len(coords))
            return coords, holes
        logger.warning("holes_connected.geojson missing or empty; no loop points loaded")
        return [], []

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
            loop_points, loop_holes = self._load_or_build_loop_points()

            # Hole lines no longer required; hole labels come from holes_connected.geojson

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
                points = list(reversed(loop_points))  # beverage cart traverses reverse
                holes = list(reversed(loop_holes)) if loop_holes else [None] * len(points)
                num_points = len(points)
                # Align number of timestamps to available points
                # Cycle through points if service window exceeds one loop
                for i, t in enumerate(timestamps[1:]):
                    idx = i % num_points
                    lon, lat = points[idx]
                    current_hole = holes[idx] if idx < len(holes) else None
                    self.coordinates.append(
                        {
                            "latitude": float(lat),
                            "longitude": float(lon),
                            "timestamp": int(t),
                            "type": "bev_cart",
                            "current_hole": current_hole,
                        }
                    )

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
    rng_seed: Optional[int] = None,
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
    orders = simulate_golfer_orders(groups, order_probability_per_9_holes, rng_seed=rng_seed)

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
            
            # Create individual delivery visualizations unless disabled
            if not bool(getattr(results, "no_individual_plots", False)):
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
