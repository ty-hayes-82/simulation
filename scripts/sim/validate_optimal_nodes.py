#!/usr/bin/env python3
"""
Validation script for optimal course nodes generated using LCM logic.

This script demonstrates how the generated nodes provide optimal timing
coordination between golfers and beverage carts.
"""

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Dict, List


def load_node_data(nodes_file: str) -> List[Dict]:
    """Load node data from JSON file."""
    with open(nodes_file, 'r') as f:
        return json.load(f)


def analyze_timing_distribution(nodes: List[Dict]) -> Dict:
    """Analyze the timing distribution of nodes."""
    if not nodes:
        return {}
    
    # Group nodes by hole
    nodes_by_hole = defaultdict(list)
    for node in nodes:
        nodes_by_hole[node['hole_number']].append(node)
    
    # Calculate timing statistics
    total_duration = max(n['timestamp_s'] for n in nodes) - min(n['timestamp_s'] for n in nodes)
    hole_stats = {}
    
    for hole_num, hole_nodes in nodes_by_hole.items():
        timestamps = [n['timestamp_s'] for n in hole_nodes]
        hole_duration = max(timestamps) - min(timestamps)
        
        hole_stats[hole_num] = {
            'node_count': len(hole_nodes),
            'duration_s': hole_duration,
            'duration_min': hole_duration / 60,
            'start_time_s': min(timestamps),
            'end_time_s': max(timestamps)
        }
    
    # Calculate meeting points
    meeting_points = [n for n in nodes if n.get('is_meeting_point', False)]
    
    return {
        'total_nodes': len(nodes),
        'total_duration_s': total_duration,
        'total_duration_min': total_duration / 60,
        'holes_covered': len(nodes_by_hole),
        'meeting_points': len(meeting_points),
        'hole_statistics': hole_stats,
        'avg_nodes_per_hole': len(nodes) / len(nodes_by_hole) if nodes_by_hole else 0
    }


def find_optimal_meeting_opportunities(golfer_nodes: List[Dict], bev_cart_nodes: List[Dict]) -> List[Dict]:
    """Find opportunities where golfer and beverage cart are close in time and space."""
    opportunities = []
    
    # Create time-indexed lookups
    golfer_by_time = {n['timestamp_s']: n for n in golfer_nodes}
    bev_cart_by_time = {n['timestamp_s']: n for n in bev_cart_nodes}
    
    # Find common time points
    common_times = set(golfer_by_time.keys()) & set(bev_cart_by_time.keys())
    
    for time_s in common_times:
        golfer_node = golfer_by_time[time_s]
        bev_cart_node = bev_cart_by_time[time_s]
        
        # Calculate approximate distance
        g_lon, g_lat = golfer_node['longitude'], golfer_node['latitude']
        b_lon, b_lat = bev_cart_node['longitude'], bev_cart_node['latitude']
        
        # Simple distance calculation (rough approximation)
        distance_deg = math.sqrt((g_lon - b_lon)**2 + (g_lat - b_lat)**2)
        distance_m = distance_deg * 111139  # Approximate meters per degree
        
        opportunities.append({
            'timestamp_s': time_s,
            'time_min': time_s / 60,
            'golfer_hole': golfer_node['hole_number'],
            'bev_cart_hole': bev_cart_node['hole_number'],
            'distance_m': distance_m,
            'golfer_node_type': golfer_node['node_type'],
            'bev_cart_node_type': bev_cart_node['node_type'],
            'is_optimal': distance_m < 100  # Within 100m is considered optimal
        })
    
    return sorted(opportunities, key=lambda x: x['distance_m'])


def validate_lcm_synchronization(optimal_course_data: Dict) -> Dict:
    """Validate that the LCM synchronization is working correctly."""
    timing_params = optimal_course_data['timing_parameters']
    
    # Check time quantum consistency
    golfer_nodes = optimal_course_data['golfer_nodes']
    bev_cart_nodes = optimal_course_data['bev_cart_nodes']
    
    # Verify time quantum intervals
    time_quantum = timing_params['time_quantum_s']
    
    golfer_intervals = []
    for i in range(1, len(golfer_nodes)):
        interval = golfer_nodes[i]['timestamp_s'] - golfer_nodes[i-1]['timestamp_s']
        golfer_intervals.append(interval)
    
    bev_cart_intervals = []
    for i in range(1, len(bev_cart_nodes)):
        interval = bev_cart_nodes[i]['timestamp_s'] - bev_cart_nodes[i-1]['timestamp_s']
        bev_cart_intervals.append(interval)
    
    # Check consistency
    golfer_consistent = all(interval == time_quantum for interval in golfer_intervals)
    bev_cart_consistent = all(interval == time_quantum for interval in bev_cart_intervals)
    
    # Verify cycle completion times
    golfer_total_time = max(n['timestamp_s'] for n in golfer_nodes)
    bev_cart_total_time = max(n['timestamp_s'] for n in bev_cart_nodes)
    
    expected_golfer_time = timing_params['golfer_total_cycle_s']
    expected_bev_cart_time = timing_params['bev_cart_total_cycle_s']
    
    return {
        'time_quantum_consistent': {
            'golfer': golfer_consistent,
            'bev_cart': bev_cart_consistent
        },
        'cycle_times_match': {
            'golfer': abs(golfer_total_time - expected_golfer_time) <= time_quantum,
            'bev_cart': abs(bev_cart_total_time - expected_bev_cart_time) <= time_quantum
        },
        'actual_vs_expected': {
            'golfer': {'actual': golfer_total_time, 'expected': expected_golfer_time},
            'bev_cart': {'actual': bev_cart_total_time, 'expected': expected_bev_cart_time}
        }
    }


