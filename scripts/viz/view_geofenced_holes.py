#!/usr/bin/env python3
"""
Simple viewer for geofenced holes as filled polygons.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt

from golfsim.logging import get_logger, init_logging
from utils import add_log_level_argument, add_course_dir_argument, setup_encoding

logger = get_logger(__name__)


def main() -> int:
    setup_encoding()
    parser = argparse.ArgumentParser(description="View geofenced holes as filled polygons")
    add_course_dir_argument(parser)
    parser.add_argument(
        "--save",
        default=None,
        help="Optional path to save the rendered figure",
    )
    add_log_level_argument(parser)
    args = parser.parse_args()

    init_logging(args.log_level)

    course_dir = Path(args.course_dir)
    geojson_path = course_dir / "geojson" / "generated" / "holes_geofenced.geojson"

    if not geojson_path.exists():
        logger.error("Geofenced holes file not found: %s", geojson_path)
        return 1

    try:
        holes_gdf = gpd.read_file(geojson_path)
    except Exception as e:
        logger.error("Failed to load GeoJSON: %s", e)
        return 1

    fig, ax = plt.subplots(figsize=(12, 10))
    
    # Plot filled polygons
    holes_gdf.plot(
        ax=ax,
        facecolor="lightblue",
        edgecolor="blue",
        alpha=0.5,
    )
    
    # Label each hole at centroid
    for idx, row in holes_gdf.iterrows():
        centroid = row.geometry.centroid
        ax.text(
            centroid.x,
            centroid.y,
            str(row["hole"]),
            fontsize=12,
            ha="center",
            va="center",
            bbox=dict(facecolor="white", edgecolor="none", alpha=0.7)
        )
    
    ax.set_title(f"Geofenced Holes - {course_dir.name.replace('_', ' ').title()}")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    
    # Equal aspect ratio
    ax.set_aspect("equal")

    if args.save:
        out = Path(args.save)
        out.parent.mkdir(parents=True, exist_ok=True)
        plt.savefig(out, dpi=300, bbox_inches="tight")
        logger.info("Saved figure: %s", out)
    else:
        plt.show()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
