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

Windows PowerShell friendly: one short command per line, no piping/chaining.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

import simpy

from golfsim.logging import init_logging, get_logger
from golfsim.config.loaders import load_tee_times_config, load_simulation_config
from golfsim.simulation.services import (
    BeverageCartService,
    run_multi_golfer_simulation,
)
from golfsim.simulation.phase_simulations import generate_golfer_track
from golfsim.simulation.scenarios import build_groups_from_scenario as _lib_build_groups_from_scenario, build_groups_interval as _lib_build_groups_interval
from golfsim.simulation.crossings import (
    compute_crossings_from_files,
    serialize_crossings_summary,
)
from golfsim.simulation.bev_cart_pass import simulate_beverage_cart_sales
from golfsim.io.results import write_unified_coordinates_csv, write_order_tracking_log
from golfsim.viz.matplotlib_viz import render_beverage_cart_plot
from golfsim.utils.time import seconds_since_7am
from golfsim.io.phase_reporting import save_phase3_output_files, write_phase3_summary
from golfsim.analysis.metrics_integration import generate_and_save_metrics
from golfsim.viz.matplotlib_viz import load_course_geospatial_data
from golfsim.viz.matplotlib_viz import render_delivery_plot
from utils.io import update_coordinates_manifest, copy_to_visualization_public  # re-exported helpers


logger = get_logger(__name__)
# -------------------- Backlog metrics --------------------
def _compute_backlog_metrics(sim_result: Dict[str, Any]) -> Dict[str, Any]:
    """Compute backlog-related delay metrics from a delivery-runner simulation result.

    Backlog here is represented by non-zero `queue_delay_s` for orders in
    `delivery_stats` (time an order waited before processing began because the
    runner was busy with prior work).

    Returns a dictionary suitable for embedding back into the simulation result
    and for use in per-run markdown summaries.
    """
    delivery_stats: List[Dict[str, Any]] = sim_result.get("delivery_stats", []) or []
    if not delivery_stats:
        return {
            "orders_processed": 0,
            "orders_delayed_by_backlog": 0,
            "backlog_rate": 0.0,
            "avg_queue_delay_s_all": 0.0,
            "avg_queue_delay_s_delayed": 0.0,
            "max_queue_delay_s": 0.0,
        }

    queue_delays_s: List[float] = [float(d.get("queue_delay_s", 0.0) or 0.0) for d in delivery_stats]
    processed_count: int = len(delivery_stats)
    delayed_count: int = sum(1 for q in queue_delays_s if q > 0.0)
    total_queue_delay_s: float = sum(queue_delays_s)
    max_queue_delay_s: float = max(queue_delays_s) if queue_delays_s else 0.0
    avg_queue_delay_s_all: float = total_queue_delay_s / float(processed_count) if processed_count > 0 else 0.0
    avg_queue_delay_s_delayed: float = (
        (sum(q for q in queue_delays_s if q > 0.0) / float(delayed_count)) if delayed_count > 0 else 0.0
    )
    backlog_rate: float = (delayed_count / float(processed_count)) if processed_count > 0 else 0.0

    return {
        "orders_processed": processed_count,
        "orders_delayed_by_backlog": delayed_count,
        "backlog_rate": backlog_rate,
        "avg_queue_delay_s_all": avg_queue_delay_s_all,
        "avg_queue_delay_s_delayed": avg_queue_delay_s_delayed,
        "max_queue_delay_s": max_queue_delay_s,
    }



# -------------------- Shared helpers --------------------
def _copy_to_visualization_folder(csv_file_path: Path, mode: str, run_idx: int) -> None:
    """Copy GPS CSV to visualization public folder using shared utility."""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{mode}_run_{run_idx:02d}_{timestamp}.csv"
        dest = copy_to_visualization_public(csv_file_path, subfolder="coordinates", filename=filename)
        logger.info("Copied GPS data to visualization folder: %s", dest)
        try:
            manifest_path = update_coordinates_manifest(dest)
            logger.info("Updated coordinates manifest: %s", manifest_path)
        except Exception as e:
            logger.warning("Failed to update coordinates manifest: %s", e)
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to copy GPS data to visualization folder: %s", e)