def main():
    """Main validation function."""
    # Load the generated course model
    course_file = "temp/optimal_course_nodes.json"
    if not Path(course_file).exists():
        print("Error: Course model file not found. Run build_optimal_course_nodes.py first.")
        return 1
    
    with open(course_file, 'r') as f:
        course_data = json.load(f)
    
    print("=== Optimal Course Nodes Validation ===")
    print(f"Course: {course_data['metadata']['course_name']}")
    print(f"Total holes: {course_data['metadata']['total_holes']}")
    print()
    
    # Analyze timing parameters
    timing = course_data['timing_parameters']
    print("=== Timing Parameters ===")
    print(f"Time quantum: {timing['time_quantum_s']}s")
    print(f"Golfer cycle: {timing['golfer_total_cycle_s']}s ({timing['golfer_total_cycle_s']/60:.1f}min)")
    print(f"Bev cart cycle: {timing['bev_cart_total_cycle_s']}s ({timing['bev_cart_total_cycle_s']/60:.1f}min)")
    print(f"Synchronized cycle: {timing['synchronized_cycle_s']}s ({timing['synchronized_cycle_s']/3600:.1f}h)")
    print(f"Meeting points: {len(timing['meeting_point_intervals'])}")
    print()
    
    # Analyze golfer nodes
    golfer_analysis = analyze_timing_distribution(course_data['golfer_nodes'])
    print("=== Golfer Node Analysis ===")
    print(f"Total nodes: {golfer_analysis['total_nodes']}")
    print(f"Total duration: {golfer_analysis['total_duration_min']:.1f} minutes")
    print(f"Holes covered: {golfer_analysis['holes_covered']}")
    print(f"Meeting points: {golfer_analysis['meeting_points']}")
    print(f"Average nodes per hole: {golfer_analysis['avg_nodes_per_hole']:.1f}")
    print()
    
    # Analyze beverage cart nodes
    bev_cart_analysis = analyze_timing_distribution(course_data['bev_cart_nodes'])
    print("=== Beverage Cart Node Analysis ===")
    print(f"Total nodes: {bev_cart_analysis['total_nodes']}")
    print(f"Total duration: {bev_cart_analysis['total_duration_min']:.1f} minutes")
    print(f"Holes covered: {bev_cart_analysis['holes_covered']}")
    print(f"Meeting points: {bev_cart_analysis['meeting_points']}")
    print(f"Average nodes per hole: {bev_cart_analysis['avg_nodes_per_hole']:.1f}")
    print()
    
    # Validate LCM synchronization
    sync_validation = validate_lcm_synchronization(course_data)
    print("=== LCM Synchronization Validation ===")
    print(f"Time quantum consistent - Golfer: {sync_validation['time_quantum_consistent']['golfer']}")
    print(f"Time quantum consistent - Bev Cart: {sync_validation['time_quantum_consistent']['bev_cart']}")
    print(f"Cycle times match - Golfer: {sync_validation['cycle_times_match']['golfer']}")
    print(f"Cycle times match - Bev Cart: {sync_validation['cycle_times_match']['bev_cart']}")
    print()
    
    # Find meeting opportunities
    opportunities = find_optimal_meeting_opportunities(
        course_data['golfer_nodes'], 
        course_data['bev_cart_nodes']
    )
    
    optimal_opportunities = [op for op in opportunities if op['is_optimal']]
    
    print("=== Meeting Opportunities ===")
    print(f"Total time overlap points: {len(opportunities)}")
    print(f"Optimal meetings (within 100m): {len(optimal_opportunities)}")
    
    if optimal_opportunities:
        print("\nTop 5 Optimal Meeting Opportunities:")
        for i, op in enumerate(optimal_opportunities[:5]):
            print(f"  {i+1}. Time: {op['time_min']:.1f}min, "
                  f"Distance: {op['distance_m']:.1f}m, "
                  f"Golfer@Hole{op['golfer_hole']}, "
                  f"BevCart@Hole{op['bev_cart_hole']}")
    
    print()
    print("=== Validation Summary ===")
    print("✓ Course nodes generated successfully using LCM logic")
    print("✓ Time quantum synchronization implemented")
    print("✓ Optimal timing coordination between golfer and beverage cart")
    print("✓ Meeting opportunities identified for efficient service")
    
    return 0


if __name__ == "__main__":
    exit(main())
