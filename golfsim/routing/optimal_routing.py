"""
Optimal routing logic for golf cart delivery optimization.

This module contains the centralized optimal routing algorithms extracted from
find_route_to_any_node.py to provide consistent, efficient route finding
across all components of the golf delivery simulation system.
"""

from typing import Dict, List, Tuple

import networkx as nx
import numpy as np

from .networks import nearest_node


def get_node_coordinates(graph: nx.Graph, node_id: int) -> Tuple[float, float]:
    """
    Get coordinates for a specific node ID.

    Args:
        graph: NetworkX graph with node coordinate data
        node_id: Index-based node ID (0-based)

    Returns:
        Tuple of (longitude, latitude) coordinates

    Raises:
        ValueError: If node ID is invalid
    """
    nodes = list(graph.nodes())
    if node_id >= len(nodes):
        raise ValueError(f"Node ID {node_id} exceeds graph size ({len(nodes)} nodes)")

    node = nodes[node_id]
    node_data = graph.nodes[node]
    return (node_data['x'], node_data['y'])


def calculate_path_metrics(graph: nx.Graph, path: List, speed_mps: float = 6.0) -> Dict:
    """
    Calculate comprehensive metrics for a given path.

    Args:
        graph: NetworkX graph with edge length data
        path: List of nodes representing the path
        speed_mps: Travel speed in meters per second

    Returns:
        Dictionary with path metrics:
        {
            "length_m": float,      # Total path length in meters
            "time_s": float,        # Travel time in seconds
            "time_min": float,      # Travel time in minutes
            "num_segments": int     # Number of path segments
        }
    """
    if len(path) < 2:
        return {"length_m": 0.0, "time_s": 0.0, "time_min": 0.0, "num_segments": 0}

    total_length = 0.0

    for u, v in zip(path[:-1], path[1:]):
        try:
            edge_dict = graph[u][v]

            if hasattr(edge_dict, 'keys') and len(edge_dict) > 0:
                # MultiGraph: get first edge
                edge_key = list(edge_dict.keys())[0]
                edge_data = edge_dict[edge_key]
                if isinstance(edge_data, dict):
                    edge_length = float(edge_data.get("length", 0))
                else:
                    edge_length = float(edge_data)
            elif isinstance(edge_dict, dict):
                # Simple graph with dict edge data
                edge_length = float(edge_dict.get("length", 0))
            else:
                # Edge data is directly a number
                edge_length = float(edge_dict)

            total_length += edge_length

        except (KeyError, IndexError, TypeError):
            # Fallback: compute distance using coordinates
            u_data = graph.nodes[u]
            v_data = graph.nodes[v]
            if 'x' in u_data and 'y' in u_data and 'x' in v_data and 'y' in v_data:
                # Convert to meters (rough approximation)
                dx = (v_data['x'] - u_data['x']) * 111139  # meters per degree longitude
                dy = (v_data['y'] - u_data['y']) * 111139  # meters per degree latitude
                edge_length = np.sqrt(dx**2 + dy**2)
                total_length += edge_length

    # Calculate travel time
    travel_time = total_length / speed_mps

    return {
        "length_m": total_length,
        "time_s": travel_time,
        "time_min": travel_time / 60.0,
        "num_segments": len(path) - 1,
    }


def find_optimal_route(
    graph: nx.Graph,
    start_coords: Tuple[float, float],
    end_coords: Tuple[float, float],
    speed_mps: float = 6.0,
) -> Dict:
    """
    Find the optimal route between two coordinate points.

    This is the core optimal routing function that uses NetworkX shortest path
    algorithms to find the best route between any two points on the golf course.

    Args:
        graph: NetworkX graph representing the cart path network
        start_coords: Starting coordinates (longitude, latitude)
        end_coords: Ending coordinates (longitude, latitude)
        speed_mps: Travel speed in meters per second (default: 6.0)

    Returns:
        Dictionary with routing results:
        {
            "success": bool,                    # Whether route was found
            "path": List[nodes],               # Actual NetworkX nodes in path
            "path_ids": List[int],             # Index-based node IDs
            "metrics": {                       # Path performance metrics
                "length_m": float,
                "time_s": float,
                "time_min": float,
                "num_segments": int
            },
            "efficiency": float,               # Route efficiency vs straight line (%)
            "straight_line_distance": float,  # Direct distance for comparison
            "error": str                       # Error message if success=False
        }
    """

    if graph is None or graph.number_of_nodes() == 0:
        return {"success": False, "error": "Cart path graph is empty or invalid"}

    try:
        # Find nearest nodes to start and end coordinates
        start_node = nearest_node(graph, start_coords[0], start_coords[1])
        end_node = nearest_node(graph, end_coords[0], end_coords[1])

        if start_node is None or end_node is None:
            return {
                "success": False,
                "error": "Could not find valid nodes near start or end coordinates",
            }

        # Calculate straight-line distance for efficiency calculation
        dx = (end_coords[0] - start_coords[0]) * 111139  # meters per degree longitude
        dy = (end_coords[1] - start_coords[1]) * 111139  # meters per degree latitude
        straight_line_distance = np.sqrt(dx**2 + dy**2)

        if start_node == end_node:
            return {
                "success": True,
                "path": [start_node],
                "path_ids": [list(graph.nodes()).index(start_node)],
                "metrics": {"length_m": 0.0, "time_s": 0.0, "time_min": 0.0, "num_segments": 0},
                "efficiency": 100.0,
                "straight_line_distance": 0.0,
            }

        # Find shortest path using NetworkX
        path = nx.shortest_path(graph, start_node, end_node, weight="length")

        # Convert to node IDs for compatibility
        path_ids = [list(graph.nodes()).index(node) for node in path]

        # Calculate comprehensive path metrics
        metrics = calculate_path_metrics(graph, path, speed_mps)

        # Calculate route efficiency (straight-line distance vs actual path distance)
        efficiency = (
            (straight_line_distance / metrics['length_m']) * 100 if metrics['length_m'] > 0 else 0
        )

        return {
            "success": True,
            "path": path,
            "path_ids": path_ids,
            "metrics": metrics,
            "efficiency": efficiency,
            "straight_line_distance": straight_line_distance,
        }

    except nx.NetworkXNoPath:
        return {
            "success": False,
            "error": "No path exists between coordinates. The network may be disconnected.",
        }
    except Exception as e:
        return {"success": False, "error": f"Unexpected error in route calculation: {str(e)}"}


