#!/usr/bin/env python3
"""
Single Golfer Delivery Simulation Runner

Thin CLI that delegates to golfsim.simulation.engine.run_golf_delivery_simulation.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from typing import Dict
from pathlib import Path

import pandas as pd

from golfsim.simulation.engine import run_golf_delivery_simulation
from golfsim.config.loaders import load_simulation_config
from golfsim.io.results import save_results_bundle, write_unified_coordinates_csv
from golfsim.viz.matplotlib_viz import render_delivery_plot, load_course_geospatial_data, create_folium_delivery_map
from golfsim.logging import init_logging, get_logger
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))
from utils import setup_encoding, add_log_level_argument, add_course_dir_argument
from utils.simulation_reporting import (
    log_simulation_results,
    handle_simulation_error,
    create_argparse_epilog,
    create_delivery_log,
)

logger = get_logger(__name__)



def main() -> int:
    """Main function with CLI interface."""
    setup_encoding()
    
    examples = [
        "python run_single_golfer_simulation.py --hole 14",
        "python run_single_golfer_simulation.py --hole 16",
        "python run_single_golfer_simulation.py",
        "python run_single_golfer_simulation.py --hole 8 --prep-time 15",
    ]
    
    parser = argparse.ArgumentParser(
        description="Golf course delivery simulation with enhanced cart path routing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=create_argparse_epilog(examples)
    )
    add_log_level_argument(parser)
    add_course_dir_argument(parser)
    
    parser.add_argument("--hole", type=int, choices=range(1, 19), metavar="1-18",
                       help="Specific hole to place order (1-18), or random if not specified")
    parser.add_argument("--prep-time", type=int, default=10,
                       help="Food preparation time in minutes (default: 10)")
    parser.add_argument("--runner-speed", type=float, default=None,
                        help="Runner speed in m/s (default: converted from config 'delivery_runner_speed_mph')")
    parser.add_argument("--placement", choices=["tee", "mid", "green"], default="mid",
                        help="Where on the specified --hole to place the order: tee, mid, or green (default: mid)")
    parser.add_argument("--runner-delay", type=float, default=0.0, metavar="MIN",
                        help="Additional delay in minutes before runner departs (simulates busy runner; default: 0)")
    parser.add_argument("--no-enhanced", action="store_true",
                       help="Don't use enhanced cart network (use original)")
    parser.add_argument("--no-coordinates", action="store_true",
                       help="Disable detailed GPS coordinate tracking (enabled by default for better visualization)")
    parser.add_argument("--output", type=str, default="outputs", help="Root directory for simulation results.")
    parser.add_argument("--no-visualization", action="store_true",
                       help="Skip creating delivery route visualization")
    
    args = parser.parse_args()
    
    # --- Pre-simulation setup ---
    
    # Ensure geofenced holes file exists, create it if not
    course_dir = Path(args.course_dir)
    geofenced_holes_path = course_dir / "geojson" / "generated" / "holes_geofenced.geojson"
    if not geofenced_holes_path.exists():
        logger.info("Geofenced holes file not found, generating it now...")
        try:
            import subprocess
            boundary_path = course_dir / "geojson" / "course_polygon.geojson"
            holes_path = course_dir / "geojson" / "holes.geojson"
            
            if not boundary_path.exists() or not holes_path.exists():
                logger.error("Boundary or holes geojson file missing, cannot generate geofenced holes.")
                return 1

            subprocess.run(
                [
                    "python", "scripts/course_prep/geofence_holes.py",
                    "--boundary", str(boundary_path),
                    "--holes", str(holes_path),
                ],
                check=True,
                capture_output=True,
                text=True
            )
            logger.info("Successfully generated geofenced holes file.")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to generate geofenced holes file: {e.stderr}")
            return 1
        except FileNotFoundError:
            logger.error("Could not find geofence_holes.py script. Make sure you are in the project root.")
            return 1

    # Create output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_base = Path(args.output)
    output_dir = output_base / f"simulation_{timestamp}"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Initialize logging to file
    init_logging()

    logger.info("Golf Course Delivery Simulation")
    logger.info(f"Course: {args.course_dir}")
    logger.info(f"Order hole: {args.hole if args.hole else 'Random'}")
    logger.info(f"Prep time: {args.prep_time} minutes")
    # Determine effective speed for logging (config mph → m/s conversion handled by loader)
    try:
        sim_cfg_preview = load_simulation_config(args.course_dir)
        cfg_mps = float(getattr(sim_cfg_preview, "delivery_runner_speed_mps", 6.0))
    except Exception:
        cfg_mps, cfg_mph = 6.0, 6.0
    if args.runner_speed is None:
        logger.info(f"Runner speed: {cfg_mps:.2f} m/s [from config]")
    else:
        logger.info(f"Runner speed (override): {args.runner_speed:.2f} m/s")
    logger.info(f"Enhanced routing: {'No' if args.no_enhanced else 'Yes'}")
    logger.info(f"Hole placement on hole: {args.placement}")
    if args.runner_delay and args.runner_delay > 0:
        logger.info(f"Runner busy delay: {args.runner_delay} minutes")
    logger.info(f"Output: {output_dir}")
    
    try:
        # Run simulation
        results = run_golf_delivery_simulation(
            course_dir=args.course_dir,
            order_hole=args.hole,
            prep_time_min=args.prep_time,
            runner_speed_mps=args.runner_speed,
            hole_placement=args.placement,
            runner_delay_min=args.runner_delay,
            use_enhanced_network=not args.no_enhanced,
            track_coordinates=not args.no_coordinates
        )
        
        # Save results using library function
        save_results_bundle(results, output_dir)
        
        # Log results using shared utility
        log_simulation_results(results, track_coords=not args.no_coordinates)
        
        # Create unified coordinates CSV combining golfer and delivery runner
        if not args.no_coordinates:
            try:
                points_by_id = {}
                if results.get('golfer_coordinates'):
                    points_by_id['golfer_1'] = results['golfer_coordinates']
                if results.get('runner_coordinates'):
                    points_by_id['delivery_runner_1'] = results['runner_coordinates']
                if points_by_id:
                    combined_csv = output_dir / "coordinates.csv"
                    write_unified_coordinates_csv(points_by_id, combined_csv)
                    logger.info("Saved combined coordinates CSV: %s", combined_csv)
            except Exception as e:
                logger.warning("Failed to write combined coordinates CSV: %s", e)

        # Create detailed delivery log
        create_delivery_log(results, output_dir / "delivery_log.md")
        
        logger.info(f"All results saved to: {output_dir.absolute()}")
        
        # Create visualization unless disabled
        if not args.no_visualization:
            logger.info("Creating delivery visualization...")
            try:
                course_data = load_course_geospatial_data(args.course_dir)
                config_path = Path(args.course_dir) / "config" / "simulation_config.json"
                with config_path.open() as f:
                    config = json.load(f)
                clubhouse_coords = (config["clubhouse"]["longitude"], config["clubhouse"]["latitude"])

                # Create Folium map
                folium_map_path = output_dir / "delivery_route_map.html"
                create_folium_delivery_map(results, course_data, folium_map_path)
                
                # Load coordinate data if available
                golfer_df = None
                runner_df = None
                if not args.no_coordinates:
                    golfer_csv = output_dir / "golfer_coordinates.csv"
                    runner_csv = output_dir / "runner_coordinates.csv"
                    if golfer_csv.exists():
                        try:
                            golfer_df = pd.read_csv(golfer_csv)
                        except Exception as e:
                            logger.warning(f"Failed to read golfer coordinates: {e}")
                    if runner_csv.exists():
                        try:
                            runner_df = pd.read_csv(runner_csv)
                        except Exception as e:
                            logger.warning(f"Failed to read runner coordinates: {e}")
                
                # Load cart graph if available
                cart_graph = None
                cart_graph_pkl = Path(args.course_dir) / "pkl" / "cart_graph.pkl"
                if cart_graph_pkl.exists():
                    try:
                        import pickle
                        with cart_graph_pkl.open("rb") as f:
                            cart_graph = pickle.load(f)
                    except Exception as e:
                        logger.warning(f"Failed to load cart graph: {e}")
                
                output_file = output_dir / "delivery_route_visualization.png"
                debug_coords_file = output_dir / "visualization_debug_coords.csv"
                render_delivery_plot(
                    results=results,
                    course_data=course_data,
                    clubhouse_coords=clubhouse_coords,
                    golfer_coords=golfer_df,
                    runner_coords=runner_df,
                    cart_graph=cart_graph,
                    save_path=output_file,
                    course_name=Path(args.course_dir).name.replace("_", " ").title(),
                    style="simple",
                    save_debug_coords_path=debug_coords_file
                )
                logger.info("Delivery visualization created successfully.")
                    
            except Exception as e:
                logger.error(f"Error creating visualization: {e}")
                import traceback
                traceback.print_exc()
        
        return 0
        
    except Exception as e:
        if not handle_simulation_error(e, exit_on_first=True):
            return 1
        return 1


if __name__ == "__main__":
    exit(main())