def _copy_order_tracking_to_viz_folder(csv_file_path: Path, mode: str, run_idx: int) -> None:
    """Copy order tracking CSV to visualization public folder using shared utility."""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{mode}_order_tracking_run_{run_idx:02d}_{timestamp}.csv"
        dest = copy_to_visualization_public(csv_file_path, filename=filename)
        logger.info("Copied order tracking log to visualization folder: %s", dest)
        try:
            manifest_path = update_coordinates_manifest(dest)
            logger.info("Updated coordinates manifest: %s", manifest_path)
        except Exception as e:
            logger.warning("Failed to update coordinates manifest: %s", e)
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to copy order tracking log to visualization folder: %s", e)


def _create_order_tracking_log(sim_result: Dict, output_path: Path) -> None:
    """Create a comprehensive order tracking log with timestamps and status updates."""
    import csv
    from datetime import datetime, timedelta
    
    # Get activity log from simulation result
    activity_log = sim_result.get('activity_log', [])
    orders = sim_result.get('orders', [])
    
    # Create a mapping of order_id to order details for context
    order_details = {order.get('order_id'): order for order in orders}
    
    # Prepare CSV data
    csv_rows = []
    
    # Add header
    header = [
        'Timestamp',
        'Clock_Time', 
        'Order_ID',
        'Golfer_ID',
        'Hole_Number',
        'Activity_Type',
        'Description',
        'Location',
        'Queue_Position',
        'Context_Info'
    ]
    csv_rows.append(header)
    
    # Process each activity log entry
    for entry in activity_log:
        timestamp_s = entry.get('timestamp_s', 0)
        time_str = entry.get('time_str', '')
        activity_type = entry.get('activity_type', '')
        description = entry.get('description', '')
        order_id = entry.get('order_id', '')
        location = entry.get('location', '')
        
        # Get order details if available
        golfer_id = ''
        hole_number = ''
        context_info = ''
        queue_position = ''
        
        if order_id and order_id in order_details:
            order = order_details[order_id]
            golfer_id = order.get('golfer_id', '')
            hole_number = str(order.get('hole_num', ''))
            
            # Add context based on activity type
            if activity_type == 'order_received':
                context_info = f"Order placed by {golfer_id} for delivery to hole {hole_number}"
            elif activity_type == 'order_queued':
                # Extract queue position from description
                if 'position' in description:
                    try:
                        queue_position = description.split('position ')[1].split(')')[0]
                        context_info = f"Order waiting in preparation queue"
                    except:
                        context_info = "Order added to queue"
            elif activity_type == 'prep_start':
                context_info = f"Kitchen started preparing order for {golfer_id}"
            elif activity_type == 'prep_complete':
                context_info = f"Order ready for delivery to hole {hole_number}"
            elif activity_type == 'delivery_start':
                context_info = f"Runner departing clubhouse with order for {golfer_id}"
            elif activity_type == 'delivery_complete':
                context_info = f"Order successfully delivered to {golfer_id} at hole {hole_number}"
            elif activity_type == 'order_failed':
                context_info = f"Order failed - unable to deliver to {golfer_id}"
        else:
            # System-level activities without specific order
            if activity_type == 'service_opened':
                context_info = "Delivery service became available for orders"
            elif activity_type == 'service_closed':
                context_info = "Delivery service no longer accepting orders"
            elif activity_type == 'idle':
                context_info = "Runner waiting for new orders"
            elif activity_type == 'queue_status':
                context_info = "Queue status update"
        
        # Format timestamp for better readability
        formatted_timestamp = f"{timestamp_s:.1f}s"
        
        # Create row
        row = [
            formatted_timestamp,
            time_str,
            order_id,
            golfer_id,
            hole_number,
            activity_type,
            description,
            location,
            queue_position,
            context_info
        ]
        csv_rows.append(row)
    
    # Write CSV file
    try:
        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerows(csv_rows)
    except Exception as e:
        logger.warning("Failed to create order tracking log: %s", e)


