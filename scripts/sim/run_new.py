#!/usr/bin/env python3
"""
New Unified Simulation Runner

A streamlined CLI that uses the refactored golfsim library for running simulations.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
import os
from typing import Any

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import golfsim
import geopandas as gpd

from golfsim.logging import init_logging, get_logger
from golfsim.simulation.orchestration import run_delivery_runner_simulation, create_simulation_config_from_args
from golfsim.viz.heatmap_viz import (
    load_geofenced_holes,
    extract_order_data,
    calculate_delivery_time_stats,
)

logger = get_logger(__name__)


def build_feature_collection(
    hole_polygons: dict[int, Any],
    hole_stats: dict[int, dict[str, float]],
) -> dict[str, Any]:
    """Build a GeoJSON FeatureCollection of hole polygons with delivery stats.

    Each feature contains properties:
      - hole: int
      - has_data: bool
      - avg_time, min_time, max_time, count (when available)
    """
    features: list[dict[str, Any]] = []

    for hole_num, geom in hole_polygons.items():
        props: dict[str, Any] = {"hole": int(hole_num)}
        stats = hole_stats.get(hole_num)
        if stats:
            props.update(
                {
                    "has_data": True,
                    "avg_time": float(stats.get("avg_time", 0.0)),
                    "min_time": float(stats.get("min_time", 0.0)),
                    "max_time": float(stats.get("max_time", 0.0)),
                    "count": int(stats.get("count", 0)),
                }
            )
        else:
            props.update({"has_data": False})

        # Convert shapely geometry to GeoJSON-like mapping
        gdf = gpd.GeoDataFrame({"geometry": [geom]}, crs="EPSG:4326")
        feature_geom = json.loads(gdf.to_json())["features"][0]["geometry"]

        features.append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": feature_geom,
            }
        )

    return {"type": "FeatureCollection", "features": features}


def export_hole_delivery_geojson(
    results: dict[str, Any], 
    course_dir: Path,
    output_path: Path
) -> None:
    """Export hole delivery statistics as GeoJSON from simulation results."""
    try:
        # Extract order-level delivery times
        order_data = extract_order_data(results)
        
        # Compute per-hole statistics
        hole_stats = calculate_delivery_time_stats(order_data)
        
        # Load hole polygons from geofenced file
        hole_polygons = load_geofenced_holes(course_dir)
        
        # Build and save GeoJSON
        feature_collection = build_feature_collection(hole_polygons, hole_stats)
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(feature_collection, f)
        
        logger.info("Exported hole delivery GeoJSON to: %s", output_path)
        
    except Exception as e:
        logger.warning("Failed to export hole delivery GeoJSON: %s", e)


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Unified simulation runner for beverage carts and delivery runner (refactored)",
    )

    # Common arguments
    parser.add_argument("--course-dir", default="courses/pinetree_country_club", help="Course directory")
    parser.add_argument("--num-runs", type=int, default=1, help="Number of runs")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory root")
    parser.add_argument("--log-level", type=str, default="INFO", help="Log level")

    # Mode selection
    parser.add_argument("--num-carts", type=int, default=0, help="Number of beverage carts")
    parser.add_argument("--num-runners", type=int, default=1, help="Number of delivery runners")
    
    # Groups scheduling
    parser.add_argument("--groups-count", type=int, default=0, help="Number of golfer groups")
    parser.add_argument("--tee-scenario", type=str, default="typical_weekday", help="Tee-times scenario")
    parser.add_argument("--first-tee", type=str, default="09:00", help="First tee time (HH:MM format)")
    
    # Delivery runner params
    parser.add_argument("--prep-time", type=int, default=None, help="Food preparation time in minutes (overrides config)")
    parser.add_argument("--runner-speed", type=float, default=None, help="Runner speed in m/s (overrides config)")
    parser.add_argument("--golfer-total-minutes", type=int, default=None, help="Total minutes for golfer round (overrides config)")
    
    # Hole restrictions
    parser.add_argument("--block-up-to-hole", type=int, default=0, help="Block ordering for holes ≤ this number (e.g., 5 blocks 1–5)")
    parser.add_argument("--block-holes-10-12", action="store_true", default=False, help="Block ordering for holes 10–12")
    
    # GeoJSON export options
    parser.add_argument("--export-geojson", action="store_true", default=True, help="Export hole delivery times GeoJSON (default: True)")
    parser.add_argument("--geojson-output", type=str, default="my-map-animation/public/hole_delivery_times.geojson", help="GeoJSON output path")

    args = parser.parse_args()
    init_logging(args.log_level)

    logger.info("Starting simulation with %d runners, %d carts", args.num_runners, args.num_carts)
    
    # Create configuration from arguments
    config = create_simulation_config_from_args(args)
    
    # Run the appropriate simulation
    if args.num_runners > 0:
        results = run_delivery_runner_simulation(config, args=args)
        logger.info("Simulation completed successfully")
        
        # Export hole delivery GeoJSON if requested
        if args.export_geojson:
            geojson_path = Path(args.geojson_output)
            # Use absolute path if not already absolute
            if not geojson_path.is_absolute():
                geojson_path = Path.cwd() / geojson_path
                
            export_hole_delivery_geojson(
                results=results,
                course_dir=Path(config.course_dir),
                output_path=geojson_path
            )
        
        return results
    else:
        raise SystemExit("Nothing to simulate: set --num-runners > 0")
    
    logger.info("Simulation completed.")

if __name__ == "__main__":
    main()
