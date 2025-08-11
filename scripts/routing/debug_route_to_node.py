#!/usr/bin/env python3
"""
Dynamic route finder for golf cart delivery optimization.
Find the fastest route from clubhouse to any specified node ID.
"""

import sys
import pickle
import json
import networkx as nx
import matplotlib.pyplot as plt
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import numpy as np
import argparse

sys.path.append('.')

from golfsim.routing.networks import nearest_node
from golfsim.logging import init_logging, get_logger
from utils.cli import add_log_level_argument

logger = get_logger(__name__)

def load_course_data() -> Dict:
    """Load cart graph and clubhouse coordinates."""
    course_dir = Path("courses/pinetree_country_club")
    
    # Load cart graph
    cart_graph_path = course_dir / "pkl" / "cart_graph.pkl"
    with open(cart_graph_path, 'rb') as f:
        cart_graph = pickle.load(f)
    
    # Load clubhouse coordinates
    config_path = course_dir / "config" / "simulation_config.json"
    with open(config_path, 'r') as f:
        config = json.load(f)
        clubhouse_coords = (config["clubhouse"]["longitude"], config["clubhouse"]["latitude"])
    
    return {
        'cart_graph': cart_graph,
        'clubhouse_coords': clubhouse_coords
    }

def get_node_coordinates(graph: nx.Graph, node_id: int) -> Tuple[float, float]:
    """Get coordinates for a specific node ID."""
    nodes = list(graph.nodes())
    if node_id >= len(nodes):
        raise ValueError(f"Node ID {node_id} exceeds graph size ({len(nodes)} nodes)")
    
    node = nodes[node_id]
    node_data = graph.nodes[node]
    return (node_data['x'], node_data['y'])

def calculate_path_metrics(graph: nx.Graph, path: List, speed_mps: float = 6.0) -> Dict:
    """Calculate total length and travel time for a path."""
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
        "num_segments": len(path) - 1
    }

