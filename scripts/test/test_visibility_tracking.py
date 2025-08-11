#!/usr/bin/env python3
"""
Test script to demonstrate golfer-beverage cart visibility tracking functionality.

This script creates a simple test scenario with one golfer and one beverage cart,
processes their GPS coordinates through the visibility tracking service,
and outputs a CSV with color-coded visibility status.
"""

import sys
from pathlib import Path
import json

# Add golfsim to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from golfsim.simulation.visibility_tracking import create_visibility_service
from golfsim.io.results import write_coordinates_csv_with_visibility
from golfsim.logging import init_logging

def create_test_data():
    """Create test GPS data for demonstration."""
    # Simulate a golfer playing through holes with timestamps every minute
    golfer_points = []
    
    # Starting coordinates (roughly hole 1 tee)
    base_lat, base_lon = 35.7796, -78.6382
    
    # Golfer progresses through course over 4 hours (240 minutes)
    for minute in range(240):
        timestamp_s = 7200 + (minute * 60)  # Start at 9 AM (7200s from 7 AM baseline)
        
        # Simulate movement across course
        lat_offset = (minute / 240.0) * 0.01  # Move north
        lon_offset = (minute / 240.0) * 0.01  # Move east
        
        hole_num = min(18, (minute // 13) + 1)  # ~13 minutes per hole
        
        golfer_points.append({
            "id": "test_golfer_1",
            "latitude": base_lat + lat_offset,
            "longitude": base_lon + lon_offset,
            "timestamp": timestamp_s,
            "type": "golfer",
            "hole": hole_num,
        })
    
    # Simulate beverage cart making rounds (encounters golfer at specific times)
    cart_points = []
    cart_encounters = [
        30,   # 30 minutes in - close encounter
        95,   # 95 minutes in - another encounter  
        180,  # 180 minutes in - final encounter
    ]
    
    for minute in range(240):
        timestamp_s = 7200 + (minute * 60)
        
        # Cart follows different path
        lat_offset = (minute / 240.0) * 0.009  # Slightly different movement
        lon_offset = (minute / 240.0) * 0.011
        
        # Cart gets close to golfer during encounter times
        if any(abs(minute - enc) <= 2 for enc in cart_encounters):
            # Very close to golfer during encounters (within 50m)
            golfer_at_minute = next((p for p in golfer_points if p["timestamp"] == timestamp_s), None)
            if golfer_at_minute:
                cart_points.append({
                    "id": "test_bev_cart_1", 
                    "latitude": golfer_at_minute["latitude"] + 0.0003,  # ~30m offset
                    "longitude": golfer_at_minute["longitude"] + 0.0003,
                    "timestamp": timestamp_s,
                    "type": "bevcart",
                    "hole": golfer_at_minute["hole"],
                })
        else:
            # Cart at normal distance
            cart_points.append({
                "id": "test_bev_cart_1",
                "latitude": base_lat + lat_offset + 0.003,  # Further away
                "longitude": base_lon + lon_offset + 0.003,
                "timestamp": timestamp_s,
                "type": "bevcart", 
                "hole": min(18, ((minute + 30) // 13) + 1),  # Cart offset schedule
            })
    
    return golfer_points, cart_points

def main():
    """Run the visibility tracking test."""
    init_logging()
    
    print("Creating test GPS data...")
    golfer_points, cart_points = create_test_data()
    
    print(f"Generated {len(golfer_points)} golfer points and {len(cart_points)} cart points")
    
    # Test direct visibility service usage
    print("\nTesting visibility tracking service...")
    visibility_service = create_visibility_service(
        proximity_threshold_m=100.0,
        green_to_yellow_min=20.0,
        yellow_to_orange_min=40.0, 
        orange_to_red_min=60.0,
        red_pulsing_enabled=True
    )
    
    # Process coordinates
    visibility_service.process_coordinates_batch(golfer_points, cart_points)
    
    # Get enhanced golfer points
    enhanced_golfer_points = visibility_service.annotate_golfer_points_with_visibility(golfer_points)
    
    # Show summary
    summary = visibility_service.get_visibility_summary()
    print(f"Visibility tracking results:")
    print(f"  - Total golfers: {summary['total_golfers']}")
    print(f"  - Total visibility events: {summary['total_visibility_events']}")
    print(f"  - Proximity threshold: {summary['thresholds']['proximity_threshold_m']}m")
    
    # Show some example enhanced points
    print("\nSample enhanced golfer points:")
    for i, point in enumerate(enhanced_golfer_points[::30]):  # Every 30th point
        status = point.get("visibility_status", "unknown")
        time_since = point.get("time_since_last_sighting_min")
        pulsing = point.get("pulsing", False)
        
        time_str = f"{(point['timestamp'] - 7200) // 60}min" 
        sighting_str = f"{time_since:.1f}min ago" if time_since is not None else "never"
        pulse_str = " [PULSING]" if pulsing else ""
        
        print(f"  {time_str}: {status.upper()} (last sighting: {sighting_str}){pulse_str}")
    
    # Test CSV output with visibility tracking
    print("\nTesting CSV output with visibility tracking...")
    output_dir = Path("outputs/visibility_test")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    csv_path = write_coordinates_csv_with_visibility(
        {"test_golfer_1": enhanced_golfer_points, "test_bev_cart_1": cart_points},
        output_dir / "test_coordinates_with_visibility.csv",
        enable_visibility_tracking=True
    )
    
    print(f"Enhanced CSV saved to: {csv_path}")
    
    # Also save raw data for comparison
    from golfsim.io.results import write_unified_coordinates_csv
    raw_csv_path = write_unified_coordinates_csv(
        {"test_golfer_1": golfer_points, "test_bev_cart_1": cart_points},
        output_dir / "test_coordinates_raw.csv"
    )
    
    print(f"Raw CSV saved to: {raw_csv_path}")
    
    # Save test metadata
    metadata = {
        "test_description": "Golfer-beverage cart visibility tracking demonstration",
        "scenario": "Single golfer plays 18 holes over 4 hours, encounters beverage cart 3 times",
        "visibility_events": summary["total_visibility_events"],
        "encounter_times_min": [30, 95, 180],
        "thresholds": summary["thresholds"],
    }
    
    with open(output_dir / "test_metadata.json", "w") as f:
        json.dump(metadata, f, indent=2)
    
    print(f"\nTest completed successfully!")
    print(f"Review the CSV files to see the visibility status color coding:")
    print(f"  - Green: Recently saw cart (< 20 min)")
    print(f"  - Yellow: Moderate time since last sighting (20-40 min)")
    print(f"  - Orange: Long time since last sighting (40-60 min)")
    print(f"  - Red: Very long time since last sighting (> 60 min) [with pulsing flag]")

if __name__ == "__main__":
    main()
