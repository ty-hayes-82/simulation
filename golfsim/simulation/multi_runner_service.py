from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import simpy

from ..logging import get_logger
from .. import utils
from .delivery_service_base import BaseDeliveryService, DeliveryOrder


logger = get_logger(__name__)


@dataclass
class MultiRunnerDeliveryService(BaseDeliveryService):
    num_runners: int = 2
    # Optional: pass golfer groups so we can predict current hole at departure
    groups: Optional[List[Dict[str, Any]]] = None
    time_quantum_s: int = 60

    # Shared queue implemented using a SimPy Store for incoming orders
    order_store: Optional[simpy.Store] = None
    # Dedicated per-runner queues to enable deterministic assignment
    runner_stores: List[simpy.Store] = field(default_factory=list)
    order_timing_logs: List[Dict] = field(default_factory=list)

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
        self.prep_time_s = self.prep_time_min * 60
        self._load_course_config()
        self._load_node_travel_times()  # New method to load node travel times
        self._init_runner_stores_and_processes()
        self._init_group_tee_times()
        self._loop_points, self._loop_holes = utils.load_connected_points(self.course_dir)

    def _init_runner_stores_and_processes(self) -> None:
        """Initialize per-runner data structures and simulation processes."""
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

    def _init_group_tee_times(self) -> None:
        """Initialize a lookup for group tee times for faster access."""
        if self.groups:
            self._tee_time_by_group = {
                int(g.get("group_id")): int(g.get("tee_time_s", 0))
                for g in self.groups
                if g is not None and g.get("group_id") is not None
            }
        else:
            self._tee_time_by_group = {}

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

    def _nearest_hole_from_coords(self, lon: float, lat: float) -> Optional[int]:
        """Map a coordinate to the nearest hole using holes_connected point index mapping.

        Falls back to simple vacancy if labels are missing.
        """
        if not self._loop_points:
            return None
        best_idx = -1
        best_d = float("inf")
        for idx, (px, py) in enumerate(self._loop_points):
            d = utils.haversine_m(lon, lat, px, py)
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

    def _calculate_delivery_route(self, order: DeliveryOrder, target_hole: int, predicted_coords: Optional[Tuple[float, float]]) -> Dict[str, Any]:
        """Calculate the delivery route for an order.
        
        This method determines the best path using the node index from the course graph.
        If a path cannot be determined for any reason, the method raises an exception
        to fail loudly rather than using fallback logic.
        
        Args:
            order: The delivery order
            target_hole: The target hole number for delivery
            predicted_coords: Optional predicted delivery coordinates
            
        Returns:
            Dict containing:
                - delivery_distance_m: Total delivery distance in meters
                - delivery_time_s: Outbound delivery time in seconds  
                - delivered_hole_num: Final hole number for delivery
                - trip_to_golfer: Optional routing data for outbound trip
                - trip_back: Optional routing data for return trip
                - predicted_delivery_location: Optional predicted coordinates
                
        Raises:
            Exception: If routing fails and no valid path can be determined
        """
        trip_to_golfer = None
        trip_back = None
        delivery_distance_m = 0.0
        delivery_time_s = 0.0
        delivered_hole_num = int(target_hole)
        
        logger.debug(f"Delivery routing debug: predicted_coords={predicted_coords}, target_hole={target_hole}")

        # Treat predictions that land at (or extremely near) the clubhouse as invalid.
        # Routing clubhouse→clubhouse yields zero-length paths which break downstream metrics.
        predicted_is_valid = False
        try:
            if (
                predicted_coords
                and predicted_coords[0] != 0
                and predicted_coords[1] != 0
                and self.clubhouse_coords is not None
            ):
                dx = (float(predicted_coords[0]) - float(self.clubhouse_coords[0])) * 111139.0
                dy = (float(predicted_coords[1]) - float(self.clubhouse_coords[1])) * 111139.0
                dist_to_clubhouse_m = (dx * dx + dy * dy) ** 0.5
                # If within 3 meters of clubhouse, deem invalid and fall back to hole-based routing
                predicted_is_valid = dist_to_clubhouse_m > 3.0
        except Exception:
            predicted_is_valid = False
        
        
        if predicted_is_valid:
            logger.debug("Using predicted coordinates routing path")
            # Route to predicted coords using enhanced graph
            from .engine import enhanced_delivery_routing
            import pickle
            from pathlib import Path
            
            cart_graph = None
            try:
                with open((Path(self.course_dir) / "pkl" / "cart_graph.pkl"), "rb") as f:
                    cart_graph = pickle.load(f)
                    logger.debug(f"Loaded cart graph with {cart_graph.number_of_nodes()} nodes")
            except Exception as e:
                logger.debug(f"Failed to load cart graph: {e}")
                raise Exception(f"Cannot load cart graph for routing: {e}")
                
            if cart_graph is not None:
                try:
                    trip_to_golfer = enhanced_delivery_routing(
                        cart_graph, self.clubhouse_coords, predicted_coords, self.runner_speed_mps
                    )
                    trip_back = enhanced_delivery_routing(
                        cart_graph, predicted_coords, self.clubhouse_coords, self.runner_speed_mps
                    )
                    delivery_distance_m = float(trip_to_golfer.get("length_m", 0.0) + trip_back.get("length_m", 0.0))
                    delivery_time_s = float(trip_to_golfer.get("time_s", 0.0))
                    logger.debug(f"Predicted coords routing result: distance={delivery_distance_m}m, time={delivery_time_s}s")
                    # Map predicted coords to nearest hole via holes_connected idx network
                    delivered_hole_num = self._nearest_hole_from_coords(predicted_coords[0], predicted_coords[1]) or delivered_hole_num
                except Exception as e:
                    logger.debug(f"Enhanced routing with predicted coords failed: {e}")
                    raise Exception(f"Enhanced routing failed: {e}")
            else:
                raise Exception("Cart graph is None after loading")
        else:
            logger.debug("No valid predicted coordinates, using hole-based enhanced routing")
            # Use hole-based enhanced routing
            try:
                delivery_route_data = self._calculate_enhanced_delivery_route(target_hole)
                delivery_distance_m = delivery_route_data["delivery_distance_m"]
                delivery_time_s = delivery_route_data["delivery_time_s"]
                trip_to_golfer = delivery_route_data.get("trip_to_golfer")
                trip_back = delivery_route_data.get("trip_back")
                delivered_hole_num = int(target_hole)
                logger.debug(f"Hole-based routing result: distance={delivery_distance_m}m, time={delivery_time_s}s")
            except Exception as e:
                logger.debug(f"Hole-based enhanced routing failed: {e}")
                raise Exception(f"Hole-based routing failed: {e}")
        
        # Safety net: if outbound routing produced zero (or near-zero) time/length,
        # fall back to hole-based routing, then simple heuristics as last resort.
        try:
            zero_time = (float(delivery_time_s) <= 0.0)
            zero_length = (float(delivery_distance_m) <= 0.0)
        except Exception:
            zero_time = True
            zero_length = True
        if zero_time or zero_length:
            logger.debug("Outbound route yielded zero time/length; retrying with hole-based routing fallback")
            try:
                fallback = self._calculate_enhanced_delivery_route(target_hole)
                delivery_distance_m = float(fallback.get("delivery_distance_m", 0.0))
                delivery_time_s = float(fallback.get("delivery_time_s", 0.0))
                trip_to_golfer = fallback.get("trip_to_golfer") or trip_to_golfer
                trip_back = fallback.get("trip_back") or trip_back
                delivered_hole_num = int(target_hole)
            except Exception:
                # Final fallback to simple calculation
                d_m, t_s = self._calculate_delivery_details(int(target_hole))
                delivery_distance_m = float(d_m)
                delivery_time_s = float(t_s)
                trip_to_golfer = None
                trip_back = None

        result = {
            "delivery_distance_m": delivery_distance_m,
            "delivery_time_s": delivery_time_s,
            "delivered_hole_num": delivered_hole_num,
        }
        
        if trip_to_golfer:
            result["trip_to_golfer"] = trip_to_golfer
        if trip_back:
            result["trip_back"] = trip_back
        if predicted_coords:
            result["predicted_delivery_location"] = [float(predicted_coords[0]), float(predicted_coords[1])]
            
        return result

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
            logger.debug(f"Hole {hole_num} location: {hole_location}")
            if not hole_location:
                # Fall back to simple calculation if no hole location
                logger.debug(f"No hole location found for hole {hole_num}, using simple calculation")
                distance_m, travel_time_s = self._calculate_delivery_details(hole_num)
                return {
                    "delivery_distance_m": distance_m,
                    "delivery_time_s": travel_time_s,
                }
            
            # Calculate trip to golfer
            logger.debug(f"Routing from clubhouse {self.clubhouse_coords} to hole {hole_num} at {hole_location}")
            try:
                trip_to_golfer = enhanced_delivery_routing(
                    cart_graph, self.clubhouse_coords, hole_location, self.runner_speed_mps
                )
                logger.debug(f"Trip to golfer successful: {trip_to_golfer.get('nodes', [])[:3]}... ({len(trip_to_golfer.get('nodes', []))} nodes)")
            except Exception as e:
                logger.debug(f"Trip to golfer failed: {e}")
                raise
            
            # Calculate return trip
            try:
                trip_back = enhanced_delivery_routing(
                    cart_graph, hole_location, self.clubhouse_coords, self.runner_speed_mps
                )
                logger.debug(f"Trip back successful: {trip_back.get('nodes', [])[:3]}... ({len(trip_back.get('nodes', []))} nodes)")
            except Exception as e:
                logger.debug(f"Trip back failed: {e}")
                raise
            
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
            # Log the specific error and fall back to simple calculation
            logger.debug(f"Enhanced routing failed for hole {hole_num}: {e}")
            distance_m, travel_time_s = self._calculate_delivery_details(hole_num)
            return {
                "delivery_distance_m": distance_m,
                "delivery_time_s": travel_time_s,
            }

    def _get_hole_location(self, hole_num: int) -> Optional[Tuple[float, float]]:
        """Get the coordinates for a hole based on course geospatial data."""
        try:
            from ..viz.matplotlib_viz import load_course_geospatial_data
            
            course_data = load_course_geospatial_data(self.course_dir)
            if 'holes' not in course_data:
                return None
                
            holes_gdf = course_data['holes']
            for _, hole in holes_gdf.iterrows():
                # Try both 'hole' and 'ref' properties for compatibility
                hole_id_raw = hole.get('hole', hole.get('ref', str(hole.name + 1)))
                try:
                    hole_id = int(hole_id_raw)
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

    def place_order(self, order: DeliveryOrder) -> None:
        """Place an order in the shared queue for multi-runner processing."""
        order.order_placed_time = self.env.now
        self.order_store.put(order)

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
            
            # Add tee time to order for prediction logic
            order.tee_time_s = self._tee_time_by_group.get(order.golfer_group_id, 0)

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

        # This is the actual departure time, after any return trips and prep are completed.
        actual_departure_time_s = self.env.now
        
        # Predict an intercept hole considering prep time, runner travel time, and golfer progression
        target_hole = self._choose_intercept_hole(order)

        # Predict precise delivery coordinates using node-based system
        predicted_coords: Optional[Tuple[float, float]] = None
        order_node_idx = -1
        predicted_delivery_node_idx = -1
        try:
            from .engine import predict_optimal_delivery_location, find_nearest_node_index
            
            # Convert hole to node index (approximate: hole * nodes_per_hole)
            order_node_idx = max(0, (int(order.hole_num) - 1) * self._nodes_per_hole)
            
            # Convert order object to dict to pass to prediction function
            from dataclasses import asdict
            order_dict = asdict(order)

            predicted_coords = predict_optimal_delivery_location(
                order_node_idx=order_node_idx,
                prep_time_min=0.0, # Prep is complete, so no additional prep time
                travel_time_s=0.0,
                course_dir=self.course_dir,
                runner_speed_mps=float(self.runner_speed_mps),
                departure_time_s=actual_departure_time_s, # Use actual departure time
                clubhouse_lonlat=self.clubhouse_coords,
                estimated_delay_s=0.0,
                order=order_dict,
            )
            if predicted_coords:
                predicted_delivery_node_idx = find_nearest_node_index(predicted_coords, self.course_dir)
            logger.debug(f"Predicted delivery location: {predicted_coords} (node: {predicted_delivery_node_idx})")
        except Exception as e:
            logger.debug(f"Prediction failed: {e}")
            predicted_coords = None

        # Calculate delivery route using the dedicated routing method
        route_result = None
        try:
            route_result = self._calculate_delivery_route(order, target_hole, predicted_coords)
            delivery_distance_m = route_result["delivery_distance_m"]
            delivery_time_s = route_result["delivery_time_s"]
            delivered_hole_num = route_result["delivered_hole_num"]
            trip_to_golfer = route_result.get("trip_to_golfer")
            trip_back = route_result.get("trip_back")
        except Exception as e:
            logger.debug(f"Exception in delivery routing, using simple fallback: {e}")
            # As a last resort, fall back to simple delivery details
            distance_m, time_s = self._calculate_delivery_details(int(target_hole))
            delivery_distance_m = float(distance_m)
            delivery_time_s = float(time_s)
            delivered_hole_num = int(target_hole)
            trip_to_golfer = None
            trip_back = None
            logger.debug(f"Simple fallback result: distance={delivery_distance_m}m, time={delivery_time_s}s")
        
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

        # Correctly calculate drive time from actual departure
        drive_out_time_s = order.delivered_time - order.delivery_started_time

        # If node travel times are available, use the pre-calculated time for accuracy
        if self.node_travel_times and 0 <= predicted_delivery_node_idx < len(self.node_travel_times):
            drive_out_time_s = self.node_travel_times[predicted_delivery_node_idx]["time_s"]

        placed_time = order.order_placed_time if order.order_placed_time is not None else order.delivered_time
        order.total_completion_time_s = order.delivered_time - placed_time
        return_time_s = self._calculate_return_time(self.runner_locations[runner_index], predicted_delivery_node_idx)
        
        # Find the golfer's actual node index at the time of delivery
        actual_delivery_node_idx = -1
        try:
            golfer_tee_time = self._tee_time_by_group.get(int(order.golfer_group_id), 0)
            if golfer_tee_time > 0:
                time_since_tee_off_s = order.delivered_time - golfer_tee_time
                actual_delivery_node_idx = int(time_since_tee_off_s // self.time_quantum_s)
        except Exception:
            pass  # Could fail if group info not present

        self.log_activity("delivery_complete", f"{runner_label} delivered Order {order.order_id} to Hole {delivered_hole_num} (Total completion: {order.total_completion_time_s/60:.1f} min)", runner_id=runner_label, order_id=order.order_id, location=self.runner_locations[runner_index])

        # Log detailed order timing
        self.order_timing_logs.append({
            "order_id": order.order_id,
            "order_time_s": order.order_time_s,
            "ready_for_pickup_time_s": order.order_time_s + self.prep_time_s,
            "departure_time_s": actual_departure_time_s,
            "delivery_timestamp_s": order.delivered_time,
            "return_timestamp_s": order.delivered_time + return_time_s
        })

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
            "delivery_time_s": drive_out_time_s,
            "return_time_s": return_time_s,
            "total_drive_time_s": drive_out_time_s + return_time_s,
            "delivery_distance_m": delivery_distance_m,
            "total_completion_time_s": order.total_completion_time_s,
            "delivered_at_time_s": order.delivered_time,
            "runner_id": runner_label,
            "order_node_idx": order_node_idx,
            "predicted_delivery_node_idx": predicted_delivery_node_idx,
            "actual_delivery_node_idx": actual_delivery_node_idx
        }
        # Add routing data for visualization if available
        logger.debug(f"Saving delivery stats: trip_to_golfer={bool(trip_to_golfer)}, trip_back={bool(trip_back)}")
        if trip_to_golfer:
            logger.debug(f"trip_to_golfer keys: {list(trip_to_golfer.keys())}")
            delivery_stats_entry["trip_to_golfer"] = trip_to_golfer
        if trip_back:
            logger.debug(f"trip_back keys: {list(trip_back.keys())}")
            delivery_stats_entry["trip_back"] = trip_back
        if predicted_coords:
            delivery_stats_entry["predicted_delivery_location"] = [float(predicted_coords[0]), float(predicted_coords[1])]
        elif route_result and route_result.get("predicted_delivery_location"):
            delivery_stats_entry["predicted_delivery_location"] = route_result["predicted_delivery_location"]
            
        self.delivery_stats.append(delivery_stats_entry)
        # Mark runner available for next assignment
        self.runner_busy[runner_index] = False

    def _calculate_return_time(self, runner_location: str, node_idx: Optional[int] = None) -> float:
        """Calculate return time from a location. Prioritizes node-based times."""
        if runner_location == "clubhouse":
            return 0.0
        
        # Prefer precise, node-based travel times if available
        if node_idx is not None and self.node_travel_times and 0 <= node_idx < len(self.node_travel_times):
            return self.node_travel_times[node_idx]["time_s"]
            
        # Fallback to parsing hole number
        try:
            if runner_location.startswith("hole_"):
                hole_num = int(runner_location.split("_")[1])
                distance_m, time_s = self._calculate_delivery_details(hole_num)
                return float(time_s)
        except Exception:
            pass
        # Fallback constant
        return 8 * 60.0

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
