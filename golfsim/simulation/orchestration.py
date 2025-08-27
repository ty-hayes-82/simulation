"""
Simulation Orchestration Module

High-level functions that configure and execute different simulation scenarios.
This module provides the main API for running simulations with various configurations.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, Any, Optional
import json
import simpy
from ..config.models import SimulationConfig
from ..config.loaders import (
    load_simulation_config,
    build_groups_from_scenario,
    build_groups_interval,
    parse_hhmm_to_seconds_since_7am,
)
from ..logging import get_logger
from ..simulation.services import MultiRunnerDeliveryService, DeliveryOrder
from ..simulation.tracks import (
    generate_golfer_points_for_groups,
    load_holes_connected_points,
    interpolate_path_points,
)
from ..postprocessing.coordinates import generate_runner_coordinates_from_events
from ..io.reporting import (
    write_order_logs_csv,
    write_runner_action_log,
    generate_simulation_metrics_json,
    build_simulation_id,
    events_from_groups_tee_off,
    events_from_orders_list,
    events_from_activity_log,
    write_event_log_csv,
    write_order_timing_logs_csv,
)
from ..io.results import (
    copy_to_public_coordinates,
    sync_run_outputs_to_public,
    write_unified_coordinates_csv,
)
from ..analysis.metrics_integration import generate_and_save_metrics
from ..viz.heatmap_viz import create_course_heatmap
from ..utils import generate_standardized_output_name
from .orders import (
    calculate_delivery_order_probability_per_9_holes,
    generate_delivery_orders_with_pass_boost,
    generate_delivery_orders_by_hour_distribution,
    generate_dynamic_hourly_distribution,
)
from golfsim.simulation.delivery_service import DeliveryService
from golfsim.simulation.beverage_cart_service import BeverageCartService
from golfsim.simulation.order_generation import simulate_golfer_orders
from golfsim.config.loaders import load_simulation_config
from golfsim.viz.matplotlib_viz import render_delivery_plot, render_individual_delivery_plots, load_course_geospatial_data
from golfsim.routing.utils import get_hole_for_node
import simpy
from pathlib import Path
import pickle
from typing import Any, Dict, List, Optional
import logging

logger = get_logger(__name__)


def _determine_variant_key(blocked_holes: set[int]) -> str:
    if not blocked_holes:
        return "none"
    
    front = {1, 2, 3}
    mid = {4, 5, 6}
    back = {10, 11, 12}
    
    has_front = front.issubset(blocked_holes)
    has_mid = mid.issubset(blocked_holes)
    has_back = back.issubset(blocked_holes)
    
    # Build key from parts
    parts = []
    if has_front: parts.append("front")
    if has_mid: parts.append("mid")
    if has_back: parts.append("back")
    
    key = "_".join(parts)
    
    # Check if the key exactly matches the combination of sets
    expected_holes = set()
    if has_front: expected_holes.update(front)
    if has_mid: expected_holes.update(mid)
    if has_back: expected_holes.update(back)
    
    if blocked_holes == expected_holes and key:
        return key
    
    return "custom" if blocked_holes else "none"


def run_multi_golfer_simulation(
    course_dir: str,
    groups: List[Dict[str, Any]],
    num_runners: int,
    prep_time_min: int,
    runner_speed_mps: float,
    order_probability_per_9_holes: float = 0.3,
    env: Optional[simpy.Environment] = None,
    output_dir: Optional[str] = None,
    create_visualization: bool = True,
    rng_seed: Optional[int] = None,
) -> Dict[str, Any]:
    simulation_env = env or simpy.Environment()
    config = load_simulation_config(course_dir)
    
    service = DeliveryService(
        env=simulation_env,
        config=config,
        num_runners=num_runners,
        prep_time_min=prep_time_min,
        runner_speed_mps=runner_speed_mps,
        groups=groups,
    )

    orders = simulate_golfer_orders(groups, order_probability_per_9_holes, rng_seed=rng_seed, course_dir=course_dir)

    def order_arrival_process():
        last_time = simulation_env.now
        for order in orders:
            target_time = max(order.order_time_s, service.service_open_s)
            if target_time > last_time:
                yield simulation_env.timeout(target_time - last_time)
            service.place_order(order)
            last_time = target_time

    simulation_env.process(order_arrival_process())

    run_until = max(service.service_close_s + 1, max((o.order_time_s for o in orders), default=0) + 4 * 3600)
    simulation_env.run(until=run_until)

    results: Dict[str, Any] = {
        "success": True,
        "simulation_type": "multi_golfer_multi_runner",
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
            "num_runners": num_runners,
            "course_dir": str(course_dir),
        },
    }

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

    if create_visualization and output_dir and results["orders"]:
        try:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            
            sim_cfg = load_simulation_config(course_dir)
            clubhouse_coords = sim_cfg.clubhouse
            course_data = load_course_geospatial_data(course_dir)
            
            cart_graph = None
            cart_graph_path = Path(course_dir) / "pkl" / "cart_graph.pkl"
            if cart_graph_path.exists():
                with open(cart_graph_path, "rb") as f:
                    cart_graph = pickle.load(f)
            
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


def run_delivery_runner_simulation(config: SimulationConfig, **kwargs) -> Dict[str, Any]:
    """Run delivery runner simulation."""
    args = kwargs.get("args")

    config.output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Starting dynamic delivery runner sims: %d runs", config.num_runs)
    all_runs: list[dict] = []

    first_tee_s = parse_hhmm_to_seconds_since_7am(config.first_tee)
    
    # Load simulation config to get total orders and optional hourly distribution
    # This is already loaded into the config object
    
    for run_idx in range(1, int(config.num_runs) + 1):
        # Prefer scenario unless explicitly disabled via --tee-scenario none
        scenario_groups_base = build_groups_from_scenario(config.course_dir, str(config.tee_scenario))
        if scenario_groups_base:
            groups = scenario_groups_base
            # Only shift scenario times if first_tee was explicitly provided (not using default)
            # For detailed tee times scenarios, use the exact times from the scenario
            should_shift_times = (
                hasattr(args, 'first_tee') and args.first_tee is not None and args.first_tee != "09:00"
            ) if args else False
            
            if should_shift_times:
                # If a first tee override is provided, shift entire scenario to match desired first tee
                try:
                    if isinstance(groups, list) and groups:
                        current_min = min(int(g.get("tee_time_s", 0) or 0) for g in groups)
                        delta = int(first_tee_s - current_min)
                        if delta != 0:
                            for g in groups:
                                g["tee_time_s"] = max(0, int(g.get("tee_time_s", 0) or 0) + delta)
                            logger.info("Shifted scenario tee times by %+ds to align first tee to %s", delta, str(config.first_tee))
                except Exception:
                    pass
            else:
                # Use scenario times as-is for detailed tee times
                if isinstance(groups, list) and groups:
                    logger.info("Using detailed tee times from scenario '%s' without shifting", str(config.tee_scenario))
            # Respect groups_count when a scenario is used by taking the first N groups by tee time
            try:
                max_groups = int(getattr(config, "groups_count", 0) or 0)
                if max_groups > 0 and len(groups) > max_groups:
                    groups = sorted(groups, key=lambda g: int(g.get("tee_time_s", 0) or 0))[:max_groups]
                    # Optionally renumber group_id sequentially for cleaner outputs
                    for idx, g in enumerate(groups, start=1):
                        g["group_id"] = idx
                    logger.info("Using first %d golfer group(s) from scenario (of %d total)", max_groups, len(scenario_groups_base))
            except Exception:
                pass
        else:
            groups = build_groups_interval(int(config.groups_count), first_tee_s, float(config.groups_interval_min)) if config.groups_count > 0 else []

        # Decide order generation mode
        hourly_dist = getattr(config, "delivery_hourly_distribution", None)
        
        # If hourly distribution is not provided, create a default dynamic distribution
        if not isinstance(hourly_dist, dict) or not hourly_dist:
            service_start_hour = int(config.service_hours.start_hour) if config.service_hours else 10
            service_end_hour = int(config.service_hours.end_hour) if config.service_hours else 19
            hourly_dist = generate_dynamic_hourly_distribution(service_start_hour, service_end_hour)

        requested_total_orders = int(args.delivery_total_orders) if getattr(args, "delivery_total_orders", None) is not None else int(config.delivery_total_orders)

        crossings = None # Disabled in this mode

        effective_runner_speed = config.delivery_runner_speed_mps

        env = simpy.Environment()
        # Create an empty order log file with headers
        order_log_path = Path(config.output_dir) / f"run_{run_idx:02d}" / "order_logs.csv"
        order_log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(order_log_path, "w") as f:
            f.write("order_id,placed_ts,placed_hole,queue,mins_to_set,drive_out_min,drive_total_min,delivery_hole,golfer_node_idx,predicted_node_idx,actual_node_idx\n")

        # Use the simulation config to create the service
        delivery_service = MultiRunnerDeliveryService(
            env,
            course_dir=config.course_dir,
            num_runners=int(config.num_runners),
            runner_speed_mps=effective_runner_speed,
            prep_time_min=int(config.delivery_prep_time_sec / 60),
            groups=groups,
            time_quantum_s=config.speeds.time_quantum_s
        )

        orders: list[DeliveryOrder] = []
        orders_all: list[DeliveryOrder] = []
        # Initialize defaults so metadata below is safe even when no groups
        blocked_holes: set[int] = set()
        variant_key: str = "none"
        if groups:
            # --- Start: New blocked holes logic ---
            blocked_holes: set[int] = set()
            
            block_up_to_hole = getattr(args, "block_up_to_hole", 0)
            if block_up_to_hole > 0:
                blocked_holes.update(range(1, int(block_up_to_hole) + 1))

            if getattr(args, "block_holes_10_12", False):
                blocked_holes.update([10, 11, 12])

            block_holes_list = getattr(args, "block_holes", None)
            if block_holes_list:
                try:
                    blocked_holes.update(int(h) for h in block_holes_list)
                except (ValueError, TypeError):
                    logger.warning("Invalid value in --block-holes list; expected integers.")

            block_holes_range = getattr(args, "block_holes_range", None)
            if isinstance(block_holes_range, str) and "-" in block_holes_range:
                try:
                    a_str, b_str = block_holes_range.split("-", 1)
                    a = int(a_str); b = int(b_str)
                    blocked_holes.update(range(min(a, b), max(a, b) + 1))
                except (ValueError, TypeError):
                     logger.warning("Invalid value for --block-holes-range; expected format like '1-3'.")

            if blocked_holes:
                logger.info(f"Generating orders with blocked holes: {sorted(list(blocked_holes))}")
            
            variant_key = _determine_variant_key(blocked_holes)
            # --- End: New blocked holes logic ---

            orders_all = generate_delivery_orders_by_hour_distribution(
                groups=groups,
                hourly_distribution=hourly_dist,
                total_orders=int(requested_total_orders),
                service_open_hhmm=str(config.service_hours.start_hour) + ":00" if config.service_hours else "10:00",
                service_close_hhmm=str(config.service_hours.end_hour) + ":00" if config.service_hours else "19:00",
                opening_ramp_minutes=int(getattr(config, "delivery_opening_ramp_minutes", 0)),
                course_dir=config.course_dir,
                rng_seed=config.random_seed,
                service_open_s=int(delivery_service.service_open_s),
                blocked_holes=blocked_holes if blocked_holes else None,
            )
            
            orders = orders_all

        def order_arrival_process():
            last_time = env.now
            for order in orders:
                # Get the golfer's current node at the time of the order
                golfer_group = delivery_service.groups_by_id.get(order.golfer_group_id)
                if golfer_group:
                    # Calculate current node index based on time elapsed since tee time
                    tee_time_s = int(golfer_group.get("tee_time_s", 0))
                    time_elapsed_s = order.order_time_s - tee_time_s
                    # Each node represents 1 minute of play time
                    current_node = max(0, int(time_elapsed_s // 60))
                    
                    # Get the correct hole for the node
                    correct_hole = get_hole_for_node(current_node, config.course_dir)
                    if correct_hole is not None:
                        order.hole_num = correct_hole

                target_time = max(order.order_time_s, delivery_service.service_open_s)
                if target_time > last_time:
                    yield env.timeout(target_time - last_time)
                delivery_service.place_order(order)
                last_time = target_time

        env.process(order_arrival_process())

        run_until = max(delivery_service.service_close_s + 1, max((o.order_time_s for o in orders), default=0) + 4 * 3600)
        env.run(until=run_until)

        sim_result: dict[str, Any] = {
            "success": True,
            "simulation_type": "multi_golfer_multi_runner" if int(config.num_runners) > 1 else "multi_golfer_single_runner",
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
            "orders_all": [
                {
                    "order_id": getattr(o, "order_id", None),
                    "golfer_group_id": getattr(o, "golfer_group_id", None),
                    "golfer_id": getattr(o, "golfer_id", None),
                    "hole_num": getattr(o, "hole_num", None),
                    "order_time_s": getattr(o, "order_time_s", None),
                    "status": getattr(o, "status", "pending"),
                    "total_completion_time_s": getattr(o, "total_completion_time_s", 0.0),
                }
                for o in (orders_all or [])
            ],
            "delivery_stats": delivery_service.delivery_stats,
            "failed_orders": [
                {"order_id": getattr(o, "order_id", None), "reason": getattr(o, "failure_reason", None)}
                for o in delivery_service.failed_orders
            ],
            "activity_log": delivery_service.activity_log,
            "metadata": {
                "prep_time_min": int(config.delivery_prep_time_sec / 60),
                "runner_speed_mps": float(config.delivery_runner_speed_mps),
                "num_groups": len(groups),
                "num_runners": int(config.num_runners),
                "course_dir": str(config.course_dir),
                "service_open_s": int(delivery_service.service_open_s),
                "service_close_s": int(delivery_service.service_close_s),
                "blocked_holes": sorted(list(blocked_holes)),
                "variant_key": variant_key,
            },
        }

        bev_points: list[dict[str, Any]] = []
        bev_sales_result: dict[str, Any] = {"sales": [], "revenue": 0.0}
        golfer_points: list[dict[str, Any]] = []

        # Optional heatmap generation (skip in minimal outputs mode or when no_heatmap set)
        if sim_result["orders"] and not config.no_heatmap and not bool(getattr(config, "minimal_outputs", False)):
            try:
                run_path = config.output_dir / f"run_{run_idx:02d}"
                run_path.mkdir(parents=True, exist_ok=True)
                
                heatmap_file = run_path / "delivery_heatmap.png"
                course_name = Path(config.course_dir).name.replace("_", " ").title()
                create_course_heatmap(
                    results=sim_result,
                    course_dir=config.course_dir,
                    save_path=heatmap_file,
                    title=f"{course_name} - Delivery Runner Heatmap (Run {run_idx})",
                    colormap='white_to_red'
                )
                logger.info("Created delivery heatmap: %s", heatmap_file)
                sim_result["heatmap_path"] = str(heatmap_file)
            except Exception as e:
                logger.warning("Failed to create delivery heatmap: %s", e)

        run_path = config.output_dir / f"run_{run_idx:02d}"
        run_path.mkdir(parents=True, exist_ok=True)

        (run_path / "results.json").write_text(json.dumps(sim_result, indent=2, default=str), encoding="utf-8")
        
        # Other reports that must be written before coordinates
        if not bool(getattr(config, "minimal_outputs", False)):
            try:
                write_order_logs_csv(sim_result, run_path / "order_logs.csv")
            except Exception as e:
                logger.warning("Failed to write order logs CSV: %s", e)
            try:
                write_runner_action_log(sim_result.get("activity_log", []) or [], run_path / "runner_action_log.csv")
            except Exception as e:
                logger.warning("Failed to write runner action log: %s", e)

            # Write the new detailed order timing log
            if hasattr(delivery_service, "order_timing_logs"):
                write_order_timing_logs_csv(delivery_service.order_timing_logs, run_path / "order_timing_logs.csv")


        
        # Other reports
        try:
            # Always generate core simulation metrics JSON (needed by map app)
            generate_simulation_metrics_json(
                sim_result,
                run_path / "simulation_metrics.json",
                service_hours=float(config.service_hours_duration),
                sla_minutes=int(config.sla_minutes),
                revenue_per_order=config.delivery_avg_order_usd,
                avg_bev_order_value=float(getattr(args, "avg_order_usd", 12.0)),
                variant_key=sim_result.get("metadata", {}).get("variant_key"),
                blocked_holes=sim_result.get("metadata", {}).get("blocked_holes"),
            )
        except Exception as e:
            logger.warning("Failed to write simulation metrics JSON: %s", e)

        # Metrics generation
        metrics = type('MinimalMetrics', (), {'revenue_per_round': 0.0})()
        try:
            bev_metrics, delivery_metrics = generate_and_save_metrics(
                simulation_result=sim_result,
                output_dir=run_path,
                run_suffix=f"_run_{run_idx:02d}",
                simulation_id=f"delivery_dynamic_{run_idx:02d}",
                revenue_per_order=float(config.delivery_avg_order_usd),
                sla_minutes=int(config.sla_minutes),
                runner_id="runner_1" if int(config.num_runners) == 1 else f"{int(config.num_runners)}_runners",
                service_hours=float(config.service_hours_duration),
                bev_cart_coordinates=bev_points,
                bev_cart_service=None,  # Not used in delivery runner simulation
                golfer_data=golfer_points,
                minimal_outputs=bool(getattr(config, "minimal_outputs", False)),
            )
            if delivery_metrics:
                metrics = delivery_metrics
        except Exception as e:
            logger.warning("Failed to generate and save detailed metrics: %s", e)

        # Coordinate generation
        if not bool(getattr(config, "minimal_outputs", False)):
            if not bool(getattr(config, "coordinates_only_for_first_run", False)) or run_idx == 1:
                try:
                    events: list[dict[str, Any]] = []
                    # Unify event sources
                    try:
                        events = events_from_activity_log(sim_result.get("activity_log", []), sim_result.get("orders_all", []))
                        if not bool(getattr(config, "minimal_outputs", False)):
                            write_event_log_csv(events, run_path / "events.csv")
                    except Exception as e:
                        logger.warning("Failed to write events CSV: %s", e)

                    # Generate coordinates from golfer movement, beverage cart, and runner paths
                    golfer_points: list[dict[str, Any]] = []
                    cart_graph = None
                    
                    # Load cart graph
                    try:
                        import pickle
                        cart_graph_path = Path(config.course_dir) / "pkl" / "cart_graph.pkl"
                        if cart_graph_path.exists():
                            with cart_graph_path.open("rb") as f:
                                cart_graph = pickle.load(f)
                    except Exception:
                        cart_graph = None

                    # Generate golfer coordinates first
                    if groups:
                        gp = generate_golfer_points_for_groups(config.course_dir, groups)
                        by_gid: dict[int, list[dict[str, Any]]] = {}
                        for p in gp:
                            gid = int(p.get("group_id", 0) or 0)
                            by_gid.setdefault(gid, []).append(p)
                        for gid, pts in by_gid.items():
                            golfer_points_csv[f"golfer_group_{gid}"] = pts

                    # Generate runner coordinates using post-processing approach
                    if cart_graph is not None and events:
                        try:
                            import pandas as pd
                            
                            # Convert events to DataFrame
                            events_df = pd.DataFrame(events)
                            
                            # Convert golfer coordinates to DataFrame
                            all_golfer_coords = []
                            for group_coords in golfer_points_csv.values():
                                all_golfer_coords.extend(group_coords)
                            
                            if all_golfer_coords:
                                golfer_coords_df = pd.DataFrame(all_golfer_coords)
                                
                                # Generate runner coordinates from events
                                # Prepare optional detailed dataframes for precise node-path GPS generation
                                try:
                                    delivery_stats_df = pd.DataFrame(sim_result.get("delivery_stats", []) or [])
                                except Exception:
                                    delivery_stats_df = None
                                try:
                                    order_timing_df = pd.DataFrame(getattr(delivery_service, "order_timing_logs", []) or [])
                                except Exception:
                                    order_timing_df = None

                                golfer_points_csv: dict[str, list[dict[str, Any]]] = {}
                                runner_points = generate_runner_coordinates_from_events(
                                    events_df=events_df,
                                    golfer_coords_df=golfer_coords_df,
                                    clubhouse_coords=config.clubhouse,
                                    cart_graph=cart_graph,
                                    runner_speed_mps=float(config.delivery_runner_speed_mps),
                                    num_runners=int(config.num_runners),
                                    delivery_stats_df=delivery_stats_df,
                                    order_timing_df=order_timing_df,
                                )
                                logger.info("Generated %d runner coordinate points using post-processing approach", len(runner_points))
                            else:
                                logger.warning("No golfer coordinates available for runner coordinate generation")
                                
                        except Exception as e:
                            logger.warning("Post-processing coordinate generation failed: %s", e)
                            runner_points = []
                    else:
                        logger.warning("Cart graph not available or no events - skipping runner coordinate generation")
                    
                    # Combine all coordinate streams
                    streams: dict[str, list[dict[str, Any]]] = {}
                    if runner_points:
                        by_rid: dict[str, list[dict[str, Any]]] = {}
                        for rp in runner_points:
                            rid = str(rp.get("id", "runner_1"))
                            by_rid.setdefault(rid, []).append(rp)
                        streams.update(by_rid)
                    if golfer_points_csv:
                        streams.update(golfer_points_csv)

                    # Annotate golfer colors from order/delivery events
                    try:
                        if streams and events:
                            from golfsim.postprocessing.golfer_colors import annotate_golfer_colors
                            streams = annotate_golfer_colors(streams, events)
                    except Exception as e:
                        logger.warning("Failed to annotate golfer colors: %s", e)

                    # Timeline anchors to control animation start/end
                    # - Start: naturally anchored by earliest golfer tee time
                    # - End: force timeline to extend 5 hours after last tee time
                    try:
                        if groups:
                            last_tee_s = max(int(g.get("tee_time_s", 0) or 0) for g in groups)
                            anchor_end_s = int(last_tee_s + 5 * 3600)
                            # Use clubhouse coords for anchor point
                            if config.clubhouse and isinstance(config.clubhouse, tuple) and len(config.clubhouse) == 2:
                                lon, lat = float(config.clubhouse[0]), float(config.clubhouse[1])
                            else:
                                lon, lat = -84.5928, 34.0379
                            timeline_point = {
                                "id": "timeline",
                                "latitude": lat,
                                "longitude": lon,
                                "timestamp": anchor_end_s,
                                "type": "timeline",
                                "hole": "clubhouse",
                            }
                            streams.setdefault("timeline", []).append(timeline_point)
                    except Exception:
                        pass

                    # Write coordinates CSV
                    if streams:
                        write_unified_coordinates_csv(streams, run_path / "coordinates.csv")
                        logger.info("Wrote coordinates CSV with %d streams", len(streams))
                    else:
                        logger.warning("No coordinate streams generated")
                        
                except Exception as e:
                    logger.warning("Failed to write animation coordinates CSV: %s", e)

        # Copy to public
        if not bool(getattr(config, "minimal_outputs", False)):
            try:
                simulation_id = build_simulation_id(config.output_dir, run_idx)
                runner_count = int(config.num_runners)
                description = f"Delivery runner simulation ({runner_count} runner{'s' if runner_count != 1 else ''})"
                copy_to_public_coordinates(
                    run_dir=run_path,
                    simulation_id=simulation_id,
                    mode="delivery-runner",
                    golfer_group_count=len(groups),
                    description=description
                )
                sync_run_outputs_to_public(run_path, description=description)
            except Exception as e:
                logger.warning("Failed to copy to public coordinates: %s", e)


        all_runs.append({
            "run_idx": run_idx,
            "groups": len(groups),
            "orders": len(sim_result.get("orders", [])),
            "failed": len(sim_result.get("failed_orders", [])),
            "rpr": float(getattr(metrics, 'revenue_per_round', 0.0) or 0.0),
        })

    if not bool(getattr(config, "minimal_outputs", False)):
        lines: list[str] = ["# Delivery Dynamic Summary", "", f"Runs: {len(all_runs)}"]
        if all_runs:
            rprs = [float(r.get("rpr", 0.0)) for r in all_runs]
            lines.append(f"Revenue per round: min=${min(rprs):.2f} max=${max(rprs):.2f} mean=${(sum(rprs)/len(rprs)):.2f}")
        (config.output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    logger.info("Done. Results in: %s", config.output_dir)
    return {"status": "completed", "output_dir": str(config.output_dir)}


def run_bev_with_golfers_simulation(config: SimulationConfig, **kwargs) -> Dict[str, Any]:
    """Run beverage cart with golfers simulation."""
    # This will be implemented by moving the _run_mode_bev_with_golfers logic here
    logger.info("Running bev with golfers simulation")
    return {"status": "placeholder", "mode": "bev-with-golfers"}


def run_single_golfer_simulation(config: SimulationConfig, **kwargs) -> Dict[str, Any]:
    """Run single golfer simulation."""
    # This will be implemented by moving the _run_mode_single_golfer logic here
    logger.info("Running single golfer simulation")
    return {"status": "placeholder", "mode": "single-golfer"}


def run_optimize_runners_simulation(config: SimulationConfig, **kwargs) -> Dict[str, Any]:
    """Run runner optimization simulation."""
    # This will be implemented by moving the _run_mode_optimize_runners logic here
    logger.info("Running runner optimization simulation")
    return {"status": "placeholder", "mode": "optimize-runners"}


def create_simulation_config_from_args(args: argparse.Namespace) -> SimulationConfig:
    """Create a SimulationConfig from command-line arguments."""
    return SimulationConfig.from_args(args)
