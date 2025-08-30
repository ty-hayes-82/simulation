"""
Order Generation Module
"""
from __future__ import annotations
import random
from typing import Any, Dict, List, Optional, Tuple
import math

from .services import DeliveryOrder
from ..config.loaders import parse_hhmm_to_seconds_since_7am
from ..utils import distribute_counts_by_fraction
from .tracks import load_holes_connected_points

def calculate_delivery_order_probability_per_9_holes(total_orders: int, num_groups: int) -> float:
    if num_groups == 0 or total_orders == 0:
        return 0.0
    return float(total_orders) / (float(num_groups) * 2.0)

def generate_dynamic_hourly_distribution(start_hour: int, end_hour: int) -> Dict[str, float]:
    """
    Generates an hourly order distribution with a lunch and dinner peak.
    Models a normal-like distribution around lunch and a smaller one around dinner.
    """
    distribution = {}

    # Parameters for the distribution peaks
    lunch_peak_hour = 12.5  # Center of lunch peak
    lunch_spread = 1.5      # Standard deviation for lunch peak
    lunch_amplitude = 3.0   # Height of lunch peak

    dinner_peak_hour = 17.5 # Center of dinner peak
    dinner_spread = 1.0     # Standard deviation for dinner peak
    dinner_amplitude = 2.0  # Height of dinner peak (less than lunch)

    base_weight = 0.5       # Base order probability

    for hour in range(start_hour, end_hour):
        # Center the calculation in the middle of the hour for a better curve
        hour_center = hour + 0.5
        
        # Calculate weight from lunch peak
        lunch_dist = abs(hour_center - lunch_peak_hour)
        lunch_weight = lunch_amplitude * math.exp(-((lunch_dist ** 2) / (2 * lunch_spread ** 2)))

        # Calculate weight from dinner peak
        dinner_dist = abs(hour_center - dinner_peak_hour)
        dinner_weight = dinner_amplitude * math.exp(-((dinner_dist ** 2) / (2 * dinner_spread ** 2)))

        # Total weight for the hour is the sum of peaks + base
        total_weight = base_weight + lunch_weight + dinner_weight
        distribution[f"{hour:02d}:00"] = total_weight
        
    return distribution

def generate_delivery_orders_with_pass_boost(
    groups: List[Dict[str, Any]],
    base_prob_per_9: float,
    crossings_data: Optional[Dict[str, Any]] = None,
    rng_seed: Optional[int] = None,
    course_dir: Optional[str] = None,
    boost_per_nine: float = 0.10,
    service_open_s: Optional[int] = None,
    opening_ramp_minutes: int = 0,
) -> List[DeliveryOrder]:
    if rng_seed is not None:
        random.seed(int(rng_seed))

    front_back_pass_by_group: Dict[int, Tuple[bool, bool]] = {}
    if crossings_data and isinstance(crossings_data, dict) and crossings_data.get("groups"):
        try:
            for group_entry in crossings_data["groups"]:
                gid = int(group_entry.get("group", 0))
                front_pass = False
                back_pass = False
                for crossing in group_entry.get("crossings", []) or []:
                    hole = crossing.get("hole")
                    if isinstance(hole, int):
                        if 1 <= hole <= 9:
                            front_pass = True or front_pass
                        elif 10 <= hole <= 18:
                            back_pass = True or back_pass
                if gid:
                    front_back_pass_by_group[gid] = (front_pass, back_pass)
        except Exception:
            front_back_pass_by_group = {}

    def clamp01(x: float) -> float:
        return max(0.0, min(1.0, float(x)))

    try:
        total_nodes = len(load_holes_connected_points(course_dir)) if course_dir else 0
    except Exception:
        total_nodes = 0
    total_nodes = int(total_nodes) if total_nodes and total_nodes > 0 else 18 * 12
    nodes_per_hole = max(1.0, float(total_nodes) / 18.0)

    orders: List[DeliveryOrder] = []
    for group in groups or []:
        group_id = int(group.get("group_id", 0))
        tee_time_s = int(group.get("tee_time_s", 0))

        front_pass, back_pass = front_back_pass_by_group.get(group_id, (False, False))
        p_front = clamp01(base_prob_per_9 + (boost_per_nine if front_pass else 0.0))
        p_back = clamp01(base_prob_per_9 + (boost_per_nine if back_pass else 0.0))

        hole_front = int(random.randint(1, 9))
        start_node = int(round((hole_front - 1) * nodes_per_hole))
        end_node = int(round(hole_front * nodes_per_hole)) - 1
        node_idx = start_node if end_node < start_node else random.randint(start_node, end_node)
        order_time_front_s = tee_time_s + int(node_idx) * 60
        
        if not isinstance(service_open_s, (int, float)) or order_time_front_s >= int(service_open_s):
            if random.random() < p_front:
                orders.append(
                    DeliveryOrder(
                        order_id=None,
                        golfer_group_id=group_id,
                        golfer_id=f"G{group_id}",
                        order_time_s=order_time_front_s,
                        hole_num=hole_front,
                    )
                )

        hole_back = int(random.randint(10, 18))
        start_node = int(round((hole_back - 1) * nodes_per_hole))
        end_node = int(round(hole_back * nodes_per_hole)) - 1
        node_idx = start_node if end_node < start_node else random.randint(start_node, end_node)
        order_time_back_s = tee_time_s + int(node_idx) * 60
        
        if not isinstance(service_open_s, (int, float)) or order_time_back_s >= int(service_open_s):
            if random.random() < p_back:
                orders.append(
                    DeliveryOrder(
                        order_id=None,
                        golfer_group_id=group_id,
                        golfer_id=f"G{group_id}",
                        order_time_s=order_time_back_s,
                        hole_num=hole_back,
                    )
                )

    orders.sort(key=lambda o: float(getattr(o, "order_time_s", 0.0)))
    for i, o in enumerate(orders, start=1):
        o.order_id = f"{i:03d}"

    return orders


