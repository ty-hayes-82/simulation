#!/usr/bin/env python3
"""
Quick visual debug for holes_geofenced.geojson

Loads the geofenced hole polygons and fills each hole with a distinct color.
Saves a PNG to help verify that we are coloring the INTERIOR of each polygon.

Usage:
  python scripts/viz/test_geofenced_holes_fill.py \
    --course-dir courses/pinetree_country_club \
    --output outputs/holes_geofenced_fill.png
"""

from __future__ import annotations

import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt

from golfsim.logging import init_logging, get_logger


logger = get_logger(__name__)


def load_geofenced_holes(course_dir: Path) -> gpd.GeoDataFrame:
    geojson_path = course_dir / "geojson" / "generated" / "holes_geofenced.geojson"
    if not geojson_path.exists():
        raise FileNotFoundError(f"Missing file: {geojson_path}")

    gdf = gpd.read_file(geojson_path)
    # Normalize CRS if present
    try:
        gdf = gdf.to_crs(4326)
    except Exception:
        pass

    if "hole" not in gdf.columns:
        logger.warning("'hole' property not found in holes_geofenced.geojson; plotting without labels")

    return gdf


def plot_geofenced_holes(gdf: gpd.GeoDataFrame, output_path: Path, title: str = "Geofenced Holes Fill Test") -> Path:
    # Choose a categorical colormap with enough distinct colors
    cmap = "tab20"  # up to 20 distinct colors; repeated if more

    fig, ax = plt.subplots(figsize=(12, 14))

    # Plot polygons; holes without a 'hole' value still get a color
    # Using 'hole' as the column will ensure consistent color per hole id
    if "hole" in gdf.columns:
        gdf.plot(ax=ax, column="hole", cmap=cmap, edgecolor="black", linewidth=1.2, alpha=0.8, legend=False)
    else:
        gdf.plot(ax=ax, color="#66c2a5", edgecolor="black", linewidth=1.2, alpha=0.8)

    # Annotate each polygon with its hole number at a representative interior point
    if "hole" in gdf.columns:
        for _, row in gdf.iterrows():
            geom = row.geometry
            if geom is None:
                continue
            rep = geom.representative_point()
            hole = row.get("hole")
            ax.annotate(str(hole), (rep.x, rep.y), fontsize=10, weight="bold", ha="center", va="center",
                        color="white", bbox=dict(boxstyle="round,pad=0.2", facecolor="black", alpha=0.6))

    ax.set_aspect("equal", adjustable="box")
    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(title)
    ax.grid(True, alpha=0.25)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(output_path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    logger.info("Saved geofenced holes fill test: %s (%.1f KB)", output_path, output_path.stat().st_size / 1024)
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Render geofenced holes with solid fills for debugging")
    parser.add_argument("--course-dir", type=Path, default=Path("courses/pinetree_country_club"),
                        help="Path to course directory that contains geojson/generated/holes_geofenced.geojson")
    parser.add_argument("--output", type=Path, default=Path("outputs/holes_geofenced_fill.png"),
                        help="Where to save the PNG output")
    parser.add_argument("--title", type=str, default="Geofenced Holes Fill Test",
                        help="Plot title")
    parser.add_argument("--verbose", action="store_true", help="Enable debug logging")

    args = parser.parse_args()

    init_logging(level="DEBUG" if args.verbose else "INFO")

    try:
        gdf = load_geofenced_holes(args.course_dir)
        plot_geofenced_holes(gdf, args.output, title=args.title)
        print(f"✓ Saved: {args.output}")
        return 0
    except Exception as exc:
        logger.error("Failed to render geofenced holes: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


