#!/usr/bin/env python3
"""
Unified Simulation Runner

Combines functionality from:
- scripts/sim/run_bev_cart_dynamic.py
- scripts/sim/run_delivery_dynamic.py

Modes:
- bev-carts: Beverage cart GPS only (supports 1..N carts)
- bev-with-golfers: Single cart + golfer groups sales simulation
- golfers-only: Generate golfer GPS tracks only (no cart, no runner)
- delivery-runner: Delivery runner serving 0..N golfer groups
- single-golfer: Single golfer delivery simulation (parity with run_single_golfer_simulation)
- optimize-runners: Find minimal number of delivery runners to meet SLA target

Windows PowerShell friendly: one short command per line, no piping/chaining.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
import sys
from typing import Dict, List, Tuple, Any, Optional

import simpy
import csv

from golfsim.logging import init_logging, get_logger
from golfsim.config.loaders import load_tee_times_config, load_simulation_config
from golfsim.simulation.services import (
    BeverageCartService,
    MultiRunnerDeliveryService,
    DeliveryOrder,
)
from golfsim.simulation.phase_simulations import generate_golfer_track
from golfsim.simulation.crossings import (
    compute_crossings_from_files,
    serialize_crossings_summary,
)
from golfsim.simulation.bev_cart_pass import simulate_beverage_cart_sales
from golfsim.io.results import write_unified_coordinates_csv, save_results_bundle
from golfsim.viz.matplotlib_viz import (
    render_beverage_cart_plot,
    render_delivery_plot,
    load_course_geospatial_data,
    create_folium_delivery_map,
)
from golfsim.viz.heatmap_viz import create_course_heatmap
from golfsim.io.phase_reporting import save_phase3_output_files, write_phase3_summary
from golfsim.analysis.metrics_integration import generate_and_save_metrics
from golfsim.simulation.engine import run_golf_delivery_simulation
from utils.simulation_reporting import (
    log_simulation_results,
    write_multi_run_summary,
    create_delivery_log,
    handle_simulation_error,
)


logger = get_logger(__name__)


def _calculate_utilization_from_activity_log(activity_logs: List[Dict[str, Any]], service_hours: float) -> Dict[str, Dict[str, float]]:
    """Calculate runner utilization from activity log including all delivery attempts.
    
    Counts time from delivery_start to returning for ALL deliveries (successful and failed).
    """
    by_runner: Dict[str, Dict[str, float]] = {}
    
    if not activity_logs:
        return by_runner
    
    service_seconds = service_hours * 3600
    
    # Group activities by runner_id
    runner_activities = {}
    for activity in activity_logs:
        runner_id = activity.get('runner_id')
        if runner_id:
            if runner_id not in runner_activities:
                runner_activities[runner_id] = []
            runner_activities[runner_id].append(activity)
    
    # Calculate total delivery time per runner
    for runner_id, activities in runner_activities.items():
        # Sort activities by timestamp
        activities.sort(key=lambda x: x.get('timestamp_s', 0))
        
        total_delivery_time = 0.0
        current_delivery_start = None
        service_start_time = None
        service_end_time = None
        
        for activity in activities:
            activity_type = activity.get('activity_type', '')  # Use activity_type from service logs
            timestamp = activity.get('timestamp_s', 0)
            
            # Track actual service window for this runner
            if 'service_opened' in activity_type:
                service_start_time = timestamp
            elif 'service_closed' in activity_type:
                service_end_time = timestamp
            
            if 'delivery_start' in activity_type:
                current_delivery_start = timestamp
            elif 'returning' in activity_type and current_delivery_start is not None:
                # Calculate time for this complete delivery cycle
                delivery_cycle_time = timestamp - current_delivery_start
                total_delivery_time += delivery_cycle_time
                current_delivery_start = None
        
        # If there's an uncompleted delivery (failed/timeout), count time until service end
        if current_delivery_start is not None and service_end_time is not None:
            incomplete_delivery_time = service_end_time - current_delivery_start
            if incomplete_delivery_time > 0:  # Only add positive time
                total_delivery_time += incomplete_delivery_time
        
        # Calculate utilization percentage using fixed service window
        utilization_pct = (total_delivery_time / service_seconds) * 100
        
        by_runner[runner_id] = {
            'driving': utilization_pct,
            'total_delivery_time_s': total_delivery_time,
        }
    
    return by_runner


def _calculate_delivery_utilization_from_stats(delivery_stats: List[Dict[str, Any]], service_hours: float) -> Dict[str, Dict[str, float]]:
    """Calculate runner utilization as total drive time / total working time per runner.
    
    Drive time = delivery_time_s + return_time_s (excludes prep time, which is handled by kitchen).
    """
    service_seconds = service_hours * 3600
    by_runner: Dict[str, Dict[str, float]] = {}
    
    # Group delivery stats by runner_id
    for stat in delivery_stats:
        runner_id = stat.get('runner_id', 'runner_1')  # Default to runner_1 if not specified
        if runner_id not in by_runner:
                    by_runner[runner_id] = {
            'total_drive_time_s': 0.0,  # Total time actively traveling (delivery + return)
            'orders_delivered': 0,
            'completion_times': []
        }
        
        # Add delivery time (actual time runner spends driving - outbound + return)
        delivery_time_s = stat.get('delivery_time_s', 0)
        return_time_s = stat.get('return_time_s', 0)
        total_drive_time_s = delivery_time_s + return_time_s  # Total time runner is actively traveling
        
        by_runner[runner_id]['total_drive_time_s'] += total_drive_time_s
        by_runner[runner_id]['orders_delivered'] += 1
        by_runner[runner_id]['completion_times'].append(stat.get('total_completion_time_s', 0) / 60.0)  # Convert to minutes
    
    # Calculate utilization percentages
    for runner_id, data in by_runner.items():
        total_drive_time = data['total_drive_time_s']
        delivery_utilization_pct = (total_drive_time / service_seconds) * 100.0
        
        by_runner[runner_id] = {
            'delivery_utilization_pct': delivery_utilization_pct,
            'total_drive_time_s': total_drive_time,
            'total_work_time_s': service_seconds,
        }
    
    return by_runner


def _calculate_order_metrics_from_stats(delivery_stats: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """Calculate order count and average order time per runner from delivery stats."""
    by_runner: Dict[str, Dict[str, float]] = {}
    
    # Group delivery stats by runner_id
    for stat in delivery_stats:
        runner_id = stat.get('runner_id', 'runner_1')  # Default to runner_1 if not specified
        if runner_id not in by_runner:
            by_runner[runner_id] = {
                'orders_delivered': 0,
                'completion_times': []
            }
        
        total_time_s = stat.get('total_completion_time_s', 0)
        by_runner[runner_id]['orders_delivered'] += 1
        by_runner[runner_id]['completion_times'].append(total_time_s / 60.0)  # Convert to minutes
    
    # Calculate averages
    for runner_id, data in by_runner.items():
        completion_times = data['completion_times']
        avg_order_time_min = sum(completion_times) / len(completion_times) if completion_times else 0.0
        
        by_runner[runner_id] = {
            'orders_delivered': data['orders_delivered'],
            'avg_order_time_min': avg_order_time_min,
        }
    
    return by_runner


def _calculate_bev_cart_order_probability(total_orders: int, num_groups: int) -> float:
    """Calculate beverage cart order probability from total orders and number of groups.
    
    Each group has opportunities to order from the beverage cart when they cross paths.
    Probability = total_orders / num_groups, capped at 1.0
    """
    if num_groups <= 0:
        return 0.0
    probability = total_orders / num_groups
    return min(probability, 1.0)


def _calculate_delivery_order_probability_per_9_holes(total_orders: int, num_groups: int) -> float:
    """Calculate delivery order probability per 9 holes from total orders and number of groups.
    
    Each group plays 18 holes = 2 sets of 9 holes, so total opportunities = num_groups * 2
    Probability = total_orders / (num_groups * 2), capped at 1.0
    """
    if num_groups <= 0:
        return 0.0
    total_opportunities = num_groups * 2  # Each group has 2 opportunities (front 9, back 9)
    probability = total_orders / total_opportunities
    return min(probability, 1.0)


# Ensure project root is importable for `utils` imports when running as a script
try:
    sys.path.append(str(Path(__file__).parent.parent.parent))
except Exception:
    pass

# -------------------- Shared helpers --------------------
def _generate_standardized_output_name(
    mode: str,
    num_bev_carts: int = 0,
    num_runners: int = 0,
    num_golfers: int = 0,
    tee_scenario: str = None,
    hole: int = None,
) -> str:
    """Generate standardized output directory name in format:
    {timestamp}_{#}bevcarts_{#}runners_{#}golfers_{teetime_scenario if applicable}
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Build the standardized name
    parts = [ts]
    
    # Add beverage carts count
    if num_bev_carts > 0:
        parts.append(f"{num_bev_carts}bevcarts")
    else:
        parts.append("0bevcarts")
    
    # Add runners count
    if num_runners > 0:
        parts.append(f"{num_runners}runners")
    else:
        parts.append("0runners")
    
    # Add golfers count
    if num_golfers > 0:
        parts.append(f"{num_golfers}golfers")
    else:
        parts.append("0golfers")
    
    # Add tee scenario if applicable
    if tee_scenario and tee_scenario.lower() not in {"none", "manual"}:
        parts.append(tee_scenario)
    
    # Add hole info for single-golfer mode
    if hole is not None:
        parts.append(f"hole{hole}")
    elif mode == "single-golfer":
        parts.append("randomhole")
    
    return "_".join(parts)


def _seconds_to_clock_str(sec_since_7am: int) -> str:
    total = max(0, int(sec_since_7am))
    hh = 7 + (total // 3600)
    mm = (total % 3600) // 60
    ss = total % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def _first_tee_to_seconds(hhmm: str) -> int:
    hh, mm = hhmm.split(":")
    return (int(hh) - 7) * 3600 + int(mm) * 60


def _build_simulation_id(output_root: Path, run_idx: int) -> str:
    """Create a compact simulation_id for a run directory."""
    try:
        return f"{output_root.name}_run_{run_idx:02d}"
    except Exception:
        return f"sim_run_{run_idx:02d}"


def _write_event_log_csv(events: List[Dict[str, Any]], save_path: Path) -> None:
    """Write a unified, replay-friendly events CSV.

    Columns (superset; extras ignored safely):
    simulation_id, ID, timestamp, timestamp_s, action, node_id, hole, ttl_amt,
    type, order_id, runner_id, cart_id, group_id, latitude, longitude, status, details
    """
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "simulation_id",
        "ID",
        "timestamp",
        "timestamp_s",
        "action",
        "node_id",
        "hole",
        "ttl_amt",
        "type",
        "order_id",
        "runner_id",
        "cart_id",
        "group_id",
        "latitude",
        "longitude",
        "status",
        "details",
    ]
    with save_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for ev in sorted(events, key=lambda e: int(e.get("timestamp_s", 0))):
            writer.writerow(ev)


def _events_from_activity_log(
    activity_log: List[Dict[str, Any]],
    simulation_id: str,
    default_entity_type: str,
    default_entity_id: str,
) -> List[Dict[str, Any]]:
    """Map service activity logs to event rows."""
    events: List[Dict[str, Any]] = []
    for entry in activity_log or []:
        ts_s = int(entry.get("timestamp_s", 0))
        time_str = entry.get("time_str") or _seconds_to_clock_str(ts_s)
        runner_id = entry.get("runner_id")
        cart_id = entry.get("cart_id")
        entity_id = runner_id or cart_id or default_entity_id
        if cart_id:
            etype = "beverage_cart"
        elif runner_id:
            etype = "delivery_runner"
        else:
            etype = default_entity_type
        events.append(
            {
                "simulation_id": simulation_id,
                "ID": entity_id,
                "timestamp": time_str,
                "timestamp_s": ts_s,
                "action": entry.get("activity_type") or entry.get("event") or "activity",
                "node_id": entry.get("node_index"),
                "hole": entry.get("hole") or entry.get("hole_num"),
                "ttl_amt": entry.get("revenue"),
                "type": etype,
                "order_id": entry.get("order_id"),
                "runner_id": runner_id,
                "cart_id": cart_id,
                "group_id": entry.get("golfer_group_id") or entry.get("group_id"),
                "latitude": entry.get("latitude"),
                "longitude": entry.get("longitude"),
                "status": entry.get("status"),
                "details": entry.get("description"),
            }
        )
    return events


def _events_from_groups_tee_off(groups: List[Dict[str, Any]], simulation_id: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for g in groups or []:
        tee_s = int(g.get("tee_time_s", 0))
        events.append(
            {
                "simulation_id": simulation_id,
                "ID": f"golf_group_{int(g.get('group_id', 0))}",
                "timestamp": _seconds_to_clock_str(tee_s),
                "timestamp_s": tee_s,
                "action": "tee_off",
                "hole": 1,
                "type": "golfer_group",
                "group_id": int(g.get("group_id", 0)),
            }
        )
    return events


def _events_from_single_golfer_results(results: Dict[str, Any], simulation_id: str) -> List[Dict[str, Any]]:
    """Construct key timeline events from single-golfer results."""
    events: List[Dict[str, Any]] = []
    # Order placed
    order_created_s = int(results.get("order_created_s", results.get("order_time_s", 0)))
    order_hole = results.get("order_hole")
    golfer_pos = results.get("golfer_position") or ()
    events.append(
        {
            "simulation_id": simulation_id,
            "ID": "order_1",
            "timestamp": _seconds_to_clock_str(order_created_s),
            "timestamp_s": order_created_s,
            "action": "order_placed",
            "hole": order_hole,
            "type": "order",
            "latitude": golfer_pos[1] if len(golfer_pos) == 2 else None,
            "longitude": golfer_pos[0] if len(golfer_pos) == 2 else None,
        }
    )
    # Prep complete
    prep_complete_s = results.get("prep_completed_s")
    if isinstance(prep_complete_s, (int, float)):
        events.append(
            {
                "simulation_id": simulation_id,
                "ID": "runner_1",
                "timestamp": _seconds_to_clock_str(int(prep_complete_s)),
                "timestamp_s": int(prep_complete_s),
                "action": "prep_complete",
                "type": "delivery_runner",
            }
        )
    # Delivery start (derive if trip info available)
    delivered_s = int(results.get("delivered_s", 0))
    trip_to = results.get("trip_to_golfer", {}) or {}
    to_time_s = int(trip_to.get("time_s", 0))
    if delivered_s and to_time_s:
        depart_s = max(0, delivered_s - to_time_s)
        events.append(
            {
                "simulation_id": simulation_id,
                "ID": "runner_1",
                "timestamp": _seconds_to_clock_str(depart_s),
                "timestamp_s": depart_s,
                "action": "delivery_start",
                "type": "delivery_runner",
                "location": "clubhouse",
            }
        )
    # Delivered
    if delivered_s:
        # Prefer actual location if available, else predicted
        try:
            from golfsim.io.results import find_actual_delivery_location  # local import
            actual = find_actual_delivery_location(results)
        except Exception:
            actual = None
        lat = None
        lon = None
        if isinstance(actual, dict):
            lat = actual.get("latitude")
            lon = actual.get("longitude")
        elif isinstance(results.get("predicted_delivery_location"), (list, tuple)):
            lon, lat = results["predicted_delivery_location"]
        events.append(
            {
                "simulation_id": simulation_id,
                "ID": "runner_1",
                "timestamp": _seconds_to_clock_str(delivered_s),
                "timestamp_s": delivered_s,
                "action": "order_delivered",
                "hole": order_hole,
                "type": "delivery_runner",
                "latitude": lat,
                "longitude": lon,
                "status": "completed",
            }
        )
    # Runner returned
    returned_s = results.get("runner_returned_s")
    if isinstance(returned_s, (int, float)):
        rs = int(returned_s)
        events.append(
            {
                "simulation_id": simulation_id,
                "ID": "runner_1",
                "timestamp": _seconds_to_clock_str(rs),
                "timestamp_s": rs,
                "action": "runner_returned",
                "type": "delivery_runner",
                "location": "clubhouse",
            }
        )
    return events


def _events_from_orders_list(orders: List[Dict[str, Any]] | None, simulation_id: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for o in orders or []:
        ts_s = int(o.get("order_time_s", 0))
        events.append(
            {
                "simulation_id": simulation_id,
                "ID": f"order_{o.get('order_id') or ''}",
                "timestamp": _seconds_to_clock_str(ts_s),
                "timestamp_s": ts_s,
                "action": "order_placed",
                "type": "order",
                "order_id": o.get("order_id"),
                "group_id": o.get("golfer_group_id"),
                "hole": o.get("hole_num"),
                "status": o.get("status"),
            }
        )
    return events


def _generate_executive_summary(output_root: Path) -> None:
    """Generate executive summary using Google Gemini for the simulation results."""
    try:
        # Import the executive summary script
        script_path = Path(__file__).parent.parent / "analysis" / "generate_gemini_executive_summary.py"
        if not script_path.exists():
            logger.warning("Executive summary script not found: %s", script_path)
            return
        
        logger.info("Generating executive summary using Google Gemini...")
        
        # Run the executive summary script
        import subprocess
        result = subprocess.run(
            [sys.executable, str(script_path), str(output_root)],
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )
        
        if result.returncode == 0:
            logger.info("Executive summary generated successfully")
            # Log a portion of the output
            if result.stdout:
                lines = result.stdout.split('\n')
                summary_start = False
                for line in lines:
                    if "EXECUTIVE SUMMARY" in line:
                        summary_start = True
                    elif summary_start and line.strip():
                        logger.info("Summary preview: %s", line.strip()[:100] + "..." if len(line.strip()) > 100 else line.strip())
                        break
        else:
            logger.warning("Executive summary generation failed (exit code %d): %s", result.returncode, result.stderr)
            
    except subprocess.TimeoutExpired:
        logger.warning("Executive summary generation timed out after 5 minutes")
    except Exception as e:
        logger.warning("Failed to generate executive summary: %s", e)


def _generate_delivery_orders_with_pass_boost(
    groups: List[Dict[str, Any]],
    base_prob_per_9: float,
    crossings_data: Optional[Dict[str, Any]] = None,
    rng_seed: Optional[int] = None,
    minutes_per_hole: int = 12,
    boost_per_nine: float = 0.10,
) -> List[DeliveryOrder]:
    """Generate delivery orders with a +10% per-nine boost when bev-cart passes occur.

    Semantics:
    - For each group and for each nine (front 1..9, back 10..18), compute an effective probability:
      p_nine = clamp(base_prob_per_9 + 0.10, 0..1) if there is at least one bev-cart pass in that nine,
      otherwise p_nine = base_prob_per_9.
    - Draw independently for front and back. If success, place the order at a random hole within that nine
      using ~12 minutes per hole pacing from the group's tee time.
    - Returns a chronologically ordered list of DeliveryOrder with sequential order_ids assigned.
    """
    import random

    if rng_seed is not None:
        random.seed(int(rng_seed))

    # Build a quick lookup: group_index (1-based, by tee order) -> (front_pass: bool, back_pass: bool)
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
            # If anything goes wrong, fall back to no boosts
            front_back_pass_by_group = {}

    def clamp01(x: float) -> float:
        return max(0.0, min(1.0, float(x)))

    orders: List[DeliveryOrder] = []
    for group in groups or []:
        group_id = int(group.get("group_id", 0))
        tee_time_s = int(group.get("tee_time_s", 0))

        # Determine boosted probabilities for this group
        front_pass, back_pass = front_back_pass_by_group.get(group_id, (False, False))
        p_front = clamp01(base_prob_per_9 + (boost_per_nine if front_pass else 0.0))
        p_back = clamp01(base_prob_per_9 + (boost_per_nine if back_pass else 0.0))

        # Front nine draw
        if random.random() < p_front:
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

        # Back nine draw
        if random.random() < p_back:
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

    # Assign sequential IDs in chronological order
    orders.sort(key=lambda o: float(getattr(o, "order_time_s", 0.0)))
    for i, o in enumerate(orders, start=1):
        o.order_id = f"{i:03d}"

    return orders

def _build_groups_interval(count: int, first_tee_s: int, interval_min: float) -> List[Dict]:
    groups: List[Dict] = []
    for i in range(count):
        groups.append({
            "group_id": i + 1,
            "tee_time_s": int(first_tee_s + i * int(interval_min * 60)),
            "num_golfers": 4,
        })
    return groups


def _generate_golfer_points_for_groups(course_dir: str, groups: List[Dict]) -> List[Dict]:
    all_points: List[Dict] = []
    for g in groups:
        pts = generate_golfer_track(course_dir, g["tee_time_s"]) or []
        for p in pts:
            p["group_id"] = g["group_id"]
        all_points.extend(pts)
    return all_points


# -------------------- Tee-times scenarios --------------------
def _parse_hhmm_to_seconds_since_7am(hhmm: str) -> int:
    try:
        hh, mm = hhmm.split(":")
        return (int(hh) - 7) * 3600 + int(mm) * 60
    except Exception:
        return 0


def _build_groups_from_scenario(course_dir: str, scenario_key: str, default_group_size: int = 4) -> List[Dict]:
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
    for hour_label, golfers in sorted(hourly.items(), key=lambda kv: _parse_hhmm_to_seconds_since_7am(kv[0])):
        golfers_int = int(golfers or 0)
        if golfers_int <= 0:
            continue

        # Number of groups for this hour
        groups_this_hour = (golfers_int + default_group_size - 1) // default_group_size
        if groups_this_hour <= 0:
            continue

        base_s = _parse_hhmm_to_seconds_since_7am(hour_label)
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


# -------------------- Beverage cart modes --------------------
def _run_bev_carts_only_once(run_idx: int, course_dir: str, num_carts: int, output_root: Path) -> Dict:
    env = simpy.Environment()
    services: Dict[str, BeverageCartService] = {}
    for n in range(1, num_carts + 1):
        # Stagger starting holes for multiple carts
        starting_hole = 18 if n == 1 else 9
        services[str(n)] = BeverageCartService(
            env=env,
            course_dir=course_dir,
            cart_id=f"bev_cart_{n}",
            track_coordinates=True,
            starting_hole=starting_hole,
        )

    any_service = next(iter(services.values()))
    env.run(until=any_service.service_end_s)

    run_dir = output_root / f"sim_{run_idx:02d}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Combined CSV for all carts
    write_unified_coordinates_csv(
        {label: svc.coordinates for label, svc in services.items()},
        run_dir / "bev_cart_coordinates.csv",
    )

    # Combined PNG
    all_coords: List[Dict] = []
    for svc in services.values():
        all_coords.extend(svc.coordinates)
    if all_coords:
        render_beverage_cart_plot(all_coords, course_dir=course_dir, save_path=run_dir / "bev_cart_route.png")

    # Stats
    stats = {
        "mode": "bev-carts",
        "run_idx": run_idx,
        "carts": num_carts,
        "points_per_cart": {k: len(v.coordinates) for k, v in services.items()},
        "first_ts": min((int(v.coordinates[0]["timestamp"]) for v in services.values() if v.coordinates), default=None),
        "last_ts": max((int(v.coordinates[-1]["timestamp"]) for v in services.values() if v.coordinates), default=None),
    }
    (run_dir / "stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")

    # Events CSV (cart activities)
    try:
        simulation_id = _build_simulation_id(output_root, run_idx)
        events: List[Dict[str, Any]] = []
        for label, svc in services.items():
            events.extend(
                _events_from_activity_log(
                    svc.activity_log,
                    simulation_id=simulation_id,
                    default_entity_type="beverage_cart",
                    default_entity_id=f"bev_cart_{label}",
                )
            )
        if events:
            _write_event_log_csv(events, run_dir / "events.csv")
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to write beverage cart events: %s", e)

    # Metrics per cart using integrated approach
    try:
        for label, svc in services.items():
            points = svc.coordinates or []
            if not points:
                continue

            sim_result: Dict[str, Any] = {
                "bev_points": points,
                "sales_result": {"sales": []},
                "simulation_type": "beverage_cart_only",
            }

            generate_and_save_metrics(
                simulation_result=sim_result,
                output_dir=run_dir,
                bev_cart_coordinates=points,
                bev_cart_service=svc,
                run_suffix=f"_{label}",
                simulation_id=f"bev_only_run_{run_idx:02d}",
                cart_id=f"bev_cart_{label}",
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to generate metrics: %s", e)

    return stats


def _run_bev_with_groups_once(
    run_idx: int,
    course_dir: str,
    groups: List[Dict],
    pass_order_probability: float,
    avg_order_value: float,
    output_root: Path,
    rng_seed: Optional[int] = None,
) -> Dict:
    start_time = time.time()

    # Compute crossings using files for accuracy
    nodes_geojson = str(Path(course_dir) / "geojson" / "generated" / "lcm_course_nodes.geojson")
    holes_geojson = str(Path(course_dir) / "geojson" / "generated" / "holes_geofenced.geojson")
    config_json = str(Path(course_dir) / "config" / "simulation_config.json")

    first_tee_s = min(g["tee_time_s"] for g in groups) if groups else (9 - 7) * 3600
    last_tee_s = max(g["tee_time_s"] for g in groups) if groups else first_tee_s
    bev_start_s = (9 - 7) * 3600

    crossings = compute_crossings_from_files(
        nodes_geojson=nodes_geojson,
        holes_geojson=holes_geojson,
        config_json=config_json,
        v_fwd_mph=None,
        v_bwd_mph=None,
        bev_start=_seconds_to_clock_str(bev_start_s),
        groups_start=_seconds_to_clock_str(first_tee_s),
        groups_end=_seconds_to_clock_str(last_tee_s),
        groups_count=len(groups) if groups else 0,
        random_seed=int(rng_seed) if rng_seed is not None else run_idx,
        tee_mode="interval",
        groups_interval_min=15.0,
    ) if groups else None

    # Generate golfer points and simulate sales (if groups)
    golfer_points = _generate_golfer_points_for_groups(course_dir, groups) if groups else []

    sales_result = simulate_beverage_cart_sales(
        course_dir=course_dir,
        groups=groups or [],
        pass_order_probability=float(pass_order_probability),
        price_per_order=float(avg_order_value),
        minutes_between_holes=2.0,
        minutes_per_hole=None,
        golfer_points=golfer_points,
        crossings_data=crossings,
    ) if groups else {"sales": [], "revenue": 0.0}

    # Build beverage cart GPS via BeverageCartService for consistency
    env = simpy.Environment()
    svc = BeverageCartService(env=env, course_dir=course_dir, cart_id="bev_cart_1", track_coordinates=True, starting_hole=18)
    env.run(until=svc.service_end_s)
    bev_points = svc.coordinates

    # Save outputs
    run_dir = output_root / f"sim_{run_idx:02d}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Coordinates CSV, combine golfer groups and cart
    tracks: Dict[str, List[Dict]] = {"bev_cart_1": bev_points}
    for g in (groups or []):
        gid = g["group_id"]
        pts = [p for p in golfer_points if p.get("group_id") == gid]
        tracks[f"golfer_group_{gid}"] = pts
    write_unified_coordinates_csv(tracks, run_dir / "coordinates.csv")

    # Visualization for cart
    if bev_points:
        render_beverage_cart_plot(bev_points, course_dir=course_dir, save_path=run_dir / "bev_cart_route.png")
    
    # Heatmap visualization for beverage cart sales
    try:
        heatmap_file = run_dir / "bev_cart_sales_heatmap.png"
        # Format beverage cart sales for heatmap function
        # Convert sales data to order-like format for heatmap
        heatmap_results = {'orders': [], 'delivery_stats': []}
        if isinstance(sales_result, dict) and 'sales' in sales_result:
            for i, sale in enumerate(sales_result['sales']):
                # Extract relevant fields from sales data for heatmap
                order_entry = {
                    'hole_num': sale.get('hole', sale.get('hole_num', 1)),
                    'total_completion_time_s': sale.get('service_time_s', 0),  # Use service time as proxy for completion time
                    'order_id': f'sale_{i+1}',
                    'golfer_group_id': sale.get('golfer_group_id', sale.get('group_id', 1)),
                    'order_time_s': sale.get('order_time_s', sale.get('timestamp_s', 0))
                }
                heatmap_results['orders'].append(order_entry)
        
        if heatmap_results['orders']:  # Only create heatmap if there are sales
            course_name = Path(course_dir).name.replace("_", " ").title()
            create_course_heatmap(
                results=heatmap_results,
                course_dir=course_dir,
                save_path=heatmap_file,
                title=f"{course_name} - Beverage Cart Sales Heatmap (Run {run_idx})",
                colormap='RdYlGn_r'
            )
            logger.info("Created beverage cart sales heatmap: %s", heatmap_file)
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to create beverage cart sales heatmap: %s", e)

    # Sales and result
    (run_dir / "sales.json").write_text(json.dumps(sales_result, indent=2), encoding="utf-8")
    result_meta = {
        "mode": "bev-with-golfers",
        "run_idx": run_idx,
        "groups": groups,
        "first_tee_time_s": first_tee_s,
        "last_tee_time_s": last_tee_s,
        "revenue": float(sales_result.get("revenue", 0.0)),
        "num_sales": len(sales_result.get("sales", [])),
        "crossings": serialize_crossings_summary(crossings) if crossings else None,
        "simulation_runtime_s": time.time() - start_time,
        # Include full sales payload so downstream writers can persist transaction details
        "sales_result": sales_result,
    }
    (run_dir / "result.json").write_text(json.dumps(result_meta, indent=2), encoding="utf-8")

    # Events CSV (tee-offs, cart activities, pass/sales)
    try:
        simulation_id = _build_simulation_id(output_root, run_idx)
        events: List[Dict[str, Any]] = []
        # Tee-offs
        events.extend(_events_from_groups_tee_off(groups, simulation_id))
        # Cart activities
        events.extend(
            _events_from_activity_log(
                svc.activity_log if 'svc' in locals() else [],
                simulation_id=simulation_id,
                default_entity_type="beverage_cart",
                default_entity_id="bev_cart_1",
            )
        )
        # Sales activity log from sales_result
        sales_log = sales_result.get("activity_log", []) if isinstance(sales_result, dict) else []
        events.extend(
            _events_from_activity_log(
                sales_log,
                simulation_id=simulation_id,
                default_entity_type="order",
                default_entity_id="sales_event",
            )
        )
        if events:
            _write_event_log_csv(events, run_dir / "events.csv")
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to write events for bev-with-golfers run %d: %s", run_idx, e)

    # Metrics for the single cart using integrated approach
    try:
        sim_result: Dict[str, Any] = {
            "bev_points": bev_points,
            "sales_result": sales_result,
            "golfer_points": golfer_points,
            "simulation_type": "beverage_cart_with_golfers",
        }

        generate_and_save_metrics(
            simulation_result=sim_result,
            output_dir=run_dir,
            bev_cart_coordinates=bev_points,
            bev_cart_service=svc,
            golfer_data=golfer_points,
            simulation_id=f"bev_groups_run_{run_idx:02d}",
            cart_id="bev_cart_1",
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to generate metrics: %s", e)

    return result_meta


# -------------------- Mode entrypoints --------------------
def _run_mode_single_golfer(args: argparse.Namespace) -> None:
    # Single golfer mode: 0 bev carts, 1 runner, 1 golfer
    hole = getattr(args, "hole", None)
    default_name = _generate_standardized_output_name(
        mode="single-golfer",
        num_bev_carts=0,
        num_runners=1,
        num_golfers=1,
        tee_scenario=None,
        hole=hole,
    )
    output_root = Path(args.output_dir or (Path("outputs") / default_name))
    output_root.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Starting single-golfer delivery sims: %d run(s), hole=%s, prep=%d min, runner_speed=%.2f mph (%.2f m/s)",
        int(args.num_runs),
        args.hole if getattr(args, "hole", None) else "random",
        int(args.prep_time),
        float(args.runner_speed),
        float(args.runner_speed) * 0.44704,
    )

    all_runs: List[Dict] = []

    for i in range(1, int(args.num_runs) + 1):
        run_dir = output_root / f"sim_{i:02d}"
        run_dir.mkdir(parents=True, exist_ok=True)

        try:
            mph_to_mps = float(args.runner_speed) * 0.44704
            results = run_golf_delivery_simulation(
                course_dir=args.course_dir,
                order_hole=getattr(args, "hole", None),
                prep_time_min=int(args.prep_time),
                runner_speed_mps=mph_to_mps,
                hole_placement=str(getattr(args, "placement", "mid")),
                runner_delay_min=float(getattr(args, "runner_delay", 0.0)),
                use_enhanced_network=not bool(getattr(args, "no_enhanced", False)),
                track_coordinates=not bool(getattr(args, "no_coordinates", False)),
            )

            # Save results bundle (CSV + JSON)
            save_results_bundle(results, run_dir)

            # Log results consistently
            log_simulation_results(results, run_idx=i, track_coords=not bool(getattr(args, "no_coordinates", False)))

            # Combined unified coordinates CSV
            try:
                points_by_id: Dict[str, List[Dict]] = {}
                if results.get('golfer_coordinates'):
                    points_by_id['golfer_1'] = results['golfer_coordinates']
                if results.get('runner_coordinates'):
                    points_by_id['delivery_runner_1'] = results['runner_coordinates']
                if points_by_id:
                    write_unified_coordinates_csv(points_by_id, run_dir / "coordinates.csv")
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to write combined coordinates CSV: %s", e)

            # Delivery log
            try:
                create_delivery_log(results, run_dir / "delivery_log.md")
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to create delivery log: %s", e)

            # Events CSV (single-golfer timeline)
            try:
                simulation_id = _build_simulation_id(output_root, i)
                events = _events_from_single_golfer_results(results, simulation_id)
                if events:
                    _write_event_log_csv(events, run_dir / "events.csv")
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to write events CSV: %s", e)

            # Visualization
            if not bool(getattr(args, "no_visualization", False)):
                try:
                    course_data = load_course_geospatial_data(args.course_dir)
                    sim_cfg = load_simulation_config(args.course_dir)
                    clubhouse_coords = sim_cfg.clubhouse

                    # Load per-entity CSVs if present (optional)
                    golfer_df = None
                    runner_df = None
                    try:
                        import pandas as pd  # local import
                        golfer_csv = run_dir / "golfer_coordinates.csv"
                        runner_csv = run_dir / "runner_coordinates.csv"
                        if golfer_csv.exists():
                            golfer_df = pd.read_csv(golfer_csv)
                        if runner_csv.exists():
                            runner_df = pd.read_csv(runner_csv)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("Failed to read coordinates CSVs: %s", e)

                    # Load cart graph
                    cart_graph = None
                    try:
                        import pickle
                        cart_graph_pkl = Path(args.course_dir) / "pkl" / "cart_graph.pkl"
                        if cart_graph_pkl.exists():
                            with cart_graph_pkl.open("rb") as f:
                                cart_graph = pickle.load(f)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("Failed to load cart graph: %s", e)

                    # Folium map
                    try:
                        folium_map_path = run_dir / "delivery_route_map.html"
                        create_folium_delivery_map(results, course_data, folium_map_path)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("Failed to create folium map: %s", e)

                    # PNG visualization
                    try:
                        output_file = run_dir / "delivery_route_visualization.png"
                        debug_coords_file = run_dir / "visualization_debug_coords.csv"
                        render_delivery_plot(
                            results=results,
                            course_data=course_data,
                            clubhouse_coords=clubhouse_coords,
                            golfer_coords=golfer_df,
                            runner_coords=runner_df,
                            cart_graph=cart_graph,
                            save_path=output_file,
                            course_name=Path(args.course_dir).name.replace("_", " ").title(),
                            style="simple",
                            save_debug_coords_path=debug_coords_file,
                        )
                    except Exception as e:  # noqa: BLE001
                        logger.warning("Failed to create PNG visualization: %s", e)

                    # Heatmap visualization
                    try:
                        heatmap_file = run_dir / "delivery_heatmap.png"
                        # Format single-golfer results for heatmap function
                        heatmap_results = {
                            'orders': [{
                                'hole_num': results.get('order_hole', 1),
                                'total_completion_time_s': results.get('total_service_time_s', 0),
                                'order_id': 'order_1',
                                'golfer_group_id': 1,
                                'order_time_s': results.get('order_time_s', 0)
                            }],
                            'delivery_stats': []
                        }
                        course_name = Path(args.course_dir).name.replace("_", " ").title()
                        create_course_heatmap(
                            results=heatmap_results,
                            course_dir=args.course_dir,
                            save_path=heatmap_file,
                            title=f"{course_name} - Single Golfer Delivery Heatmap (Run {i})",
                            colormap='RdYlGn_r'
                        )
                        logger.info("Created delivery heatmap: %s", heatmap_file)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("Failed to create delivery heatmap: %s", e)
                except Exception as e:  # noqa: BLE001
                    logger.warning("Visualization step failed: %s", e)

            # Minimal per-run stats file
            try:
                stats_md = [
                    f"# Single Golfer — Run {i:02d}",
                    "",
                    f"Order time: {float(results.get('order_time_s', 0.0))/60.0:.1f} min",
                    f"Service time: {float(results.get('total_service_time_s', 0.0))/60.0:.1f} min",
                    f"Distance (out+back): {float(results.get('delivery_distance_m', 0.0)):.0f} m",
                ]
                (run_dir / f"stats_run_{i:02d}.md").write_text("\n".join(stats_md), encoding="utf-8")
            except Exception:
                pass

            # Collect for summary
            all_runs.append(results)

        except Exception as e:  # noqa: BLE001
            if not handle_simulation_error(e, run_idx=i, exit_on_first=True):
                break

    # Multi-run summary
    try:
        write_multi_run_summary(all_runs, output_root, title="Single Golfer Delivery — Summary")
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to write single-golfer summary: %s", e)

    # Generate executive summary using Google Gemini
    _generate_executive_summary(output_root)

    logger.info("Complete. Results saved to: %s", output_root)
def _run_mode_bev_carts(args: argparse.Namespace) -> None:
    # Bev carts mode: N bev carts, 0 runners, 0 golfers
    default_name = _generate_standardized_output_name(
        mode="bev-carts",
        num_bev_carts=int(args.num_carts),
        num_runners=0,
        num_golfers=0,
        tee_scenario=None,
    )
    output_root = Path(args.output_dir or (Path("outputs") / default_name))
    output_root.mkdir(parents=True, exist_ok=True)

    logger.info("Starting beverage cart GPS runs: %d runs, %d carts", args.num_runs, args.num_carts)
    all_stats: List[Dict] = []

    for i in range(1, int(args.num_runs) + 1):
        stats = _run_bev_carts_only_once(i, args.course_dir, int(args.num_carts), output_root)
        all_stats.append(stats)

    # Write a mode-specific summary
    if all_stats:
        lines: List[str] = [
            "# Beverage Cart GPS Summary",
            "",
            f"Runs: {len(all_stats)}",
            f"Carts per run: {int(args.num_carts)}",
            "",
            "## Run Details",
        ]
        for idx, st in enumerate(all_stats, start=1):
            ppc = st.get("points_per_cart", {}) or {}
            first_ts = st.get("first_ts")
            last_ts = st.get("last_ts")
            ppc_str = ", ".join([f"{k}: {v}" for k, v in ppc.items()]) if ppc else "n/a"
            window = f"{_seconds_to_clock_str(first_ts)}–{_seconds_to_clock_str(last_ts)}" if first_ts is not None and last_ts is not None else "n/a"
            lines += [
                f"### Run {idx:02d}",
                f"- **Points per cart**: {ppc_str}",
                f"- **Service window**: {window}",
                "",
                "## Artifacts",
                "- `bev_cart_coordinates.csv` — GPS track for each cart",
                "- `bev_cart_route.png` — Route visualization",
                "- `bev_cart_metrics_*.md` — Metrics per cart",
            ]
        (output_root / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    
    # Generate executive summary using Google Gemini
    _generate_executive_summary(output_root)
    
    logger.info("Complete. Results saved to: %s", output_root)


def _run_mode_bev_with_golfers(args: argparse.Namespace) -> None:
    # Bev with golfers mode: 1 bev cart, 0 runners, N golfers
    default_name = _generate_standardized_output_name(
        mode="bev-with-golfers",
        num_bev_carts=1,
        num_runners=0,
        num_golfers=int(args.groups_count),
        tee_scenario=str(args.tee_scenario),
    )
    output_root = Path(args.output_dir or (Path("outputs") / default_name))
    output_root.mkdir(parents=True, exist_ok=True)

    logger.info("Starting beverage cart + golfers runs: %d runs, %d groups", args.num_runs, args.groups_count)
    phase3_summary_rows: List[Dict] = []

    # Build groups either from scenario (preferred) or manual args
    scenario_groups_base = _build_groups_from_scenario(args.course_dir, str(args.tee_scenario))
    if scenario_groups_base:
        first_tee_s = int(min(g["tee_time_s"] for g in scenario_groups_base))
    else:
        hh, mm = args.first_tee.split(":")
        first_tee_s = (int(hh) - 7) * 3600 + int(mm) * 60

    # Load simulation config to get total orders
    sim_config = load_simulation_config(args.course_dir)
    
    for i in range(1, int(args.num_runs) + 1):
        groups = scenario_groups_base or _build_groups_interval(int(args.groups_count), first_tee_s, float(args.groups_interval_min))
        # Use configured beverage cart order probability per 9 holes
        bev_order_probability = float(getattr(sim_config, "bev_cart_order_probability_per_9_holes", 0.35))
        res = _run_bev_with_groups_once(
            i,
            args.course_dir,
            groups,
            bev_order_probability,
            float(args.avg_order_usd),
            output_root,
            rng_seed=getattr(args, "random_seed", None),
        )

        # Save phase3-style outputs for the generated result
        # Ensure we propagate full sales_result (with sales list) from the run
        sales_result_full = res.get("sales_result", {
            "sales": [],
            "revenue": float(res.get("revenue", 0.0)),
        })

        sim_result = {
            "type": "standard",
            "run_idx": i,
            "sales_result": sales_result_full,
            "golfer_points": _generate_golfer_points_for_groups(args.course_dir, groups),
            "bev_points": [],  # filled below
            "pass_events": [],
            "tee_time_s": res.get("first_tee_time_s", (9 - 7) * 3600),
            "beverage_cart_service": None,
        }

        env2 = simpy.Environment()
        svc2 = BeverageCartService(env=env2, course_dir=args.course_dir, cart_id="bev_cart_1", track_coordinates=True, starting_hole=18)
        env2.run(until=svc2.service_end_s)
        sim_result["bev_points"] = svc2.coordinates
        run_dir = output_root / f"sim_{i:02d}"
        save_phase3_output_files(sim_result, run_dir, include_stats=False)

        phase3_summary_rows.append({
            "run_idx": i,
            "revenue": float(res.get("revenue", 0.0)),
            "num_sales": int(res.get("num_sales", 0)),
            "tee_time_s": int(res.get("first_tee_time_s", (9 - 7) * 3600)),
        })

    if phase3_summary_rows:
        write_phase3_summary(phase3_summary_rows, output_root)
    
    # Generate executive summary using Google Gemini
    _generate_executive_summary(output_root)
    
    logger.info("Complete. Results saved to: %s", output_root)


def _run_mode_golfers_only(args: argparse.Namespace) -> None:
    # Golfers only mode: 0 bev carts, 0 runners, N golfers
    default_name = _generate_standardized_output_name(
        mode="golfers-only",
        num_bev_carts=0,
        num_runners=0,
        num_golfers=int(args.groups_count),
        tee_scenario=str(args.tee_scenario),
    )
    output_root = Path(args.output_dir or (Path("outputs") / default_name))
    output_root.mkdir(parents=True, exist_ok=True)

    logger.info("Starting golfers-only runs: %d runs, %d groups", args.num_runs, args.groups_count)
    run_summaries: List[Dict] = []

    scenario_groups_base = _build_groups_from_scenario(args.course_dir, str(args.tee_scenario))
    if scenario_groups_base:
        first_tee_s = int(min(g["tee_time_s"] for g in scenario_groups_base))
    else:
        hh, mm = args.first_tee.split(":")
        first_tee_s = (int(hh) - 7) * 3600 + int(mm) * 60

    for i in range(1, int(args.num_runs) + 1):
        groups = scenario_groups_base or _build_groups_interval(int(args.groups_count), first_tee_s, float(args.groups_interval_min))
        golfer_points = _generate_golfer_points_for_groups(args.course_dir, groups)

        sim_result = {
            "type": "standard",
            "run_idx": i,
            "sales_result": {"sales": [], "revenue": 0.0},
            "golfer_points": golfer_points,
            "bev_points": [],
            "pass_events": [],
            "tee_time_s": groups[0]["tee_time_s"] if groups else (9 - 7) * 3600,
            "beverage_cart_service": None,
        }
        run_dir = output_root / f"sim_{i:02d}"
        save_phase3_output_files(sim_result, run_dir, include_stats=False)

        # Events CSV (tee-offs only in this mode)
        try:
            simulation_id = _build_simulation_id(output_root, i)
            events = _events_from_groups_tee_off(groups, simulation_id)
            if events:
                _write_event_log_csv(events, run_dir / "events.csv")
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to write events for golfers-only run %d: %s", i, e)

        run_summaries.append({
            "run_idx": i,
            "tee_time_s": int(sim_result["tee_time_s"]),
            "groups": len(groups),
        })

    # Write a mode-specific summary
    if run_summaries:
        lines: List[str] = [
            "# Golfers-Only Summary",
            "",
            f"Runs: {len(run_summaries)}",
            "",
            "## Run Details",
        ]
        for r in run_summaries:
            lines += [
                f"### Run {r['run_idx']:02d}",
                f"- **Golfer Tee Time**: {_seconds_to_clock_str(r['tee_time_s'])}",
                f"- **Groups**: {r['groups']}",
                "",
                "## Artifacts",
                "- `coordinates.csv` — GPS tracks for golfer groups",
            ]
        (output_root / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    
    # Generate executive summary using Google Gemini
    _generate_executive_summary(output_root)
    
    logger.info("Complete. Results saved to: %s", output_root)


def _run_mode_delivery_runner(args: argparse.Namespace) -> None:
    # Delivery runner mode: 0 bev carts (GPS not simulated here), N runners, N golfers
    default_name = _generate_standardized_output_name(
        mode="delivery-runner",
        num_bev_carts=0,
        num_runners=int(args.num_runners),
        num_golfers=int(args.groups_count),
        tee_scenario=str(args.tee_scenario),
    )
    output_dir = Path(args.output_dir or (Path("outputs") / default_name))
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Starting dynamic delivery runner sims: %d runs", args.num_runs)
    all_runs: List[Dict] = []

    first_tee_s = _first_tee_to_seconds(args.first_tee)
    
    # Load simulation config to get total orders
    from golfsim.config.loaders import load_simulation_config  # local import to avoid scoping issues
    sim_config = load_simulation_config(args.course_dir)

    for run_idx in range(1, int(args.num_runs) + 1):
        # Prefer scenario unless explicitly disabled via --tee-scenario none
        scenario_groups_base = _build_groups_from_scenario(args.course_dir, str(args.tee_scenario))
        if scenario_groups_base:
            groups = scenario_groups_base
        else:
            groups = _build_groups_interval(int(args.groups_count), first_tee_s, float(args.groups_interval_min)) if args.groups_count > 0 else []

        # Calculate base probability from total orders and number of groups
        delivery_order_probability = _calculate_delivery_order_probability_per_9_holes(sim_config.delivery_total_orders, len(groups))

        # Compute crossings to detect bev-cart passes for boost
        crossings = None
        if groups and not bool(getattr(args, "no_bev_cart", False)):
            try:
                nodes_geojson = str(Path(args.course_dir) / "geojson" / "generated" / "lcm_course_nodes.geojson")
                holes_geojson = str(Path(args.course_dir) / "geojson" / "generated" / "holes_geofenced.geojson")
                config_json = str(Path(args.course_dir) / "config" / "simulation_config.json")
                first_tee_in_groups = min(g["tee_time_s"] for g in groups)
                last_tee_in_groups = max(g["tee_time_s"] for g in groups)
                bev_start_s = (9 - 7) * 3600
                crossings = compute_crossings_from_files(
                    nodes_geojson=nodes_geojson,
                    holes_geojson=holes_geojson,
                    config_json=config_json,
                    v_fwd_mph=None,
                    v_bwd_mph=None,
                    bev_start=_seconds_to_clock_str(bev_start_s),
                    groups_start=_seconds_to_clock_str(first_tee_in_groups),
                    groups_end=_seconds_to_clock_str(last_tee_in_groups),
                    groups_count=len(groups),
                    random_seed=int(args.random_seed) if args.random_seed is not None else None,
                    tee_mode="interval",
                    groups_interval_min=float(args.groups_interval_min),
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to compute crossings for bev-cart pass boost: %s", e)
                crossings = None

        # Use unified multi-runner service even for a single runner to allow custom order generation
        env = simpy.Environment()
        service = MultiRunnerDeliveryService(
            env=env,
            course_dir=args.course_dir,
            num_runners=int(args.num_runners),
            runner_speed_mps=float(args.runner_speed),
            prep_time_min=int(args.prep_time),
        )

        # Generate orders with bev-cart pass boost and feed into shared queue
        orders: List[DeliveryOrder] = []
        if groups:
            orders_all = _generate_delivery_orders_with_pass_boost(
                groups=groups,
                base_prob_per_9=float(delivery_order_probability),
                crossings_data=crossings,
                rng_seed=args.random_seed,
            )
            # Restrict order placement to service open window
            orders = [
                o for o in orders_all
                if service.service_open_s <= int(getattr(o, "order_time_s", 0)) <= service.service_close_s
            ]

        def order_arrival_process():  # simpy process
            last_time = env.now
            for order in orders:
                target_time = max(order.order_time_s, service.service_open_s)
                if target_time > last_time:
                    yield env.timeout(target_time - last_time)
                service.place_order(order)
                last_time = target_time

        env.process(order_arrival_process())

        run_until = max(service.service_close_s + 1, max((o.order_time_s for o in orders), default=0) + 4 * 3600)
        env.run(until=run_until)

        # Summarize results in unified format (delivery part)
        sim_result: Dict[str, Any] = {
            "success": True,
            "simulation_type": "multi_golfer_multi_runner" if int(args.num_runners) > 1 else "multi_golfer_single_runner",
            "orders": [
                {
                    "order_id": getattr(o, "order_id", None),
                    "golfer_group_id": getattr(o, "golfer_group_id", None),
                    "golfer_id": getattr(o, "golfer_id", None),
                    "hole_num": getattr(o, "hole_num", None),
                    "order_time_s": getattr(o, "order_time_s", None),
                    "status": getattr(o, "status", "pending"),
                    "total_completion_time_s": getattr(o, "total_completion_time_s", 0.0),
                }
                for o in orders
            ],
            "delivery_stats": service.delivery_stats,
            "failed_orders": [
                {"order_id": getattr(o, "order_id", None), "reason": getattr(o, "failure_reason", None)}
                for o in service.failed_orders
            ],
            "activity_log": service.activity_log,
            "metadata": {
                "prep_time_min": int(args.prep_time),
                "runner_speed_mps": float(args.runner_speed),
                "num_groups": len(groups),
                "num_runners": int(args.num_runners),
                "course_dir": str(args.course_dir),
            },
        }

        # Optionally add beverage cart GPS and sales (traditional bev-cart revenue) for combined metrics
        bev_points: List[Dict[str, Any]] = []
        bev_sales_result: Dict[str, Any] = {"sales": [], "revenue": 0.0}
        golfer_points: List[Dict[str, Any]] = []
        if groups and not bool(getattr(args, "no_bev_cart", False)):
            try:
                # Generate golfer tracks for bev sales proximity/visibility
                golfer_points = _generate_golfer_points_for_groups(args.course_dir, groups)

                # Build beverage cart GPS via BeverageCartService for consistency
                env2 = simpy.Environment()
                svc2 = BeverageCartService(env=env2, course_dir=args.course_dir, cart_id="bev_cart_1", track_coordinates=True, starting_hole=18)
                env2.run(until=svc2.service_end_s)
                bev_points = svc2.coordinates or []

                # Use configured beverage cart order probability per 9 holes
                bev_order_probability = float(getattr(sim_config, "bev_cart_order_probability_per_9_holes", 0.35))
                bev_sales_result = simulate_beverage_cart_sales(
                    course_dir=args.course_dir,
                    groups=groups,
                    pass_order_probability=float(bev_order_probability),
                    price_per_order=float(getattr(args, "avg_order_usd", 12.0)),
                    minutes_between_holes=2.0,
                    minutes_per_hole=None,
                    golfer_points=golfer_points,
                    crossings_data=crossings,
                )

                # Attach bev data so metrics integration can detect bev-cart
                sim_result["bev_points"] = bev_points
                sim_result["sales_result"] = bev_sales_result
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to include beverage cart revenue in delivery-runner mode: %s", e)

        # Create visualizations if requested and there are orders
        if sim_result["orders"] and not bool(getattr(args, "no_visualization", False)):
            try:
                from golfsim.viz.matplotlib_viz import render_delivery_plot, render_individual_delivery_plots
                from golfsim.viz.matplotlib_viz import load_course_geospatial_data
                from golfsim.config.loaders import load_simulation_config
                import networkx as nx

                run_path = output_dir / f"run_{run_idx:02d}"
                run_path.mkdir(parents=True, exist_ok=True)

                # Load course data for visualization
                sim_cfg = load_simulation_config(args.course_dir)
                clubhouse_coords = sim_cfg.clubhouse
                course_data = load_course_geospatial_data(args.course_dir)

                # Try to load cart graph
                cart_graph = None
                cart_graph_path = Path(args.course_dir) / "pkl" / "cart_graph.pkl"
                if cart_graph_path.exists():
                    import pickle
                    with open(cart_graph_path, "rb") as f:
                        cart_graph = pickle.load(f)

                # Create main visualization (all orders together)
                viz_path = run_path / "delivery_orders_map.png"
                render_delivery_plot(
                    results=sim_result,
                    course_data=course_data,
                    clubhouse_coords=clubhouse_coords,
                    cart_graph=cart_graph,
                    save_path=viz_path,
                    style="detailed"
                )

                logger.info("Created delivery visualization: %s", viz_path)
                sim_result["visualization_path"] = str(viz_path)

                # Create individual delivery visualizations (optional)
                if not bool(getattr(args, "no_individual_plots", False)):
                    individual_paths = render_individual_delivery_plots(
                        results=sim_result,
                        course_data=course_data,
                        clubhouse_coords=clubhouse_coords,
                        cart_graph=cart_graph,
                        output_dir=run_path,
                        filename_prefix="delivery_order",
                        style="detailed"
                    )

                    if individual_paths:
                        logger.info("Created %d individual delivery visualizations", len(individual_paths))
                        sim_result["individual_visualization_paths"] = [str(p) for p in individual_paths]

                # Heatmap visualization
                try:
                    heatmap_file = run_path / "delivery_heatmap.png"
                    course_name = Path(args.course_dir).name.replace("_", " ").title()
                    create_course_heatmap(
                        results=sim_result,
                        course_dir=args.course_dir,
                        save_path=heatmap_file,
                        title=f"{course_name} - Delivery Runner Heatmap (Run {run_idx})",
                        colormap='RdYlGn_r'
                    )
                    logger.info("Created delivery heatmap: %s", heatmap_file)
                    sim_result["heatmap_path"] = str(heatmap_file)
                except Exception as e:  # noqa: BLE001
                    logger.warning("Failed to create delivery heatmap: %s", e)

            except Exception as e:
                logger.warning("Failed to create delivery visualization: %s", e)
                sim_result["visualization_error"] = str(e)

        # Persist outputs
        run_path = output_dir / f"run_{run_idx:02d}"
        run_path.mkdir(parents=True, exist_ok=True)

        # Raw results
        (run_path / "results.json").write_text(json.dumps(sim_result, indent=2, default=str), encoding="utf-8")

        # Generate metrics using integrated approach (both bev cart and delivery if present)
        try:
            bev_metrics, delivery_metrics = generate_and_save_metrics(
                simulation_result=sim_result,
                output_dir=run_path,
                run_suffix=f"_run_{run_idx:02d}",
                simulation_id=f"delivery_dynamic_{run_idx:02d}",
                revenue_per_order=float(args.revenue_per_order),
                sla_minutes=int(args.sla_minutes),
                runner_id="runner_1" if int(args.num_runners) == 1 else f"{int(args.num_runners)}_runners",
                service_hours=float(args.service_hours),
                bev_cart_coordinates=bev_points,
                bev_cart_service=svc2 if 'svc2' in locals() else None,
                golfer_data=golfer_points,
            )
            # Combine RPR if both are present
            if bev_metrics and hasattr(bev_metrics, 'revenue_per_round') and delivery_metrics and hasattr(delivery_metrics, 'revenue_per_round'):
                combined_rpr = float(getattr(bev_metrics, 'revenue_per_round', 0.0)) + float(getattr(delivery_metrics, 'revenue_per_round', 0.0))
                metrics = type('CombinedMetrics', (), {'revenue_per_round': combined_rpr})()
            else:
                metrics = delivery_metrics or bev_metrics
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to generate metrics for run %d: %s", run_idx, e)
            metrics = type('MinimalMetrics', (), {
                'revenue_per_round': 0.0,
            })()

        # Events CSV (tee-offs + orders + runner activity)
        try:
            simulation_id = _build_simulation_id(output_dir, run_idx)
            events: List[Dict[str, Any]] = []
            events.extend(_events_from_groups_tee_off(groups, simulation_id))
            if isinstance(sim_result, dict):
                events.extend(_events_from_orders_list(sim_result.get("orders"), simulation_id))
            act = []
            if isinstance(sim_result, dict):
                act = sim_result.get("activity_log", []) or []
            events.extend(
                _events_from_activity_log(
                    act,
                    simulation_id=simulation_id,
                    default_entity_type="delivery_runner",
                    default_entity_id="runner_1" if int(args.num_runners) == 1 else "runners",
                )
            )
            # Include beverage cart activities and sales events if present
            if bev_points and 'svc2' in locals():
                events.extend(
                    _events_from_activity_log(
                        svc2.activity_log,
                        simulation_id=simulation_id,
                        default_entity_type="beverage_cart",
                        default_entity_id="bev_cart_1",
                    )
                )
            if isinstance(bev_sales_result, dict) and bev_sales_result.get("activity_log"):
                events.extend(
                    _events_from_activity_log(
                        bev_sales_result.get("activity_log", []),
                        simulation_id=simulation_id,
                        default_entity_type="order",
                        default_entity_id="sales_event",
                    )
                )
            if events:
                _write_event_log_csv(events, run_path / "events.csv")
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to write events for delivery-runner run %d: %s", run_idx, e)

        # Simple stats
        orders = sim_result.get("orders", [])
        failed_orders = sim_result.get("failed_orders", [])

        stats_md = [
            f"# Delivery Dynamic — Run {run_idx:02d}",
            "",
            f"Groups: {len(groups)}",
            f"Orders placed: {len([o for o in orders if o.get('status') == 'processed'])}",
            f"Orders failed: {len(failed_orders)}",
            f"Revenue per order: ${float(args.revenue_per_order):.2f}",
        ]
        (run_path / f"stats_run_{run_idx:02d}.md").write_text("\n".join(stats_md), encoding="utf-8")

        all_runs.append({
            "run_idx": run_idx,
            "groups": len(groups),
            "orders": len(orders),
            "failed": len(failed_orders),
            "rpr": float(getattr(metrics, 'revenue_per_round', 0.0) or 0.0),
        })

    # Phase-level summary
    lines: List[str] = ["# Delivery Dynamic Summary", "", f"Runs: {len(all_runs)}"]
    if all_runs:
        rprs = [float(r.get("rpr", 0.0)) for r in all_runs]
        lines.append(f"Revenue per round: min=${min(rprs):.2f} max=${max(rprs):.2f} mean=${(sum(rprs)/len(rprs)):.2f}")
    (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    # Generate executive summary using Google Gemini
    _generate_executive_summary(output_dir)

    logger.info("Done. Results in: %s", output_dir)


def _run_mode_optimize_runners(args: argparse.Namespace) -> None:
    """Find minimal number of runners to meet on-time SLA target.

    Uses the same generation logic as delivery-runner mode (multi-runner queue),
    iterating the runner count from 1..max_runners, running num_runs simulations
    for each candidate, and computing the share of successful deliveries whose
    total_completion_time_s ≤ sla_minutes*60. The first runner count whose
    aggregated on-time rate ≥ target_on_time is returned as the recommendation.
    """
    default_name = _generate_standardized_output_name(
        mode="delivery-runner",
        num_bev_carts=0,
        num_runners=0,
        num_golfers=int(args.groups_count),
        tee_scenario=str(args.tee_scenario),
    ) + "_optimize"
    output_dir = Path(args.output_dir or (Path("outputs") / default_name))
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Optimizing runners: target on-time ≥ %.1f%% within %d min (max %d runners, %d runs/candidate)",
        float(args.target_on_time) * 100.0,
        int(args.sla_minutes),
        int(args.max_runners),
        int(args.num_runs),
    )

    # Build groups from scenario or manual args
    scenario_groups_base = _build_groups_from_scenario(args.course_dir, str(args.tee_scenario))
    if scenario_groups_base:
        groups_master = scenario_groups_base
    else:
        first_tee_s = _first_tee_to_seconds(args.first_tee)
        groups_master = _build_groups_interval(int(args.groups_count), first_tee_s, float(args.groups_interval_min)) if args.groups_count > 0 else []

    if not groups_master:
        raise SystemExit("No golfer groups defined; set --tee-scenario or --groups-count/--first-tee.")

    # Load simulation config to get total orders
    from golfsim.config.loaders import load_simulation_config  # local import to avoid scoping issues
    sim_config = load_simulation_config(args.course_dir)
    delivery_order_probability = _calculate_delivery_order_probability_per_9_holes(sim_config.delivery_total_orders, len(groups_master))

    # Pre-compute bev-cart crossings for pass-based probability boost
    crossings_opt: Optional[Dict[str, Any]] = None
    try:
        if groups_master:
            nodes_geojson = str(Path(args.course_dir) / "geojson" / "generated" / "lcm_course_nodes.geojson")
            holes_geojson = str(Path(args.course_dir) / "geojson" / "generated" / "holes_geofenced.geojson")
            config_json = str(Path(args.course_dir) / "config" / "simulation_config.json")
            first_tee_in_groups = min(g["tee_time_s"] for g in groups_master)
            last_tee_in_groups = max(g["tee_time_s"] for g in groups_master)
            bev_start_s = (9 - 7) * 3600
            crossings_opt = compute_crossings_from_files(
                nodes_geojson=nodes_geojson,
                holes_geojson=holes_geojson,
                config_json=config_json,
                v_fwd_mph=None,
                v_bwd_mph=None,
                bev_start=_seconds_to_clock_str(bev_start_s),
                groups_start=_seconds_to_clock_str(first_tee_in_groups),
                groups_end=_seconds_to_clock_str(last_tee_in_groups),
                groups_count=len(groups_master),
                random_seed=int(args.random_seed) if args.random_seed is not None else None,
                tee_mode="interval",
                groups_interval_min=float(args.groups_interval_min),
            )
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to compute crossings for optimization: %s", e)
        crossings_opt = None

    results_table: List[Dict[str, Any]] = []
    recommendation: Optional[int] = None

    for num_runners in range(1, int(args.max_runners) + 1):
        total_delivered = 0
        total_on_time = 0
        total_failed = 0
        total_orders = 0
        total_late = 0
        # Collect utilization data from all runs for this runner count
        all_activity_logs = []
        all_delivery_stats = []

        for run_idx in range(1, int(args.num_runs) + 1):
            env = simpy.Environment()
            service = MultiRunnerDeliveryService(
                env=env,
                course_dir=args.course_dir,
                num_runners=int(num_runners),
                runner_speed_mps=float(args.runner_speed),
                prep_time_min=int(args.prep_time),
            )

            # Generate orders deterministically per run index, with bev-cart pass boost
            orders_all = _generate_delivery_orders_with_pass_boost(
                groups=[dict(g) for g in groups_master],
                base_prob_per_9=float(delivery_order_probability),
                crossings_data=crossings_opt,
                rng_seed=(args.random_seed or 0) + run_idx,
            )
            # Restrict order placement to service open window
            orders = [
                o for o in orders_all
                if service.service_open_s <= int(getattr(o, "order_time_s", 0)) <= service.service_close_s
            ]

            def order_arrival_process():  # simpy process
                last_time = env.now
                for order in orders:
                    target_time = max(order.order_time_s, service.service_open_s)
                    if target_time > last_time:
                        yield env.timeout(target_time - last_time)
                    service.place_order(order)
                    last_time = target_time

            env.process(order_arrival_process())

            run_until = max(service.service_close_s + 1, max((o.order_time_s for o in orders), default=0) + 4 * 3600)
            env.run(until=run_until)

            # Aggregate per-run SLA counts
            sla_s = int(args.sla_minutes) * 60
            delivered = service.delivery_stats or []
            on_time = sum(1 for d in delivered if int(d.get("total_completion_time_s", 0)) <= sla_s)
            late = max(0, len(delivered) - on_time)
            total_delivered += len(delivered)
            total_on_time += on_time
            total_failed += len(service.failed_orders or [])
            total_late += late
            total_orders += len(orders)
            
            # Collect activity log and delivery stats for utilization calculation
            if hasattr(service, 'activity_log') and service.activity_log:
                all_activity_logs.extend(service.activity_log)
            # Also collect delivery stats for utilization calculation
            if hasattr(service, 'delivery_stats') and service.delivery_stats:
                all_delivery_stats.extend(service.delivery_stats)
            


        on_time_rate = (total_on_time / total_delivered) if total_delivered > 0 else 0.0
        
        # Calculate utilization metrics across all runs for this runner count
        utilization_data = {}
        order_metrics = {}
        if all_activity_logs:
            try:
                # Calculate utilization from activity log (includes all time, even for failed orders)
                utilization_data = _calculate_utilization_from_activity_log(all_activity_logs, float(args.service_hours))
                # Use delivery stats for order metrics (successful orders only)
                order_metrics = _calculate_order_metrics_from_stats(all_delivery_stats) if all_delivery_stats else {}
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to calculate utilization for %d runners: %s", num_runners, e)
        
        results_table.append({
            "num_runners": int(num_runners),
            "runs": int(args.num_runs),
            "orders": int(total_orders),
            "delivered": int(total_delivered),
            "failed": int(total_failed),
            "late": int(total_late),
            "on_time_rate": float(on_time_rate),
            "utilization_by_runner": utilization_data,
            "order_metrics_by_runner": order_metrics,
        })

        # Format utilization and order metrics summary for log output
        util_summary = ""
        if utilization_data and order_metrics:
            util_parts = []
            for runner_id in utilization_data.keys():
                # Use driving utilization from the existing metrics
                driving_util = utilization_data[runner_id].get('driving', 0)
                orders_count = order_metrics[runner_id].get('orders_delivered', 0)
                avg_time = order_metrics[runner_id].get('avg_order_time_min', 0)
                util_parts.append(f"{runner_id}: {driving_util:.0f}% util, {orders_count} orders, {avg_time:.1f}min avg")
            util_summary = f" | {', '.join(util_parts)}" if util_parts else ""
        
        logger.info(
            "num_runners=%d → on-time %.1f%% (delivered %d / orders %d, late %d, failed %d)%s",
            num_runners,
            on_time_rate * 100.0,
            total_delivered,
            total_orders,
            total_late,
            total_failed,
            util_summary,
        )

        if on_time_rate >= float(args.target_on_time) and total_delivered > 0:
            recommendation = int(num_runners)
            break

    # Persist summary
    try:
        (output_dir / "optimization_summary.json").write_text(
            json.dumps(
                {
                    "target_on_time": float(args.target_on_time),
                    "sla_minutes": int(args.sla_minutes),
                    "max_runners": int(args.max_runners),
                    "num_runs_per_candidate": int(args.num_runs),
                    "results": results_table,
                    "recommended_runners": recommendation,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        lines: List[str] = [
            "# Optimize Runners Summary",
            "",
            f"Target: on-time ≥ {float(args.target_on_time)*100:.1f}% within {int(args.sla_minutes)} minutes",
            f"Runs per candidate: {int(args.num_runs)}",
            "",
            "## Results",
        ]
        for r in results_table:
            late = int(r.get('delivered', 0) - int(r.get('on_time_rate', 0) * max(1, r.get('delivered', 0))))
            
            # Format utilization and order metrics for summary
            util_text = ""
            utilization_by_runner = r.get('utilization_by_runner', {})
            order_metrics_by_runner = r.get('order_metrics_by_runner', {})
            if utilization_by_runner and order_metrics_by_runner:
                util_parts = []
                for runner_id in utilization_by_runner.keys():
                    # Use driving utilization from the existing metrics
                    driving_util = utilization_by_runner[runner_id].get('driving', 0)
                    orders_count = order_metrics_by_runner[runner_id].get('orders_delivered', 0)
                    avg_time = order_metrics_by_runner[runner_id].get('avg_order_time_min', 0)
                    util_parts.append(f"{runner_id}: {driving_util:.0f}% util, {orders_count} orders, {avg_time:.1f}min avg")
                util_text = f" | {'; '.join(util_parts)}"
            
            lines.append(
                f"- **{r['num_runners']} runner(s)**: on-time {r['on_time_rate']*100:.1f}% — delivered {r['delivered']} / orders {r['orders']} (late {late}, failed {r['failed']}){util_text}"
            )
        lines += [
            "",
            f"## Recommended runners: {recommendation if recommendation is not None else 'not achieved up to max'}",
        ]
        (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to write optimization summary: %s", e)

    # Generate heatmap for recommended runner configuration
    if recommendation is not None:
        try:
            logger.info("Generating heatmap for recommended %d runners...", recommendation)
            
            # Run one final simulation with the recommended number of runners for heatmap
            env = simpy.Environment()
            service = MultiRunnerDeliveryService(
                env=env,
                course_dir=args.course_dir,
                num_runners=int(recommendation),
                runner_speed_mps=float(args.runner_speed),
                prep_time_min=int(args.prep_time),
            )

            # Generate orders with bev-cart pass boost for heatmap
            orders_all = _generate_delivery_orders_with_pass_boost(
                groups=[dict(g) for g in groups_master],
                base_prob_per_9=float(delivery_order_probability),
                crossings_data=crossings_opt,
                rng_seed=(args.random_seed or 0) + 999,  # Use different seed for heatmap run
            )
            orders = [
                o for o in orders_all
                if service.service_open_s <= int(getattr(o, "order_time_s", 0)) <= service.service_close_s
            ]

            def order_arrival_process():  # simpy process
                last_time = env.now
                for order in orders:
                    target_time = max(order.order_time_s, service.service_open_s)
                    if target_time > last_time:
                        yield env.timeout(target_time - last_time)
                    service.place_order(order)
                    last_time = target_time

            env.process(order_arrival_process())
            run_until = max(service.service_close_s + 1, max((o.order_time_s for o in orders), default=0) + 4 * 3600)
            env.run(until=run_until)

            # Format results for heatmap
            heatmap_results = {
                'orders': [
                    {
                        "order_id": getattr(o, "order_id", None),
                        "golfer_group_id": getattr(o, "golfer_group_id", None),
                        "hole_num": getattr(o, "hole_num", None),
                        "order_time_s": getattr(o, "order_time_s", None),
                        "total_completion_time_s": getattr(o, "total_completion_time_s", 0.0),
                    }
                    for o in orders
                ],
                'delivery_stats': service.delivery_stats
            }

            # Create heatmap
            heatmap_file = output_dir / "recommended_runners_heatmap.png"
            course_name = Path(args.course_dir).name.replace("_", " ").title()
            create_course_heatmap(
                results=heatmap_results,
                course_dir=args.course_dir,
                save_path=heatmap_file,
                title=f"{course_name} - Optimized Delivery Heatmap ({recommendation} Runners)",
                colormap='RdYlGn_r'
            )
            logger.info("Created optimization heatmap: %s", heatmap_file)

        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to create optimization heatmap: %s", e)

    # Generate executive summary using Google Gemini
    _generate_executive_summary(output_dir)

    if recommendation is not None:
        logger.info("Recommended number of runners: %d", recommendation)
    else:
        logger.info("Target not achieved up to max runners = %d", int(args.max_runners))


# -------------------- CLI --------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified simulation runner for beverage carts and delivery runner",
    )

    # Top-level mode selector
    parser.add_argument(
        "--mode",
        type=str,
        choices=["bev-carts", "bev-with-golfers", "golfers-only", "delivery-runner", "single-golfer", "optimize-runners"],
        default="bev-carts",
        help="Simulation mode",
    )

    # Common
    parser.add_argument("--course-dir", default="courses/pinetree_country_club", help="Course directory")
    parser.add_argument("--num-runs", type=int, default=5, help="Number of runs")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory root")
    parser.add_argument("--log-level", type=str, default="INFO", help="Log level")

    # Groups scheduling
    parser.add_argument("--groups-count", type=int, default=0, help="Number of golfer groups (0 for none)")
    parser.add_argument("--groups-interval-min", type=float, default=15.0, help="Interval between groups in minutes")
    parser.add_argument("--first-tee", type=str, default="09:00", help="First tee time HH:MM")
    parser.add_argument(
        "--tee-scenario",
        type=str,
        default="typical_weekday",
        help=(
            "Tee-times scenario key from course tee_times_config.json. "
            "Use 'none' to disable and rely on manual --groups-* options."
        ),
    )

    # Beverage cart params
    parser.add_argument("--num-carts", type=int, default=1, help="Number of carts for bev-carts mode")
    parser.add_argument("--order-prob", type=float, default=0.4, help="[DEPRECATED] Use bev_cart_order_probability_per_9_holes in simulation_config.json")
    parser.add_argument("--avg-order-usd", type=float, default=12.0, help="Average order value in USD for bev-with-golfers")
    parser.add_argument("--random-seed", type=int, default=None, help="Optional RNG seed for bev-with-golfers runs and crossings")

    # Delivery runner params
    parser.add_argument("--order-prob-9", type=float, default=0.5, help="[DEPRECATED] Order probability is now calculated from delivery_total_orders in simulation_config.json")
    parser.add_argument("--prep-time", type=int, default=10, help="Food preparation time in minutes")
    parser.add_argument(
        "--runner-speed",
        type=float,
        default=6.0,
        help="Runner speed (single-golfer: mph; other modes: m/s)",
    )
    parser.add_argument("--revenue-per-order", type=float, default=25.0, help="Revenue per successful order")
    parser.add_argument("--sla-minutes", type=int, default=30, help="SLA in minutes")
    parser.add_argument("--service-hours", type=float, default=10.0, help="Active service hours for runner (metrics scaling)")
    parser.add_argument("--num-runners", type=int, default=1, help="Number of delivery runners (1 for single-runner, >1 enables multi-runner shared queue)")
    parser.add_argument("--no-bev-cart", action="store_true", help="Disable bev-cart pass boost (simulate 0 beverage carts during delivery hours)")
    parser.add_argument("--no-individual-plots", action="store_true", help="Skip per-order PNGs; keep overall map/heatmap")
    # Optimization params
    parser.add_argument("--target-on-time", type=float, default=0.99, help="Target on-time rate (0..1) for optimization")
    parser.add_argument("--max-runners", type=int, default=6, help="Maximum runners to consider for optimization")

    # Single-golfer params
    parser.add_argument("--hole", type=int, choices=range(1, 19), metavar="1-18", help="Specific hole for single-golfer mode; random if omitted")
    parser.add_argument("--placement", choices=["tee", "mid", "green"], default="mid", help="Where on the --hole to place the order")
    parser.add_argument("--runner-delay", type=float, default=0.0, metavar="MIN", help="Additional delay before runner departs (busy runner)")
    parser.add_argument("--no-enhanced", action="store_true", help="Don't use enhanced cart network")
    parser.add_argument("--no-coordinates", action="store_true", help="Disable GPS coordinate tracking")
    parser.add_argument("--no-visualization", action="store_true", help="Skip creating visualizations")

    args = parser.parse_args()
    init_logging(args.log_level)

    logger.info("Unified simulation runner starting. Mode: %s", args.mode)
    logger.info("Course: %s", args.course_dir)
    logger.info("Runs: %d", args.num_runs)

    if args.mode == "bev-carts":
        _run_mode_bev_carts(args)
    elif args.mode == "bev-with-golfers":
        if int(args.num_carts) != 1:
            logger.warning("bev-with-golfers uses a single cart; forcing --num-carts=1")
        _run_mode_bev_with_golfers(args)
    elif args.mode == "golfers-only":
        _run_mode_golfers_only(args)
    elif args.mode == "delivery-runner":
        _run_mode_delivery_runner(args)
    elif args.mode == "single-golfer":
        _run_mode_single_golfer(args)
    elif args.mode == "optimize-runners":
        _run_mode_optimize_runners(args)
    else:
        raise SystemExit(f"Unknown mode: {args.mode}")


if __name__ == "__main__":
    main()


