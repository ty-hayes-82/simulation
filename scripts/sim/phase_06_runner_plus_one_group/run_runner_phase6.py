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
from datetime import datetime, timedelta
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
from utils.simulation_reporting import (
    log_simulation_results,
    write_simulation_stats,
    write_multi_run_summary,
    handle_simulation_error,
    create_argparse_epilog,
)


logger = get_logger(__name__)


def format_time_from_seconds(seconds: float) -> str:
    """Convert seconds to HH:MM:SS format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_time_from_round_start(seconds: float) -> str:
    """Format time as minutes into the round."""
    minutes = seconds / 60.0
    return f"{minutes:.1f} min into round"


def create_delivery_log(results: Dict, run_idx: int, save_path: Path) -> None:
    """
    Create a detailed delivery person log with timestamps for all key events.
    
    Args:
        results: Simulation results dictionary
        run_idx: Run index for identification
        save_path: Path where to save the delivery log
    """
    # Extract key timestamps
    order_time_s = results.get('order_time_s', 0)
    order_created_s = results.get('order_created_s', order_time_s)
    prep_completed_s = results.get('prep_completed_s', 0)
    delivered_s = results.get('delivered_s', 0)
    runner_returned_s = results.get('runner_returned_s', 0)
    
    # Calculate derived times
    prep_duration = prep_completed_s - order_created_s
    delivery_duration = delivered_s - prep_completed_s
    return_duration = runner_returned_s - delivered_s
    total_service_time = results.get('total_service_time_s', 0)
    
    # Get delivery details
    order_hole = results.get('order_hole', 'Unknown')
    delivery_distance = results.get('delivery_distance_m', 0)
    prediction_method = results.get('prediction_method', 'Unknown')
    
    # Create the log content
    lines = [
        f"# Delivery Log - Run {run_idx:02d}",
        "",
        f"**Order Details:**",
        f"- Hole: {order_hole}",
        f"- Prediction Method: {prediction_method}",
        f"- Total Service Time: {format_time_from_seconds(total_service_time)}",
        f"- Delivery Distance: {delivery_distance:.0f} meters",
        "",
        "## Timeline",
        "",
    ]
    
    # Add timeline events
    events = [
        ("Order Placed", order_created_s, "Customer places order"),
        ("Food Preparation Started", order_created_s, "Kitchen begins preparing order"),
        ("Food Ready", prep_completed_s, "Order prepared and ready for pickup"),
        ("Delivery Started", prep_completed_s, "Runner departs from clubhouse"),
        ("Order Delivered", delivered_s, "Customer receives their order"),
        ("Runner Returned", runner_returned_s, "Runner arrives back at clubhouse"),
    ]
    
    for event_name, timestamp, description in events:
        if timestamp > 0:
            time_str = format_time_from_seconds(timestamp)
            round_time = format_time_from_round_start(timestamp)
            lines.append(f"**{time_str}** ({round_time}) - {event_name}")
            lines.append(f"  {description}")
            lines.append("")
    
    # Add duration breakdown
    lines.extend([
        "## Duration Breakdown",
        "",
        f"- **Food Preparation**: {format_time_from_seconds(prep_duration)}",
        f"- **Delivery Time**: {format_time_from_seconds(delivery_duration)}",
        f"- **Return Time**: {format_time_from_seconds(return_duration)}",
        f"- **Total Service**: {format_time_from_seconds(total_service_time)}",
        "",
    ])
    
    # Add delivery location details if available
    predicted_location = results.get('predicted_delivery_location')
    if predicted_location:
        lines.extend([
            "## Delivery Location",
            "",
            f"- **Predicted**: {predicted_location[1]:.6f}, {predicted_location[0]:.6f}",
            "",
        ])
    
    # Add efficiency metrics if available
    trip_to_golfer = results.get('trip_to_golfer', {})
    if 'efficiency' in trip_to_golfer and trip_to_golfer['efficiency'] is not None:
        lines.extend([
            "## Route Efficiency",
            "",
            f"- **Efficiency**: {trip_to_golfer['efficiency']:.1f}% vs straight line",
            "",
        ])
    
    # Add prediction debug info if available
    prediction_debug = results.get('prediction_debug', {})
    if prediction_debug:
        lines.extend([
            "## Prediction Details",
            "",
        ])
        for key, value in prediction_debug.items():
            if key != 'prediction_coordinates':  # Skip coordinates to keep it readable
                lines.append(f"- **{key.replace('_', ' ').title()}**: {value}")
        lines.append("")
    
    # Write the log file
    save_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Created delivery log: %s", save_path)


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


def run_single(
    course_dir: Path,
    run_idx: int,
    output_root: Path,
    order_hole: Optional[int],
    prep_time_min: int,
    runner_speed_mps: float,
    track_coords: bool,
    use_enhanced_network: bool,
) -> Dict:
    """Execute one simulation and persist artifacts in sim_{NN}/."""
    run_dir = output_root / f"sim_{run_idx:02d}"
    run_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Run core simulation
        results = run_golf_delivery_simulation(
            course_dir=str(course_dir),
            order_hole=order_hole,
            prep_time_min=prep_time_min,
            runner_speed_mps=runner_speed_mps,
            use_enhanced_network=use_enhanced_network,
            track_coordinates=track_coords,
        )

        # Persist results bundle (CSV + simulation_results.json)
        save_results_bundle(results, run_dir)

        # Write stats using shared utility
        write_simulation_stats(results, run_dir / "stats.md", "Phase 6 — Single Runner + One Golfer Group")

        # Create detailed delivery log
        create_delivery_log(results, run_idx, run_dir / "delivery_log.md")

        # Log results using shared utility
        log_simulation_results(results, run_idx, track_coords)

        # Render delivery PNG (simple style by default)
        _render_run_png(results, course_dir, run_dir, style="simple")

        return results

    except Exception as e:
        if not handle_simulation_error(e, run_idx, exit_on_first=True):
            raise
        raise


def main() -> int:
    setup_encoding()

    examples = [
        "python run_runner_phase6.py --runs 5",
        "python run_runner_phase6.py --runs 3 --hole 14",
        "python run_runner_phase6.py --runs 2 --prep-time 15 --runner-speed 5.0",
        "python run_runner_phase6.py --runs 1 --no-enhanced",
    ]

    parser = argparse.ArgumentParser(
        description="Phase 6: Single runner + one golfer group",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=create_argparse_epilog(examples)
    )
    add_log_level_argument(parser)
    add_course_dir_argument(parser)
    parser.add_argument("--runs", type=int, default=5, help="Number of runs (default: 5)")
    parser.add_argument("--hole", type=int, choices=range(1, 19), metavar="1-18", help="Specific hole to place order (optional)")
    parser.add_argument("--prep-time", type=int, default=10, help="Food preparation time in minutes (default: 10)")
    parser.add_argument("--runner-speed", type=float, default=6.0, help="Runner speed in m/s (default: 6.0)")
    parser.add_argument("--no-enhanced", action="store_true", help="Don't use enhanced cart network (use original)")
    parser.add_argument("--no-coordinates", action="store_true", help="Disable detailed GPS coordinate tracking (enabled by default for better visualization)")
    parser.add_argument("--no-visualization", action="store_true", help="Skip creating delivery route visualization")

    args = parser.parse_args()
    init_logging(args.log_level)

    course_dir = Path(args.course_dir)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path("outputs") / f"{ts}_phase_06"
    output_root.mkdir(parents=True, exist_ok=True)

    logger.info("Phase 6 — Single Runner + One Golfer Group")
    logger.info("Course: %s", course_dir)
    logger.info("Runs: %d", int(args.runs))
    logger.info("Order hole: %s", args.hole if args.hole else 'Random')
    logger.info("Prep time: %d minutes", int(args.prep_time))
    logger.info("Runner speed: %.2f m/s", float(args.runner_speed))
    logger.info("Enhanced routing: %s", 'No' if args.no_enhanced else 'Yes')
    logger.info("Track coordinates: %s", 'No' if args.no_coordinates else 'Yes')
    logger.info("Output: %s", output_root)

    all_runs: List[Dict] = []
    for i in range(1, int(args.runs) + 1):
        logger.info("Running sim %d/%d...", i, int(args.runs))
        try:
            result = run_single(
                course_dir=course_dir,
                run_idx=i,
                output_root=output_root,
                order_hole=int(args.hole) if args.hole else None,
                prep_time_min=int(args.prep_time),
                runner_speed_mps=float(args.runner_speed),
                track_coords=not args.no_coordinates,
                use_enhanced_network=not args.no_enhanced,
            )
            all_runs.append(result)
        except Exception as e:
            if not handle_simulation_error(e, i, exit_on_first=True):
                return 1

    # Write summary using shared utility
    write_multi_run_summary(all_runs, output_root, "Phase 6 — Single Runner + One Golfer Group")
    logger.info("Complete. Results saved to: %s", output_root)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