def _seconds_to_clock_str(sec_since_7am: int) -> str:
    total = max(0, int(sec_since_7am))
    hh = 7 + (total // 3600)
    mm = (total % 3600) // 60
    ss = total % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def _first_tee_to_seconds(hhmm: str) -> int:
    return seconds_since_7am(hhmm)


def _build_groups_interval(count: int, first_tee_s: int, interval_min: float) -> List[Dict]:
    return _lib_build_groups_interval(count, first_tee_s, interval_min)


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
    return seconds_since_7am(hhmm)


def _build_groups_from_scenario(course_dir: str, scenario_key: str, default_group_size: int = 4) -> List[Dict]:
    return _lib_build_groups_from_scenario(course_dir, scenario_key, default_group_size)


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
    csv_path = write_unified_coordinates_csv(
        {label: svc.coordinates for label, svc in services.items()},
        run_dir / "bev_cart_coordinates.csv",
    )
    
    # Copy to visualization folder
    _copy_to_visualization_folder(csv_path, "bev_carts", run_idx)

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
        random_seed=run_idx,
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
    csv_path = write_unified_coordinates_csv(tracks, run_dir / "coordinates.csv")
    
    # Copy to visualization folder
    _copy_to_visualization_folder(csv_path, "bev_with_golfers", run_idx)

    # Visualization for cart
    if bev_points:
        render_beverage_cart_plot(bev_points, course_dir=course_dir, save_path=run_dir / "bev_cart_route.png")

    # Sales and result: write full sales_result once; avoid later overwrites
    sales_path = run_dir / "sales.json"
    if not sales_path.exists():
        sales_path.write_text(json.dumps(sales_result, indent=2), encoding="utf-8")
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
    }
    # Include sales_result in metadata so downstream writers have access
    result_meta_with_sales = dict(result_meta)
    result_meta_with_sales["sales_result"] = sales_result
    (run_dir / "result.json").write_text(json.dumps(result_meta_with_sales, indent=2), encoding="utf-8")

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

    # Ensure downstream writers can access full sales data from this return value
    result_meta["sales_result"] = sales_result
    return result_meta


# -------------------- Mode entrypoints --------------------
def _run_mode_bev_carts(args: argparse.Namespace) -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_root = Path("outputs") / ts / "bevcarts"
    output_root = Path(args.output_dir) if args.output_dir else default_root
    output_root.mkdir(parents=True, exist_ok=True)

    logger.info("Starting beverage cart GPS runs: %d runs, %d carts", args.num_runs, args.num_carts)
    phase3_summary_rows: List[Dict] = []

    for i in range(1, int(args.num_runs) + 1):
        stats = _run_bev_carts_only_once(i, args.course_dir, int(args.num_carts), output_root)
        # Summary row compatible with phase3 writers (no revenue)
        phase3_summary_rows.append({
            "run_idx": i,
            "revenue": 0.0,
            "num_sales": 0,
            "tee_time_s": (9 - 7) * 3600,
        })

    if phase3_summary_rows:
        write_phase3_summary(phase3_summary_rows, output_root)
    logger.info("Complete. Results saved to: %s", output_root)


