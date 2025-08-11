#!/usr/bin/env python3
"""
Simplified Golf Course Delivery Simulation Runner

This script provides a clean interface to run golf delivery simulations
using the enhanced cart path network for optimal routing.

Usage Examples:
    # Run simulation with order on specific hole
    python run_simulation.py --hole 16
    
    # Run simulation with random order placement
    python run_simulation.py
    
    # Run with different prep time
    python run_simulation.py --prep-time 15 --hole 8
"""
import argparse
import json
import subprocess
import sys
import os
from datetime import datetime
from pathlib import Path

from golfsim.io.results import SimulationResult, save_results_bundle
from golfsim.logging import init_logging, get_logger
from utils.encoding import setup_encoding
from utils.cli import add_log_level_argument

setup_encoding()

from golfsim.simulation.engine import run_golf_delivery_simulation

logger = get_logger(__name__)


def find_actual_delivery_location(results):
    """Find the actual location where delivery occurred based on runner coordinates."""
    runner_coords = results.get('runner_coordinates', [])
    delivered_time = results.get('delivered_s', 0)
    
    if not runner_coords or not delivered_time:
        return None
    
    # Find the runner coordinate closest to delivery time
    closest_coord = None
    closest_time_diff = float('inf')
    
    for coord in runner_coords:
        time_diff = abs(coord.get('timestamp', 0) - delivered_time)
        if time_diff < closest_time_diff:
            closest_time_diff = time_diff
            closest_coord = coord
    
    if closest_coord:
        return (closest_coord['longitude'], closest_coord['latitude'])
    
    # Fallback to predicted delivery location
    return results.get('predicted_delivery_location')


