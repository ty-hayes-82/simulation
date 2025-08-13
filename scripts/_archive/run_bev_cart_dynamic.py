"""
Dynamic beverage cart simulation runner.

Supports:
- Carts-only GPS generation (0 golfer groups) with 1..N carts
- Single-cart + golfer groups sales simulation (groups_count > 0)
- Scenario-driven groups from tee_times_config.json

Windows PowerShell friendly: one short command per line, no piping/chaining.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import simpy

from golfsim.logging import init_logging, get_logger
from golfsim.config.loaders import load_simulation_config
from golfsim.simulation.services import BeverageCartService
from golfsim.simulation.phase_simulations import (
    generate_golfer_track,
)
from golfsim.simulation.crossings import (
    compute_crossings_from_files,
    serialize_crossings_summary,
)
from golfsim.simulation.bev_cart_pass import simulate_beverage_cart_sales
from golfsim.io.results import write_unified_coordinates_csv
from golfsim.viz.matplotlib_viz import render_beverage_cart_plot
from golfsim.io.phase_reporting import save_phase3_output_files, write_phase3_summary
from golfsim.analysis.bev_cart_metrics import (
    calculate_bev_cart_metrics,
    format_metrics_report as format_bev_metrics_report,
)
from golfsim.analysis.metrics_integration import generate_and_save_metrics


logger = get_logger(__name__)


def _seconds_to_clock_str(sec_since_7am: int) -> str:
    total = max(0, int(sec_since_7am))
    hh = 7 + (total // 3600)
    mm = (total % 3600) // 60
    ss = total % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


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


def _run_carts_only_once(run_idx: int, course_dir: str, num_carts: int, output_root: Path) -> Dict:
    env = simpy.Environment()
    services: Dict[str, BeverageCartService] = {}
    for n in range(1, num_carts + 1):
        # Set different starting holes for different carts
        starting_hole = 18 if n == 1 else 9  # Cart 1: hole 18, Cart 2: hole 9
        services[str(n)] = BeverageCartService(
            env=env,
            course_dir=course_dir,
            cart_id=f"bev_cart_{n}",
            track_coordinates=True,
            starting_hole=starting_hole,
        )

    # Use any service's end time (identical by config)
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
            
            # Create a simplified simulation result for metrics generation
            sim_result = {
                "bev_points": points,
                "sales_result": {"sales": []},
                "simulation_type": "beverage_cart_only"
            }
            
            generate_and_save_metrics(
                simulation_result=sim_result,
                output_dir=run_dir,
                bev_cart_coordinates=points,
                bev_cart_service=svc,
                run_suffix=f"_{label}",
                simulation_id=f"bev_dynamic_run_{run_idx:02d}",
                cart_id=f"bev_cart_{label}"
            )
    except Exception as e:
        logger.warning("Failed to generate metrics: %s", e)

    return stats


def _run_single_cart_with_groups_once(
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
    write_unified_coordinates_csv(tracks, run_dir / "coordinates.csv")

    # Visualization for cart
    if bev_points:
        render_beverage_cart_plot(bev_points, course_dir=course_dir, save_path=run_dir / "bev_cart_route.png")

    # Sales and result
    (run_dir / "sales.json").write_text(json.dumps(sales_result, indent=2), encoding="utf-8")
    result_meta = {
        "run_idx": run_idx,
        "groups": groups,
        "first_tee_time_s": first_tee_s,
        "last_tee_time_s": last_tee_s,
        "revenue": float(sales_result.get("revenue", 0.0)),
        "num_sales": len(sales_result.get("sales", [])),
        "crossings": serialize_crossings_summary(crossings) if crossings else None,
        "simulation_runtime_s": time.time() - start_time,
    }
    (run_dir / "result.json").write_text(json.dumps(result_meta, indent=2), encoding="utf-8")

    # Metrics for the single cart using integrated approach
    try:
        # Create simulation result for metrics generation
        sim_result = {
            "bev_points": bev_points,
            "sales_result": sales_result,
            "golfer_points": golfer_points,
            "simulation_type": "beverage_cart_with_golfers"
        }
        
        generate_and_save_metrics(
            simulation_result=sim_result,
            output_dir=run_dir,
            bev_cart_coordinates=bev_points,
            bev_cart_service=svc,
            golfer_data=golfer_points,
            simulation_id=f"bev_dynamic_run_{run_idx:02d}",
            cart_id="bev_cart_1"
        )
    except Exception as e:
        logger.warning("Failed to generate metrics: %s", e)

    return result_meta


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Dynamic beverage cart simulation runner (carts-only, or single cart + golfer groups)",
    )
    parser.add_argument("--course-dir", default="courses/pinetree_country_club", help="Course directory")
    parser.add_argument("--num-runs", type=int, default=5, help="Number of runs")
    parser.add_argument("--num-carts", type=int, default=1, help="Number of carts for carts-only mode")
    parser.add_argument("--groups-count", type=int, default=0, help="Number of golfer groups (0 for carts-only)")
    parser.add_argument("--groups-interval-min", type=float, default=15.0, help="Interval in minutes between groups (interval mode)")
    parser.add_argument("--first-tee", type=str, default="09:00", help="First tee time HH:MM for interval mode")
    parser.add_argument("--order-prob", type=float, default=0.4, help="Pass order probability (0..1)")
    parser.add_argument("--avg-order-usd", type=float, default=12.0, help="Average order value in USD")
    parser.add_argument("--output-dir", type=str, default=None, help="Output root dir (defaults to outputs/{timestamp}_{x}_bevcarts_{y}_golfers)")
    parser.add_argument("--log-level", type=str, default="INFO", help="Log level")

    args = parser.parse_args()

    init_logging(args.log_level)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_name = f"{ts}_{int(args.num_carts)}_bevcarts_{int(args.groups_count)}_golfers"
    output_root = Path(args.output_dir or (Path("outputs") / default_name))
    output_root.mkdir(parents=True, exist_ok=True)

    logger.info("Starting dynamic beverage cart runs")
    logger.info("Course: %s", args.course_dir)
    logger.info("Runs: %d", args.num_runs)

    results: List[Dict] = []
    phase3_summary_rows: List[Dict] = []

    if int(args.num_carts) == 0 and int(args.groups_count) > 0:
        # Golfers-only mode (no beverage carts)
        hh, mm = args.first_tee.split(":")
        first_tee_s = (int(hh) - 7) * 3600 + int(mm) * 60

        for i in range(1, args.num_runs + 1):
            groups = _build_groups_interval(int(args.groups_count), first_tee_s, float(args.groups_interval_min))
            golfer_points = _generate_golfer_points_for_groups(args.course_dir, groups)

            # Build a phase3-shaped result to reuse standard writers
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

            phase3_summary_rows.append({
                "run_idx": i,
                "revenue": 0.0,
                "num_sales": 0,
                "tee_time_s": sim_result["tee_time_s"],
            })
            results.append({"mode": "golfers_only", "run_idx": i})

    elif int(args.groups_count) <= 0:
        # Carts-only mode (supports N carts)
        if int(args.num_carts) > 1:
            # Use multi-cart function for 2+ carts
            for i in range(1, args.num_runs + 1):
                stats = _run_carts_only_once(i, args.course_dir, int(args.num_carts), output_root)
                results.append(stats)
                
                phase3_summary_rows.append({
                    "run_idx": i,
                    "revenue": 0.0,
                    "num_sales": 0,
                    "tee_time_s": (9 - 7) * 3600,
                })
        else:
            # Single cart mode
            for i in range(1, args.num_runs + 1):
                # Generate cart GPS using service (single-cart output shape)
                env = simpy.Environment()
                svc = BeverageCartService(env=env, course_dir=args.course_dir, cart_id="bev_cart_1", track_coordinates=True, starting_hole=18)
                env.run(until=svc.service_end_s)

                sim_result = {
                    "type": "standard",
                    "run_idx": i,
                    "sales_result": {"sales": [], "revenue": 0.0},
                    "golfer_points": [],
                    "bev_points": svc.coordinates,
                    "pass_events": [],
                    "tee_time_s": (9 - 7) * 3600,
                    "beverage_cart_service": svc,
                }
                run_dir = output_root / f"sim_{i:02d}"
                save_phase3_output_files(sim_result, run_dir, include_stats=False)
                
                # Generate metrics for single cart
                try:
                    generate_and_save_metrics(
                        simulation_result=sim_result,
                        output_dir=run_dir,
                        bev_cart_coordinates=svc.coordinates,
                        bev_cart_service=svc,
                        simulation_id=f"bev_dynamic_run_{i:02d}",
                        cart_id="bev_cart_1"
                    )
                except Exception as e:
                    logger.warning("Failed to generate metrics for run %d: %s", i, e)

                phase3_summary_rows.append({
                    "run_idx": i,
                    "revenue": 0.0,
                    "num_sales": 0,
                    "tee_time_s": sim_result["tee_time_s"],
                })
                results.append({"mode": "carts_only", "run_idx": i})
    else:
        # Single cart + groups mode (num_carts forced to 1)
        if args.num_carts != 1:
            logger.warning("groups-count > 0 requires a single cart; forcing --num-carts=1")
        # Build groups
        hh, mm = args.first_tee.split(":")
        first_tee_s = (int(hh) - 7) * 3600 + int(mm) * 60

        for i in range(1, args.num_runs + 1):
            groups = _build_groups_interval(int(args.groups_count), first_tee_s, float(args.groups_interval_min))
            res = _run_single_cart_with_groups_once(
                i,
                args.course_dir,
                groups,
                float(args.order_prob),
                float(args.avg_order_usd),
                output_root,
            )
            results.append(res)
            # Save phase3-style outputs for the generated result
            sim_result = {
                "type": "standard",
                "run_idx": i,
                "sales_result": {
                    "sales": res.get("sales_result", {}).get("sales", []),
                    "revenue": res.get("revenue", 0.0),
                },
                "golfer_points": _generate_golfer_points_for_groups(args.course_dir, groups),
                "bev_points": simpy.Environment() and [],  # placeholder not used; will be overwritten below
                "pass_events": [],
                "tee_time_s": res.get("first_tee_time_s", (9 - 7) * 3600),
                "beverage_cart_service": None,
            }
            # Rebuild bev_points via BeverageCartService for consistent rendering
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

    # Phase3-style summary at root
    if phase3_summary_rows:
        write_phase3_summary(phase3_summary_rows, output_root)
    logger.info("Complete. Results saved to: %s", output_root)


if __name__ == "__main__":
    main()



