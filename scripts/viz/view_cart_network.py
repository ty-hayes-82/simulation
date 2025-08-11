#!/usr/bin/env python3
"""
Quick viewer for cart path network and course features.

Thin CLI that loads course geojsons and optional cart graph, with logging.
"""

from __future__ import annotations

import argparse
import pickle
from pathlib import Path

import matplotlib.pyplot as plt

from golfsim.logging import get_logger, init_logging
from golfsim.viz.matplotlib_viz import (
    load_course_geospatial_data,
    plot_course_features,
    plot_cart_network,
)
from utils import add_log_level_argument, add_course_dir_argument, setup_encoding


logger = get_logger(__name__)


def main() -> int:
    setup_encoding()
    parser = argparse.ArgumentParser(description="View cart paths and course features")
    add_course_dir_argument(parser)
    parser.add_argument(
        "--no-graph",
        action="store_true",
        help="Skip loading cart_graph.pkl",
    )
    parser.add_argument(
        "--save",
        default=None,
        help="Optional path to save the rendered figure",
    )
    add_log_level_argument(parser)
    args = parser.parse_args()

    init_logging(args.log_level)

    course_dir = Path(args.course_dir)
    course_data = load_course_geospatial_data(course_dir)

    cart_graph = None
    if not args.no_graph:
        pkl_path = course_dir / "pkl" / "cart_graph.pkl"
        if pkl_path.exists():
            try:
                with pkl_path.open("rb") as f:
                    cart_graph = pickle.load(f)
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to load cart graph: %s", e)
        else:
            logger.warning("Cart graph not found at %s", pkl_path)

    fig, ax = plt.subplots(1, 1, figsize=(16, 12))
    plot_course_features(ax, course_data)
    if cart_graph is not None:
        plot_cart_network(ax, cart_graph)
    ax.set_title(course_dir.name.replace("_", " ").title())

    if args.save:
        out = Path(args.save)
        out.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(out, dpi=300, bbox_inches="tight", facecolor="white")
        logger.info("Saved figure: %s", out)
    else:
        plt.show()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
