"""
Phase 6 simulation runner: Delivery staff + one golfer group.

This script pivots from beverage-cart phases to a single runner delivery model
using the improved single-golfer simulation engine. It runs one or more sims,
persists results in a Phase-style outputs directory, and renders delivery PNGs
compatible with the standalone renderer.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from golfsim.logging import get_logger, init_logging
from golfsim.simulation.engine import run_golf_delivery_simulation
from golfsim.config.loaders import load_simulation_config
from golfsim.io.results import save_results_bundle
from golfsim.viz.matplotlib_viz import (
    load_course_geospatial_data,
    render_delivery_plot,
)

# Ensure project root is on sys.path for `utils` imports when running via python path/to/script.py
import sys
from pathlib import Path as _P
sys.path.append(str(_P(__file__).parent.parent.parent.parent))

from utils import setup_encoding, add_log_level_argument, add_course_dir_argument


logger = get_logger(__name__)


def _write_run_stats(results: Dict, run_dir: Path) -> None:
    """Create a concise stats.md for a single run."""
    order_time_min = float(results.get("order_time_s", 0.0)) / 60.0
    service_time_min = float(results.get("total_service_time_s", 0.0)) / 60.0
    delivery_distance_m = float(results.get("delivery_distance_m", 0.0))
    travel_time_min = float(results.get("delivery_travel_time_s", 0.0)) / 60.0
    prep_time_min = float(results.get("prep_time_s", 0.0)) / 60.0

    lines = [
        "# Phase 6 — Single Runner + One Golfer Group",
        "",
        f"Order placed: {order_time_min:.1f} min into round",
        f"Service time (order→delivery): {service_time_min:.1f} min",
        f"Prep time: {prep_time_min:.1f} min",
        f"Travel time (out+back): {travel_time_min:.1f} min",
        f"Delivery distance (out+back): {delivery_distance_m:.0f} m",
    ]

    # Optional efficiency metrics
    trip_to_golfer = results.get("trip_to_golfer", {})
    if isinstance(trip_to_golfer, dict):
        eff = trip_to_golfer.get("efficiency")
        if isinstance(eff, (int, float)):
            lines.append(f"Route efficiency (to golfer): {float(eff):.1f}%")

    (run_dir / "stats.md").write_text("\n".join(lines), encoding="utf-8")


def _load_optional_csv(csv_path: Path) -> Optional[pd.DataFrame]:
    if csv_path.exists():
        try:
            return pd.read_csv(csv_path)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to read %s: %s", csv_path, e)
    return None


def _render_run_png(results: Dict, course_dir: Path, run_dir: Path, style: str = "simple") -> Optional[Path]:
    """Render the delivery visualization PNG for a run directory."""
    try:
        course_data = load_course_geospatial_data(course_dir)
        sim_cfg = load_simulation_config(course_dir)
        clubhouse_coords = sim_cfg.clubhouse

        # Optional overlays: coordinates if present
        golfer_df = _load_optional_csv(run_dir / "golfer_coordinates.csv")
        runner_df = _load_optional_csv(run_dir / "runner_coordinates.csv")

        # Optional cart graph
        cart_graph = None
        cart_graph_pkl = course_dir / "pkl" / "cart_graph.pkl"
        if cart_graph_pkl.exists():
            try:
                import pickle

                with cart_graph_pkl.open("rb") as f:
                    cart_graph = pickle.load(f)
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to load cart graph: %s", e)

        save_path = run_dir / "delivery_visualization.png"
        render_delivery_plot(
            results=results,
            course_data=course_data,
            clubhouse_coords=clubhouse_coords,
            golfer_coords=golfer_df,
            runner_coords=runner_df,
            cart_graph=cart_graph,
            save_path=save_path,
            course_name=course_dir.name.replace("_", " ").title(),
            style=style,
        )
        return save_path
    except Exception as e:  # noqa: BLE001
        logger.warning("PNG rendering failed: %s", e)
        return None


def _write_summary(all_runs: List[Dict], output_root: Path) -> None:
    if not all_runs:
        output_root.joinpath("summary.md").write_text("No runs.", encoding="utf-8")
        return

    service_times = [float(r.get("total_service_time_s", 0.0)) / 60.0 for r in all_runs]
    distances = [float(r.get("delivery_distance_m", 0.0)) for r in all_runs]

    lines = [
        "# Phase 6 — Single Runner + One Golfer Group",
        "",
        f"Runs: {len(all_runs)}",
        f"Service time (min): min={min(service_times):.1f}, max={max(service_times):.1f}, mean={(sum(service_times)/len(service_times)):.1f}",
        f"Delivery distance (m): min={min(distances):.0f}, max={max(distances):.0f}, mean={(sum(distances)/len(distances)):.0f}",
        "",
        "## Runs",
        "",
    ]

    for idx, r in enumerate(all_runs, 1):
        order_min = float(r.get("order_time_s", 0.0)) / 60.0
        svc_min = float(r.get("total_service_time_s", 0.0)) / 60.0
        dist_m = float(r.get("delivery_distance_m", 0.0))
        lines.extend(
            [
                f"### sim_{idx:02d}",
                f"- Order time: {order_min:.1f} min",
                f"- Service time: {svc_min:.1f} min",
                f"- Distance: {dist_m:.0f} m",
                "",
            ]
        )

    output_root.joinpath("summary.md").write_text("\n".join(lines), encoding="utf-8")


def run_single(
    course_dir: Path,
    run_idx: int,
    output_root: Path,
    order_hole: Optional[int],
    prep_time_min: int,
    runner_speed_mps: float,
    track_coords: bool,
) -> Dict:
    """Execute one simulation and persist artifacts in sim_{NN}/."""
    run_dir = output_root / f"sim_{run_idx:02d}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Run core simulation
    results = run_golf_delivery_simulation(
        course_dir=str(course_dir),
        order_hole=order_hole,
        prep_time_min=prep_time_min,
        runner_speed_mps=runner_speed_mps,
        use_enhanced_network=True,
        track_coordinates=track_coords,
    )

    # Persist results bundle (CSV + simulation_results.json)
    save_results_bundle(results, run_dir)

    # Also write a concise stats.md
    _write_run_stats(results, run_dir)

    # Render delivery PNG (simple style by default)
    _render_run_png(results, course_dir, run_dir, style="simple")

    return results


def main() -> int:
    setup_encoding()

    parser = argparse.ArgumentParser(description="Phase 6: Single runner + one golfer group")
    add_log_level_argument(parser)
    add_course_dir_argument(parser)
    parser.add_argument("--runs", type=int, default=5, help="Number of runs (default: 5)")
    parser.add_argument("--hole", type=int, choices=range(1, 19), metavar="1-18", help="Specific hole to place order (optional)")
    parser.add_argument("--prep-time", type=int, default=10, help="Food preparation time in minutes (default: 10)")
    parser.add_argument("--runner-speed", type=float, default=6.0, help="Runner speed in m/s (default: 6.0)")
    parser.add_argument("--no-coordinates", action="store_true", help="Disable saving detailed GPS coordinates")

    args = parser.parse_args()
    init_logging(args.log_level)

    course_dir = Path(args.course_dir)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path("outputs") / f"{ts}_phase_06"
    output_root.mkdir(parents=True, exist_ok=True)

    logger.info("Phase 6 — Single Runner + One Golfer Group")
    logger.info("Course: %s", course_dir)
    logger.info("Runs: %d", int(args.runs))
    if args.hole:
        logger.info("Order hole: %d", int(args.hole))
    logger.info("Prep: %d min | Runner speed: %.2f m/s", int(args.prep_time), float(args.runner_speed))

    all_runs: List[Dict] = []
    for i in range(1, int(args.runs) + 1):
        logger.info("Running sim %d/%d...", i, int(args.runs))
        result = run_single(
            course_dir=course_dir,
            run_idx=i,
            output_root=output_root,
            order_hole=int(args.hole) if args.hole else None,
            prep_time_min=int(args.prep_time),
            runner_speed_mps=float(args.runner_speed),
            track_coords=not args.no_coordinates,
        )
        all_runs.append(result)

    # Write summary at the root of the phase outputs
    _write_summary(all_runs, output_root)
    logger.info("Complete. Results saved to: %s", output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


