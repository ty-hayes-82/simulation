from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .delivery_service_base import BaseDeliveryService, DeliveryOrder


@dataclass
class SingleRunnerDeliveryService(BaseDeliveryService):
    order_queue: List[DeliveryOrder] = field(default_factory=list)
    # Internal runtime state
    runner_busy: bool = False
    runner_location: str = "clubhouse"

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
                    f"Order {o.order_id} exceeded timeout before departure; discarding",
                    o.order_id,
                    "clubhouse",
                )
                self.runner_busy = False
                return
            else:
                kept.append(o)
        self.order_queue = kept

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
                f"Order {order.order_id} exceeded timeout before processing (>{int(self.queue_timeout_s/60)} min)",
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
            return_time = self._calculate_return_time(self.runner_location)
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
        return_time_s = self._calculate_return_time(self.runner_location)
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
