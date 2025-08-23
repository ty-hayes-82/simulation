"""
Routing utilities for runner shortest paths on cart-path graph.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import networkx as nx
from shapely.geometry import Point
import geopandas as gpd
import pandas as pd

_gdf_cache: Dict[int, gpd.GeoDataFrame] = {}


def nearest_node(G: nx.Graph, lon: float, lat: float):
    """Return nearest node by euclidean distance using node 'x'/'y'.

    Deterministic fallback behavior:
    - If no nodes have valid 'x' and 'y' attributes, return None
    - If the graph is empty, return None
    """
    if G is None or G.number_of_nodes() == 0:
        return None

    graph_id = id(G)

    if graph_id not in _gdf_cache:
        node_list = [
            (node, data.get("x"), data.get("y"))
            for node, data in G.nodes(data=True)
            if data.get("x") is not None and data.get("y") is not None
        ]
        if not node_list:
            return None

        df = pd.DataFrame(node_list, columns=['node', 'x', 'y'])
        # Use node ID as index for easy lookup later with idxmin()
        gdf = gpd.GeoDataFrame(
            df.drop(columns=['node']),
            geometry=gpd.points_from_xy(df.x, df.y),
            index=df.node
        )
        _gdf_cache[graph_id] = gdf

    gdf = _gdf_cache[graph_id]
    if gdf.empty:
        return None
        
    target = Point(lon, lat)

    # Calculate distances from the target to all nodes in a vectorized way
    distances = gdf.distance(target)

    # Find the index (node ID) of the minimum distance
    return distances.idxmin()


def shortest_path_on_cartpaths(
    G: nx.Graph,
    src: Tuple[float, float],
    dst: Tuple[float, float],
    speed_mps: float = 6.0,
    allow_backwards_routing: bool = True,
) -> Dict[str, object]:
    """
    UPDATED: Use optimal routing logic consistently.

    Compute shortest path (by distance) and travel time for runners.
    Returns format compatible with existing code:
    { 'nodes': [n0,...,nk], 'length_m': L, 'time_s': L/speed_mps }
    """
    from .optimal_routing import find_optimal_route

    route_result = find_optimal_route(G, src, dst, speed_mps)

    if not route_result["success"]:
        # Surface clear error for disconnected networks or other failures
        error_msg = route_result.get("error", "Routing failed")
        raise ValueError(error_msg)

    # Check if backwards routing should be attempted for long routes
    path = route_result["path"]
    length_m = route_result["metrics"]["length_m"]
    time_s = route_result["metrics"]["time_s"]

    if allow_backwards_routing and len(path) > 50:
        # Try alternative routing strategies for deliveries to later holes
        backwards_path = try_backwards_routing(G, path[0], path[-1], src, dst)
        if backwards_path and len(backwards_path) < len(path):
            # Calculate metrics for backwards path using optimal routing
            from .optimal_routing import calculate_path_metrics

            backwards_metrics = calculate_path_metrics(G, backwards_path, speed_mps)

            # Use backwards route if it's significantly shorter
            if backwards_metrics["length_m"] < length_m * 0.8:  # 20% shorter threshold
                return {
                    "nodes": backwards_path,
                    "length_m": backwards_metrics["length_m"],
                    "time_s": backwards_metrics["time_s"],
                    "routing_type": "backwards",
                }

    return {"nodes": path, "length_m": length_m, "time_s": time_s, "routing_type": "optimal"}


def try_backwards_routing(
    G: nx.Graph,
    src_node,
    dst_node,
    src_coords: Tuple[float, float],
    dst_coords: Tuple[float, float],
) -> Optional[List]:
    """
    Attempt backwards routing for delivery optimization.

    For deliveries to later holes (especially back 9), try routing backwards
    from the clubhouse toward hole 18, then finding shortcuts to the destination.
    """
    try:
        # Strategy 1: Look for intermediate waypoints that might provide shortcuts
        # For hole 16 deliveries, try routing via hole 18 area first

        # Identify potential waypoint nodes near hole 18 (end of the course)
        hole_18_area = (-84.5928762, 34.0380253)  # Approximate hole 18 coordinates
        waypoint_node = nearest_node(G, hole_18_area[0], hole_18_area[1])

        if waypoint_node and waypoint_node != src_node and waypoint_node != dst_node:
            # Try: clubhouse -> hole 18 area -> destination
            try:
                path1 = nx.shortest_path(G, src_node, waypoint_node, weight="length")
                path2 = nx.shortest_path(G, waypoint_node, dst_node, weight="length")

                # Combine paths, avoiding duplicate waypoint node
                combined_path = path1 + path2[1:]

                # Only return if this creates a meaningfully different route
                if (
                    len(combined_path)
                    < len(nx.shortest_path(G, src_node, dst_node, weight="length")) * 0.9
                ):
                    return combined_path

            except nx.NetworkXNoPath:
                pass

        # Strategy 2: Try multiple alternative waypoints
        # Look for nodes that might provide shortcuts based on golf course layout
        alternative_waypoints = [
            (-84.5930, 34.0380),  # Near clubhouse/hole 18
            (-84.5925, 34.0375),  # Alternative route start
            (-84.5920, 34.0370),  # Another potential waypoint
        ]

        for waypoint_coords in alternative_waypoints:
            waypoint = nearest_node(G, waypoint_coords[0], waypoint_coords[1])
            if waypoint and waypoint != src_node and waypoint != dst_node:
                try:
                    path1 = nx.shortest_path(G, src_node, waypoint, weight="length")
                    path2 = nx.shortest_path(G, waypoint, dst_node, weight="length")
                    combined_path = path1 + path2[1:]

                    if (
                        len(combined_path)
                        < len(nx.shortest_path(G, src_node, dst_node, weight="length")) * 0.85
                    ):
                        return combined_path

                except nx.NetworkXNoPath:
                    continue

    except Exception:
        pass

    return None
