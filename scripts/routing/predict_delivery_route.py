#!/usr/bin/env python3
"""
Enhanced Delivery Path Prediction using Travel Times and Food Prep Time

This script demonstrates sophisticated delivery prediction for golf course runners
using the travel_times.json data to optimize delivery paths based on:
1. Food preparation time
2. Current golfer position and movement patterns  
3. Hole-to-hole travel times from the travel_times.json data
4. Predicted golfer location at delivery time

Usage:
    python scripts/predict_delivery_path.py --hole 8 --prep-time 10
    python scripts/predict_delivery_path.py --hole 16 --prep-time 15
"""

import argparse
import json
import math
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime

from golfsim.logging import init_logging, get_logger
from utils.cli import add_log_level_argument

logger = get_logger(__name__)

def load_travel_times(course_dir: str) -> Dict:
    """Load travel times data from JSON file."""
    travel_times_path = Path(course_dir) / "travel_times.json"
    with open(travel_times_path, 'r') as f:
        return json.load(f)

def predict_golfer_movement_pattern(
    current_hole: int,
    travel_times_data: Dict,
    golfer_pace_factor: float = 1.0
) -> Dict[int, float]:
    """
    Predict when golfer will be at each hole based on travel times and pace.
    
    Args:
        current_hole: Current hole the golfer is on
        travel_times_data: Travel times data from travel_times.json
        golfer_pace_factor: Multiplier for golfer speed (1.0 = average, 0.8 = slow, 1.2 = fast)
        
    Returns:
        Dictionary mapping hole numbers to predicted arrival times (minutes from now)
    """
    holes_data = travel_times_data.get("holes", [])
    
    # Standard time estimates for playing each hole
    hole_play_times = {
        "3": 8,   # Par 3: 8 minutes
        "4": 12,  # Par 4: 12 minutes  
        "5": 16   # Par 5: 16 minutes
    }
    
    predicted_times = {}
    cumulative_time = 0
    
    for hole_info in holes_data:
        hole_num = hole_info["hole"]
        par = str(hole_info["par"])
        
        if hole_num < current_hole:
            continue
            
        if hole_num == current_hole:
            # Assume golfer is halfway through current hole
            play_time = hole_play_times.get(par, 12) * 0.5
        else:
            play_time = hole_play_times.get(par, 12)
            
        # Add travel time between holes (from cart path data)
        travel_time = hole_info["travel_time_min"]
        
        # Apply pace factor
        total_time = (play_time + travel_time) * golfer_pace_factor
        
        cumulative_time += total_time
        predicted_times[hole_num] = cumulative_time
        
    return predicted_times