def find_optimal_route_cli(graph: nx.Graph, clubhouse_coords: Tuple[float, float], 
                          target_node_id: int, speed_mps: float = 6.0) -> Dict:
    """
    CLI wrapper for optimal routing with node ID interface.
    """
    # Import from centralized module instead of local implementation
    from golfsim.routing.optimal_routing import find_optimal_route_with_node_id
    
    logger.info(f"FINDING OPTIMAL ROUTE: Clubhouse → Node {target_node_id}")
    logger.info("=" * 60)
    
    route_result = find_optimal_route_with_node_id(graph, clubhouse_coords, target_node_id, speed_mps)
    
    if route_result["success"]:
        # Get additional data for display
        clubhouse_node = nearest_node(graph, clubhouse_coords[0], clubhouse_coords[1])
        clubhouse_node_id = list(graph.nodes()).index(clubhouse_node)
        target_coords = route_result["target_coords"]
        
        logger.info(f"Start: Clubhouse (Node {clubhouse_node_id}) at {clubhouse_coords}")
        logger.info(f"Target: Node {target_node_id} at {target_coords}")
        logger.info(f"Straight-line distance: {route_result['straight_line_distance']:.1f} meters")
        
        metrics = route_result["metrics"]
        efficiency = route_result["efficiency"]
        
        logger.info("Optimal route found!")
        logger.info(f"   • Path efficiency: {efficiency:.1f}% (vs. straight line)")
        logger.info(f"   • Route distance: {metrics['length_m']:.1f} meters")
        logger.info(f"   • Travel time: {metrics['time_min']:.1f} minutes ({metrics['time_s']:.1f} seconds)")
        logger.info(f"   • Path segments: {metrics['num_segments']} segments through {len(route_result['path'])} nodes")
        
        # Show key waypoints (first 10 and last 5 nodes)
        path_ids = route_result["path_ids"]
        if len(path_ids) > 15:
            waypoint_display = ' → '.join(map(str, path_ids[:10])) + ' → ... → ' + ' → '.join(map(str, path_ids[-5:]))
        else:
            waypoint_display = ' → '.join(map(str, path_ids))
        logger.info(f"   • Route: {waypoint_display}")
        
        # Identify key waypoints (every ~10% of the route)
        key_waypoints = []
        waypoint_interval = max(1, len(path_ids) // 8)  # 8 waypoints max
        for i in range(0, len(path_ids), waypoint_interval):
            if i < len(path_ids):
                waypoint_coords = get_node_coordinates(graph, path_ids[i])
                key_waypoints.append({
                    'node_id': path_ids[i],
                    'coords': waypoint_coords,
                    'position': i / (len(path_ids) - 1) * 100  # Percentage along route
                })
        
        if len(key_waypoints) > 2:  # More than just start and end
            logger.info("Key waypoints along route:")
            for waypoint in key_waypoints[1:-1]:  # Skip start and end
                logger.info(f"      Node {waypoint['node_id']} at {waypoint['coords']} ({waypoint['position']:.0f}% of route)")
        
        # Add key waypoints to result
        route_result["key_waypoints"] = key_waypoints
        route_result["clubhouse_node_id"] = clubhouse_node_id
        
        return route_result
    else:
        return route_result

def visualize_route(graph: nx.Graph, route_result: Dict, clubhouse_coords: Tuple[float, float], 
                   target_node_id: int, output_path: str = None):
    """Create visualization of the optimal route."""
    
    if not route_result["success"]:
        logger.error(f"Cannot visualize: {route_result['error']}")
        return
    
    logger.info("Creating route visualization...")
    
    fig, ax = plt.subplots(1, 1, figsize=(18, 14))
    
    # Plot all cart path edges as background network
    all_edges = list(graph.edges())
    for u, v in all_edges:
        u_data = graph.nodes[u]
        v_data = graph.nodes[v]
        
        if 'x' in u_data and 'y' in u_data and 'x' in v_data and 'y' in v_data:
            x_coords = [u_data['x'], v_data['x']]
            y_coords = [u_data['y'], v_data['y']]
            ax.plot(x_coords, y_coords, color='lightgray', linewidth=0.8, alpha=0.4, zorder=1)
    
    # Plot the optimal route
    path = route_result["path"]
    route_x = [graph.nodes[node]['x'] for node in path]
    route_y = [graph.nodes[node]['y'] for node in path]
    
    # Plot route with gradient color (start blue, end red)
    for i in range(len(route_x) - 1):
        progress = i / (len(route_x) - 1)
        color = plt.cm.coolwarm(progress)  # Blue to red gradient
        ax.plot([route_x[i], route_x[i+1]], [route_y[i], route_y[i+1]], 
               color=color, linewidth=4, alpha=0.8, zorder=3)
    
    # Plot key points
    # Clubhouse
    ax.scatter([clubhouse_coords[0]], [clubhouse_coords[1]], c='green', s=300, 
              marker='*', edgecolors='black', linewidth=2, zorder=6, label='Clubhouse (Start)')
    
    # Target node
    target_coords = route_result["target_coords"]
    ax.scatter([target_coords[0]], [target_coords[1]], c='red', s=200, 
              marker='D', edgecolors='black', linewidth=2, zorder=6, label=f'Node {target_node_id} (Target)')
    
    # Key waypoints
    key_waypoints = route_result["key_waypoints"]
    if len(key_waypoints) > 2:
        waypoint_coords = [wp['coords'] for wp in key_waypoints[1:-1]]
        waypoint_x = [coord[0] for coord in waypoint_coords]
        waypoint_y = [coord[1] for coord in waypoint_coords]
        
        ax.scatter(waypoint_x, waypoint_y, c='orange', s=80, 
                  marker='o', edgecolors='black', linewidth=1, zorder=5, 
                  label='Key Waypoints', alpha=0.8)
        
        # Label key waypoints
        for waypoint in key_waypoints[1:-1]:
            if waypoint['position'] % 25 < 5:  # Label roughly every 25% of route
                ax.annotate(f"Node {waypoint['node_id']}", waypoint['coords'], 
                           xytext=(8, 8), textcoords='offset points',
                           fontsize=9, ha='left', va='bottom',
                           bbox=dict(boxstyle='round,pad=0.2', facecolor='orange', alpha=0.7))
    
    # Add labels for start and end points
    ax.annotate('CLUBHOUSE\n(START)', clubhouse_coords, xytext=(15, 15), 
               textcoords='offset points', fontsize=12, ha='left', va='bottom', weight='bold',
               bbox=dict(boxstyle='round,pad=0.4', facecolor='green', alpha=0.8, edgecolor='black'),
               color='white', zorder=8)
    
    ax.annotate(f'NODE {target_node_id}\n(TARGET)', target_coords, xytext=(15, -25), 
               textcoords='offset points', fontsize=12, ha='left', va='top', weight='bold',
               bbox=dict(boxstyle='round,pad=0.4', facecolor='red', alpha=0.8, edgecolor='black'),
               color='white', zorder=8)
    
    # Add straight-line reference
    ax.plot([clubhouse_coords[0], target_coords[0]], [clubhouse_coords[1], target_coords[1]], 
           color='purple', linewidth=2, linestyle='--', alpha=0.6, zorder=2, 
           label='Straight Line (Reference)')
    
    # Set plot properties
    metrics = route_result["metrics"]
    efficiency = route_result["efficiency"]
    
    ax.set_title(f"Optimal Route: Clubhouse → Node {target_node_id}\n" +
                f"Distance: {metrics['length_m']:.1f}m | Time: {metrics['time_min']:.1f}min | " +
                f"Efficiency: {efficiency:.1f}%", 
                fontsize=16, weight='bold', pad=20)
    
    ax.set_xlabel("Longitude", fontsize=14)
    ax.set_ylabel("Latitude", fontsize=14)
    ax.set_aspect('equal')
    ax.grid(True, linestyle='--', alpha=0.3)
    ax.legend(loc='best', fontsize=11)
    
    # Add info box
    info_text = f"""Route Details:
• Total Distance: {metrics['length_m']:.1f} m
• Travel Time: {metrics['time_min']:.1f} min
• Path Segments: {metrics['num_segments']}
• Route Efficiency: {efficiency:.1f}%
• Straight Line: {route_result['straight_line_distance']:.1f} m"""
    
    ax.text(0.02, 0.98, info_text, transform=ax.transAxes, 
            verticalalignment='top', fontsize=11,
            bbox=dict(boxstyle='round,pad=0.5', facecolor='white', alpha=0.9, edgecolor='gray'))
    
    # Save visualization
    if output_path is None:
        output_path = f"outputs/route_to_node_{target_node_id}.png"
    
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(output_file, bbox_inches='tight', facecolor='white', dpi=300)
    plt.close()
    
    logger.info(f"Route visualization saved to: {output_file}")

def interactive_mode(graph: nx.Graph, clubhouse_coords: Tuple[float, float]):
    """Interactive mode for multiple route queries."""
    logger.info("INTERACTIVE MODE")
    logger.info("=" * 50)
    logger.info("Enter node IDs to find optimal routes from the clubhouse.")
    logger.info(f"Valid node IDs: 0 to {graph.number_of_nodes()-1}")
    logger.info("Type 'quit' or 'exit' to stop, 'help' for commands.")
    
    while True:
        try:
            user_input = input(f"\nEnter target node ID: ").strip().lower()
            
            if user_input in ['quit', 'exit', 'q']:
                logger.info("Goodbye!")
                break
            elif user_input in ['help', 'h']:
                logger.info("Available commands:")
                logger.info(f"  • Enter any number (0-{graph.number_of_nodes()-1}) to find route")
                logger.info("  • 'quit' or 'exit' to stop")
                logger.info("  • 'help' for this message")
                continue
            
            # Try to parse as integer
            target_node_id = int(user_input)
            
            # Find route
            route_result = find_optimal_route_cli(graph, clubhouse_coords, target_node_id)
            
            if route_result["success"]:
                # Ask if user wants visualization
                viz_input = input("📊 Create visualization? (y/n): ").strip().lower()
                if viz_input in ['y', 'yes']:
                    visualize_route(graph, route_result, clubhouse_coords, target_node_id)
            else:
                logger.error(route_result['error'])
                
        except ValueError:
            logger.warning(f"Invalid input. Please enter a number between 0 and {graph.number_of_nodes()-1}")
        except KeyboardInterrupt:
            logger.info("Goodbye!")
            break
        except Exception as e:
            logger.error(f"Error: {e}")

def main():
    """Main function with command line interface."""
    parser = argparse.ArgumentParser(
        description="Find optimal routes from clubhouse to any node in the golf cart network",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/find_route_to_any_node.py --node 200
  python scripts/find_route_to_any_node.py --node 150 --visualize
  python scripts/find_route_to_any_node.py --interactive
  python scripts/find_route_to_any_node.py --node 300 --speed 8.0
        """
    )
    
    parser.add_argument("--node", "-n", type=int, 
                       help="Target node ID to find route to")
    parser.add_argument("--interactive", "-i", action="store_true",
                       help="Start interactive mode for multiple queries")
    parser.add_argument("--visualize", "-v", action="store_true",
                       help="Create visualization of the route")
    parser.add_argument("--speed", "-s", type=float, default=6.0,
                       help="Cart speed in m/s (default: 6.0)")
    parser.add_argument("--output", "-o", type=str,
                       help="Output path for visualization (default: auto-generated)")
    add_log_level_argument(parser)
    
    args = parser.parse_args()
    init_logging(args.log_level)
    
    try:
        logger.info("GOLF CART ROUTE OPTIMIZER")
        logger.info("=" * 50)
        logger.info("Loading course data...")
        
        data = load_course_data()
        cart_graph = data['cart_graph']
        clubhouse_coords = data['clubhouse_coords']
        
        logger.info(f"Loaded cart network: {cart_graph.number_of_nodes():,} nodes, {cart_graph.number_of_edges():,} edges")
        logger.info(f"Clubhouse location: {clubhouse_coords}")
        
        if args.interactive:
            interactive_mode(cart_graph, clubhouse_coords)
        elif args.node is not None:
            # Single route query
            route_result = find_optimal_route_cli(cart_graph, clubhouse_coords, args.node, args.speed)
            
            if route_result["success"]:
                if args.visualize:
                    visualize_route(cart_graph, route_result, clubhouse_coords, args.node, args.output)
                    
                logger.info(f"SUMMARY FOR NODE {args.node}:")
                logger.info(f"   • Distance: {route_result['metrics']['length_m']:.1f} meters")
                logger.info(f"   • Time: {route_result['metrics']['time_min']:.1f} minutes")
                logger.info(f"   • Efficiency: {route_result['efficiency']:.1f}% vs straight line")
            else:
                print(f"{route_result['error']}")
        else:
            # No specific arguments, show help
            parser.print_help()
            logger.info("Tip: Try '--interactive' mode for exploring multiple routes!")
            
    except FileNotFoundError as e:
        logger.error(f"Course data not found: {e}")
        logger.error("Make sure you're in the correct directory with cart_graph.pkl available")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
