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

from golfsim.simulation.engine import run_golf_delivery_simulation
from golfsim.io.results import save_results_bundle, find_actual_delivery_location
from golfsim.viz.matplotlib_viz import render_delivery_plot, load_course_geospatial_data
from golfsim.logging import init_logging, get_logger
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))
from utils import setup_encoding, add_log_level_argument, add_course_dir_argument

logger = get_logger(__name__)


def main() -> int:
    """Main function with CLI interface."""
    setup_encoding()
    
    parser = argparse.ArgumentParser(
        description="Golf course delivery simulation with enhanced cart path routing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Order placed on hole 14 (late in round - shows smart prediction)
  python run_single_golfer_simulation.py --hole 14

  # Order placed on hole 16 (where we found the shortcut!)
  python run_single_golfer_simulation.py --hole 16

  # Random order placement during round
  python run_single_golfer_simulation.py
  
  # Order on hole 8 with 15-minute prep time
  python run_single_golfer_simulation.py --hole 8 --prep-time 15
        """
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
    parser.add_argument("--save-coordinates", action="store_true",
                       help="Save detailed GPS coordinate tracking (disabled by default for performance)")
    parser.add_argument("--output-dir", default=None,
                       help="Output directory (default: outputs/simulation_TIMESTAMP)")
    parser.add_argument("--no-visualization", action="store_true",
                       help="Skip creating delivery route visualization")
    
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
    logger.info(f"Output: {output_dir}")
    
    try:
        # Run simulation
        results = run_golf_delivery_simulation(
            course_dir=args.course_dir,
            order_hole=args.hole,
            prep_time_min=args.prep_time,
            runner_speed_mps=args.runner_speed,
            use_enhanced_network=not args.no_enhanced,
            track_coordinates=args.save_coordinates
        )
        
        # Save results using library function
        save_results_bundle(results, output_dir)
        
        # Print comprehensive summary
        logger.info("Simulation Results:")
        logger.info(f"   Order time: {results['order_time_s']/60:.1f} minutes into round")
        logger.info(f"   Service time: {results['total_service_time_s']/60:.1f} minutes")
        logger.info(f"   Delivery distance: {results['delivery_distance_m']:.0f} meters")
        logger.info(f"   Preparation time: {results['prep_time_s']/60:.1f} minutes")
        logger.info(f"   Travel time: {results['delivery_travel_time_s']/60:.1f} minutes")
        
        # Show route efficiency if available
        trip_to_golfer = results.get('trip_to_golfer', {})
        if 'efficiency' in trip_to_golfer:
            logger.info(f"   Route efficiency: {trip_to_golfer['efficiency']:.1f}% vs straight line")
        
        # Show actual delivery location if coordinates were tracked
        if args.save_coordinates:
            delivery_location = find_actual_delivery_location(results)
            if delivery_location:
                logger.info(f"   Actual delivery location: Hole {delivery_location['hole']} at {delivery_location['latitude']:.6f}, {delivery_location['longitude']:.6f}")
        
        if results.get('prediction_method'):
            logger.info(f"   Prediction method: {results['prediction_method']}")
        
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
                
                output_file = output_dir / "delivery_route_visualization.png"
                render_delivery_plot(results, course_data, clubhouse_coords, output_file)
                logger.info("Delivery visualization created successfully.")
                    
            except Exception as e:
                logger.error(f"Error creating visualization: {e}")
                import traceback
                traceback.print_exc()
        
        return 0
        
    except FileNotFoundError as e:
        logger.error(f"Data file not found: {e}")
        logger.error(f"Make sure the course directory exists and contains required data files")
        return 1
    except Exception as e:
        logger.error(f"Simulation error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
