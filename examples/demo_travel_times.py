#!/usr/bin/env python3
"""
Demo script showing how to use the calculated travel times data.

This script demonstrates:
1. Loading the travel times data
2. Finding the closest/farthest holes for delivery
3. Calculating optimal delivery schedules
4. Visualizing travel time distributions

Usage:
    python examples/demo_travel_times.py
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


def load_travel_times(course_dir: str = "courses/pinetree_country_club") -> Dict:
    """Load the pre-calculated travel times data."""
    travel_times_path = Path(course_dir) / "travel_times.json"

    if not travel_times_path.exists():
        print(f"Travel times not found at {travel_times_path}")
        print("Run: python scripts/routing/calculate_travel_times.py first")
        sys.exit(1)

    with open(travel_times_path, 'r') as f:
        return json.load(f)


def find_delivery_extremes(travel_times: Dict, delivery_method: str = "golf_cart") -> Dict:
    """Find the closest and farthest holes for a given delivery method."""
    extremes = {
        "closest_to_tee": {"hole": None, "time_min": float('inf'), "distance_m": float('inf')},
        "farthest_to_tee": {"hole": None, "time_min": 0, "distance_m": 0},
        "closest_to_target": {"hole": None, "time_min": float('inf'), "distance_m": float('inf')},
        "farthest_to_target": {"hole": None, "time_min": 0, "distance_m": 0},
    }

    for hole_num, hole_data in travel_times["holes"].items():
        if delivery_method not in hole_data["travel_times"]:
            continue

        method_data = hole_data["travel_times"][delivery_method]

        # Check to tee
        if "to_tee" in method_data and "time_min" in method_data["to_tee"]:
            tee_time = method_data["to_tee"]["time_min"]
            tee_distance = method_data["to_tee"]["distance_m"]

            if tee_time < extremes["closest_to_tee"]["time_min"]:
                extremes["closest_to_tee"] = {
                    "hole": hole_num,
                    "time_min": tee_time,
                    "distance_m": tee_distance,
                    "par": hole_data["par"],
                    "handicap": hole_data["handicap"],
                }

            if tee_time > extremes["farthest_to_tee"]["time_min"]:
                extremes["farthest_to_tee"] = {
                    "hole": hole_num,
                    "time_min": tee_time,
                    "distance_m": tee_distance,
                    "par": hole_data["par"],
                    "handicap": hole_data["handicap"],
                }

        # Check to target
        if "to_target" in method_data and "time_min" in method_data["to_target"]:
            target_time = method_data["to_target"]["time_min"]
            target_distance = method_data["to_target"]["distance_m"]

            if target_time < extremes["closest_to_target"]["time_min"]:
                extremes["closest_to_target"] = {
                    "hole": hole_num,
                    "time_min": target_time,
                    "distance_m": target_distance,
                    "par": hole_data["par"],
                    "handicap": hole_data["handicap"],
                }

            if target_time > extremes["farthest_to_target"]["time_min"]:
                extremes["farthest_to_target"] = {
                    "hole": hole_num,
                    "time_min": target_time,
                    "distance_m": target_distance,
                    "par": hole_data["par"],
                    "handicap": hole_data["handicap"],
                }

    return extremes


def get_delivery_order_by_distance(
    travel_times: Dict, delivery_method: str = "golf_cart", to_target: bool = False
) -> List[Tuple[str, float, float]]:
    """Get holes ordered by delivery time (closest first)."""
    holes_with_times = []
    destination = "to_target" if to_target else "to_tee"

    for hole_num, hole_data in travel_times["holes"].items():
        if delivery_method in hole_data["travel_times"]:
            method_data = hole_data["travel_times"][delivery_method]

            if destination in method_data and "time_min" in method_data[destination]:
                time_min = method_data[destination]["time_min"]
                distance_m = method_data[destination]["distance_m"]
                holes_with_times.append((hole_num, time_min, distance_m))

    # Sort by time
    holes_with_times.sort(key=lambda x: x[1])
    return holes_with_times


def calculate_delivery_schedule(
    travel_times: Dict, delivery_method: str = "golf_cart", max_deliveries_per_trip: int = 4
) -> List[Dict]:
    """Calculate an efficient delivery schedule."""
    # Get holes ordered by proximity to clubhouse
    ordered_holes = get_delivery_order_by_distance(travel_times, delivery_method, to_target=False)

    trips = []
    for i in range(0, len(ordered_holes), max_deliveries_per_trip):
        trip_holes = ordered_holes[i : i + max_deliveries_per_trip]

        # Calculate total trip time (assuming you visit in order and return to clubhouse)
        total_time = 0
        total_distance = 0

        for hole_num, time_min, distance_m in trip_holes:
            total_time += time_min * 2  # Round trip time
            total_distance += distance_m * 2  # Round trip distance

        trips.append(
            {
                "trip_number": len(trips) + 1,
                "holes": [{"hole": h, "time_min": t, "distance_m": d} for h, t, d in trip_holes],
                "total_time_min": total_time,
                "total_distance_m": total_distance,
                "hole_count": len(trip_holes),
            }
        )

    return trips


def print_summary_stats(travel_times: Dict):
    """Print a summary of travel time statistics."""
    print("Travel Time Summary")
    print("=" * 50)

    course_name = travel_times["metadata"]["course_name"]
    total_holes = travel_times["summary"]["total_holes"]

    print(f"Course: {course_name}")
    print(f"Total Holes: {total_holes}")
    print(
        f"Network: {travel_times['metadata']['graph_stats']['nodes']} nodes, {travel_times['metadata']['graph_stats']['edges']} edges"
    )
    print()

    # Focus only on golf cart delivery
    method = "golf_cart"
    if method in travel_times["calculation_params"]["speeds_mps"]:
        speed_mph = travel_times["calculation_params"]["speeds_mph"][method]
        print(f"Golf Cart Delivery ({speed_mph:.1f} mph):")

        if method in travel_times["summary"]["statistics"]:
            stats = travel_times["summary"]["statistics"][method]

            if "to_tee" in stats:
                tee_stats = stats["to_tee"]
                print(f"  To Tees:")
                print(
                    f"    Time: {tee_stats['time_min']['min']:.1f} - {tee_stats['time_min']['max']:.1f} min (avg: {tee_stats['time_min']['mean']:.1f} min)"
                )
                print(
                    f"    Distance: {tee_stats['distance_m']['min']:.0f} - {tee_stats['distance_m']['max']:.0f} m (avg: {tee_stats['distance_m']['mean']:.0f} m)"
                )

            if "to_target" in stats:
                target_stats = stats["to_target"]
                print(f"  To Targets:")
                print(
                    f"    Time: {target_stats['time_min']['min']:.1f} - {target_stats['time_min']['max']:.1f} min (avg: {target_stats['time_min']['mean']:.1f} min)"
                )
                print(
                    f"    Distance: {target_stats['distance_m']['min']:.0f} - {target_stats['distance_m']['max']:.0f} m (avg: {target_stats['distance_m']['mean']:.0f} m)"
                )
        print()


def main():
    """Demo the travel times functionality."""
    print("Golf Delivery Travel Times Demo")
    print("=" * 40)
    print()

    # Load travel times data
    travel_times = load_travel_times()

    # Print summary statistics
    print_summary_stats(travel_times)

    # Find extremes for golf cart delivery
    print("Golf Cart Delivery Extremes")
    print("-" * 30)
    extremes = find_delivery_extremes(travel_times, "golf_cart")

    closest_tee = extremes["closest_to_tee"]
    print(
        f"Closest hole to tee: #{closest_tee['hole']} (Par {closest_tee['par']}) - {closest_tee['time_min']:.1f} min, {closest_tee['distance_m']:.0f}m"
    )

    farthest_tee = extremes["farthest_to_tee"]
    print(
        f"Farthest hole to tee: #{farthest_tee['hole']} (Par {farthest_tee['par']}) - {farthest_tee['time_min']:.1f} min, {farthest_tee['distance_m']:.0f}m"
    )
    print()

    # Show delivery order
    print("Optimal Delivery Order (Golf Cart to Tees)")
    print("-" * 45)
    delivery_order = get_delivery_order_by_distance(travel_times, "golf_cart", False)

    for i, (hole_num, time_min, distance_m) in enumerate(delivery_order[:10]):  # Show first 10
        hole_data = travel_times["holes"][hole_num]
        print(
            f"{i+1:2d}. Hole #{hole_num} (Par {hole_data['par']}) - {time_min:.1f} min, {distance_m:.0f}m"
        )

    if len(delivery_order) > 10:
        print(f"    ... and {len(delivery_order) - 10} more holes")
    print()

    # Calculate delivery schedule
    print("Sample Delivery Schedule (4 holes per trip)")
    print("-" * 45)
    trips = calculate_delivery_schedule(travel_times, "golf_cart", 4)

    for trip in trips[:3]:  # Show first 3 trips
        print(f"Trip {trip['trip_number']}: {trip['hole_count']} holes")
        holes_list = ", ".join([f"#{h['hole']}" for h in trip['holes']])
        print(f"  Holes: {holes_list}")
        print(f"  Total time: {trip['total_time_min']:.1f} min")
        print(f"  Total distance: {trip['total_distance_m']:.0f}m")
        print()

    # Show closest hole details
    print("Closest Hole Details")
    print("-" * 25)
    closest_hole = delivery_order[0][0]  # Get closest hole number
    hole_data = travel_times["holes"][closest_hole]

    print(f"Hole #{closest_hole} (Par {hole_data['par']}) - Shortest delivery time:")
    if "golf_cart" in hole_data["travel_times"]:
        method_data = hole_data["travel_times"]["golf_cart"]["to_tee"]
        speed_mph = travel_times["calculation_params"]["speeds_mph"]["golf_cart"]
        print(
            f"  Golf Cart: {method_data['time_min']:.1f} min ({method_data['distance_m']:.0f}m at {speed_mph:.1f} mph)"
        )

    print()
    print("Demo completed. Use this data for golf cart delivery optimization.")


if __name__ == "__main__":
    main()
