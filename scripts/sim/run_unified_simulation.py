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
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

import simpy

from golfsim.logging import init_logging, get_logger
from golfsim.config.loaders import load_tee_times_config
from golfsim.simulation.services import (
    BeverageCartService,
    run_multi_golfer_simulation,
)
from golfsim.simulation.phase_simulations import generate_golfer_track
from golfsim.simulation.crossings import (
    compute_crossings_from_files,
    serialize_crossings_summary,
)
from golfsim.simulation.bev_cart_pass import simulate_beverage_cart_sales
from golfsim.io.results import write_unified_coordinates_csv
from golfsim.viz.matplotlib_viz import render_beverage_cart_plot
from golfsim.io.phase_reporting import save_phase3_output_files, write_phase3_summary
from golfsim.analysis.metrics_integration import generate_and_save_metrics


logger = get_logger(__name__)


# -------------------- Shared helpers --------------------
def _seconds_to_clock_str(sec_since_7am: int) -> str:
    total = max(0, int(sec_since_7am))
    hh = 7 + (total // 3600)
    mm = (total % 3600) // 60
    ss = total % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def _first_tee_to_seconds(hhmm: str) -> int:
    hh, mm = hhmm.split(":")
    return (int(hh) - 7) * 3600 + int(mm) * 60


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
    write_unified_coordinates_csv(tracks, run_dir / "coordinates.csv")

    # Visualization for cart
    if bev_points:
        render_beverage_cart_plot(bev_points, course_dir=course_dir, save_path=run_dir / "bev_cart_route.png")

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
    }
    (run_dir / "result.json").write_text(json.dumps(result_meta, indent=2), encoding="utf-8")

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
def _run_mode_bev_carts(args: argparse.Namespace) -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_name = f"{ts}_bev_carts_{int(args.num_carts)}carts"
    output_root = Path(args.output_dir or (Path("outputs") / default_name))
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
    default_name = f"{ts}_bev_with_golfers_{int(args.groups_count)}groups"
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
    default_name = f"{ts}_golfers_only_{int(args.groups_count)}groups"
    output_root = Path(args.output_dir or (Path("outputs") / default_name))
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
    output_dir = Path(args.output_dir or (Path("outputs") / f"delivery_dynamic_{datetime.now().strftime('%Y%m%d_%H%M%S')}"))
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


