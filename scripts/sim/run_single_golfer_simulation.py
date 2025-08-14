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


def create_delivery_log(results: Dict, save_path: Path) -> None:
    """
    Create a detailed delivery person log with timestamps for all key events.
    
    Args:
        results: Simulation results dictionary
        save_path: Path where to save the delivery log
    """
    # Extract key timestamps
    order_time_s = results.get('order_time_s', 0)
    order_created_s = results.get('order_created_s', order_time_s)
    prep_completed_s = results.get('prep_completed_s', 0)
    delivered_s = results.get('delivered_s', 0)
    runner_returned_s = results.get('runner_returned_s', 0)
    runner_busy_delay_s = results.get('runner_busy_delay_s', 0.0)
    
    # Calculate actual departure time (prep complete + delay)
    runner_departed_s = prep_completed_s + runner_busy_delay_s
    
    # Calculate derived times
    prep_duration = prep_completed_s - order_created_s
    delay_duration = runner_busy_delay_s
    delivery_duration = delivered_s - runner_departed_s  # Time from departure to delivery
    return_duration = runner_returned_s - delivered_s
    total_service_time = results.get('total_service_time_s', 0)
    
    # Get delivery details
    order_hole = results.get('order_hole', 'Unknown')
    delivery_distance = results.get('delivery_distance_m', 0)
    prediction_method = results.get('prediction_method', 'Unknown')
    
    # Create the log content
    lines = [
        "# Delivery Log",
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
    ]
    
    # Add delay event if there was a delay
    if runner_busy_delay_s > 0:
        events.append(("Runner Available", runner_departed_s, f"Runner becomes available after {delay_duration/60:.0f} minute delay"))
        events.append(("Delivery Started", runner_departed_s, "Runner departs from clubhouse"))
    else:
        events.append(("Delivery Started", prep_completed_s, "Runner departs from clubhouse"))
    
    events.extend([
        ("Order Delivered", delivered_s, "Customer receives their order"),
        ("Runner Returned", runner_returned_s, "Runner arrives back at clubhouse"),
    ])
    
    for event_name, timestamp, description in events:
        if timestamp > 0:
            time_str = format_time_from_seconds(timestamp)
            round_time = format_time_from_round_start(timestamp)
            lines.append(f"**{time_str}** ({round_time}) - {event_name}")
            lines.append(f"  {description}")
            lines.append("")
    
    # Add duration breakdown
    duration_lines = [
        "## Duration Breakdown",
        "",
        f"- **Food Preparation**: {format_time_from_seconds(prep_duration)}",
    ]
    
    # Add delay information if there was a delay
    if runner_busy_delay_s > 0:
        duration_lines.append(f"- **Runner Delay**: {format_time_from_seconds(delay_duration)} (runner was busy)")
    
    duration_lines.extend([
        f"- **Delivery Time**: {format_time_from_seconds(delivery_duration)} (travel time only)",
        f"- **Return Time**: {format_time_from_seconds(return_duration)}",
        f"- **Total Service**: {format_time_from_seconds(total_service_time)}",
        "",
    ])
    
    lines.extend(duration_lines)
    
    # Add delivery location details if available
    predicted_location = results.get('predicted_delivery_location')
    if predicted_location:
        lines.extend([
            "## Delivery Location",
            "",
            f"- **Predicted**: {predicted_location[1]:.6f}, {predicted_location[0]:.6f}",
        ])
    # Append actual delivery location if coordinates were tracked
    from golfsim.io.results import find_actual_delivery_location
    actual_loc = find_actual_delivery_location(results)
    if actual_loc:
        hole = actual_loc.get('hole')
        coord_line = f"- **Actual**: {actual_loc['latitude']:.6f}, {actual_loc['longitude']:.6f}"
        if hole:
            coord_line += f" (Hole {hole})"
        lines.extend([
            coord_line,
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
    parser.add_argument("--runner-speed", type=float, default=6.0,
                       help="Runner speed in m/s (default: 6.0)")
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
    logger.info(f"Runner speed: {args.runner_speed} m/s")
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