def _run_mode_bev_with_golfers(args: argparse.Namespace) -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_root = Path("outputs") / ts / "bevcarts"
    output_root = Path(args.output_dir) if args.output_dir else default_root
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

    for i in range(1, int(args.num_runs) + 1):
        groups = scenario_groups_base or _build_groups_interval(int(args.groups_count), first_tee_s, float(args.groups_interval_min))
        res = _run_bev_with_groups_once(
            i,
            args.course_dir,
            groups,
            float(args.order_prob),
            float(args.avg_order_usd),
            output_root,
        )

        # Save phase3-style outputs for the generated result
        sim_result = {
            "type": "standard",
            "run_idx": i,
            "sales_result": {
                "sales": res.get("sales_result", {}).get("sales", []),
                "revenue": res.get("revenue", 0.0),
            },
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
    logger.info("Complete. Results saved to: %s", output_root)


def _run_mode_golfers_only(args: argparse.Namespace) -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_root = Path("outputs") / ts / "golfers"
    output_root = Path(args.output_dir) if args.output_dir else default_root
    output_root.mkdir(parents=True, exist_ok=True)

    logger.info("Starting golfers-only runs: %d runs, %d groups", args.num_runs, args.groups_count)
    phase3_summary_rows: List[Dict] = []

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
        
        # Copy coordinates to visualization folder
        coordinates_csv = run_dir / "coordinates.csv"
        if coordinates_csv.exists():
            _copy_to_visualization_folder(coordinates_csv, "golfers_only", i)

        phase3_summary_rows.append({
            "run_idx": i,
            "revenue": 0.0,
            "num_sales": 0,
            "tee_time_s": sim_result["tee_time_s"],
        })

    if phase3_summary_rows:
        write_phase3_summary(phase3_summary_rows, output_root)
    logger.info("Complete. Results saved to: %s", output_root)


def _run_mode_delivery_runner(args: argparse.Namespace) -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_root = Path("outputs") / ts / "runners"
    output_dir = Path(args.output_dir) if args.output_dir else default_root
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Starting dynamic delivery runner sims: %d runs", args.num_runs)
    all_runs: List[Dict] = []

    first_tee_s = _first_tee_to_seconds(args.first_tee)

    for run_idx in range(1, int(args.num_runs) + 1):
        # Prefer scenario unless explicitly disabled via --tee-scenario none
        scenario_groups_base = _build_groups_from_scenario(args.course_dir, str(args.tee_scenario))
        if scenario_groups_base:
            groups = scenario_groups_base
        else:
            groups = _build_groups_interval(int(args.groups_count), first_tee_s, float(args.groups_interval_min)) if args.groups_count > 0 else []

        sim_result = run_multi_golfer_simulation(
            course_dir=args.course_dir,
            groups=groups,
            order_probability_per_9_holes=float(args.order_prob_9),
            prep_time_min=int(args.prep_time),
            runner_speed_mps=float(args.runner_speed),
            output_dir=str(output_dir / f"run_{run_idx:02d}"),
            create_visualization=True,
        )

        # Persist outputs
        run_path = output_dir / f"run_{run_idx:02d}"
        run_path.mkdir(parents=True, exist_ok=True)

        # Raw results
        (run_path / "results.json").write_text(json.dumps(sim_result, indent=2, default=str), encoding="utf-8")

        # Generate metrics using integrated approach
        try:
            _, delivery_metrics = generate_and_save_metrics(
                simulation_result=sim_result,
                output_dir=run_path,
                run_suffix=f"_run_{run_idx:02d}",
                simulation_id=f"delivery_dynamic_{run_idx:02d}",
                revenue_per_order=float(args.revenue_per_order),
                sla_minutes=int(args.sla_minutes),
                runner_id="runner_1",
                service_hours=float(args.service_hours),
            )
            metrics = delivery_metrics
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to generate metrics for run %d: %s", run_idx, e)
            metrics = type('MinimalMetrics', (), {
                'revenue_per_round': 0.0,
            })()

        # Backlog metrics
        backlog = _compute_backlog_metrics(sim_result)

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
            "",
            "## Backlog & Queue Delay",
            f"Orders processed: {backlog['orders_processed']}",
            f"Orders delayed by backlog: {backlog['orders_delayed_by_backlog']} ({backlog['backlog_rate']*100:.1f}%)",
            f"Avg queue delay (all): {backlog['avg_queue_delay_s_all']/60:.1f} min",
            f"Avg queue delay (delayed only): {backlog['avg_queue_delay_s_delayed']/60:.1f} min",
            f"Max queue delay: {backlog['max_queue_delay_s']/60:.1f} min",
        ]
        (run_path / f"stats_run_{run_idx:02d}.md").write_text("\n".join(stats_md), encoding="utf-8")

        # -------------------- Build and save runner coordinates CSV (smoothed) --------------------
        try:
            import json as _json
            import pickle as _pickle
            import math as _math
            import pandas as _pd
            from pathlib import Path as _Path
            from shapely.geometry import LineString as _LineString

            def _find_nearest_cart_node(_graph, _target):
                if _graph is None or not getattr(_graph, "nodes", None):
                    return None
                best, best_d = None, float("inf")
                tx, ty = float(_target[0]), float(_target[1])
                for n, data in _graph.nodes(data=True):
                    if "x" in data and "y" in data:
                        dx = float(data["x"]) - tx
                        dy = float(data["y"]) - ty
                        d = dx * dx + dy * dy
                        if d < best_d:
                            best, best_d = n, d
                return best

            def _resample_polyline(coords: list[tuple[float, float]], points_per_segment: int = 5) -> list[tuple[float, float]]:
                if len(coords) < 2:
                    return list(coords)
                dense: list[tuple[float, float]] = [coords[0]]
                for i in range(1, len(coords)):
                    x0, y0 = coords[i - 1]
                    x1, y1 = coords[i]
                    for k in range(1, max(2, points_per_segment)):
                        t = k / float(points_per_segment)
                        dense.append((x0 + t * (x1 - x0), y0 + t * (y1 - y0)))
                    dense.append((x1, y1))
                return dense

            def _smooth_polyline(coords: list[tuple[float, float]], window: int = 5) -> list[tuple[float, float]]:
                if window < 2 or len(coords) <= 2:
                    return coords
                half = window // 2
                smoothed: list[tuple[float, float]] = []
                for i in range(len(coords)):
                    xa = max(0, i - half)
                    xb = min(len(coords), i + half + 1)
                    seg = coords[xa:xb]
                    if not seg:
                        smoothed.append(coords[i])
                        continue
                    sx = sum(p[0] for p in seg) / len(seg)
                    sy = sum(p[1] for p in seg) / len(seg)
                    smoothed.append((sx, sy))
                return smoothed

            # Load course data and cart graph
            course_data = load_course_geospatial_data(args.course_dir)
            sim_cfg = load_simulation_config(args.course_dir)  # for clubhouse
            clubhouse = tuple(sim_cfg.clubhouse or (0.0, 0.0))  # lon, lat

            cart_graph = None
            cart_graph_path = Path(args.course_dir) / "pkl" / "cart_graph.pkl"
            if cart_graph_path.exists():
                with open(cart_graph_path, "rb") as f:
                    cart_graph = _pickle.load(f)

            # Build hole delivery targets: prefer green centroid, fallback to hole end, then midpoint
            hole_target: dict[int, tuple[float, float]] = {}
            try:
                greens_gdf = course_data.get("greens")
                if greens_gdf is not None and len(greens_gdf) > 0:
                    ref_col = "ref" if "ref" in greens_gdf.columns else None
                    if ref_col is not None:
                        for _, row in greens_gdf.iterrows():
                            try:
                                num = int(str(row[ref_col]))
                            except Exception:
                                continue
                            geom = row.geometry
                            if geom is not None:
                                centroid = geom.centroid
                                hole_target[num] = (float(centroid.x), float(centroid.y))
            except Exception:
                pass

            try:
                holes_gdf = course_data.get("holes")
                if holes_gdf is not None and len(holes_gdf) > 0:
                    ref_col = "ref" if "ref" in holes_gdf.columns else None
                    for _, row in holes_gdf.iterrows():
                        try:
                            num = int(str(row[ref_col])) if ref_col is not None else None
                        except Exception:
                            num = None
                        geom = row.geometry
                        if num is None or geom is None or not hasattr(geom, "coords"):
                            continue
                        coords = list(geom.coords)
                        if num not in hole_target and len(coords) >= 2:
                            # Prefer hole end; else compute midpoint
                            end_pt = (float(coords[-1][0]), float(coords[-1][1]))
                            hole_target[num] = end_pt
                        if num not in hole_target and len(coords) >= 2:
                            line = _LineString(coords)
                            mid = line.interpolate(0.5, normalized=True)
                            hole_target[num] = (float(mid.x), float(mid.y))
            except Exception:
                pass

            # Build runner path coords for each processed order (out and back)
            runner_points: list[dict] = []
            delivery_stats = sim_result.get("delivery_stats", [])
            for stat in delivery_stats:
                hole_num = int(stat.get("hole_num", 0))
                if hole_num <= 0 or hole_num not in hole_target:
                    continue
                target = hole_target[hole_num]

                # Compute path using cart graph if available, else straight line
                path_coords: list[tuple[float, float]]
                if cart_graph is not None:
                    try:
                        import networkx as _nx
                        start_node = _find_nearest_cart_node(cart_graph, clubhouse)
                        end_node = _find_nearest_cart_node(cart_graph, target)
                        if start_node is not None and end_node is not None:
                            path = _nx.shortest_path(cart_graph, start_node, end_node, weight="length")
                            path_coords = [(cart_graph.nodes[n]["x"], cart_graph.nodes[n]["y"]) for n in path]
                        else:
                            path_coords = [clubhouse, target]
                    except Exception:
                        path_coords = [clubhouse, target]
                else:
                    path_coords = [clubhouse, target]

                # Densify and smooth
                dense = _resample_polyline(path_coords, points_per_segment=6)
                smooth = _smooth_polyline(dense, window=7)

                # Timing for outbound leg
                delivered_at = float(stat.get("delivered_at_time_s", 0.0) or 0.0)
                delivery_time = float(stat.get("delivery_time_s", 0.0) or 0.0)
                return_time = float(stat.get("return_time_s", 0.0) or 0.0)
                start_time = max(0.0, delivered_at - delivery_time)
                # Assign timestamps linearly along path
                if len(smooth) > 1 and delivery_time > 0:
                    dt = delivery_time / (len(smooth) - 1)
                else:
                    dt = 10.0
                t = start_time
                for (x, y) in smooth:
                    runner_points.append({
                        "latitude": float(y),
                        "longitude": float(x),
                        "timestamp": int(t),
                        "type": "delivery-runner",
                        "hole": f"to_{hole_num}",
                    })
                    t += dt

                # Return path (reverse)
                if return_time > 0:
                    back = list(reversed(smooth))
                    if len(back) > 1:
                        dt_back = return_time / (len(back) - 1)
                    else:
                        dt_back = 10.0
                    t = delivered_at
                    for (x, y) in back:
                        runner_points.append({
                            "latitude": float(y),
                            "longitude": float(x),
                            "timestamp": int(t),
                            "type": "delivery-runner",
                            "hole": f"back_{hole_num}",
                        })
                        t += dt_back

            # Generate golfer GPS points for these groups
            golfer_points: List[Dict] = _generate_golfer_points_for_groups(args.course_dir, groups) if groups else []

            # Save unified coordinates CSV in run folder (runner + golfers)
            tracks: Dict[str, List[Dict]] = {}
            if runner_points:
                tracks["runner_1"] = runner_points
            # Group golfer points by group_id
            if golfer_points:
                by_gid: Dict[str, List[Dict]] = {}
                for p in golfer_points:
                    gid = str(p.get("group_id", "unknown"))
                    by_gid.setdefault(gid, []).append(p)
                for gid, pts in by_gid.items():
                    tracks[f"golfer_group_{gid}"] = pts

            if tracks:
                csv_path = write_unified_coordinates_csv(tracks, run_path / "coordinates.csv")
                _copy_to_visualization_folder(csv_path, "delivery_runner", run_idx)
            
            # Attach to results for downstream tools
            if runner_points:
                sim_result["runner_coordinates"] = runner_points
            if golfer_points:
                sim_result["golfer_points"] = golfer_points
                # Overwrite visualization with smoothed path
                course_data = load_course_geospatial_data(args.course_dir)
                sim_cfg2 = load_simulation_config(args.course_dir)
                clubhouse2 = tuple(sim_cfg2.clubhouse or (0.0, 0.0))
                try:
                    import pandas as pd
                    df = pd.DataFrame(runner_points)
                except Exception:
                    df = _pd.DataFrame(runner_points)
                viz_path = run_path / "delivery_orders_map.png"
                try:
                    render_delivery_plot(
                        results=sim_result,
                        course_data=course_data,
                        clubhouse_coords=clubhouse2,
                        runner_coords=df,
                        cart_graph=None,
                        save_path=viz_path,
                        style="detailed",
                    )
                    
                    # Generate individual order maps
                    from golfsim.viz.matplotlib_viz import render_individual_order_maps
                    individual_maps = render_individual_order_maps(
                        results=sim_result,
                        course_data=course_data,
                        clubhouse_coords=clubhouse2,
                        runner_coords=df,
                        cart_graph=None,
                        output_dir=run_path / "individual_orders",
                        course_name="Pinetree Country Club",
                        style="detailed",
                    )
                    logger.info("Generated %d individual order maps", len(individual_maps))
                    
                    # Generate order tracking log
                    order_tracking_path = run_path / "order_tracking_log.csv"
                    write_order_tracking_log(sim_result, order_tracking_path)
                    logger.info("Generated order tracking log: %s", order_tracking_path)
                    
                    # Copy order tracking log to visualization folder
                    _copy_order_tracking_to_viz_folder(order_tracking_path, "delivery_runner", run_idx)
                    
                except Exception as _e:
                    logger.warning("Failed to render smoothed delivery plot: %s", _e)
                logger.info("Saved smoothed runner coordinates CSV: %s", csv_path)
        except Exception as e:
            logger.warning("Failed to build/save runner coordinates CSV: %s", e)

        # Attach backlog metrics for summary aggregation
        all_runs.append({
            "run_idx": run_idx,
            "groups": len(groups),
            "orders": len(orders),
            "failed": len(failed_orders),
            "rpr": float(getattr(metrics, 'revenue_per_round', 0.0) or 0.0),
            "backlog": backlog,
        })

    # Phase-level summary
    lines: List[str] = ["# Delivery Dynamic Summary", "", f"Runs: {len(all_runs)}"]
    if all_runs:
        rprs = [float(r.get("rpr", 0.0)) for r in all_runs]
        lines.append(f"Revenue per round: min=${min(rprs):.2f} max=${max(rprs):.2f} mean=${(sum(rprs)/len(rprs)):.2f}")
        # Backlog summary across runs
        delays_all = [r.get("backlog", {}).get("avg_queue_delay_s_all", 0.0) for r in all_runs]
        delayed_rates = [r.get("backlog", {}).get("backlog_rate", 0.0) for r in all_runs]
        if delays_all:
            lines.append(
                f"Avg queue delay (all orders): min={min(delays_all)/60:.1f}m max={max(delays_all)/60:.1f}m mean={(sum(delays_all)/len(delays_all))/60:.1f}m"
            )
        if delayed_rates:
            lines.append(
                f"Backlog rate: min={min(delayed_rates)*100:.1f}% max={max(delayed_rates)*100:.1f}% mean={(sum(delayed_rates)/len(delayed_rates))*100:.1f}%"
            )
    (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    logger.info("Done. Results in: %s", output_dir)


# -------------------- CLI --------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified simulation runner for beverage carts and delivery runner",
    )

    # Top-level mode selector
    parser.add_argument(
        "--mode",
        type=str,
        choices=["bev-carts", "bev-with-golfers", "golfers-only", "delivery-runner"],
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
    parser.add_argument("--order-prob", type=float, default=0.4, help="Pass order probability (0..1) for bev-with-golfers")
    parser.add_argument("--avg-order-usd", type=float, default=12.0, help="Average order value in USD for bev-with-golfers")

    # Delivery runner params
    parser.add_argument("--order-prob-9", type=float, default=0.5, help="Order probability per 9 holes per group (0..1)")
    parser.add_argument("--prep-time", type=int, default=10, help="Food preparation time in minutes")
    parser.add_argument("--runner-speed", type=float, default=6.0, help="Runner speed in m/s")
    parser.add_argument("--revenue-per-order", type=float, default=25.0, help="Revenue per successful order")
    parser.add_argument("--sla-minutes", type=int, default=30, help="SLA in minutes")
    parser.add_argument("--service-hours", type=float, default=10.0, help="Active service hours for runner (metrics scaling)")

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
    else:
        raise SystemExit(f"Unknown mode: {args.mode}")


if __name__ == "__main__":
    main()


