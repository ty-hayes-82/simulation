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
import shutil
from typing import Any
import subprocess

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


def cleanup_old_simulation_outputs(output_root: str = "outputs") -> None:
    """Remove all existing simulation output directories to ensure clean results."""
    try:
        project_root = Path(__file__).parent.parent.parent
        outputs_dir = project_root / output_root
        
        if not outputs_dir.exists():
            logger.info("No existing outputs directory to clean")
            return
            
        # Find all simulation output directories (timestamped folders)
        old_dirs = [d for d in outputs_dir.iterdir() if d.is_dir() and d.name.startswith("202")]
        
        if not old_dirs:
            logger.info("No old simulation outputs to clean")
            return
            
        logger.info("Cleaning up %d old simulation output directories", len(old_dirs))
        for old_dir in old_dirs:
            try:
                shutil.rmtree(old_dir)
                logger.debug("Removed old output directory: %s", old_dir.name)
            except Exception as e:
                logger.warning("Failed to remove %s: %s", old_dir.name, e)
                
        logger.info("✅ Cleaned up old simulation outputs")
        
    except Exception as e:
        logger.warning("Failed to cleanup old outputs: %s", e)


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
    parser.add_argument("--keep-old-outputs", action="store_true", default=False, help="Keep existing simulation outputs (default: clean them up)")

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
    parser.add_argument("--delivery-total-orders", type=int, default=None, help="Total number of delivery orders to generate (overrides config)")
    
    # Hole restrictions
    parser.add_argument("--block-up-to-hole", type=int, default=0, help="Block ordering for holes ≤ this number (e.g., 5 blocks 1–5)")
    parser.add_argument("--block-holes-10-12", action="store_true", default=False, help="Block ordering for holes 10–12")
    parser.add_argument("--block-holes", nargs="+", type=int, default=None, help="Block ordering for specific holes, e.g., --block-holes 3 4 5")
    parser.add_argument("--block-holes-range", type=str, default=None, help="Block a range of holes, e.g., 3-5")
    
    # GeoJSON export options
    parser.add_argument("--export-geojson", action="store_true", default=True, help="Export hole delivery times GeoJSON (default: True)")

    # Minimal outputs mode: only write files needed by the map app controls/manifest
    parser.add_argument("--minimal-outputs", action="store_true", default=False, help="Only write coordinates.csv, simulation_metrics.json, and results.json; skip heatmaps, logs, extra metrics, and public copies")
    parser.add_argument("--coordinates-only-for-first-run", action="store_true", default=False, help="Only generate coordinates.csv for the first run in a multi-run simulation")

    args = parser.parse_args()
    init_logging(args.log_level)

    # Clean up old simulation outputs unless explicitly told to keep them
    if not args.keep_old_outputs:
        cleanup_old_simulation_outputs()

    logger.info("Starting simulation with %d runners, %d carts", args.num_runners, args.num_carts)
    
    # Create configuration from arguments
    # If minimal-outputs, implicitly disable heatmap to save time and space
    if args.minimal_outputs:
        args.no_heatmap = True

    config = create_simulation_config_from_args(args)
    
    # Run the appropriate simulation
    if args.num_runners > 0:
        results = run_delivery_runner_simulation(config, args=args)
        logger.info("Simulation completed successfully")
        
        # Export hole delivery GeoJSON if requested
        if args.export_geojson:
            # The `results` dict from the simulation orchestrator is a summary.
            # We need to load the detailed results.json from the output directory.
            output_dir = Path(results.get("output_dir", ""))
            run_dir = output_dir / "run_01"
            detailed_results_path = run_dir / "results.json"
            if output_dir and detailed_results_path.exists():
                with detailed_results_path.open("r", encoding="utf-8") as f:
                    detailed_results = json.load(f)

                # 1) Write a per-run GeoJSON beside coordinates.csv for this run
                try:
                    per_run_geojson = run_dir / "hole_delivery_times.geojson"
                    export_hole_delivery_geojson(
                        results=detailed_results,
                        course_dir=Path(config.course_dir),
                        output_path=per_run_geojson,
                    )
                except Exception as e:
                    logger.warning("Failed to write per-run hole delivery GeoJSON: %s", e)

                # 2) Also write the global/public GeoJSON path for quick preview
                try:
                    if hasattr(args, "geojson_output") and getattr(args, "geojson_output", None):
                        geojson_path = Path(args.geojson_output)
                        if not geojson_path.is_absolute():
                            geojson_path = Path.cwd() / geojson_path
                        export_hole_delivery_geojson(
                            results=detailed_results,
                            course_dir=Path(config.course_dir),
                            output_path=geojson_path,
                        )
                except Exception as e:
                    logger.warning("Failed to write public hole delivery GeoJSON: %s", e)
            else:
                logger.warning("Could not find detailed results.json to generate heatmap data.")
        
        # --- Auto-publish to my-map-animation/public/coordinates ---
        try:
            viewer_dir = Path("my-map-animation")
            if viewer_dir.exists():
                env = os.environ.copy()
                try:
                    output_dir = Path(results.get("output_dir", "")).resolve()
                    outputs_root = output_dir.parent if output_dir else None
                    if outputs_root and outputs_root.exists():
                        env["SIM_BASE_DIR"] = str(outputs_root)
                except Exception:
                    pass
                subprocess.run([sys.executable, "run_map_app.py"], cwd=str(viewer_dir), env=env, check=False)
                logger.info("Published simulation artifacts to my-map-animation/public/coordinates via run_map_app.py")
            else:
                logger.info("Viewer directory '%s' not found; skipping auto-publish.", viewer_dir)
        except Exception as e:
            logger.warning("Failed to auto-publish to my-map-animation: %s", e)

        return
    else:
        raise SystemExit("Nothing to simulate: set --num-runners > 0")
    
    logger.info("Simulation completed.")

if __name__ == "__main__":
    main()
