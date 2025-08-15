#!/usr/bin/env python3
"""
Two-Golfer Delivery Simulation Runner

Purpose:
- Simulate a single delivery runner handling two golfer orders with a configurable
  time gap between them.
- You specify the hole for Golfer 1 and Golfer 2, and the gap (minutes) between
  when their orders are placed.
- Useful to measure how much delay the second order experiences if the first
  order is far away.

Implementation notes:
- Uses golfsim.simulation.services.SingleRunnerDeliveryService, which models a
  single runner with a queue and realistic prep + travel + return times.
- Orders are scheduled at explicit times: order #1 aligned to the specified hole
  using minutes-per-hole pacing from the tee time, and order #2 occurs after the
  configured gap.
- Saves a concise results.json, a markdown log, and a PNG map visualization.

Windows PowerShell friendly: one short command per line, no piping/chaining.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List

import simpy

from golfsim.logging import init_logging, get_logger
from golfsim.simulation.services import SingleRunnerDeliveryService, DeliveryOrder
from golfsim.config.loaders import load_simulation_config
from golfsim.viz.matplotlib_viz import load_course_geospatial_data, render_delivery_plot

import sys
from pathlib import Path as _Path
sys.path.append(str(_Path(__file__).parent.parent.parent))
from utils import setup_encoding
from utils.cli import add_log_level_argument, add_course_dir_argument
from utils.simulation_reporting import create_argparse_epilog


logger = get_logger(__name__)


def _parse_hhmm_to_seconds_since_7am(hhmm: str) -> int:
    try:
        hh, mm = hhmm.split(":")
        return (int(hh) - 7) * 3600 + int(mm) * 60
    except Exception:
        return (9 - 7) * 3600  # default to 09:00


def _seconds_to_clock_str(sec_since_7am: int) -> str:
    total = max(0, int(sec_since_7am))
    hh = 7 + (total // 3600)
    mm = (total % 3600) // 60
    ss = total % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def _build_results_dict(service: SingleRunnerDeliveryService, orders: List[DeliveryOrder], course_dir: str) -> Dict[str, Any]:
    """Build a result payload compatible with existing visualization utilities."""
    results: Dict[str, Any] = {
        "success": True,
        "simulation_type": "two_golfers_single_runner",
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
            {"order_id": o.order_id, "reason": o.failure_reason} for o in service.failed_orders
        ],
        "activity_log": service.activity_log,
        "metadata": {
            "prep_time_min": int(service.prep_time_min),
            "runner_speed_mps": float(service.runner_speed_mps),
            "num_orders": len(orders),
            "course_dir": str(course_dir),
        },
    }
    return results


def _write_two_order_log(orders: List[DeliveryOrder], delivery_stats: List[Dict[str, Any]], save_path: Path) -> None:
    # Map stats by order_id for convenience
    stats_by_id: Dict[str | None, Dict[str, Any]] = {d.get("order_id"): d for d in (delivery_stats or [])}

    def fmt_minutes(seconds: float | None) -> str:
        s = float(seconds or 0.0)
        return f"{s/60.0:.1f} min"

    lines: List[str] = [
        "# Two-Order Delivery Log",
        "",
    ]

    for idx, o in enumerate(orders, start=1):
        st = stats_by_id.get(o.order_id, {})
        lines += [
            f"## Order {idx} — ID {o.order_id}",
            f"- Golfer Group: {o.golfer_group_id}",
            f"- Hole: {o.hole_num}",
            f"- Order Time: {_seconds_to_clock_str(int(o.order_time_s))}",
            f"- Queue Delay: {fmt_minutes(st.get('queue_delay_s'))}",
            f"- Prep Time: {fmt_minutes(st.get('prep_time_s'))}",
            f"- Travel (to golfer): {fmt_minutes(st.get('delivery_time_s'))}",
            f"- Return Time: {fmt_minutes(st.get('return_time_s'))}",
            f"- Total Completion: {fmt_minutes(st.get('total_completion_time_s'))}",
            "",
        ]

    # If both are present, highlight the second order's queue delay explicitly
    if len(orders) >= 2:
        second = orders[1]
        st2 = stats_by_id.get(second.order_id, {})
        lines += [
            "## Impact Summary",
            f"Second order queue delay: {fmt_minutes(st2.get('queue_delay_s'))}",
            "",
        ]

    save_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    setup_encoding()

    examples = [
        "python scripts/sim/run_two_golfer_simulation.py --hole1 4 --hole2 16 --gap-min 15",
        "python scripts/sim/run_two_golfer_simulation.py --hole1 2 --hole2 3 --gap-min 5 --first-tee 09:15",
    ]

    parser = argparse.ArgumentParser(
        description="Two-golfer delivery simulation with a single runner and explicit order gap",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=create_argparse_epilog(examples),
    )
    add_log_level_argument(parser)
    add_course_dir_argument(parser)

    parser.add_argument("--hole1", type=int, choices=range(1, 19), required=True, help="Hole for Golfer 1 order (1-18)")
    parser.add_argument("--hole2", type=int, choices=range(1, 19), required=True, help="Hole for Golfer 2 order (1-18)")
    parser.add_argument("--gap-min", type=float, required=True, help="Gap between orders in minutes (Golfer 2 after Golfer 1)")

    parser.add_argument("--first-tee", type=str, default="09:00", help="First tee time HH:MM for Golfer 1")
    parser.add_argument("--second-tee", type=str, default=None, help="First tee time HH:MM for Golfer 2 (optional)")
    parser.add_argument("--minutes-per-hole", type=float, default=12.0, help="Pacing minutes per hole to align order 1 time (default: 12)")

    parser.add_argument("--prep-time", type=int, default=10, help="Food preparation time in minutes (default: 10)")
    # Speed overrides: prefer MPH override, otherwise MPS; default to course config MPH
    parser.add_argument("--runner-speed-mph", type=float, default=None, help="Runner speed in mph (override; default from course config)")
    parser.add_argument("--runner-speed", type=float, default=None, help="Runner speed in m/s (override; alias for --runner-speed-mps)")
    parser.add_argument("--runner-speed-mps", type=float, default=None, help="Runner speed in m/s (override; default from course config)")

    parser.add_argument("--output", type=str, default="outputs", help="Root directory for simulation results")
    parser.add_argument("--no-visualization", action="store_true", help="Skip creating visualization PNG map")

    args = parser.parse_args()

    # Output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_base = Path(args.output)
    output_dir = output_base / f"two_golfers_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Initialize logging
    init_logging(args.log_level)

    logger.info("Two-Golfer Delivery Simulation")
    logger.info("Course: %s", args.course_dir)
    logger.info("Golfer 1 hole: %s", args.hole1)
    logger.info("Golfer 2 hole: %s", args.hole2)
    logger.info("Gap between orders: %.1f min", float(args.gap_min))
    logger.info("First tee: %s", args.first_tee)
    logger.info("Minutes per hole: %.1f", float(args.minutes_per_hole))
    logger.info("Prep time: %d min", int(args.prep_time))
    # Determine effective runner speed (default from config MPH)
    try:
        sim_cfg_preview = load_simulation_config(args.course_dir)
        cfg_mps_default = float(getattr(sim_cfg_preview, "delivery_runner_speed_mps", 6.0))
        cfg_mph_default = cfg_mps_default / 0.44704
    except Exception:
        cfg_mps_default, cfg_mph_default = 6.0, 6.0
    override_mps: float
    if args.runner_speed_mph is not None:
        override_mps = float(args.runner_speed_mph) * 0.44704
        logger.info("Runner speed (override mph): %.2f mph (%.2f m/s)", float(args.runner_speed_mph), override_mps)
    elif args.runner_speed is not None:
        override_mps = float(args.runner_speed)
        logger.info("Runner speed (override mps): %.2f m/s", override_mps)
    elif args.runner_speed_mps is not None:
        override_mps = float(args.runner_speed_mps)
        logger.info("Runner speed (override mps): %.2f m/s", override_mps)
    else:
        override_mps = cfg_mps_default
        logger.info("Runner speed: %.1f mph (%.2f m/s) [from config]", cfg_mph_default, cfg_mps_default)
    logger.info("Output: %s", output_dir)

    try:
        # Prepare environment and service
        env = simpy.Environment()
        service = SingleRunnerDeliveryService(
            env=env,
            course_dir=args.course_dir,
            runner_speed_mps=float(override_mps),
            prep_time_min=int(args.prep_time),
        )

        # Align first order time with tee time and hole position
        tee_time_s = _parse_hhmm_to_seconds_since_7am(str(args.first_tee))
        order1_time_s = int(tee_time_s + max(0.0, (float(args.hole1) - 1.0)) * float(args.minutes_per_hole) * 60.0)
        # Enforce service open
        order1_time_s = max(int(order1_time_s), int(service.service_open_s))
        # Base second order time from second tee (if provided)
        tee2_time_s = _parse_hhmm_to_seconds_since_7am(str(args.second_tee)) if args.second_tee else None
        base_second_from_tee = None
        if tee2_time_s is not None:
            base_second_from_tee = int(tee2_time_s + max(0.0, (float(args.hole2) - 1.0)) * float(args.minutes_per_hole) * 60.0)
        # Ensure second order is at least gap-min after first order
        gap_based_second = int(order1_time_s + float(args.gap_min) * 60.0)
        if base_second_from_tee is not None:
            order2_time_s = max(base_second_from_tee, gap_based_second, int(service.service_open_s))
        else:
            order2_time_s = max(gap_based_second, int(service.service_open_s))

        # Build two explicit orders
        orders: List[DeliveryOrder] = [
            DeliveryOrder(order_id="001", golfer_group_id=1, golfer_id="G1", order_time_s=float(order1_time_s), hole_num=int(args.hole1)),
            DeliveryOrder(order_id="002", golfer_group_id=2, golfer_id="G2", order_time_s=float(order2_time_s), hole_num=int(args.hole2)),
        ]

        def order_feeder():  # simpy process
            last_t = env.now
            for o in orders:
                target = max(int(o.order_time_s), int(service.service_open_s))
                if target > last_t:
                    yield env.timeout(target - last_t)
                service.place_order(o)
                last_t = target

        env.process(order_feeder())

        # Run until after second order should complete (allow buffer)
        run_until = max(service.service_close_s + 1, int(order2_time_s + 4 * 3600))
        env.run(until=run_until)

        # Build results + write files
        results = _build_results_dict(service, orders, args.course_dir)

        # Save JSON
        (output_dir / "results.json").write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

        # Markdown log
        _write_two_order_log(orders, service.delivery_stats, output_dir / "two_delivery_log.md")

        # Visualization (match single-golfer artifacts: HTML Folium + PNG + debug CSV)
        if not args.no_visualization and results.get("orders"):
            try:
                course_data = load_course_geospatial_data(args.course_dir)
                sim_cfg = load_simulation_config(args.course_dir)
                clubhouse_coords = sim_cfg.clubhouse

                # Create Folium map HTML like single-golfer
                from golfsim.viz.matplotlib_viz import create_folium_delivery_map
                folium_map_path = output_dir / "delivery_route_map.html"
                create_folium_delivery_map(results, course_data, folium_map_path)

                # Try to load cart graph for consistent visuals
                cart_graph = None
                try:
                    import pickle
                    cart_graph_pkl = Path(args.course_dir) / "pkl" / "cart_graph.pkl"
                    if cart_graph_pkl.exists():
                        with cart_graph_pkl.open("rb") as f:
                            cart_graph = pickle.load(f)
                except Exception:
                    cart_graph = None

                # PNG map with same filename and style as single-golfer
                output_file = output_dir / "delivery_route_visualization.png"
                debug_coords_file = output_dir / "visualization_debug_coords.csv"
                render_delivery_plot(
                    results=results,
                    course_data=course_data,
                    clubhouse_coords=clubhouse_coords,
                    golfer_coords=None,
                    runner_coords=None,
                    cart_graph=cart_graph,
                    save_path=output_file,
                    course_name=Path(args.course_dir).name.replace("_", " ").title(),
                    style="simple",
                    save_debug_coords_path=debug_coords_file,
                )
                logger.info("Delivery visualization created successfully.")
            except Exception as viz_err:  # noqa: BLE001
                logger.warning("Failed to create visualization: %s", viz_err)

        # Console highlights
        # Find second order stats for quick delay check
        delay_min = None
        for d in service.delivery_stats:
            if d.get("order_id") == "002":
                delay_min = float(d.get("queue_delay_s", 0.0)) / 60.0
                break
        if delay_min is not None:
            logger.info("Second order queue delay: %.1f minutes", delay_min)

        logger.info("All results saved to: %s", output_dir.absolute())
        return 0

    except Exception as e:  # noqa: BLE001
        logger.error("Error in two-golfer simulation: %s", e)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


