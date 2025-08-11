#!/usr/bin/env python3
"""
Builds the cart path network strictly from existing cart path data,
without adding any automated shortcuts or connections. This ensures that all
routes adhere to the defined paths in the GeoJSON source.
"""
import sys
sys.path.insert(0, '.')

import json
import pickle
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Set
import math

import geopandas as gpd
import networkx as nx
import numpy as np
from shapely.geometry import Point, LineString, Polygon
from shapely.ops import nearest_points

from golfsim.data.osm_ingest import build_cartpath_graph
from golfsim.routing.networks import shortest_path_on_cartpaths, nearest_node


def haversine_distance(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Calculate distance in meters between two points using Haversine formula."""
    R = 6371000  # Earth radius in meters
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c


def analyze_network_connectivity(graph: nx.Graph, clubhouse_coords: Tuple[float, float], 
                               hole_coords: Dict[str, Dict], speed_mps: float = 6.0) -> Dict:
    """Analyze network connectivity and identify routing inefficiencies using optimal routing."""
    print("🔍 Analyzing network connectivity with optimal routing...")
    
    # Import optimal routing for consistent analysis
    from golfsim.routing.optimal_routing import find_optimal_route
    
    analysis = {
        "components": list(nx.connected_components(graph)),
        "routing_issues": [],
        "potential_shortcuts": []
    }
    
    print(f"   Network has {len(analysis['components'])} connected components")
    component_sizes = [len(c) for c in analysis["components"]]
    print(f"   Component sizes: {sorted(component_sizes, reverse=True)}")
    
    # Test routing to each hole and identify inefficiencies
    for hole_num, hole_info in hole_coords.items():
        tee_coords = hole_info["tee_coords"]
        
        # Use optimal routing for analysis
        route_result = find_optimal_route(graph, clubhouse_coords, tee_coords, speed_mps)
        
        if route_result["success"]:
            actual_distance = route_result["metrics"]["length_m"]
            efficiency_ratio = route_result["efficiency"] / 100.0  # Convert from percentage
            direct_distance = route_result["straight_line_distance"]
            detour_distance = actual_distance - direct_distance
            
            if efficiency_ratio < 0.4:  # Route is more than 2.5x longer than direct
                analysis["routing_issues"].append({
                    "hole": hole_num,
                    "actual_distance": actual_distance,
                    "direct_distance": direct_distance,
                    "efficiency_ratio": efficiency_ratio,
                    "detour_distance": detour_distance,
                    "severity": "high" if efficiency_ratio < 0.3 else "medium"
                })
                
                print(f"    Hole {hole_num}: {actual_distance:.0f}m route for {direct_distance:.0f}m direct ({efficiency_ratio:.2f} efficiency)")
        else:
            print(f"   Hole {hole_num}: Routing failed - {route_result['error']}")
            analysis["routing_issues"].append({
                "hole": hole_num,
                "error": route_result["error"],
                "severity": "critical"
            })
    
    return analysis


def find_open_endpoints(graph: nx.Graph) -> List:
    """Find nodes with degree 1 (open endpoints) in the cart path network."""
    return [node for node in graph.nodes() if graph.degree(node) == 1]


def find_closest_nodes_to_clubhouse(graph: nx.Graph, clubhouse_coords: Tuple[float, float], 
                                   nodes_to_check: List, max_distance: float = 1000.0) -> List:
    """Find nodes from the given list that are closest to the clubhouse within max_distance."""
    closest_nodes = []
    
    for node in nodes_to_check:
        node_data = graph.nodes[node]
        if 'x' in node_data and 'y' in node_data:
            distance = haversine_distance(
                clubhouse_coords[0], clubhouse_coords[1],
                node_data['x'], node_data['y']
            )
            if distance <= max_distance:
                closest_nodes.append({
                    'node': node,
                    'distance': distance,
                    'coords': (node_data['x'], node_data['y'])
                })
    
    # Sort by distance
    closest_nodes.sort(key=lambda x: x['distance'])
    return closest_nodes


def auto_connect_clubhouse_to_endpoints(cart_graph: nx.Graph, clubhouse_coords: Tuple[float, float],
                                       max_connection_distance: float = 500.0) -> nx.Graph:
    """
    Automatically connect the clubhouse to open endpoints in disconnected components.
    
    This ensures all cart path segments are reachable from the clubhouse for delivery routing.
    """
    print("🔗 Auto-connecting clubhouse to disconnected cart path segments...")
    
    # Find all connected components
    components = list(nx.connected_components(cart_graph))
    print(f"   Found {len(components)} connected components")
    
    if len(components) <= 1:
        print("   Network already fully connected, no connections needed")
        return cart_graph
    
    # Find which component contains the clubhouse
    clubhouse_node = nearest_node(cart_graph, clubhouse_coords[0], clubhouse_coords[1])
    clubhouse_component = None
    
    for i, component in enumerate(components):
        if clubhouse_node in component:
            clubhouse_component = i
            break
    
    if clubhouse_component is None:
        print("   Could not find clubhouse component, skipping auto-connection")
        return cart_graph
    
    print(f"   Clubhouse is in component {clubhouse_component} (size: {len(components[clubhouse_component])})")
    
    # Find open endpoints in each component
    all_endpoints = find_open_endpoints(cart_graph)
    
    # Group endpoints by component
    endpoint_by_component = {}
    for node in all_endpoints:
        for i, component in enumerate(components):
            if node in component:
                if i not in endpoint_by_component:
                    endpoint_by_component[i] = []
                endpoint_by_component[i].append(node)
                break
    
    connections_added = 0
    
    # Connect each disconnected component to the clubhouse component
    for comp_idx, component in enumerate(components):
        if comp_idx == clubhouse_component:
            continue  # Skip the clubhouse component
        
        print(f"   🔍 Processing component {comp_idx} (size: {len(component)})")
        
        # Get endpoints for this component
        comp_endpoints = endpoint_by_component.get(comp_idx, [])
        clubhouse_endpoints = endpoint_by_component.get(clubhouse_component, [])
        
        if not comp_endpoints or not clubhouse_endpoints:
            print(f"      No endpoints found for connection")
            continue
        
        # Find the shortest connection between this component and clubhouse component
        best_connection = None
        min_distance = float('inf')
        
        for comp_node in comp_endpoints:
            for club_node in clubhouse_endpoints:
                comp_data = cart_graph.nodes[comp_node]
                club_data = cart_graph.nodes[club_node]
                
                if 'x' in comp_data and 'y' in comp_data and 'x' in club_data and 'y' in club_data:
                    distance = haversine_distance(
                        comp_data['x'], comp_data['y'],
                        club_data['x'], club_data['y']
                    )
                    
                    if distance < min_distance and distance <= max_connection_distance:
                        min_distance = distance
                        best_connection = {
                            'comp_node': comp_node,
                            'club_node': club_node,
                            'distance': distance,
                            'comp_coords': (comp_data['x'], comp_data['y']),
                            'club_coords': (club_data['x'], club_data['y'])
                        }
        
        # Add the connection if found
        if best_connection:
            comp_node = best_connection['comp_node']
            club_node = best_connection['club_node']
            distance = best_connection['distance']
            
            # Add edge between the nodes
            cart_graph.add_edge(comp_node, club_node, length=distance)
            connections_added += 1
            
            print(f"      Connected to clubhouse: {distance:.1f}m")
            print(f"         From: ({best_connection['comp_coords'][0]:.6f}, {best_connection['comp_coords'][1]:.6f})")
            print(f"         To:   ({best_connection['club_coords'][0]:.6f}, {best_connection['club_coords'][1]:.6f})")
        else:
            print(f"      No suitable connection found (max distance: {max_connection_distance}m)")
    
    print(f"   Added {connections_added} automatic clubhouse connections")
    
    # Verify connectivity after connections
    final_components = list(nx.connected_components(cart_graph))
    print(f"   📊 Final network: {len(final_components)} components (was {len(components)})")
    
    return cart_graph


def build_base_cart_network(data_dir: Path, auto_connect_clubhouse: bool = None) -> nx.Graph:
    """Builds the base cart path network from GeoJSON data with optional auto-connections."""
    print(" Building cart path network from source data...")
    
    # Define paths for different data types
    config_dir = data_dir / "config"
    geojson_dir = data_dir / "geojson"

    # Load course data
    with open(config_dir / "simulation_config.json", 'r') as f:
        config = json.load(f)
    
    # Load course polygon
    course_poly_gdf = gpd.read_file(geojson_dir / "course_polygon.geojson").to_crs(4326)
    course_polygon = course_poly_gdf.geometry.iloc[0]
    
    # Build initial cart graph
    print("Building initial cart path graph...")
    cart_graph = build_cartpath_graph(
        course_poly=course_polygon,
        cartpath_geojson=str(geojson_dir / "cart_paths_connected.geojson"),
        broaden=False
    )
    
    print(f"   Graph built: {cart_graph.number_of_nodes()} nodes, {cart_graph.number_of_edges()} edges")
    
    # Determine auto-connect setting from config or parameter
    network_params = config.get("network_params", {})
    if auto_connect_clubhouse is None:
        auto_connect_clubhouse = network_params.get("auto_connect_clubhouse", True)
    
    # Auto-connect clubhouse to disconnected components if enabled
    if auto_connect_clubhouse and network_params.get("connect_on_network_build", True):
        clubhouse_coords = (config["clubhouse"]["longitude"], config["clubhouse"]["latitude"])
        max_distance = network_params.get("max_connection_distance_m", 500.0)
        cart_graph = auto_connect_clubhouse_to_endpoints(cart_graph, clubhouse_coords, max_distance)
    
    return cart_graph


def add_delivery_shortcuts(cart_graph: nx.Graph, clubhouse_coords: Tuple[float, float], 
                          hole_coords: Dict[str, Dict], max_shortcut_distance: float = 800.0) -> nx.Graph:
    """
    Add direct shortcuts from clubhouse to holes for efficient delivery routing.
    
    This adds edges that allow delivery runners to go directly to later holes
    instead of following the sequential golf path through holes 1-9.
    """
    print(" Adding delivery shortcuts to cart network...")
    
    # Find the nearest node to the clubhouse
    clubhouse_node = nearest_node(cart_graph, clubhouse_coords[0], clubhouse_coords[1])
    clubhouse_data = cart_graph.nodes[clubhouse_node]
    print(f"   Clubhouse node: ({clubhouse_data['x']:.6f}, {clubhouse_data['y']:.6f})")
    
    shortcuts_added = 0
    
    # Add shortcuts to holes that are inefficiently routed
    for hole_num, hole_info in hole_coords.items():
        hole_coords_tuple = hole_info["tee_coords"]
        
        # Calculate direct distance from clubhouse to hole
        direct_distance = haversine_distance(
            clubhouse_coords[0], clubhouse_coords[1],
            hole_coords_tuple[0], hole_coords_tuple[1]
        )
        
        # Only add shortcuts for holes within reasonable distance
        if direct_distance <= max_shortcut_distance:
            # Find nearest node to this hole
            hole_node = nearest_node(cart_graph, hole_coords_tuple[0], hole_coords_tuple[1])
            hole_data = cart_graph.nodes[hole_node]
            
            # Use optimal routing to evaluate existing routes before adding shortcuts
            from golfsim.routing.optimal_routing import find_optimal_route
            
            existing_route = find_optimal_route(cart_graph, clubhouse_coords, hole_coords_tuple, 6.0)
            if existing_route["success"]:
                efficiency = existing_route["efficiency"] / 100.0  # Convert from percentage
                
                # Add shortcut if routing is inefficient (< 90% efficiency) for optimal delivery times
                efficiency_threshold = 0.90  # Maximum threshold for shortest possible routes
                
                if efficiency < efficiency_threshold:
                    # Add direct edge between clubhouse and hole nodes
                    if not cart_graph.has_edge(clubhouse_node, hole_node):
                        cart_graph.add_edge(clubhouse_node, hole_node, length=direct_distance)
                        shortcuts_added += 1
                        print(f"   Added shortcut to hole {hole_num}: {direct_distance:.0f}m (was {existing_route['metrics']['length_m']:.0f}m, {efficiency:.1%} efficiency)")
                else:
                    print(f"   ✓ Hole {hole_num}: {efficiency:.1%} efficiency - no shortcut needed")
            else:
                print(f"    Could not analyze hole {hole_num}: {existing_route['error']}")
                # Add shortcut anyway for unreachable holes
                if not cart_graph.has_edge(clubhouse_node, hole_node):
                    cart_graph.add_edge(clubhouse_node, hole_node, length=direct_distance)
                    shortcuts_added += 1
                    print(f"   Added shortcut to unreachable hole {hole_num}: {direct_distance:.0f}m")
    
    print(f"   Added {shortcuts_added} delivery shortcuts")
    return cart_graph


def validate_network_with_optimal_routing(graph: nx.Graph, clubhouse_coords: Tuple[float, float], 
                                        hole_coords: Dict[str, Dict]) -> Dict:
    """
    Validate entire network using optimal routing logic.
    
    Returns comprehensive analysis of routing efficiency to all holes.
    """
    from golfsim.routing.optimal_routing import find_optimal_route
    
    print("🔍 Validating network with optimal routing...")
    
    validation_results = {
        "total_holes": len(hole_coords),
        "successful_routes": 0,
        "failed_routes": [],
        "efficiency_stats": [],
        "recommendations": []
    }
    
    for hole_num, hole_info in hole_coords.items():
        tee_coords = hole_info["tee_coords"]
        
        route_result = find_optimal_route(graph, clubhouse_coords, tee_coords, 6.0)
        
        if route_result["success"]:
            validation_results["successful_routes"] += 1
            validation_results["efficiency_stats"].append({
                "hole": hole_num,
                "efficiency": route_result["efficiency"],
                "distance_m": route_result["metrics"]["length_m"],
                "time_min": route_result["metrics"]["time_min"]
            })
        else:
            validation_results["failed_routes"].append({
                "hole": hole_num,
                "error": route_result["error"]
            })
    
    # Generate recommendations
    if validation_results["efficiency_stats"]:
        avg_efficiency = sum(stat["efficiency"] for stat in validation_results["efficiency_stats"]) / len(validation_results["efficiency_stats"])
        low_efficiency_holes = [stat for stat in validation_results["efficiency_stats"] if stat["efficiency"] < 60]
        
        validation_results["recommendations"].append(f"Average network efficiency: {avg_efficiency:.1f}%")
        
        if low_efficiency_holes:
            validation_results["recommendations"].append(f"Consider adding shortcuts for {len(low_efficiency_holes)} holes with <60% efficiency")
        
        if validation_results["failed_routes"]:
            validation_results["recommendations"].append(f"Fix connectivity issues for {len(validation_results['failed_routes'])} unreachable holes")
    
    print(f"   Validated routes to {validation_results['successful_routes']}/{validation_results['total_holes']} holes")
    if validation_results["failed_routes"]:
        print(f"    {len(validation_results['failed_routes'])} holes unreachable")
    
    return validation_results


def main():
    """Main function to build the cart network from source data."""
    parser = argparse.ArgumentParser(description="Build cart path network from source GeoJSON data")
    parser.add_argument("course_dir", nargs="?", default="courses/pinetree_country_club",
                       help="Course directory containing GeoJSON files")
    parser.add_argument("--save-graph", action="store_true", default=True,
                       help="Save the graph as cart_graph.pkl (default: True)")
    parser.add_argument("--analyze", action="store_true", default=False,
                       help="Analyze routing efficiency to each hole")
    parser.add_argument("--add-shortcuts", action="store_true", default=False,
                       help="Add delivery shortcuts for efficient routing")
    parser.add_argument("--no-auto-connect", action="store_true", default=False,
                       help="Disable automatic clubhouse connections to disconnected components")
    
    args = parser.parse_args()
    
    course_dir = Path(args.course_dir)
    if not course_dir.exists():
        print(f"Course directory not found: {course_dir}")
        return 1

    pkl_dir = course_dir / "pkl"
    geojson_dir = course_dir / "geojson"
    config_dir = course_dir / "config"
    
    try:
        # Build the base cart network with auto-connection (unless disabled)
        # Command line flag overrides config settings
        auto_connect = None if not args.no_auto_connect else False
        cart_graph = build_base_cart_network(course_dir, auto_connect_clubhouse=auto_connect)
        
        # Analyze routing if requested
        if args.analyze:
            print("\n🔍 Analyzing routing efficiency...")
            
            # Load configuration and hole data
            with open(config_dir / "simulation_config.json", 'r') as f:
                config = json.load(f)
            
            clubhouse_coords = (config["clubhouse"]["longitude"], config["clubhouse"]["latitude"])
            
            # Load hole coordinates (using hole centroids)
            holes_gdf = gpd.read_file(geojson_dir / "holes.geojson").to_crs(4326)
            hole_coords = {}
            
            for _, hole in holes_gdf.iterrows():
                hole_num = str(hole.get('ref', 'unknown'))
                if hole_num != 'unknown':
                    centroid = hole.geometry.centroid
                    hole_coords[hole_num] = {
                        "tee_coords": (centroid.x, centroid.y)
                    }
            
            # Test routing to hole 9 specifically
            if '9' in hole_coords:
                hole_9_coords = hole_coords['9']['tee_coords']
                print(f"\nTesting route from clubhouse to hole 9...")
                print(f"   Clubhouse: {clubhouse_coords}")
                print(f"   Hole 9: {hole_9_coords}")
                
                try:
                    route_result = shortest_path_on_cartpaths(cart_graph, clubhouse_coords, hole_9_coords, 6.0)
                    actual_distance = route_result["length_m"]
                    num_nodes = len(route_result["nodes"])
                    
                    # Calculate direct distance
                    direct_distance = haversine_distance(
                        clubhouse_coords[0], clubhouse_coords[1],
                        hole_9_coords[0], hole_9_coords[1]
                    )
                    
                    efficiency_ratio = direct_distance / actual_distance
                    
                    print(f"   📏 Direct distance: {direct_distance:.0f}m")
                    print(f"    Actual route: {actual_distance:.0f}m ({num_nodes} nodes)")
                    print(f"   📊 Efficiency: {efficiency_ratio:.2f} ({efficiency_ratio*100:.1f}%)")
                    
                    if efficiency_ratio < 0.5:
                        print(f"    INEFFICIENT ROUTING: Route is {actual_distance/direct_distance:.1f}x longer than direct!")
                        print(f"   🔧 This suggests the cart network requires sequential traversal")
                        
                        # Show first few and last few nodes to understand the path
                        print(f"   🗺️  Route path (first 5 nodes):")
                        for i, node in enumerate(route_result["nodes"][:5]):
                            node_data = cart_graph.nodes[node]
                            print(f"      {i+1}: ({node_data.get('x', 'N/A'):.6f}, {node_data.get('y', 'N/A'):.6f})")
                        
                        if num_nodes > 10:
                            print(f"   ... ({num_nodes-10} intermediate nodes)")
                            print(f"   🗺️  Route path (last 5 nodes):")
                            for i, node in enumerate(route_result["nodes"][-5:]):
                                node_data = cart_graph.nodes[node]
                                print(f"      {num_nodes-5+i+1}: ({node_data.get('x', 'N/A'):.6f}, {node_data.get('y', 'N/A'):.6f})")
                    
                except Exception as e:
                    print(f"   Routing to hole 9 failed: {e}")
            
            # Perform full network analysis
            analysis = analyze_network_connectivity(cart_graph, clubhouse_coords, hole_coords)
            
            # Add delivery shortcuts if requested
            if args.add_shortcuts:
                print("\n Adding delivery shortcuts...")
                cart_graph = add_delivery_shortcuts(cart_graph, clubhouse_coords, hole_coords)
                
                # Re-analyze after adding shortcuts
                print("\n🔍 Re-analyzing network after shortcuts...")
                analysis = analyze_network_connectivity(cart_graph, clubhouse_coords, hole_coords)
                
                # Validate network with optimal routing
                validation_results = validate_network_with_optimal_routing(cart_graph, clubhouse_coords, hole_coords)
                
                # Print validation summary
                print("\n📊 Network Validation Summary:")
                for recommendation in validation_results["recommendations"]:
                    print(f"   • {recommendation}")
        
        # Save the graph if requested
        if args.save_graph:
            output_path = pkl_dir / "cart_graph.pkl"
            with open(output_path, 'wb') as f:
                pickle.dump(cart_graph, f)
            print(f"💾 Saved graph to {output_path}")
        
        print("Network build complete!")
        
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