def generate_delivery_orders_by_hour_distribution(
    *,
    groups: List[Dict[str, Any]],
    hourly_distribution: Dict[str, float],
    total_orders: int,
    service_open_hhmm: str,
    service_close_hhmm: str,
    opening_ramp_minutes: int = 0,
    course_dir: Optional[str] = None,
    rng_seed: Optional[int] = None,
    service_open_s: Optional[int] = None,
    blocked_holes: Optional[set[int]] = None,
) -> List[DeliveryOrder]:
    if rng_seed is not None:
        random.seed(int(rng_seed))

    open_s = service_open_s if isinstance(service_open_s, int) else parse_hhmm_to_seconds_since_7am(service_open_hhmm)
    close_s = parse_hhmm_to_seconds_since_7am(service_close_hhmm)
    if close_s <= open_s:
        close_s = open_s + 10 * 3600

    def hhmm_to_s(hhmm: str) -> int:
        try:
            hh, mm = hhmm.split(":")
            return (int(hh) - 7) * 3600 + int(mm) * 60
        except Exception:
            return 0

    hour_items = sorted(((k, float(v)) for k, v in (hourly_distribution or {}).items()), key=lambda kv: hhmm_to_s(kv[0]))
    hour_items = [(hh, pct) for (hh, pct) in hour_items if open_s <= hhmm_to_s(hh) < close_s]
    if not hour_items:
        return []

    hour_labels = [hh for hh, _ in hour_items]
    fractions = [pct for _, pct in hour_items]
    counts = distribute_counts_by_fraction(total_orders, fractions)

    try:
        total_nodes = len(load_holes_connected_points(course_dir)) if course_dir else 0
    except Exception:
        total_nodes = 18 * 12
    total_nodes = int(total_nodes) if total_nodes and total_nodes > 0 else 18 * 12
    nodes_per_hole = max(1, int(round(float(total_nodes) / 18.0)))

    def group_active_at(ts_s: int) -> List[Dict[str, Any]]:
        active: List[Dict[str, Any]] = []
        play_seconds = max(1, int(total_nodes * 60))
        for g in groups or []:
            start = int(g.get("tee_time_s", 0))
            end = start + play_seconds
            if start <= ts_s <= end:
                active.append(g)
        return active

    def infer_hole_for_group_at_time(g: Dict[str, Any], ts_s: int) -> int:
        start = int(g.get("tee_time_s", 0))
        delta_min = max(0, int((ts_s - start) // 60))
        node_idx = delta_min
        hole = 1 + int(node_idx // nodes_per_hole)
        return max(1, min(18, hole))

    orders: List[DeliveryOrder] = []
    _blocked_holes = set(blocked_holes) if blocked_holes else set()

    for idx, (hh, cnt) in enumerate(zip(hour_labels, counts)):
        start_s = hhmm_to_s(hh)
        end_s = min(start_s + 3600, close_s)
        if end_s <= start_s or cnt <= 0:
            continue
        
        for _ in range(cnt):
            for attempt in range(50):  # Try up to 5 times to place an order on an allowed hole
                order_time_s = random.randint(start_s, end_s - 1)
                if service_open_s is not None:
                    order_time_s = max(order_time_s, service_open_s)
                
                active_groups = group_active_at(order_time_s)
                if not active_groups:
                    continue

                group = random.choice(active_groups)
                hole = infer_hole_for_group_at_time(group, order_time_s)
                
                if hole not in _blocked_holes:
                    orders.append(
                        DeliveryOrder(
                            order_id=None,
                            golfer_group_id=group.get("group_id"),
                            golfer_id=f"G{group.get('group_id')}",
                            order_time_s=order_time_s,
                            hole_num=hole,
                        )
                    )
                    break  # Successfully placed order, move to the next one
    
    # --- Fill remainder orders on allowed holes if necessary ---
    if len(orders) < total_orders:
        num_to_add = total_orders - len(orders)
        
        fallback_group = groups[0] if groups else {"group_id": 1, "tee_time_s": open_s}

        for _ in range(num_to_add):
            for attempt in range(20): # More attempts to find a valid spot
                order_time_s = random.randint(open_s, close_s - 1)
                
                active_groups = group_active_at(order_time_s)
                group = random.choice(active_groups) if active_groups else fallback_group
                hole = infer_hole_for_group_at_time(group, order_time_s)

                if hole not in _blocked_holes:
                    orders.append(
                        DeliveryOrder(
                            order_id=None,
                            golfer_group_id=group.get("group_id"),
                            golfer_id=f"G{group.get('group_id')}",
                            order_time_s=order_time_s,
                            hole_num=hole,
                        )
                    )
                    break

    orders.sort(key=lambda o: float(getattr(o, "order_time_s", 0.0)))
    for i, o in enumerate(orders, start=1):
        o.order_id = f"{i:03d}"

    # Trim any excess orders that might have been created
    if len(orders) > total_orders:
        orders = orders[:total_orders]
        # Re-assign IDs after trimming
        for i, o in enumerate(orders, start=1):
            o.order_id = f"{i:03d}"
            
    return orders
