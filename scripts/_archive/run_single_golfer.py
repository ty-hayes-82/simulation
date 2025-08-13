#!/usr/bin/env python3
"""
Simplified Golf Course Delivery Simulation Runner (archived)

Superseded by `scripts/sim/run_single_golfer_simulation.py` and unified runner modes.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from golfsim.io.results import SimulationResult, save_results_bundle
from golfsim.logging import init_logging, get_logger
from utils.encoding import setup_encoding
from utils.cli import add_log_level_argument

from golfsim.simulation.engine import run_golf_delivery_simulation

logger = get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Golf course delivery simulation with enhanced cart path routing (archived)",
    )
    add_log_level_argument(parser)
    parser.add_argument("--course-dir", default="courses/pinetree_country_club")
    parser.add_argument("--hole", type=int, choices=range(1, 19))
    parser.add_argument("--prep-time", type=int, default=10)
    parser.add_argument("--runner-speed", type=float, default=6.0)
    parser.add_argument("--no-enhanced", action="store_true")
    parser.add_argument("--save-coordinates", action="store_true")
    parser.add_argument("--output-dir", default=None)

    args = parser.parse_args()
    init_logging(args.log_level)

    # Setup output directory
    if args.output_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output_dir = f"outputs/simulation_{timestamp}"
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        results = run_golf_delivery_simulation(
            course_dir=args.course_dir,
            order_hole=args.hole,
            prep_time_min=args.prep_time,
            runner_speed_mps=args.runner_speed,
            use_enhanced_network=not args.no_enhanced,
            track_coordinates=args.save_coordinates,
        )

        simulation_result = SimulationResult(
            metadata={
                "simulation_type": "single_golfer",
                "course": str(args.course_dir),
                "timestamp": datetime.now().isoformat(),
            },
            delivery_metrics=results.get("delivery_metrics", {}),
            golfer_coordinates=results.get("golfer_coordinates", []),
            runner_coordinates=results.get("runner_coordinates", []),
            route_data=results.get("route_data", {}),
            timing_data=results.get("timing_data", {}),
            additional_data={k: v for k, v in results.items() if k not in [
                "delivery_metrics", "golfer_coordinates", "runner_coordinates", "route_data", "timing_data"
            ]},
        )

        save_results_bundle(simulation_result, output_dir)
        logger.info("Saved results bundle to: %s", output_dir)
        return 0
    except Exception as e:
        logger.error("Simulation error: %s", e)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


