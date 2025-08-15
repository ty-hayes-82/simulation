#!/usr/bin/env python3
"""
Unified Simulation Runner with Delivery Hole Blocking Support

Extended version of run_unified_simulation.py that adds support for:
- Blocking delivery orders up to specified holes
- Comprehensive testing configurations
- Enhanced coordinate tracking

Modes:
- bev-carts: Beverage cart GPS only (supports 1..N carts)
- bev-with-golfers: Single cart + golfer groups sales simulation
- golfers-only: Generate golfer GPS tracks only (no cart, no runner)
- delivery-runner: Delivery runner serving 0..N golfer groups (with hole blocking support)
- single-golfer: Single golfer delivery simulation
- optimize-runners: Find minimal number of delivery runners to meet SLA target

Windows PowerShell friendly: one short command per line, no piping/chaining.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime
from pathlib import Path
import sys
from typing import Dict, List, Tuple, Any, Optional

import simpy

from golfsim.logging import init_logging, get_logger
from golfsim.config.loaders import load_tee_times_config, load_simulation_config
from golfsim.simulation.services import (
    BeverageCartService,
    run_multi_golfer_simulation,
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
from golfsim.io.phase_reporting import save_phase3_output_files, write_phase3_summary
from golfsim.analysis.metrics_integration import generate_and_save_metrics
from golfsim.simulation.engine import run_golf_delivery_simulation
from utils.simulation_reporting import (
    log_simulation_results,
    write_multi_run_summary,
    create_delivery_log,
    handle_simulation_error,
)

# Helper functions (minimal implementations needed for this script)
def _calculate_delivery_order_probability_per_9_holes(total_orders: int, num_groups: int) -> float:
    """Calculate delivery order probability per 9 holes from total orders and number of groups."""
    if num_groups <= 0:
        return 0.0
    total_opportunities = num_groups * 2  # Each group has 2 opportunities (front 9, back 9)
    probability = total_orders / total_opportunities
    return min(probability, 1.0)

def _generate_standardized_output_name(
    mode: str,
    num_bev_carts: int = 0,
    num_runners: int = 0,
    num_golfers: int = 0,
    tee_scenario: str = None,
    hole: int = None,
) -> str:
    """Generate standardized output directory name."""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    parts = [ts]
    
    if num_bev_carts > 0:
        parts.append(f"{num_bev_carts}bevcarts")
    else:
        parts.append("0bevcarts")
    
    if num_runners > 0:
        parts.append(f"{num_runners}runners")
    else:
        parts.append("0runners")
    
    if num_golfers > 0:
        parts.append(f"{num_golfers}golfers")
    else:
        parts.append("0golfers")
    
    if tee_scenario and tee_scenario.lower() not in {"none", "manual"}:
        parts.append(tee_scenario)
    
    if hole is not None:
        parts.append(f"hole{hole}")
    elif mode == "single-golfer":
        parts.append("randomhole")
    
    return "_".join(parts)

def _seconds_to_clock_str(sec_since_7am: int) -> str:
    """Convert seconds since 7am to HH:MM:SS format."""
    total = max(0, int(sec_since_7am))
    hh = 7 + (total // 3600)
    mm = (total % 3600) // 60
    ss = total % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"

def _first_tee_to_seconds(hhmm: str) -> int:
    """Convert HH:MM to seconds since 7am."""
    hh, mm = hhmm.split(":")
    return (int(hh) - 7) * 3600 + int(mm) * 60

def _build_simulation_id(output_root: Path, run_idx: int) -> str:
    """Create a compact simulation_id for a run directory."""
    try:
        return f"{output_root.name}_run_{run_idx:02d}"
    except Exception:
        return f"sim_run_{run_idx:02d}"

def _parse_hhmm_to_seconds_since_7am(hhmm: str) -> int:
    """Parse HH:MM to seconds since 7am."""
    try:
        hh, mm = hhmm.split(":")
        return (int(hh) - 7) * 3600 + int(mm) * 60
    except Exception:
        return 0

def _build_groups_from_scenario(course_dir: str, scenario_key: str, default_group_size: int = 4) -> List[Dict]:
    """Build golfer groups using a named scenario from tee_times_config.json."""
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

def _build_groups_interval(count: int, first_tee_s: int, interval_min: float) -> List[Dict]:
    """Build groups with regular intervals."""
    groups: List[Dict] = []
    for i in range(count):
        groups.append({
            "group_id": i + 1,
            "tee_time_s": int(first_tee_s + i * int(interval_min * 60)),
            "num_golfers": 4,
        })
    return groups

def _write_event_log_csv(events: List[Dict[str, Any]], save_path: Path) -> None:
    """Write a unified, replay-friendly events CSV."""
    import csv
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "simulation_id", "ID", "timestamp", "timestamp_s", "action", "node_id", "hole",
        "ttl_amt", "type", "order_id", "runner_id", "cart_id", "group_id",
        "latitude", "longitude", "status", "details",
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
        events.append({
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
        })
    return events

def _events_from_groups_tee_off(groups: List[Dict[str, Any]], simulation_id: str) -> List[Dict[str, Any]]:
    """Create events for group tee-offs."""
    events: List[Dict[str, Any]] = []
    for g in groups or []:
        tee_s = int(g.get("tee_time_s", 0))
        events.append({
            "simulation_id": simulation_id,
            "ID": f"golf_group_{int(g.get('group_id', 0))}",
            "timestamp": _seconds_to_clock_str(tee_s),
            "timestamp_s": tee_s,
            "action": "tee_off",
            "hole": 1,
            "type": "golfer_group",
            "group_id": int(g.get("group_id", 0)),
        })
    return events

def _events_from_orders_list(orders: List[Dict[str, Any]] | None, simulation_id: str) -> List[Dict[str, Any]]:
    """Create events from orders list."""
    events: List[Dict[str, Any]] = []
    for o in orders or []:
        ts_s = int(o.get("order_time_s", 0))
        events.append({
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
        })
    return events

logger = get_logger(__name__)

def _simulate_delivery_orders_with_hole_blocking(
    groups: List[Dict[str, Any]],
    delivery_prob_per_9: float,
    block_up_to_hole: int = 0,
    front9_prob_if_blocked: Optional[float] = None,
    minutes_per_hole: int = 12,
    rng_seed: Optional[int] = None,
) -> List[DeliveryOrder]:
    """Generate delivery orders with hole blocking constraints.
    
    Args:
        groups: List of golfer groups with tee times
        delivery_prob_per_9: Base probability of ordering per 9 holes
        block_up_to_hole: Block orders up to this hole number (0 = no blocking)
        front9_prob_if_blocked: Alternative probability for front 9 when blocking is active
        minutes_per_hole: Minutes between holes for timing calculation
        rng_seed: Random seed for reproducible order generation
    
    Returns:
        List of DeliveryOrder objects with timing and hole constraints applied
    """
    if rng_seed is not None:
        random.seed(rng_seed)
    
    orders: List[DeliveryOrder] = []
    block_upto = int(block_up_to_hole or 0)
    use_blocking = block_upto >= 1
    
    # Use alternative probability for front 9 if blocking is active
    front_prob = float(front9_prob_if_blocked) if (use_blocking and front9_prob_if_blocked is not None) else float(delivery_prob_per_9)
    
    # Calculate valid hole ranges
    front_min_hole = max(block_upto + 1, 1) if use_blocking else 1
    front_max_hole = 9
    
    for group in groups:
        group_id = group["group_id"]
        tee_time_s = int(group["tee_time_s"])
        
        # Front nine orders (with blocking constraints)
        if front_min_hole <= front_max_hole:  # Valid range exists
            if random.random() < front_prob:
                hole_front = random.randint(front_min_hole, front_max_hole)
                order_time_front_s = tee_time_s + (hole_front - 1) * minutes_per_hole * 60
                orders.append(DeliveryOrder(
                    order_id=None,  # Will be assigned later
                    golfer_group_id=group_id,
                    golfer_id=f"G{group_id}",
                    order_time_s=order_time_front_s,
                    hole_num=hole_front,
                ))
        
        # Back nine orders (no blocking constraints)
        if random.random() < float(delivery_prob_per_9):
            hole_back = random.randint(10, 18)
            order_time_back_s = tee_time_s + (hole_back - 1) * minutes_per_hole * 60
            orders.append(DeliveryOrder(
                order_id=None,  # Will be assigned later
                golfer_group_id=group_id,
                golfer_id=f"G{group_id}",
                order_time_s=order_time_back_s,
                hole_num=hole_back,
            ))
    
    # Sort by order time and assign sequential IDs
    orders.sort(key=lambda x: x.order_time_s)
    for i, order in enumerate(orders, 1):
        order.order_id = f"{i:03d}"
    
    return orders

def _run_mode_delivery_runner_with_blocking(args: argparse.Namespace) -> None:
    """Enhanced delivery runner mode with hole blocking support."""
    # Generate output name with blocking info
    blocking_suffix = f"_block{args.block_up_to_hole}" if args.block_up_to_hole > 0 else "_full"
    default_name = _generate_standardized_output_name(
        mode="delivery-runner",
        num_bev_carts=0,
        num_runners=int(args.num_runners),
        num_golfers=int(args.groups_count),
        tee_scenario=str(args.tee_scenario),
    ) + blocking_suffix
    
    output_dir = Path(args.output_dir or (Path("outputs") / default_name))
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info("Starting delivery runner sims with hole blocking: %d runs", args.num_runs)
    logger.info("Blocking orders up to hole: %d", args.block_up_to_hole)
    all_runs: List[Dict] = []
    
    first_tee_s = _first_tee_to_seconds(args.first_tee)
    
    # Load simulation config to get total orders
    sim_config = load_simulation_config(args.course_dir)
    
    for run_idx in range(1, int(args.num_runs) + 1):
        # Build groups from scenario or manual args
        scenario_groups_base = _build_groups_from_scenario(args.course_dir, str(args.tee_scenario))
        if scenario_groups_base:
            groups = scenario_groups_base
        else:
            groups = _build_groups_interval(int(args.groups_count), first_tee_s, float(args.groups_interval_min)) if args.groups_count > 0 else []
        
        # Calculate base probability from config
        delivery_order_probability = _calculate_delivery_order_probability_per_9_holes(sim_config.delivery_total_orders, len(groups))
        
        # Generate orders with blocking constraints
        orders = _simulate_delivery_orders_with_hole_blocking(
            groups=groups,
            delivery_prob_per_9=delivery_order_probability,
            block_up_to_hole=int(args.block_up_to_hole),
            front9_prob_if_blocked=getattr(args, 'front9_prob_if_blocked', None),
            rng_seed=(args.random_seed or 0) + run_idx,
        )
        
        logger.info("Run %d: Generated %d orders (blocked up to hole %d)", 
                   run_idx, len(orders), args.block_up_to_hole)
        
        # Create simulation environment
        env = simpy.Environment()
        service = MultiRunnerDeliveryService(
            env=env,
            course_dir=args.course_dir,
            num_runners=int(args.num_runners),
            runner_speed_mps=float(args.runner_speed),
            prep_time_min=int(args.prep_time),
        )
        
        # Feed orders into the service
        def order_arrival_process():
            last_time = env.now
            for order in orders:
                target_time = max(order.order_time_s, service.service_open_s)
                if target_time > last_time:
                    yield env.timeout(target_time - last_time)
                service.place_order(order)
                last_time = target_time
        
        env.process(order_arrival_process())
        
        # Run simulation
        run_until = max(
            service.service_close_s + 1, 
            max((o.order_time_s for o in orders), default=0) + 4 * 3600
        )
        env.run(until=run_until)
        
        # Summarize results
        sim_result = {
            "success": True,
            "simulation_type": "delivery_runner_with_blocking",
            "blocking_config": {
                "block_up_to_hole": int(args.block_up_to_hole),
                "front9_prob_if_blocked": getattr(args, 'front9_prob_if_blocked', None),
            },
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
                "block_up_to_hole": int(args.block_up_to_hole),
            },
        }
        
        # Save results
        run_path = output_dir / f"run_{run_idx:02d}"
        run_path.mkdir(parents=True, exist_ok=True)
        
        # Raw results
        (run_path / "results.json").write_text(json.dumps(sim_result, indent=2, default=str), encoding="utf-8")
        
        # Generate metrics
        try:
            _, delivery_metrics = generate_and_save_metrics(
                simulation_result=sim_result,
                output_dir=run_path,
                run_suffix=f"_run_{run_idx:02d}",
                simulation_id=f"delivery_blocked_{run_idx:02d}",
                revenue_per_order=float(args.revenue_per_order),
                sla_minutes=int(args.sla_minutes),
                runner_id="runner_1" if int(args.num_runners) == 1 else f"{int(args.num_runners)}_runners",
                service_hours=float(args.service_hours),
            )
            metrics = delivery_metrics
        except Exception as e:
            logger.warning("Failed to generate metrics for run %d: %s", run_idx, e)
            metrics = type('MinimalMetrics', (), {'revenue_per_round': 0.0})()
        
        # Events CSV
        try:
            simulation_id = _build_simulation_id(output_dir, run_idx)
            events: List[Dict[str, Any]] = []
            events.extend(_events_from_groups_tee_off(groups, simulation_id))
            events.extend(_events_from_orders_list(sim_result.get("orders"), simulation_id))
            events.extend(_events_from_activity_log(
                sim_result.get("activity_log", []),
                simulation_id=simulation_id,
                default_entity_type="delivery_runner",
                default_entity_id="runner_1" if int(args.num_runners) == 1 else "runners",
            ))
            if events:
                _write_event_log_csv(events, run_path / "events.csv")
        except Exception as e:
            logger.warning("Failed to write events for run %d: %s", run_idx, e)
        
        # Coordinates CSV if available
        try:
            if hasattr(service, 'coordinates') and service.coordinates:
                tracks = {"delivery_runners": service.coordinates}
                write_unified_coordinates_csv(tracks, run_path / "coordinates.csv")
        except Exception as e:
            logger.warning("Failed to write coordinates for run %d: %s", run_idx, e)
        
        # Simple stats
        orders_processed = sim_result.get("orders", [])
        failed_orders = sim_result.get("failed_orders", [])
        
        stats_md = [
            f"# Delivery with Blocking — Run {run_idx:02d}",
            "",
            f"**Blocking:** Up to hole {args.block_up_to_hole} {'(no blocking)' if args.block_up_to_hole == 0 else ''}",
            f"**Groups:** {len(groups)}",
            f"**Orders placed:** {len([o for o in orders_processed if o.get('status') == 'processed'])}",
            f"**Orders failed:** {len(failed_orders)}",
            f"**Runners:** {args.num_runners}",
            f"**Revenue per order:** ${float(args.revenue_per_order):.2f}",
        ]
        (run_path / f"stats_run_{run_idx:02d}.md").write_text("\n".join(stats_md), encoding="utf-8")
        
        all_runs.append({
            "run_idx": run_idx,
            "groups": len(groups),
            "orders": len(orders_processed),
            "failed": len(failed_orders),
            "blocked_up_to_hole": int(args.block_up_to_hole),
            "rpr": float(getattr(metrics, 'revenue_per_round', 0.0) or 0.0),
        })
    
    # Create summary
    lines: List[str] = [
        "# Delivery with Hole Blocking Summary", 
        "",
        f"**Blocking:** Up to hole {args.block_up_to_hole} {'(full course)' if args.block_up_to_hole == 0 else ''}",
        f"**Runs:** {len(all_runs)}",
        f"**Runners:** {args.num_runners}",
    ]
    if all_runs:
        rprs = [float(r.get("rpr", 0.0)) for r in all_runs]
        orders_counts = [r.get("orders", 0) for r in all_runs]
        lines.extend([
            f"**Revenue per round:** min=${min(rprs):.2f} max=${max(rprs):.2f} mean=${(sum(rprs)/len(rprs)):.2f}",
            f"**Orders per run:** min={min(orders_counts)} max={max(orders_counts)} mean={sum(orders_counts)/len(orders_counts):.1f}",
        ])
    (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")
    
    logger.info("Delivery runner with blocking complete. Results in: %s", output_dir)

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified simulation runner with delivery hole blocking support",
    )
    
    # Top-level mode selector
    parser.add_argument(
        "--mode",
        type=str,
        choices=["bev-carts", "bev-with-golfers", "golfers-only", "delivery-runner", "single-golfer", "optimize-runners"],
        default="delivery-runner",
        help="Simulation mode",
    )
    
    # Common args (copied from original script)
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
        help="Tee-times scenario key from course tee_times_config.json",
    )
    
    # Beverage cart params
    parser.add_argument("--num-carts", type=int, default=1, help="Number of carts for bev-carts mode")
    parser.add_argument("--avg-order-usd", type=float, default=12.0, help="Average order value in USD for bev-with-golfers")
    parser.add_argument("--no-bev-cart", action="store_true", help="Disable beverage cart simulation (for delivery-runner-only mode)")
    parser.add_argument("--random-seed", type=int, default=None, help="Optional RNG seed")
    
    # Delivery runner params
    parser.add_argument("--prep-time", type=int, default=10, help="Food preparation time in minutes")
    parser.add_argument("--runner-speed", type=float, default=2.68, help="Runner speed in m/s")
    parser.add_argument("--revenue-per-order", type=float, default=25.0, help="Revenue per successful order")
    parser.add_argument("--sla-minutes", type=int, default=30, help="SLA in minutes")
    parser.add_argument("--service-hours", type=float, default=10.0, help="Active service hours for runner")
    parser.add_argument("--num-runners", type=int, default=1, help="Number of delivery runners")
    
    # Hole blocking parameters (NEW)
    parser.add_argument("--block-up-to-hole", type=int, default=0, 
                       help="Block delivery orders up to this hole number (0 = no blocking, 3 = block holes 1-3, 6 = block holes 1-6)")
    parser.add_argument("--front9-prob-if-blocked", type=float, default=None,
                       help="Alternative order probability for front 9 when blocking is active (default: use same as back 9)")
    
    # Optimization params
    parser.add_argument("--target-on-time", type=float, default=0.99, help="Target on-time rate (0..1) for optimization")
    parser.add_argument("--max-runners", type=int, default=6, help="Maximum runners to consider for optimization")
    
    # Single-golfer params (copied from original)
    parser.add_argument("--hole", type=int, choices=range(1, 19), metavar="1-18", help="Specific hole for single-golfer mode")
    parser.add_argument("--placement", choices=["tee", "mid", "green"], default="mid", help="Where on the --hole to place the order")
    parser.add_argument("--runner-delay", type=float, default=0.0, metavar="MIN", help="Additional delay before runner departs")
    parser.add_argument("--no-enhanced", action="store_true", help="Don't use enhanced cart network")
    parser.add_argument("--no-coordinates", action="store_true", help="Disable GPS coordinate tracking")
    parser.add_argument("--no-visualization", action="store_true", help="Skip creating visualizations")
    
    args = parser.parse_args()
    init_logging(args.log_level)
    
    logger.info("Unified simulation runner with blocking starting. Mode: %s", args.mode)
    logger.info("Course: %s", args.course_dir)
    logger.info("Runs: %d", args.num_runs)
    if args.mode == "delivery-runner":
        logger.info("Hole blocking: up to hole %d", args.block_up_to_hole)
    
    # Route to appropriate mode handler
    if args.mode == "delivery-runner":
        _run_mode_delivery_runner_with_blocking(args)
    else:
        logger.warning("Mode '%s' not implemented in blocking version", args.mode)
        logger.info("This script only supports delivery-runner mode with hole blocking")
        logger.info("Use run_unified_simulation.py for other modes")
        raise SystemExit(f"Mode '{args.mode}' not supported in blocking version")

if __name__ == "__main__":
    main()
