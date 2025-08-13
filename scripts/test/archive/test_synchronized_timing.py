#!/usr/bin/env python3
"""
Test script to demonstrate synchronized timing between golfer and beverage cart.

This script shows how to use GCD/LCM calculations to ensure optimal meeting points
when the beverage cart (18→1) and golfer (1→18) pass each other.
"""

from golfsim.simulation.engine import calculate_synchronized_timing, calculate_meeting_point_offset
from golfsim.logging import init_logging

def main():
    init_logging()
    
    print("=== Synchronized Timing Analysis ===\n")
    
    # Standard timing from configuration
    golfer_minutes_per_hole = 12.0
    golfer_minutes_between_holes = 2.0
    bev_cart_minutes_per_hole = 8.0
    bev_cart_minutes_between_holes = 2.0
    
    print("Input Parameters:")
    print(f"  Golfer: {golfer_minutes_per_hole}min on hole + {golfer_minutes_between_holes}min transfer = {golfer_minutes_per_hole + golfer_minutes_between_holes}min/hole")
    print(f"  Bev Cart: {bev_cart_minutes_per_hole}min on hole + {bev_cart_minutes_between_holes}min transfer = {bev_cart_minutes_per_hole + bev_cart_minutes_between_holes}min/hole")
    print(f"  Golfer direction: 1→18 (forward)")
    print(f"  Bev Cart direction: 18→1 (reverse)")
    print()
    
    # Calculate synchronized timing
    sync_timing = calculate_synchronized_timing(
        golfer_minutes_per_hole=golfer_minutes_per_hole,
        golfer_minutes_between_holes=golfer_minutes_between_holes,
        bev_cart_minutes_per_hole=bev_cart_minutes_per_hole,
        bev_cart_minutes_between_holes=bev_cart_minutes_between_holes,
    )
    
    print("Synchronized Timing Results:")
    print(f"  Time quantum (GCD): {sync_timing['time_quantum_s']}s")
    print(f"  Golfer full cycle: {sync_timing['golfer_full_cycle_s']}s ({sync_timing['golfer_full_cycle_s']/60:.1f}min)")
    print(f"  Bev cart full cycle: {sync_timing['bev_cart_full_cycle_s']}s ({sync_timing['bev_cart_full_cycle_s']/60:.1f}min)")
    print(f"  Synchronized cycle (LCM): {sync_timing['synchronized_cycle_s']}s ({sync_timing['synchronized_cycle_s']/3600:.1f}h)")
    print()
    
    # Test different meeting scenarios
    golfer_tee_time_s = 7200  # 9:00 AM (2 hours after 7 AM baseline)
    bev_cart_start_s = 7200   # 9:00 AM (same time)
    
    print("Meeting Point Analysis:")
    print(f"  Golfer tee time: {golfer_tee_time_s/3600 + 7:.1f}:00")
    print(f"  Bev cart start: {bev_cart_start_s/3600 + 7:.1f}:00")
    print()
    
    # Calculate meeting points for different holes
    for target_hole in [5, 9, 13]:
        meeting_calc = calculate_meeting_point_offset(
            golfer_tee_time_s=golfer_tee_time_s,
            bev_cart_start_time_s=bev_cart_start_s,
            synchronized_timing=sync_timing,
            target_hole=target_hole,
        )
        
        print(f"Target Hole {target_hole}:")
        print(f"  Golfer arrives: {meeting_calc['golfer_arrival_s']/60:.1f}min from start")
        print(f"  Bev cart arrives: {meeting_calc['bev_cart_arrival_s']/60:.1f}min from start")
        print(f"  Time difference: {meeting_calc['time_difference_s']/60:.1f}min")
        print(f"  Optimal offset: {meeting_calc['optimal_offset_s']/60:.1f}min")
        print(f"  Adjusted bev cart start: {(meeting_calc['adjusted_bev_cart_start_s']/3600 + 7):.2f}:00")
        print()
    
    print("=== Recommendations ===")
    print("1. Use time_quantum_s for both golfer and beverage cart GPS generation")
    print("2. Apply optimal_offset_s to beverage cart start time for better meeting alignment")
    print("3. Monitor pass events to verify improved synchronization")

if __name__ == "__main__":
    main()
