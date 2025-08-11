#!/usr/bin/env python3
"""
Demo script showing how to use the dynamic route finder programmatically.
This shows how to integrate the route finding functionality into other scripts.
"""

import sys

sys.path.append('.')

# Import the route finding functions
from scripts.routing.find_route_to_any_node import load_course_data, find_optimal_route, visualize_route


def demo_multiple_routes():
    """Demonstrate finding routes to multiple nodes."""

    print("DEMO: Finding routes to multiple nodes")
    print("=" * 50)

    # Load course data once
    data = load_course_data()
    cart_graph = data['cart_graph']
    clubhouse_coords = data['clubhouse_coords']

    # List of nodes to find routes to
    target_nodes = [50, 100, 150, 200, 300, 400, 500]

    print(f"Finding routes from clubhouse to nodes: {target_nodes}")
    print()

    results = []

    for node_id in target_nodes:
        print(f"Route to Node {node_id}:")

        route_result = find_optimal_route(cart_graph, clubhouse_coords, node_id)

        if route_result["success"]:
            metrics = route_result["metrics"]
            efficiency = route_result["efficiency"]

            print(
                f"   Distance: {metrics['length_m']:.1f}m | Time: {metrics['time_min']:.1f}min | Efficiency: {efficiency:.1f}%"
            )

            results.append(
                {
                    'node': node_id,
                    'distance': metrics['length_m'],
                    'time': metrics['time_min'],
                    'efficiency': efficiency,
                }
            )
        else:
            print(f"   Error: {route_result['error']}")

    # Analysis of results
    print(f"\nROUTE ANALYSIS:")
    print("-" * 50)

    if results:
        # Find shortest and longest routes
        shortest = min(results, key=lambda x: x['distance'])
        longest = max(results, key=lambda x: x['distance'])
        fastest = min(results, key=lambda x: x['time'])
        most_efficient = max(results, key=lambda x: x['efficiency'])

        print(f"Shortest route: Node {shortest['node']} ({shortest['distance']:.1f}m)")
        print(f"Longest route: Node {longest['node']} ({longest['distance']:.1f}m)")
        print(f"Fastest route: Node {fastest['node']} ({fastest['time']:.1f}min)")
        print(f"Most efficient: Node {most_efficient['node']} ({most_efficient['efficiency']:.1f}%)")

        # Average metrics
        avg_distance = sum(r['distance'] for r in results) / len(results)
        avg_time = sum(r['time'] for r in results) / len(results)
        avg_efficiency = sum(r['efficiency'] for r in results) / len(results)

        print(f"\nAverages:")
        print(
            f"   Distance: {avg_distance:.1f}m | Time: {avg_time:.1f}min | Efficiency: {avg_efficiency:.1f}%"
        )


def demo_custom_speed():
    """Demonstrate how different cart speeds affect travel times."""

    print(f"\nDEMO: Effect of cart speed on travel time")
    print("=" * 50)

    data = load_course_data()
    cart_graph = data['cart_graph']
    clubhouse_coords = data['clubhouse_coords']

    target_node = 200  # Use node 200 as example
    speeds = [4.0, 6.0, 8.0, 10.0]  # Different cart speeds in m/s

    print(f"Route to Node {target_node} at different speeds:")

    for speed in speeds:
        route_result = find_optimal_route(cart_graph, clubhouse_coords, target_node, speed)

        if route_result["success"]:
            time_min = route_result["metrics"]["time_min"]
            print(f"   {speed:4.1f} m/s ({speed*3.6:4.1f} km/h): {time_min:.1f} minutes")


def demo_route_comparison():
    """Compare efficiency of routes to different areas of the course."""

    print(f"\nDEMO: Route efficiency by course area")
    print("=" * 50)

    data = load_course_data()
    cart_graph = data['cart_graph']
    clubhouse_coords = data['clubhouse_coords']

    # Sample nodes from different areas (these are examples)
    course_areas = {
        "Near Clubhouse": [700, 750, 760],
        "Front Nine": [50, 100, 150],
        "Middle Course": [300, 350, 400],
        "Back Nine": [200, 250, 300],
        "Far Reaches": [0, 25, 75],
    }

    for area_name, nodes in course_areas.items():
        print(f"\n{area_name}:")

        area_efficiencies = []
        area_times = []

        for node in nodes:
            route_result = find_optimal_route(cart_graph, clubhouse_coords, node)

            if route_result["success"]:
                efficiency = route_result["efficiency"]
                time_min = route_result["metrics"]["time_min"]
                area_efficiencies.append(efficiency)
                area_times.append(time_min)

                print(f"   Node {node:3d}: {efficiency:5.1f}% efficient, {time_min:4.1f} min")

        if area_efficiencies:
            avg_efficiency = sum(area_efficiencies) / len(area_efficiencies)
            avg_time = sum(area_times) / len(area_times)
            print(f"   Average: {avg_efficiency:5.1f}% efficient, {avg_time:4.1f} min")


if __name__ == "__main__":
    try:
        # Run all demos
        demo_multiple_routes()
        demo_custom_speed()
        demo_route_comparison()

        print(f"\nDemo complete. Try the interactive mode:")
        print(f"   python scripts/find_route_to_any_node.py --interactive")

    except Exception as e:
        print(f"Demo error: {e}")
        import traceback

        traceback.print_exc()