def find_optimal_delivery_spot(
    order_hole: int,
    prep_time_min: float,
    travel_times_data: Dict,
    runner_speed_mps: float = 6.0,
    golfer_pace_factor: float = 1.0
) -> Dict:
    """
    Find the optimal delivery spot considering prep time and golfer movement.
    
    Args:
        order_hole: Hole where order was placed
        prep_time_min: Food preparation time in minutes
        travel_times_data: Travel times data
        runner_speed_mps: Runner speed in m/s
        golfer_pace_factor: Golfer pace multiplier
        
    Returns:
        Dictionary with optimal delivery strategy
    """
    
    # Get golfer movement predictions
    golfer_predictions = predict_golfer_movement_pattern(
        order_hole, travel_times_data, golfer_pace_factor
    )
    
    # Calculate when runner can start delivery (after prep time)
    delivery_start_time = prep_time_min
    
    clubhouse_coords = travel_times_data["clubhouse_coords"]
    holes_data = {h["hole"]: h for h in travel_times_data["holes"]}
    
    # Evaluate delivery options for different holes
    delivery_options = []
    
    for target_hole, golfer_arrival_time in golfer_predictions.items():
        if target_hole < order_hole:  # Don't deliver to holes golfer has passed
            continue
            
        hole_data = holes_data.get(target_hole)
        if not hole_data:
            continue
            
        # Calculate runner travel time to this hole
        hole_distance_m = hole_data["distance_m"]
        runner_travel_time_min = (hole_distance_m / runner_speed_mps) / 60
        
        # Calculate when runner would arrive at this hole
        runner_arrival_time = delivery_start_time + runner_travel_time_min
        
        # Calculate delivery timing efficiency
        if runner_arrival_time <= golfer_arrival_time:
            # Runner arrives before golfer - golfer has to wait
            wait_time = golfer_arrival_time - runner_arrival_time
            efficiency_score = 100 - (wait_time * 5)  # Penalty for golfer waiting
            delivery_scenario = "runner_waits_for_golfer"
        else:
            # Runner arrives after golfer starts hole - need to catch up
            catch_up_time = runner_arrival_time - golfer_arrival_time
            efficiency_score = 100 - (catch_up_time * 10)  # Higher penalty for delayed delivery
            delivery_scenario = "runner_catches_up"
            
        # Bonus for delivering to the same hole where order was placed
        if target_hole == order_hole:
            efficiency_score += 20
            
        # Bonus for nearby holes (easier to find golfer)
        hole_distance_bonus = max(0, 10 - abs(target_hole - order_hole))
        efficiency_score += hole_distance_bonus
        
        delivery_options.append({
            "target_hole": target_hole,
            "hole_par": hole_data["par"],
            "distance_from_clubhouse_m": hole_distance_m,
            "runner_travel_time_min": runner_travel_time_min,
            "runner_arrival_time_min": runner_arrival_time,
            "golfer_arrival_time_min": golfer_arrival_time,
            "timing_difference_min": abs(runner_arrival_time - golfer_arrival_time),
            "efficiency_score": efficiency_score,
            "delivery_scenario": delivery_scenario,
            "recommendation_reason": f"Hole {target_hole} (Par {hole_data['par']})"
        })
    
    # Sort by efficiency score (best first)
    delivery_options.sort(key=lambda x: x["efficiency_score"], reverse=True)
    
    best_option = delivery_options[0] if delivery_options else None
    
    return {
        "order_details": {
            "order_hole": order_hole,
            "prep_time_min": prep_time_min,
            "golfer_pace_factor": golfer_pace_factor
        },
        "optimal_delivery": best_option,
        "all_delivery_options": delivery_options[:5],  # Top 5 options
        "travel_times_source": travel_times_data.get("course_name", "Unknown Course"),
        "clubhouse_coords": clubhouse_coords,
        "cart_speed_mph": travel_times_data.get("cart_speed_mph", "Unknown")
    }

def create_delivery_summary(prediction_result: Dict) -> str:
    """Create a human-readable summary of the delivery prediction."""
    
    optimal = prediction_result["optimal_delivery"]
    order_details = prediction_result["order_details"]
    
    if not optimal:
        return "No viable delivery options found"
    
    summary = []
    summary.append("🚀 OPTIMAL DELIVERY PREDICTION")
    summary.append("=" * 50)
    summary.append(f"📋 Order placed on: Hole {order_details['order_hole']}")
    summary.append(f"Food prep time: {order_details['prep_time_min']} minutes")
    summary.append(f" Golfer pace: {order_details['golfer_pace_factor']:.1f}x normal")
    summary.append("")
    
    summary.append("RECOMMENDED DELIVERY STRATEGY:")
    summary.append(f"   Target hole: {optimal['target_hole']} (Par {optimal['hole_par']})")
    summary.append(f"   Distance from clubhouse: {optimal['distance_from_clubhouse_m']:.0f}m")
    summary.append(f"   Runner travel time: {optimal['runner_travel_time_min']:.1f} minutes")
    summary.append(f"   Efficiency score: {optimal['efficiency_score']:.0f}/100")
    summary.append("")
    
    summary.append("⏰ TIMING ANALYSIS:")
    summary.append(f"   Runner arrives at: {optimal['runner_arrival_time_min']:.1f} min after order")
    summary.append(f"   Golfer arrives at: {optimal['golfer_arrival_time_min']:.1f} min after order")
    summary.append(f"   Timing difference: {optimal['timing_difference_min']:.1f} minutes")
    summary.append(f"   Scenario: {optimal['delivery_scenario'].replace('_', ' ').title()}")
    summary.append("")
    
    if optimal['delivery_scenario'] == "runner_waits_for_golfer":
        summary.append("EXCELLENT: Runner arrives first and can wait for golfer")
    elif optimal['timing_difference_min'] < 2:
        summary.append("GOOD: Well-synchronized delivery timing")
    else:
        summary.append(" SUBOPTIMAL: Consider adjusting strategy or prep time")
    
    summary.append("")
    summary.append("🔄 ALTERNATIVE OPTIONS:")
    for i, option in enumerate(prediction_result["all_delivery_options"][1:4], 2):
        summary.append(f"   {i}. Hole {option['target_hole']}: {option['efficiency_score']:.0f}/100 "
                      f"({option['timing_difference_min']:.1f}min diff)")
    
    return "\n".join(summary)