def create_delivery_visualization(results, output_dir, args):
    """Create a delivery visualization showing all simulation elements."""
    import matplotlib.pyplot as plt
    import matplotlib.patches as patches
    import numpy as np
    from pathlib import Path
    import json
    import pickle
    
    # Load course data
    course_dir = Path(args.course_dir)
    
    # Load cart graph for network visualization
    cart_graph_path = course_dir / "pkl" / "cart_graph.pkl"
    if cart_graph_path.exists():
        with open(cart_graph_path, 'rb') as f:
            cart_graph = pickle.load(f)
    else:
        logger.warning("Cart graph not found, creating simplified visualization")
        cart_graph = None
    
    # Load configuration for clubhouse location
    config_path = course_dir / "config" / "simulation_config.json"
    with open(config_path, 'r') as f:
        config = json.load(f)
    clubhouse_coords = (config["clubhouse"]["longitude"], config["clubhouse"]["latitude"])
    
    # Create the visualization
    fig, ax = plt.subplots(1, 1, figsize=(20, 16))
    
    # Plot cart path network as background
    if cart_graph:
        logger.info("Drawing cart path network...")
        for u, v in list(cart_graph.edges())[:1000]:  # Limit edges for performance
            u_data = cart_graph.nodes[u]
            v_data = cart_graph.nodes[v]
            if 'x' in u_data and 'y' in u_data and 'x' in v_data and 'y' in v_data:
                ax.plot([u_data['x'], v_data['x']], [u_data['y'], v_data['y']], 
                       'lightgray', linewidth=0.5, alpha=0.3, zorder=1)
    
    # Plot golfer path
    golfer_coords = results.get('golfer_coordinates', [])
    if golfer_coords:
        logger.info("Drawing golfer path...")
        golfer_lons = [coord['longitude'] for coord in golfer_coords]
        golfer_lats = [coord['latitude'] for coord in golfer_coords]
        
        # Plot full golfer path
        ax.plot(golfer_lons, golfer_lats, 'blue', linewidth=3, alpha=0.7, 
               label='Golfer Path (18 holes)', zorder=3)
        
        # Mark start (tee 1) and end (hole 18)
        if len(golfer_coords) > 0:
            ax.scatter([golfer_lons[0]], [golfer_lats[0]], c='green', s=200, 
                      marker='^', edgecolors='darkgreen', linewidth=2, 
                      label='Round Start (Hole 1)', zorder=6)
            ax.scatter([golfer_lons[-1]], [golfer_lats[-1]], c='red', s=200, 
                      marker='v', edgecolors='darkred', linewidth=2, 
                      label='Round End (Hole 18)', zorder=6)
    
    # Plot delivery runner path
    runner_coords = results.get('runner_coordinates', [])
    if runner_coords:
        logger.info("Drawing delivery runner path...")
        runner_lons = [coord['longitude'] for coord in runner_coords]
        runner_lats = [coord['latitude'] for coord in runner_coords]
        
        # Plot runner path with gradient color (start orange, end purple)
        for i in range(len(runner_lons) - 1):
            progress = i / max(len(runner_lons) - 1, 1)
            color = plt.cm.plasma(progress)  # Orange to purple gradient
            ax.plot([runner_lons[i], runner_lons[i+1]], [runner_lats[i], runner_lats[i+1]], 
                   color=color, linewidth=4, alpha=0.8, zorder=4)
        
        # Add arrow to show direction
        if len(runner_coords) > 1:
            mid_idx = len(runner_coords) // 2
            if mid_idx < len(runner_coords) - 1:
                dx = runner_lons[mid_idx + 1] - runner_lons[mid_idx]
                dy = runner_lats[mid_idx + 1] - runner_lats[mid_idx]
                ax.annotate('', xy=(runner_lons[mid_idx + 1], runner_lats[mid_idx + 1]),
                           xytext=(runner_lons[mid_idx], runner_lats[mid_idx]),
                           arrowprops=dict(arrowstyle='->', color='purple', lw=3),
                           zorder=5)
    
    # Mark clubhouse
    ax.scatter([clubhouse_coords[0]], [clubhouse_coords[1]], c='brown', s=400, 
              marker='s', edgecolors='black', linewidth=3, 
              label='Clubhouse (Food Prep)', zorder=7)
    
    # Mark order placement location
    order_location = results.get('golfer_position')
    if order_location:
        ax.scatter([order_location[0]], [order_location[1]], c='yellow', s=300, 
                  marker='*', edgecolors='orange', linewidth=2, 
                  label=f'Order Placed (Hole {results.get("order_hole", "?")})', zorder=8)
    
    # Mark delivery location (if different from order location)
    delivery_location = results.get('predicted_delivery_location')
    if delivery_location and delivery_location != order_location:
        ax.scatter([delivery_location[0]], [delivery_location[1]], c='lime', s=300, 
                  marker='D', edgecolors='darkgreen', linewidth=2, 
                  label='Delivery Location (Predicted)', zorder=8)
        
        # Draw line connecting order and delivery locations
        if order_location:
            ax.plot([order_location[0], delivery_location[0]], 
                   [order_location[1], delivery_location[1]], 
                   'red', linewidth=2, linestyle='--', alpha=0.7,
                   label='Golfer Movement During Delivery', zorder=3)
    
    # Find and mark the actual delivery node where runner stopped
    actual_delivery_location = find_actual_delivery_location(results)
    if actual_delivery_location:
        ax.scatter([actual_delivery_location[0]], [actual_delivery_location[1]], c='red', s=400, 
                  marker='X', edgecolors='darkred', linewidth=3, 
                  label='Actual Delivery Point', zorder=9)
        
        # Add connection line if different from predicted
        if delivery_location and actual_delivery_location != delivery_location:
            distance_difference = ((actual_delivery_location[0] - delivery_location[0])**2 + 
                                 (actual_delivery_location[1] - delivery_location[1])**2)**0.5 * 111139
            if distance_difference > 10:  # Only show if more than 10m difference
                ax.plot([delivery_location[0], actual_delivery_location[0]], 
                       [delivery_location[1], actual_delivery_location[1]], 
                       'red', linewidth=3, linestyle=':', alpha=0.8,
                       label=f'Prediction Accuracy ({distance_difference:.0f}m)', zorder=3)
    
    # Add annotations for key locations
    if order_location:
        ax.annotate(f'ORDER\n(Hole {results.get("order_hole", "?")})', 
                   order_location, xytext=(10, 10), 
                   textcoords='offset points', fontsize=11, ha='left', va='bottom',
                   bbox=dict(boxstyle='round,pad=0.3', facecolor='yellow', alpha=0.8),
                   weight='bold', zorder=9)
    
    if delivery_location and delivery_location != order_location:
        ax.annotate('DELIVERY\n(Predicted)', 
                   delivery_location, xytext=(10, -25), 
                   textcoords='offset points', fontsize=11, ha='left', va='top',
                   bbox=dict(boxstyle='round,pad=0.3', facecolor='lime', alpha=0.8),
                   weight='bold', zorder=9)
    
    # Add annotation for actual delivery location
    actual_delivery_location = find_actual_delivery_location(results)
    if actual_delivery_location:
        ax.annotate(f'ACTUAL\nDELIVERY', 
                   actual_delivery_location, xytext=(-15, 10), 
                   textcoords='offset points', fontsize=11, ha='right', va='bottom',
                   bbox=dict(boxstyle='round,pad=0.3', facecolor='red', alpha=0.8),
                   weight='bold', color='white', zorder=10)
    
    ax.annotate('CLUBHOUSE\n(Food Prep)', 
               clubhouse_coords, xytext=(15, 15), 
               textcoords='offset points', fontsize=12, ha='left', va='bottom',
               bbox=dict(boxstyle='round,pad=0.4', facecolor='brown', alpha=0.8),
               color='white', weight='bold', zorder=9)
    
    # Set plot properties
    hole_num = results.get('order_hole', 'Random')
    efficiency = results.get('trip_to_golfer', {}).get('efficiency', 0)
    service_time = results.get('total_service_time_s', 0) / 60
    
    ax.set_title(f'Golf Delivery Simulation - Order on Hole {hole_num}\n' +
                f'Service Time: {service_time:.1f} min | Route Efficiency: {efficiency:.1f}% | ' +
                f'Distance: {results.get("delivery_distance_m", 0):.0f}m', 
                fontsize=16, weight='bold', pad=20)
    
    ax.set_xlabel('Longitude', fontsize=14)
    ax.set_ylabel('Latitude', fontsize=14)
    ax.set_aspect('equal')
    ax.grid(True, linestyle='--', alpha=0.3)
    ax.legend(loc='best', fontsize=11, framealpha=0.9)
    
    # Add comprehensive info box
    info_text = f"""Simulation Details:
• Order Time: {results.get('order_time_s', 0)/60:.1f} min into round
• Prep Time: {results.get('prep_time_s', 0)/60:.1f} min
• Travel Time: {results.get('delivery_travel_time_s', 0)/60:.1f} min
• Total Service: {service_time:.1f} min
• Route Type: {results.get('trip_to_golfer', {}).get('routing_type', 'standard')}
• Prediction Method: {results.get('prediction_method', 'standard')}"""
    
    # Add prediction accuracy information
    actual_delivery_location = find_actual_delivery_location(results)
    delivery_location = results.get('predicted_delivery_location')
    if actual_delivery_location and delivery_location:
        distance_difference = ((actual_delivery_location[0] - delivery_location[0])**2 + 
                             (actual_delivery_location[1] - delivery_location[1])**2)**0.5 * 111139
        info_text += f"\n• Prediction Accuracy: {distance_difference:.1f}m error"
    
    if results.get('distance_savings_m', 0) > 0:
        info_text += f"\n• Distance Saved: {results['distance_savings_m']:.0f}m ({results.get('distance_savings_percent', 0):.1f}%)"
        info_text += f"\n• Time Saved: {results['time_savings_s']:.0f}s ({results.get('time_savings_percent', 0):.1f}%)"
    
    ax.text(0.02, 0.98, info_text, transform=ax.transAxes, 
            verticalalignment='top', fontsize=11,
            bbox=dict(boxstyle='round,pad=0.5', facecolor='white', alpha=0.95, edgecolor='gray'))
    
    # Save the visualization
    output_file = output_dir / "delivery_simulation.png"
    plt.savefig(output_file, bbox_inches='tight', facecolor='white', dpi=300)
    plt.close()
    
    logger.info(f"Delivery visualization saved: {output_file}")
    
    return output_file


