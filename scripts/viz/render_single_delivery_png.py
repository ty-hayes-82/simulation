#!/usr/bin/env python3
"""
Render a delivery route PNG from an existing simulation results JSON.

Thin CLI that delegates to shared library utilities in `golfsim.viz`.
"""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
from typing import Optional

import pandas as pd

from golfsim.config.loaders import load_simulation_config
from golfsim.logging import get_logger, init_logging
from golfsim.viz.matplotlib_viz import (
    load_course_geospatial_data,
    render_delivery_plot,
)
from utils import add_log_level_argument, add_course_dir_argument, setup_encoding


logger = get_logger(__name__)


def _load_optional_coordinates(csv_path: Path) -> Optional[pd.DataFrame]:
    if csv_path.exists():
        try:
            return pd.read_csv(csv_path)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to load coordinates CSV %s: %s", csv_path, e)
    return None


def main() -> int:
    setup_encoding()
    parser = argparse.ArgumentParser(
        description="Create a delivery route PNG from a simulation results JSON",
    )
    add_course_dir_argument(parser)
    parser.add_argument(
        "--results-json",
        required=True,
        help="Path to simulation_results.json produced by a run",
    )
    parser.add_argument(
        "--save-path",
        default=None,
        help="Output PNG path (default: alongside results JSON as delivery_visualization.png)",
    )
    parser.add_argument(
        "--style",
        default="simple",
        choices=["simple", "detailed"],
        help="Visualization style",
    )
    add_log_level_argument(parser)

    args = parser.parse_args()

    init_logging(args.log_level)

    results_path = Path(args.results_json)
    if not results_path.exists():
        logger.error("Results JSON not found: %s", results_path)
        return 1

    try:
        with results_path.open("r", encoding="utf-8") as f:
            results = json.load(f)
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to read results JSON: %s", e)
        return 1

    course_dir = Path(args.course_dir)

    # Load course context
    course_data = load_course_geospatial_data(course_dir)
    sim_cfg = load_simulation_config(course_dir)
    clubhouse_coords = sim_cfg.clubhouse

    # Optional: load cart path network if available
    cart_graph = None
    cart_graph_pkl = course_dir / "pkl" / "cart_graph.pkl"
    if cart_graph_pkl.exists():
        try:
            with cart_graph_pkl.open("rb") as f:
                cart_graph = pickle.load(f)
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to load cart graph: %s", e)

    # Optional: load detailed GPS coordinate tracks if present
    base_dir = results_path.parent
    golfer_coords = _load_optional_coordinates(base_dir / "golfer_coordinates.csv")
    runner_coords = _load_optional_coordinates(base_dir / "runner_coordinates.csv")

    # Determine save path
    if args.save_path:
        save_path = Path(args.save_path)
    else:
        save_path = base_dir / "delivery_visualization.png"

    # Render using shared viz utility
    output_path = render_delivery_plot(
        results=results,
        course_data=course_data,
        clubhouse_coords=clubhouse_coords,
        golfer_coords=golfer_coords,
        runner_coords=runner_coords,
        cart_graph=cart_graph,
        save_path=save_path,
        course_name=course_dir.name.replace("_", " ").title(),
        style=args.style,
    )

    logger.info("Visualization saved: %s", output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