def main():
    parser = argparse.ArgumentParser(
        description="Predict optimal delivery path using travel times and prep time",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Order on hole 8 with 10-minute prep time
  python scripts/predict_delivery_path.py --hole 8 --prep-time 10
  
  # Order on hole 16 with 15-minute prep time and slow golfer
  python scripts/predict_delivery_path.py --hole 16 --prep-time 15 --golfer-pace 0.8
        """
    )
    
    parser.add_argument("--hole", type=int, required=True, choices=range(1, 19),
                       help="Hole where order was placed (1-18)")
    parser.add_argument("--prep-time", type=float, default=10.0,
                       help="Food preparation time in minutes (default: 10.0)")
    parser.add_argument("--course-dir", default="courses/pinetree_country_club",
                       help="Course directory (default: courses/pinetree_country_club)")
    parser.add_argument("--runner-speed", type=float, default=6.0,
                       help="Runner speed in m/s (default: 6.0)")
    parser.add_argument("--golfer-pace", type=float, default=1.0,
                       help="Golfer pace factor (1.0=normal, 0.8=slow, 1.2=fast)")
    parser.add_argument("--output", help="Save results to JSON file")
    add_log_level_argument(parser)
    
    args = parser.parse_args()
    init_logging(args.log_level)
    
    logger.info("Golf Delivery Path Prediction")
    logger.info("=" * 40)
    logger.info(f"Course: {args.course_dir}")
    logger.info(f"Order hole: {args.hole}")
    logger.info(f"Prep time: {args.prep_time} minutes")
    logger.info(f"Runner speed: {args.runner_speed} m/s")
    logger.info(f"Golfer pace: {args.golfer_pace}x")
    
    try:
        # Load travel times data
        travel_times_data = load_travel_times(args.course_dir)
        logger.info(f"Loaded travel times for {travel_times_data.get('course_name', 'Unknown Course')}")
        logger.info(f"Cart speed: {travel_times_data.get('cart_speed_mph', 'Unknown')} mph")
        
        # Generate delivery prediction
        prediction_result = find_optimal_delivery_spot(
            order_hole=args.hole,
            prep_time_min=args.prep_time,
            travel_times_data=travel_times_data,
            runner_speed_mps=args.runner_speed,
            golfer_pace_factor=args.golfer_pace
        )
        
        # Display results
        summary = create_delivery_summary(prediction_result)
        logger.info(summary)
        
        # Save results if requested
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Add metadata
            prediction_result["metadata"] = {
                "generated_at": datetime.now().isoformat(),
                "command_args": vars(args),
                "source_script": "predict_delivery_path.py"
            }
            
            with open(output_path, 'w') as f:
                json.dump(prediction_result, f, indent=2, default=str)
            logger.info(f"Results saved to: {output_path}")
        
        return 0
        
    except FileNotFoundError as e:
        logger.error(f"Error: {e}")
        logger.error(f"Make sure travel_times.json exists in {args.course_dir}")
        return 1
    except Exception as e:
        logger.error(f"Prediction error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    exit(main())

