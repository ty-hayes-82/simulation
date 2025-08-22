from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import simpy

from ..config.models import SimulationConfig
from ..logging import get_logger

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
    status: str = "pending"
    failure_reason: Optional[str] = None


@dataclass
class DeliveryService:
    env: simpy.Environment
    config: SimulationConfig
    num_runners: int
    prep_time_min: int
    runner_speed_mps: float
    groups: Optional[List[Dict[str, Any]]] = None

    activity_log: List[Dict] = field(default_factory=list)
    delivery_stats: List[Dict] = field(default_factory=list)
    failed_orders: List[DeliveryOrder] = field(default_factory=list)

    order_store: Optional[simpy.Store] = None
    runner_stores: List[simpy.Store] = field(default_factory=list)

    clubhouse_coords: Tuple[float, float] | None = None
    service_open_s: int = 0
    service_close_s: int = 0
    hole_distance_m: Dict[int, float] | None = None
    queue_timeout_s: int = 3600

    runner_locations: List[str] = field(default_factory=list)
    runner_busy: List[bool] = field(default_factory=list)

    _tee_time_by_group: Dict[int, int] = field(default_factory=dict)
    _nodes_per_hole: int = 12
    _loop_points: List[Tuple[float, float]] = field(default_factory=list)
    _loop_holes: List[Optional[int]] = field(default_factory=list)
    _hole_lines: Dict[int, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.prep_time_s = self.prep_time_min * 60
        self._setup_from_config()
        self.order_store = simpy.Store(self.env)

        self.runner_locations = ["clubhouse"] * self.num_runners
        self.runner_busy = [False] * self.num_runners
        self.runner_stores = [simpy.Store(self.env) for _ in range(self.num_runners)]

        for idx in range(self.num_runners):
            self.env.process(self._runner_loop(idx))

        if self.num_runners > 0:
            self.env.process(self._dispatch_loop())

    def _setup_from_config(self) -> None:
        pass

    def _dispatch_loop(self):
        """Assigns orders to available runners."""
        while True:
            if not self.order_store.items:
                yield self.env.timeout(1)
                continue

            runner_index = -1
            for i, busy in enumerate(self.runner_busy):
                if not busy:
                    runner_index = i
                    break
            
            if runner_index != -1:
                order = yield self.order_store.get()
                self.runner_busy[runner_index] = True
                self.runner_stores[runner_index].put(order)
            else:
                yield self.env.timeout(1)

    def _runner_loop(self, runner_index: int):
        """A runner process that handles orders from its personal queue."""
        while True:
            order = yield self.runner_stores[runner_index].get()
            # Simulate processing time
            yield self.env.timeout(self.prep_time_s)
            self.delivery_stats.append({"order_id": order.order_id, "status": "processed"})
            self.runner_busy[runner_index] = False

    def place_order(self, order: DeliveryOrder) -> None:
        """Places an order in the main queue."""
        self.order_store.put(order)

    def log_activity(self, activity_type: str, description: str, runner_id: Optional[str] = None, order_id: str | None = None, location: Optional[str] = None, orders_in_queue: Optional[int] = None) -> None:
        """Logs an activity."""
        self.activity_log.append({
            "activity_type": activity_type,
            "description": description,
            "runner_id": runner_id,
            "order_id": order_id,
            "location": location,
            "orders_in_queue": orders_in_queue
        })