def main():
    parser = argparse.ArgumentParser(
        description="Golf course delivery simulation with enhanced cart path routing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Order placed on hole 14 (late in round - shows smart prediction)
  python run_simulation.py --hole 14

  # Order placed on hole 16 (where we found the shortcut!)
  python run_simulation.py --hole 16

  # Random order placement during round
  python run_simulation.py
  
  # Order on hole 8 with 15-minute prep time
  python run_simulation.py --hole 8 --prep-time 15
  
  # Order on hole 14 with fast runner and longer prep time
  python run_simulation.py --hole 14 --prep-time 12 --runner-speed 7.0
  
  # Order on hole 6 with detailed GPS coordinate tracking enabled
  python run_simulation.py --hole 6 --save-coordinates
        """
    )
    from utils.cli import add_log_level_argument
    add_log_level_argument(parser)
    
    parser.add_argument("--course-dir", default="courses/pinetree_country_club",
                       help="Course directory containing data files (default: courses/pinetree_country_club)")
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
                          help="Disable automatic PNG visualization generation")
    
    args = parser.parse_args()
    from golfsim.logging import init_logging
    init_logging(args.log_level)
    
    # Setup output directory
    if args.output_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        args.output_dir = f"outputs/simulation_{timestamp}"
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    from golfsim.logging import get_logger
    logger = get_logger(__name__)
    logger.info("Golf Course Delivery Simulation")
    logger.info("=" * 40)
    logger.info(f"Course: {args.course_dir}")
    logger.info(f"Output: {output_dir}")
    if args.hole:
        print(f"Order placement: Hole {args.hole}")
    else:
        logger.info("Order placement: Random during round")
    logger.info(f"Prep time: {args.prep_time} minutes")
    logger.info(f"Runner speed: {args.runner_speed} m/s")
    logger.info(f"Enhanced network: {'No' if args.no_enhanced else 'Yes'}")
    
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
        
        # Save results using standardized I/O
        simulation_result = SimulationResult(
            metadata={
                "simulation_type": "single_golfer",
                "course": str(course_dir),
                "timestamp": datetime.now().isoformat(),
                "config": {
                    "hole": args.hole,
                    "prep_time": args.prep_time,
                    "runner_speed": args.runner_speed,
                    "enhanced_network": not args.no_enhanced,
                    "track_coordinates": args.save_coordinates
                }
            },
            delivery_metrics=results.get('delivery_metrics', {}),
            golfer_coordinates=results.get('golfer_coordinates', []),
            runner_coordinates=results.get('runner_coordinates', []),
            route_data=results.get('route_data', {}),
            timing_data=results.get('timing_data', {}),
            additional_data={k: v for k, v in results.items() 
                           if k not in ['delivery_metrics', 'golfer_coordinates', 'runner_coordinates', 'route_data', 'timing_data']}
        )
        
        save_results_bundle(simulation_result, output_dir)
        logger.info(f"Saved results bundle to: {output_dir}")
        
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
            efficiency = trip_to_golfer['efficiency']
            if efficiency >= 80:
                efficiency_grade = "EXCELLENT"
            elif efficiency >= 60:
                efficiency_grade = "GOOD"
            elif efficiency >= 40:
                efficiency_grade = "FAIR"
            else:
                efficiency_grade = "POOR"
            logger.info(f"   Route efficiency: {efficiency:.1f}% {efficiency_grade}")
            logger.info(f"   Routing type: {trip_to_golfer.get('routing_type', 'standard')}")
        
        if args.hole:
            logger.info(f"Hole {args.hole} Order:")
            if 'order_hole' in results:
                logger.info(f"   Order placed on hole: {results['order_hole']}")
            order_pos = results.get('golfer_position', (None, None))
            if order_pos[0]:
                logger.info(f"   Order location: ({order_pos[0]:.6f}, {order_pos[1]:.6f})")
            
            pred_pos = results.get('predicted_delivery_location', (None, None))
            if pred_pos[0] and pred_pos != order_pos:
                logger.info(f"   Delivery location: ({pred_pos[0]:.6f}, {pred_pos[1]:.6f})")
                logger.info("   Smart prediction: Delivered to predicted position")
        
        # Show enhanced network benefits
        if not args.no_enhanced:
            logger.info("Enhanced Network Benefits:")
            logger.info("   Optimal cart path routing used")
            logger.info("   Automatic shortcut detection")
            logger.info("   Smart golfer position prediction")
            if 'distance_savings_m' in results and results['distance_savings_m'] > 0:
                logger.info(f"   Distance saved: {results['distance_savings_m']:.0f}m ({results.get('distance_savings_percent', 0):.1f}%)")
                logger.info(f"   Time saved: {results['time_savings_s']:.0f}s ({results.get('time_savings_percent', 0):.1f}%)")
        
        logger.info(f"All results saved to: {output_dir.absolute()}")
        
        # Automatically generate delivery visualization unless disabled
        if not args.no_visualization:
            logger.info("Creating delivery visualization...")
            try:
                # Create visualization with all simulation elements
                create_delivery_visualization(results, output_dir, args)
                logger.info("   Delivery visualization created successfully.")
                    
            except Exception as e:
                logger.error(f"   Error creating visualization: {e}")
                import traceback
                traceback.print_exc()
        
        return 0
        
    except FileNotFoundError as e:
        logger.error(f"Data file not found: {e}")
        logger.error("Make sure the course directory exists and contains required data files")
        return 1
    except Exception as e:
        logger.error(f"Simulation error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit(main())
