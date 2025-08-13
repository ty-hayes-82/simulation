#!/usr/bin/env python3
"""
Batch runner for configurable multi-golfer simulations.

Thin CLI that delegates to `golfsim.simulation.services.run_multi_golfer_simulation`.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from golfsim.config.loaders import load_tee_times_config
from golfsim.logging import get_logger, init_logging
from golfsim.simulation.services import run_multi_golfer_simulation
from utils import setup_encoding, add_log_level_argument, write_json


logger = get_logger(__name__)


def _build_groups_from_tee_times(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    groups: List[Dict[str, Any]] = []
    tee_times = config.get("tee_times", [])
    for idx, tt in enumerate(tee_times, start=1):
        groups.append(
            {
                "group_id": idx,
                "tee_time_s": int(tt.get("tee_time_s", 0)),
                "num_golfers": int(tt.get("num_golfers", 4)),
            }
        )
    return groups


def main() -> int:
    setup_encoding()

    parser = argparse.ArgumentParser(
        description="Run configurable multi-golfer simulations and save summaries",
    )
    parser.add_argument(
        "--course-dir",
        default="courses/pinetree_country_club",
        help="Course directory containing config files",
    )
    parser.add_argument(
        "--scenario",
        default=None,
        help="Scenario name from tee_times_config.json; run all if omitted",
    )
    parser.add_argument(
        "--runs-per-scenario",
        type=int,
        default=3,
        help="Number of runs per scenario",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs",
        help="Base output directory",
    )
    parser.add_argument(
        "--prep-time",
        type=int,
        default=10,
        help="Food preparation time minutes",
    )
    parser.add_argument(
        "--runner-speed",
        type=float,
        default=6.0,
        help="Runner speed m/s",
    )
    add_log_level_argument(parser)

    args = parser.parse_args()

    init_logging(args.log_level)
    course_dir = Path(args.course_dir)
    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    tee_cfg = load_tee_times_config(course_dir)
    scenarios = {args.scenario: tee_cfg.get(args.scenario)} if args.scenario else tee_cfg

    if not scenarios:
        logger.error("No scenarios found in tee_times_config.json")
        return 1

    for scenario_name, scenario in scenarios.items():
        if not scenario:
            logger.warning("Skipping missing scenario: %s", scenario_name)
            continue

        logger.info("Running scenario: %s", scenario_name)
        groups = _build_groups_from_tee_times(scenario)

        scenario_dir = output_root / f"multi_golfer_{scenario_name}"
        scenario_dir.mkdir(parents=True, exist_ok=True)

        for run_idx in range(1, args.runs_per_scenario + 1):
            run_dir = scenario_dir / f"run_{run_idx:03d}"
            run_dir.mkdir(parents=True, exist_ok=True)

            results = run_multi_golfer_simulation(
                course_dir=str(course_dir),
                groups=groups,
                order_probability_per_9_holes=float(
                    scenario.get("order_probability_per_9_holes", 0.3)
                ),
                prep_time_min=args.prep_time,
                runner_speed_mps=args.runner_speed,
            )

            # Save JSON summary (using SimulationResult wrapper for consistency when possible)
            out_json = write_json(run_dir / "multi_golfer_simulation_results.json", results)
            logger.info("Saved results: %s", out_json)

    logger.info("All scenarios complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
