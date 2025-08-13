#!/usr/bin/env python3
"""
Single Golfer Delivery Simulation Runner

Thin CLI that delegates to golfsim.simulation.engine.run_golf_delivery_simulation.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Dict

import pandas as pd

from golfsim.simulation.engine import run_golf_delivery_simulation
from golfsim.io.results import save_results_bundle
from golfsim.viz.matplotlib_viz import render_delivery_plot, load_course_geospatial_data
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
    pickup_delay_s = results.get('pickup_delay_s', 0)
    pickup_ready_s = results.get('pickup_ready_s', 0)
    
    # Calculate derived times
    prep_duration = prep_completed_s - order_created_s
    delivery_duration = delivered_s - prep_completed_s
    return_duration = runner_returned_s - delivered_s
    total_service_time = results.get('total_service_time_s', 0)
    pickup_delay_min = pickup_delay_s / 60.0 if pickup_delay_s else 0.0
    
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
        ("Runner Available After Delay", pickup_ready_s, f"Runner becomes available after {pickup_delay_min:.1f} min delay"),
        ("Delivery Started", prep_completed_s, "Runner departs from clubhouse"),
        ("Order Delivered", delivered_s, "Customer receives their order"),
        ("Runner Returned", runner_returned_s, "Runner arrives back at clubhouse"),
    ]
    
    for event_name, timestamp, description in events:
        if timestamp > 0:
            time_str = format_time_from_seconds(timestamp)
            round_time = format_time_from_round_start(timestamp)
            lines.append(f"**{time_str}** ({round_time}) - {event_name}")
            lines.append(f"  {description}")
            lines.append("")
    
    # Add duration breakdown
    lines.extend([
        "## Duration Breakdown",
        "",
        f"- **Food Preparation**: {format_time_from_seconds(prep_duration)}",
        f"- **Pickup Delay**: {format_time_from_seconds(pickup_delay_s)}",
        f"- **Delivery Time**: {format_time_from_seconds(delivery_duration)}",
        f"- **Return Time**: {format_time_from_seconds(return_duration)}",
        f"- **Total Service**: {format_time_from_seconds(total_service_time)}",
        "",
    ])
    
    # Add delivery location details if available
    predicted_location = results.get('predicted_delivery_location')
    if predicted_location:
        lines.extend([
            "## Delivery Location",
            "",
            f"- **Predicted**: {predicted_location[1]:.6f}, {predicted_location[0]:.6f}",
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
    parser.add_argument("--no-enhanced", action="store_true",
                       help="Don't use enhanced cart network (use original)")
    parser.add_argument("--no-coordinates", action="store_true",
                       help="Disable detailed GPS coordinate tracking (enabled by default for better visualization)")
    parser.add_argument("--output-dir", default=None,
                       help="Output directory (default: outputs/simulation_TIMESTAMP)")
    parser.add_argument("--no-visualization", action="store_true",
                       help="Skip creating delivery route visualization")
    parser.add_argument("--pickup-delay-min", type=int, default=0,
                       help="Minutes the delivery runner is unavailable before pickup (default: 0)")
    
    args = parser.parse_args()
    init_logging(args.log_level)
    
    # Create output directory
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path(f"outputs/simulation_{timestamp}")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info("Golf Course Delivery Simulation")
    logger.info(f"Course: {args.course_dir}")
    logger.info(f"Order hole: {args.hole if args.hole else 'Random'}")
    logger.info(f"Prep time: {args.prep_time} minutes")
    logger.info(f"Runner speed: {args.runner_speed} m/s")
    logger.info(f"Enhanced routing: {'No' if args.no_enhanced else 'Yes'}")
    logger.info(f"Pickup delay: {args.pickup_delay_min} minutes")
    logger.info(f"Output: {output_dir}")
    
    try:
        # Run simulation
        results = run_golf_delivery_simulation(
            course_dir=args.course_dir,
            order_hole=args.hole,
            prep_time_min=args.prep_time,
            runner_speed_mps=args.runner_speed,
            use_enhanced_network=not args.no_enhanced,
            track_coordinates=not args.no_coordinates,
            pickup_delay_min=args.pickup_delay_min,
        )
        
        # Save results using library function
        save_results_bundle(results, output_dir)
        
        # Log results using shared utility
        log_simulation_results(results, track_coords=not args.no_coordinates)
        
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
                render_delivery_plot(
                    results=results,
                    course_data=course_data,
                    clubhouse_coords=clubhouse_coords,
                    golfer_coords=golfer_df,
                    runner_coords=runner_df,
                    cart_graph=cart_graph,
                    save_path=output_file,
                    course_name=Path(args.course_dir).name.replace("_", " ").title(),
                    style="simple"
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