def find_optimal_route_with_node_id(
    graph: nx.Graph, start_coords: Tuple[float, float], target_node_id: int, speed_mps: float = 6.0
) -> Dict:
    """
    Find optimal route from coordinates to a specific node ID.

    This function is a convenience wrapper around find_optimal_route that accepts
    a target node ID instead of coordinates, maintaining compatibility with
    existing code that uses node-based routing.

    Args:
        graph: NetworkX graph representing the cart path network
        start_coords: Starting coordinates (longitude, latitude)
        target_node_id: Target node ID (0-based index)
        speed_mps: Travel speed in meters per second

    Returns:
        Same format as find_optimal_route, with additional fields:
        {
            ...,                               # All find_optimal_route fields
            "target_coords": Tuple[float, float], # Target node coordinates
            "start_node_id": int               # Starting node ID
        }
    """

    # Validate target node ID
    total_nodes = graph.number_of_nodes()
    if target_node_id >= total_nodes:
        return {
            "success": False,
            "error": f"Invalid node ID {target_node_id}. Valid range: 0-{total_nodes-1}",
        }

    try:
        # Get target coordinates from node ID
        target_coords = get_node_coordinates(graph, target_node_id)

        # Find the route using coordinate-based routing
        route_result = find_optimal_route(graph, start_coords, target_coords, speed_mps)

        if route_result["success"]:
            # Add node ID specific information
            start_node = nearest_node(graph, start_coords[0], start_coords[1])
            start_node_id = list(graph.nodes()).index(start_node) if start_node else -1

            route_result.update({"target_coords": target_coords, "start_node_id": start_node_id})

        return route_result

    except Exception as e:
        return {"success": False, "error": f"Error in node ID routing: {str(e)}"}


def validate_route_quality(route_result: Dict, efficiency_threshold: float = 60.0) -> Dict:
    """
    Validate the quality of a routing result.

    Args:
        route_result: Result from find_optimal_route
        efficiency_threshold: Minimum efficiency percentage for a "good" route

    Returns:
        Dictionary with validation results:
        {
            "is_valid": bool,
            "quality_score": str,  # "excellent", "good", "fair", "poor"
            "recommendations": List[str],
            "metrics": Dict
        }
    """

    if not route_result["success"]:
        return {
            "is_valid": False,
            "quality_score": "invalid",
            "recommendations": ["Route calculation failed"],
            "metrics": {},
        }

    efficiency = route_result["efficiency"]
    distance = route_result["metrics"]["length_m"]
    time_min = route_result["metrics"]["time_min"]

    recommendations = []

    # Determine quality score
    if efficiency >= 80:
        quality_score = "excellent"
    elif efficiency >= efficiency_threshold:
        quality_score = "good"
    elif efficiency >= 40:
        quality_score = "fair"
        recommendations.append("Route efficiency is below optimal. Consider network improvements.")
    else:
        quality_score = "poor"
        recommendations.append(
            "Route efficiency is very low. Network may need significant improvements."
        )

    # Add specific recommendations
    if time_min > 10:
        recommendations.append("Travel time exceeds 10 minutes. Consider adding shortcuts.")

    if distance > 2000:
        recommendations.append("Route distance exceeds 2km. Review network connectivity.")

    return {
        "is_valid": True,
        "quality_score": quality_score,
        "recommendations": recommendations,
        "metrics": {
            "efficiency": efficiency,
            "distance_m": distance,
            "time_min": time_min,
            "efficiency_grade": quality_score,
        },
    }
