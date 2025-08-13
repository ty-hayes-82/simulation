"""
Matplotlib visualization utilities for golf delivery simulation.

This module provides reusable plotting functions for creating delivery route
visualizations, course maps, and simulation result plots.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point

from ..logging import get_logger
from golfsim.utils.time import format_time_from_baseline

logger = get_logger(__name__)

# Set matplotlib style for better looking plots
plt.style.use('default')
plt.rcParams['figure.dpi'] = 300
plt.rcParams['font.size'] = 10
plt.rcParams['axes.titlesize'] = 14
plt.rcParams['axes.labelsize'] = 12
plt.rcParams['legend.fontsize'] = 10


def load_course_geospatial_data(course_dir: str | Path) -> Dict:
    """Load geospatial course data (holes, greens, cart paths, etc.)."""
    course_path = Path(course_dir)
    geojson_path = course_path / "geojson"
    
    course_data = {}
    
    # Load all available geospatial features
    geojson_files = {
        'course_polygon': 'course_polygon.geojson',
        'holes': 'holes.geojson', 
        'cart_paths': 'cart_paths.geojson',
        'greens': 'greens.geojson',
        'tees': 'tees.geojson',
    }
    
    for feature_name, filename in geojson_files.items():
        file_path = geojson_path / filename
        if file_path.exists():
            try:
                course_data[feature_name] = gpd.read_file(file_path).to_crs(4326)
                logger.debug("Loaded %s: %d features", feature_name, len(course_data[feature_name]))
            except Exception as e:
                logger.warning("Failed to load %s: %s", file_path, e)
    
    return course_data


def calculate_course_bounds(geospatial_data: Dict) -> Tuple[float, float, float, float]:
    """Calculate the bounds of the entire golf course from all geospatial features.
    
    Returns:
        Tuple of (lon_min, lon_max, lat_min, lat_max)
    """
    all_lons = []
    all_lats = []

    # Extract coordinates from all geospatial features
    for feature_name, gdf in geospatial_data.items():
        if gdf is not None and len(gdf) > 0:
            for _, feature in gdf.iterrows():
                geom = feature.geometry

                if geom.geom_type == "Point":
                    all_lons.append(geom.x)
                    all_lats.append(geom.y)
                elif geom.geom_type == "LineString":
                    coords = list(geom.coords)
                    all_lons.extend([coord[0] for coord in coords])
                    all_lats.extend([coord[1] for coord in coords])
                elif geom.geom_type == "Polygon":
                    coords = list(geom.exterior.coords)
                    all_lons.extend([coord[0] for coord in coords])
                    all_lats.extend([coord[1] for coord in coords])
                elif geom.geom_type == "MultiPolygon":
                    for poly in geom.geoms:
                        coords = list(poly.exterior.coords)
                        all_lons.extend([coord[0] for coord in coords])
                        all_lats.extend([coord[1] for coord in coords])

    if all_lons and all_lats:
        return min(all_lons), max(all_lons), min(all_lats), max(all_lats)
    else:
        # Fallback bounds if no data
        logger.warning("No geospatial data found, using fallback bounds")
        return -84.60, -84.58, 34.025, 34.05


def plot_course_boundary(ax, geospatial_data: Dict):
    """Plot only the course boundary - clean minimal style."""
    if 'course_polygon' not in geospatial_data:
        return
        
    course_poly = geospatial_data['course_polygon']
    for idx, feature in course_poly.iterrows():
        if feature.geometry.geom_type == "MultiPolygon":
            for poly_idx, poly in enumerate(feature.geometry.geoms):
                x, y = poly.exterior.xy
                label = 'Course Boundary' if idx == 0 and poly_idx == 0 else ""
                ax.plot(x, y, color='lightgray', linewidth=1.5, alpha=0.8, label=label)
        elif feature.geometry.geom_type == "Polygon":
            x, y = feature.geometry.exterior.xy
            label = 'Course Boundary' if idx == 0 else ""
            ax.plot(x, y, color='lightgray', linewidth=1.5, alpha=0.8, label=label)


def plot_course_features(ax, geospatial_data: Dict, include_holes: bool = True, include_greens: bool = True):
    """Plot detailed course features including holes, greens, tees, etc."""
    
    # Course boundary
    plot_course_boundary(ax, geospatial_data)

    # Greens (plot first so they appear as background)
    if include_greens and 'greens' in geospatial_data:
        greens = geospatial_data['greens']
        for idx, green in greens.iterrows():
            if green.geometry.geom_type == "Polygon":
                x, y = green.geometry.exterior.xy
                ax.fill(
                    x, y,
                    color='lightgreen',
                    alpha=0.7,
                    edgecolor='darkgreen',
                    linewidth=1,
                    label='Greens' if idx == 0 else "",
                )

    # Holes (fairways)
    if include_holes and 'holes' in geospatial_data:
        holes = geospatial_data['holes']
        for idx, hole in holes.iterrows():
            if hole.geometry.geom_type == "LineString":
                x, y = hole.geometry.xy
                hole_ref = hole.get('ref', str(idx + 1))
                ax.plot(
                    x, y,
                    color='saddlebrown',
                    linewidth=2,  # Made thinner as requested
                    alpha=0.8,
                    label='Holes' if idx == 0 else "",
                )

                # Add hole number label at the start of each hole
                start_point = Point(x[0], y[0])
                ax.annotate(
                    f'#{hole_ref}',
                    (start_point.x, start_point.y),
                    fontsize=10,
                    ha='center',
                    va='center',
                    weight='bold',
                    bbox=dict(
                        boxstyle="round,pad=0.3", 
                        facecolor='white', 
                        alpha=0.9, 
                        edgecolor='black'
                    ),
                )

    # Tees
    if 'tees' in geospatial_data:
        tees = geospatial_data['tees']
        for idx, tee in tees.iterrows():
            if tee.geometry.geom_type == "Point":
                ax.plot(
                    tee.geometry.x,
                    tee.geometry.y,
                    's',
                    color='darkgreen',
                    markersize=6,
                    alpha=0.9,
                    label='Tees' if idx == 0 else "",
                )

    # Cart paths (if available as geojson)
    if 'cart_paths' in geospatial_data:
        cart_paths = geospatial_data['cart_paths']
        for idx, path in cart_paths.iterrows():
            if path.geometry.geom_type == "LineString":
                x, y = path.geometry.xy
                ax.plot(
                    x, y,
                    color='lightgray',
                    linewidth=1,
                    alpha=0.4,
                    label='Cart Paths' if idx == 0 else "",
                )


def plot_cart_network(ax, cart_graph: nx.Graph, alpha: float = 0.3, color: str = 'lightgray'):
    """Plot the cart path network from NetworkX graph."""
    if cart_graph is None:
        return
        
    for u, v in cart_graph.edges():
        u_coords = (cart_graph.nodes[u]["x"], cart_graph.nodes[u]["y"])
        v_coords = (cart_graph.nodes[v]["x"], cart_graph.nodes[v]["y"])
        ax.plot(
            [u_coords[0], v_coords[0]],
            [u_coords[1], v_coords[1]],
            color=color,
            linewidth=1,
            alpha=alpha,
        )


def plot_golfer_path(ax, golfer_df: pd.DataFrame, results: Dict):
    """Plot the golfer's movement path during the round."""
    golfer_positions = golfer_df[golfer_df['type'] == 'golfer'].copy()

    if len(golfer_positions) == 0:
        return

    # Plot golfer path with clean blue line
    lons = golfer_positions['longitude'].values
    lats = golfer_positions['latitude'].values

    ax.plot(
        lons, lats,
        color='blue',
        linewidth=3,
        alpha=0.9,
        label='Golfer Path',
        linestyle='-',
        zorder=5,
    )

    # Mark order placement location prominently with star
    order_pos = results.get('golfer_position', [None, None])
    if order_pos[0] is not None:
        ax.plot(
            order_pos[0], order_pos[1],
            '*',
            markersize=16,
            color='red',
            label='Order Placed Here',
            markeredgecolor='darkred',
            markeredgewidth=1,
            zorder=10,
        )

        # Add text annotation with order timing
        order_time = results.get('order_time_s', 0) / 60
        ax.annotate(
            f'Order: {order_time:.1f} min\ninto round',
            (order_pos[0], order_pos[1]),
            xytext=(10, -20),
            textcoords='offset points',
            ha='left',
            va='top',
            fontsize=9,
            weight='bold',
            bbox=dict(boxstyle="round,pad=0.3", facecolor='yellow', alpha=0.9, edgecolor='orange'),
            color='black',
        )

    # Mark start position with green circle
    ax.plot(
        lons[0], lats[0],
        'o',
        markersize=12,
        color='green',
        label='Golfer Start (Tee 1)',
        markeredgecolor='darkgreen',
        markeredgewidth=2,
        zorder=10,
    )


def plot_runner_route(ax, runner_df: Optional[pd.DataFrame], results: Dict, course_data: Dict, clubhouse_coords: Tuple[float, float], cart_graph=None):
    """Plot the runner's delivery route with start, path, and end points."""
    
    # If we have actual runner coordinates, use them
    if runner_df is not None and len(runner_df) > 0:
        runner_positions = runner_df[runner_df['type'] == 'delivery-runner'].copy()
        
        if len(runner_positions) > 0:
            lons = runner_positions['longitude'].values
            lats = runner_positions['latitude'].values

            # Plot the complete delivery route in orange
            ax.plot(
                lons, lats,
                color='orange',
                linewidth=5,
                alpha=0.9,
                label='Delivery Runner Path',
                linestyle='-',
                zorder=6,
            )
            
            # Add directional arrows
            if len(lons) > 3:
                arrow_indices = [len(lons)//4, len(lons)//2, 3*len(lons)//4]
                for idx in arrow_indices:
                    if idx < len(lons) - 1:
                        ax.annotate(
                            '', xy=(lons[idx+1], lats[idx+1]), 
                            xytext=(lons[idx], lats[idx]),
                            arrowprops=dict(arrowstyle='->', color='darkorange', lw=2),
                            zorder=7
                        )
            return
    
    # If no runner coordinates, create delivery routes using cart path network
    orders = results.get('orders', [])
    delivery_stats = results.get('delivery_stats', [])
    
    if not orders:
        return
        
    # Get hole locations for approximation
    hole_locations = {}
    if 'holes' in course_data:
        holes_gdf = course_data['holes']
        for idx, hole in holes_gdf.iterrows():
            hole_ref = hole.get('ref', str(idx + 1))
            if hole.geometry.geom_type == "LineString":
                midpoint = hole.geometry.interpolate(0.5, normalized=True)
                hole_locations[int(hole_ref)] = (midpoint.x, midpoint.y)
    
    # Use cart_graph parameter directly (passed from render_delivery_plot)
    
    # Draw delivery routes for each order
    for i, order in enumerate(orders):
        hole_num = order.get('hole_num')
        if hole_num and hole_num in hole_locations:
            hole_location = hole_locations[hole_num]
            
            # If we have cart graph, try to find the actual cart path route
            if cart_graph is not None:
                try:
                    import networkx as nx
                    
                    # Find nearest nodes in cart graph to clubhouse and hole location
                    clubhouse_node = _find_nearest_cart_node(cart_graph, clubhouse_coords)
                    hole_node = _find_nearest_cart_node(cart_graph, hole_location)
                    
                    if clubhouse_node and hole_node:
                        try:
                            # Find shortest path using cart network
                            path = nx.shortest_path(cart_graph, clubhouse_node, hole_node, weight='length')
                            
                            # Extract coordinates for the path
                            path_coords = []
                            for node in path:
                                node_data = cart_graph.nodes[node]
                                path_coords.append((node_data['x'], node_data['y']))
                            
                            if len(path_coords) > 1:
                                # Plot the cart path route
                                xs, ys = zip(*path_coords)
                                ax.plot(
                                    xs, ys,
                                    color='orange',
                                    linewidth=4,
                                    alpha=0.8,
                                    linestyle='-',
                                    label='Delivery Route (Cart Path)' if i == 0 else "",
                                    zorder=6,
                                )
                                
                                # Add arrows along the path
                                _add_path_arrows(ax, path_coords)
                                continue  # Skip straight line fallback
                                
                        except (nx.NetworkXNoPath, nx.NodeNotFound):
                            pass  # Fall back to straight line if no path found
                            
                except ImportError:
                    pass  # NetworkX not available, fall back to straight line
            
            # Fallback: Draw straight line from clubhouse to delivery location
            ax.plot(
                [clubhouse_coords[0], hole_location[0]], 
                [clubhouse_coords[1], hole_location[1]],
                color='orange',
                linewidth=3,
                alpha=0.7,
                linestyle='--',
                label='Delivery Route (Straight Line)' if i == 0 else "",
                zorder=6,
            )
            
            # Add arrow to show direction
            mid_x = (clubhouse_coords[0] + hole_location[0]) / 2
            mid_y = (clubhouse_coords[1] + hole_location[1]) / 2
            dx = hole_location[0] - clubhouse_coords[0]
            dy = hole_location[1] - clubhouse_coords[1]
            
            ax.annotate(
                '', xy=(mid_x + dx*0.1, mid_y + dy*0.1), 
                xytext=(mid_x - dx*0.1, mid_y - dy*0.1),
                arrowprops=dict(arrowstyle='->', color='darkorange', lw=2),
                zorder=7
            )


def render_beverage_cart_plot(
    coordinates: List[Dict],
    course_dir: str | Path,
    save_path: str | Path,
    title: str = "Beverage Cart Route",
) -> None:
    """Render beverage cart coordinates over the course map to a PNG file.

    Parameters
    ----------
    coordinates:
        List of dict entries with 'longitude', 'latitude', and optionally 'timestamp' and 'current_hole'.
    course_dir:
        Path to course directory containing geojson data.
    save_path:
        Output PNG path.
    title:
        Plot title.
    """
    course_dir = Path(course_dir)
    save_path = Path(save_path)

    course_data = load_course_geospatial_data(course_dir)

    fig, ax = plt.subplots(figsize=(10, 8))

    # Plot features (holes and greens helpful for context)
    plot_course_features(ax, course_data, include_holes=True, include_greens=True)

    # Extract lon/lat
    if coordinates:
        lons = [c.get('longitude') for c in coordinates if c.get('longitude') is not None]
        lats = [c.get('latitude') for c in coordinates if c.get('latitude') is not None]
        if len(lons) > 1:
            ax.plot(
                lons,
                lats,
                color='purple',
                linewidth=2.5,
                alpha=0.9,
                label='Beverage Cart',
                zorder=6,
            )

            # Start and end markers
            ax.plot(lons[0], lats[0], 'o', color='green', markersize=8, label='Start', zorder=7)
            ax.plot(lons[-1], lats[-1], 'X', color='red', markersize=8, label='End', zorder=7)

    # Bounds
    lon_min, lon_max, lat_min, lat_max = calculate_course_bounds(course_data)
    ax.set_xlim(lon_min, lon_max)
    ax.set_ylim(lat_min, lat_max)

    # Use actual longitude/latitude on axes and prevent skewing
    ax.set_xlabel('Longitude')
    ax.set_ylabel('Latitude')
    ax.xaxis.set_major_formatter(mticker.ScalarFormatter(useMathText=False))
    ax.yaxis.set_major_formatter(mticker.ScalarFormatter(useMathText=False))
    ax.ticklabel_format(style='plain', axis='both', useOffset=False)
    ax.set_aspect('equal', adjustable='box')
    ax.set_title(title)
    ax.legend(loc='upper right')
    ax.grid(True, alpha=0.2)

    save_path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close(fig)


def _find_nearest_cart_node(cart_graph, target_coords):
    """Find the nearest node in the cart graph to the target coordinates."""
    if not cart_graph or not cart_graph.nodes:
        return None
        
    min_distance = float('inf')
    nearest_node = None
    
    for node, data in cart_graph.nodes(data=True):
        if 'x' in data and 'y' in data:
            # Calculate distance
            dx = data['x'] - target_coords[0]
            dy = data['y'] - target_coords[1]
            distance = (dx*dx + dy*dy)**0.5
            
            if distance < min_distance:
                min_distance = distance
                nearest_node = node
                
    return nearest_node


def _add_path_arrows(ax, path_coords):
    """Add directional arrows along a path."""
    if len(path_coords) < 2:
        return
        
    # Add arrows at regular intervals along the path
    num_arrows = min(3, len(path_coords) - 1)
    if num_arrows <= 0:
        return
        
    interval = len(path_coords) // (num_arrows + 1)
    
    for i in range(1, num_arrows + 1):
        idx = i * interval
        if idx < len(path_coords) - 1:
            start = path_coords[idx]
            end = path_coords[idx + 1]
            
            ax.annotate(
                '', xy=end, xytext=start,
                arrowprops=dict(arrowstyle='->', color='darkorange', lw=2),
                zorder=7
            )


def plot_key_locations(ax, results: Dict, clubhouse_coords: Tuple[float, float], course_data: Dict):
    """Plot key locations including clubhouse, order locations, and delivery points."""
    # Clubhouse with red square
    ax.plot(
        clubhouse_coords[0], clubhouse_coords[1],
        's',
        markersize=12,
        color='red',
        label='Clubhouse',
        markeredgecolor='darkred',
        markeredgewidth=2,
        zorder=10,
    )
    
    # Plot order placement locations and delivery points
    orders = results.get('orders', [])
    delivery_stats = results.get('delivery_stats', [])
    
    # For multi-golfer simulations, approximate order locations using hole data
    # Try to get hole locations from course data
    hole_locations = {}
    if 'holes' in course_data:
        holes_gdf = course_data['holes']
        for idx, hole in holes_gdf.iterrows():
            hole_ref = hole.get('ref', str(idx + 1))
            if hole.geometry.geom_type == "LineString":
                # Use midpoint of hole as approximate order location
                midpoint = hole.geometry.interpolate(0.5, normalized=True)
                hole_locations[int(hole_ref)] = (midpoint.x, midpoint.y)
    
    for i, order in enumerate(orders):
        # First try to get golfer position when order was placed (if available from single-golfer sim)
        golfer_coords = results.get('golfer_coordinates', [])
        order_time = order.get('order_time_s', 0)
        
        order_position = None
        for coord in golfer_coords:
            if coord.get('timestamp') == order_time:
                order_position = (coord.get('longitude'), coord.get('latitude'))
                break
        
        # If no exact coordinates, estimate where golfer was when order was placed
        # Orders are typically placed 1-3 holes before delivery
        if not order_position:
            hole_num = order.get('hole_num')
            order_time_s = order.get('order_time_s', 0)
            tee_time_s = None
            
            # Find the golfer's tee time from group data
            golfer_group_id = order.get('golfer_group_id')
            if golfer_group_id:
                # Try to get group info from results metadata or estimate
                # Estimate based on order time (golfers play ~12 min per hole)
                if order_time_s > 0:
                    # Estimate how many holes into the round the golfer was when ordering
                    # Assuming they started at tee time and play 12 min/hole
                    # We need to work backwards from delivery hole to order placement hole
                    
                    # Estimate golfer was 1-2 holes before delivery when they placed order
                    estimated_order_hole = max(1, hole_num - 2)  # 1-2 holes before delivery
                    
                    if estimated_order_hole != hole_num and estimated_order_hole in hole_locations:
                        order_position = hole_locations[estimated_order_hole]
                    elif hole_num and hole_num in hole_locations:
                        # Fallback to delivery hole if estimation fails
                        order_position = hole_locations[hole_num]
        
        if order_position:
            # Mark where order was placed with blue circle
            ax.plot(
                order_position[0], order_position[1],
                'o',
                markersize=10,
                color='blue',
                label='Order Placed' if i == 0 else "",
                markeredgecolor='darkblue',
                markeredgewidth=2,
                zorder=9,
            )
            
            # Add order number annotation with placement info
            estimated_order_hole = max(1, hole_num - 2) if hole_num else 1
            annotation_text = f'Order {order.get("order_id", i+1)}\n(placed ~hole {estimated_order_hole})'
            
            ax.annotate(
                annotation_text,
                (order_position[0], order_position[1]),
                xytext=(5, 5),
                textcoords='offset points',
                fontsize=7,
                color='darkblue',
                weight='bold',
                zorder=11,
                ha='left',
                va='bottom'
            )
    
    # Plot actual delivery locations
    # First try single-golfer sim predicted delivery location
    predicted_delivery = results.get('predicted_delivery_location', [None, None])
    if predicted_delivery[0] is not None:
        ax.plot(
            predicted_delivery[0], predicted_delivery[1],
            'D',  # Diamond shape for delivery
            markersize=12,
            color='green',
            label='Delivery Location',
            markeredgecolor='darkgreen',
            markeredgewidth=2,
            zorder=10,
        )
    else:
        # For multi-golfer sims, show delivery locations as hole locations
        for i, order in enumerate(orders):
            hole_num = order.get('hole_num')
            if hole_num and hole_num in hole_locations:
                delivery_location = hole_locations[hole_num]
                ax.plot(
                    delivery_location[0], delivery_location[1],
                    'D',  # Diamond shape for delivery
                    markersize=10,
                    color='green',
                    label='Delivery Location' if i == 0 else "",
                    markeredgecolor='darkgreen',
                    markeredgewidth=2,
                    zorder=10,
                )


def setup_plot_styling(ax, results: Dict, course_name: str, clubhouse_coords: Tuple[float, float], 
                      course_bounds: Optional[Tuple[float, float, float, float]] = None):
    """Set up plot with clean styling, bounds, labels, and legend."""
    
    # Calculate bounds from key points if not provided
    if not course_bounds:
        all_lons = [clubhouse_coords[0]]
        all_lats = [clubhouse_coords[1]]

        order_pos = results.get('golfer_position', [None, None])
        if order_pos[0] is not None:
            all_lons.append(order_pos[0])
            all_lats.append(order_pos[1])

        predicted_delivery = results.get('predicted_delivery_location', [None, None])
        if predicted_delivery[0] is not None:
            all_lons.append(predicted_delivery[0])
            all_lats.append(predicted_delivery[1])

        # Set reasonable bounds with margin
        if len(all_lons) > 1:
            lon_margin = (max(all_lons) - min(all_lons)) * 0.15
            lat_margin = (max(all_lats) - min(all_lats)) * 0.15
            ax.set_xlim(min(all_lons) - lon_margin, max(all_lons) + lon_margin)
            ax.set_ylim(min(all_lats) - lat_margin, max(all_lats) + lat_margin)
    else:
        lon_min, lon_max, lat_min, lat_max = course_bounds
        # Add some margin for better visualization
        lon_margin = (lon_max - lon_min) * 0.08
        lat_margin = (lat_max - lat_min) * 0.08
        ax.set_xlim(lon_min - lon_margin, lon_max + lon_margin)
        ax.set_ylim(lat_min - lat_margin, lat_max + lat_margin)

    # Create informative title based on simulation results
    orders = results.get('orders', [])
    agg_metrics = results.get('aggregate_metrics', {})
    
    if len(orders) == 1:
        # Single order - show specific details
        order_time = results.get('order_time_s', 0) / 60
        service_time = results.get('total_service_time_s', 0) / 60
        delivery_distance = results.get('delivery_distance_m', 0)
        ax.set_title(
            f'{course_name} - Golf Delivery Simulation\n'
            f'Order placed at {order_time:.1f} min, delivered in {service_time:.1f} min\n'
            f'Delivery distance: {delivery_distance:.0f}m',
            fontsize=16,
            pad=20,
            weight='bold',
        )
    else:
        # Multiple orders - show aggregate statistics
        total_orders = len(orders)
        processed = agg_metrics.get('orders_processed', 0)
        failed = agg_metrics.get('orders_failed', 0)
        avg_order_time = agg_metrics.get('average_order_time_s', 0) / 60
        total_distance = agg_metrics.get('total_delivery_distance_m', 0)
        
        ax.set_title(
            f'{course_name} - Golf Delivery Simulation\n'
            f'{total_orders} orders total: {processed} delivered, {failed} failed\n'
            f'Average order time: {avg_order_time:.1f} min, Total distance: {total_distance:.0f}m',
            fontsize=16,
            pad=20,
            weight='bold',
        )

    ax.set_xlabel('Longitude', fontsize=12)
    ax.set_ylabel('Latitude', fontsize=12)
    ax.grid(True, alpha=0.3)

    # Force plain decimal format for axes to avoid scientific notation
    ax.xaxis.set_major_formatter(mticker.ScalarFormatter(useMathText=False))
    ax.yaxis.set_major_formatter(mticker.ScalarFormatter(useMathText=False))
    ax.ticklabel_format(style='plain', axis='both', useOffset=False)

    # Position legend outside the plot area on the right
    ax.legend(loc='center left', bbox_to_anchor=(1.02, 0.5), fontsize=10)
    ax.set_aspect('equal')


def render_individual_order_maps(results: Dict, course_data: Dict, clubhouse_coords: Tuple[float, float],
                               runner_coords: Optional[pd.DataFrame] = None,
                               cart_graph: Optional[nx.Graph] = None,
                               output_dir: str | Path = ".",
                               course_name: str = "Golf Course",
                               style: str = "simple") -> List[Path]:
    """
    Create individual delivery maps for each delivered order.
    
    Args:
        results: Simulation results dictionary
        course_data: Dictionary containing geospatial course data
        clubhouse_coords: Tuple of (longitude, latitude) for clubhouse
        runner_coords: DataFrame with runner position tracking (optional)
        cart_graph: Cart path network graph (optional)
        output_dir: Directory to save individual order maps
        course_name: Name of the golf course
        style: Visualization style ("simple" or "detailed")
        
    Returns:
        List of paths to saved individual order visualization files
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    saved_paths = []
    orders = results.get('orders', [])
    
    # Filter to only delivered orders (status == "processed")
    delivered_orders = [order for order in orders if order.get('status') == 'processed']
    
    logger.info("Total orders: %d, Delivered orders: %d", len(orders), len(delivered_orders))
    logger.info("Creating %d individual order maps in: %s", len(delivered_orders), output_dir)
    
    # Helpers to locate hole-related points from GeoDataFrames
    def _get_green_centroid(hole_num_val: int) -> Optional[Tuple[float, float]]:
        try:
            greens_gdf = course_data.get('greens')
            if greens_gdf is not None and len(greens_gdf) > 0 and 'ref' in greens_gdf.columns:
                rows = greens_gdf[greens_gdf['ref'].astype(str) == str(hole_num_val)]
                if len(rows) > 0:
                    geom = rows.iloc[0].geometry
                    centroid = geom.centroid
                    return (float(centroid.x), float(centroid.y))
        except Exception:
            pass
        return None

    def _get_hole_start_end(hole_num_val: int) -> Tuple[Optional[Tuple[float, float]], Optional[Tuple[float, float]]]:
        start_pt = None
        end_pt = None
        try:
            holes_gdf = course_data.get('holes')
            if holes_gdf is not None and len(holes_gdf) > 0:
                # property may be 'ref' as string
                ref_col = 'ref' if 'ref' in holes_gdf.columns else None
                if ref_col is not None:
                    rows = holes_gdf[holes_gdf[ref_col].astype(str) == str(hole_num_val)]
                else:
                    rows = holes_gdf.iloc[0:0]
                if len(rows) > 0:
                    line = rows.iloc[0].geometry
                    if line is not None and hasattr(line, 'coords'):
                        coords = list(line.coords)
                        if len(coords) >= 2:
                            start_pt = (float(coords[0][0]), float(coords[0][1]))
                            end_pt = (float(coords[-1][0]), float(coords[-1][1]))
        except Exception:
            pass
        return start_pt, end_pt

    def _get_tee_point(hole_num_val: int) -> Optional[Tuple[float, float]]:
        try:
            tees_gdf = course_data.get('tees')
            if tees_gdf is not None and len(tees_gdf) > 0 and 'ref' in tees_gdf.columns:
                rows = tees_gdf[tees_gdf['ref'].astype(str) == str(hole_num_val)]
                if len(rows) > 0:
                    geom = rows.iloc[0].geometry
                    if geom.geom_type == 'Point':
                        return (float(geom.x), float(geom.y))
        except Exception:
            pass
        return None

    for order in delivered_orders:
        order_id = order.get('order_id', 'unknown')
        hole_num = order.get('hole_num', 'unknown')
        golfer_id = order.get('golfer_id', 'unknown')
        # Per-order stats (drive time, queue delay)
        ds_list = results.get('delivery_stats', []) or []
        ds = next((d for d in ds_list if str(d.get('order_id')) == str(order_id)), None)
        delivery_time_s = float(ds.get('delivery_time_s', 0.0)) if ds else 0.0
        queue_delay_s = float(ds.get('queue_delay_s', 0.0)) if ds else 0.0
        
        # Create figure for this specific order
        fig, ax = plt.subplots(1, 1, figsize=(12, 10))
        
        # Plot course features
        if style == "simple":
            plot_course_boundary(ax, course_data)
        else:
            plot_course_features(ax, course_data)
        
        # Plot cart network if available
        if cart_graph:
            plot_cart_network(ax, cart_graph, alpha=0.3)
        
        # Plot clubhouse
        ax.plot(
            clubhouse_coords[0], clubhouse_coords[1],
            's',
            markersize=12,
            color='red',
            label='Clubhouse',
            markeredgecolor='darkred',
            markeredgewidth=2,
            zorder=10,
        )
        
        # Find placed and delivery locations using GeoDataFrames
        logger.info("Order %s: Looking for hole %s", order_id, hole_num)
        hole_start, hole_end = _get_hole_start_end(int(hole_num))
        tee_point = _get_tee_point(int(hole_num))
        green_centroid = _get_green_centroid(int(hole_num))

        placed_location = tee_point or hole_start
        # Delivery target priority: green centroid > hole end > midpoint of hole line
        delivery_location = green_centroid or hole_end
        if not delivery_location and hole_start is not None and hole_end is not None:
            delivery_location = ((hole_start[0] + hole_end[0]) / 2.0, (hole_start[1] + hole_end[1]) / 2.0)
        if not delivery_location:
            logger.warning("Order %s: Could not find delivery location for hole %s", order_id, hole_num)
        
        # Plot order placed location
        if placed_location:
            ax.plot(
                placed_location[0], placed_location[1],
                'o', markersize=10, color='blue', label='Order Placed', zorder=10,
            )
            ax.annotate(
                f'Placed (Hole {hole_num})', xy=placed_location, xytext=(10, -15),
                textcoords='offset points', fontsize=9, bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.7),
            )
            # Show order placed clock time if available
            try:
                _order_time_s = int(float(order.get('order_time_s', 0) or 0))
                if _order_time_s > 0:
                    _clock = format_time_from_baseline(_order_time_s)
                    ax.annotate(
                        f'{_clock}', xy=placed_location, xytext=(10, -32),
                        textcoords='offset points', fontsize=9, color='black',
                        bbox=dict(boxstyle='round,pad=0.2', facecolor='white', alpha=0.9),
                    )
            except Exception:
                pass

        # Delivered marker: draw only at actual route end when available; else fallback
        delivered_marker_xy = None
        fallback_delivery_location = delivery_location
        
        # Plot runner path for this specific order if coordinates are available
        if runner_coords is not None and len(runner_coords) > 0:
            # Prefer precise delivery window from delivery_stats: clubhouse -> golfer leg
            order_time_s = float(order.get('order_time_s', 0) or 0)
            completion_time_s = float(order.get('total_completion_time_s', 0) or 0)

            if ds is not None:
                delivered_at = float(ds.get('delivered_at_time_s', order_time_s + completion_time_s) or 0)
                delivery_time = float(ds.get('delivery_time_s', completion_time_s) or 0)
                start_time = delivered_at - delivery_time
                end_time = delivered_at
            else:
                # Fallback to broad window around order
                start_time = order_time_s - 300
                end_time = order_time_s + completion_time_s + 300
            
            # Check available time column (could be 'time_s' or 'timestamp')
            time_col = None
            if 'time_s' in runner_coords.columns:
                time_col = 'time_s'
            elif 'timestamp' in runner_coords.columns:
                time_col = 'timestamp'
            
            if time_col:
                order_coords = runner_coords[
                    (runner_coords[time_col] >= start_time) &
                    (runner_coords[time_col] <= end_time) &
                    (runner_coords['type'].str.lower().isin(['runner','delivery-runner']))
                ].copy()
                
                if len(order_coords) > 0:
                    # If we know the exact delivered_at time, trim path to that precise point
                    if ds is not None:
                        try:
                            delivered_at = float(ds.get('delivered_at_time_s', end_time) or end_time)
                            times_arr = order_coords[time_col].astype(float).to_numpy()
                            if len(times_arr) > 0:
                                nearest_idx = int(np.argmin(np.abs(times_arr - delivered_at)))
                                if nearest_idx >= 0:
                                    order_coords = order_coords.iloc[: nearest_idx + 1]
                        except Exception:
                            pass

                    lons = order_coords['longitude'].values
                    lats = order_coords['latitude'].values
                    
                    # Plot the delivery route for this order
                    ax.plot(
                        lons, lats,
                        color='orange',
                        linewidth=4,
                        alpha=0.8,
                        label='Delivery Path',
                        linestyle='-',
                        zorder=6,
                    )
                    # Ensure delivered marker exactly matches route end
                    if len(lons) > 0:
                        end_xy = (float(lons[-1]), float(lats[-1]))
                        # Draw delivered marker only here (no duplicate at predicted spot)
                        delivered_marker_xy = end_xy
                        ax.plot(
                            end_xy[0], end_xy[1],
                            'D', markersize=12, color='green', label='Delivered',
                            markeredgecolor='darkgreen', markeredgewidth=2, zorder=12,
                        )
                        ax.annotate(
                            f'Order {order_id} delivered', xy=end_xy, xytext=(10, 10),
                            textcoords='offset points', bbox=dict(boxstyle='round,pad=0.3', facecolor='lightgreen', alpha=0.8),
                            fontsize=10, fontweight='bold', zorder=13
                        )

                        # Ensure path shows from clubhouse -> first point if not already there
                        try:
                            dx = abs(lons[0] - clubhouse_coords[0])
                            dy = abs(lats[0] - clubhouse_coords[1])
                            if dx + dy > 0.0005:  # ~50m threshold
                                ax.plot([clubhouse_coords[0], lons[0]], [clubhouse_coords[1], lats[0]],
                                        color='orange', linewidth=3, alpha=0.5, linestyle='--', zorder=5,
                                        label='Clubhouse to Route')
                        except Exception:
                            pass
        
        # If we didn't draw from route end, fallback to delivery location
        if delivered_marker_xy is None and fallback_delivery_location is not None:
            delivered_marker_xy = fallback_delivery_location
            ax.plot(
                delivered_marker_xy[0], delivered_marker_xy[1],
                'D', markersize=12, color='green', label='Delivered',
                markeredgecolor='darkgreen', markeredgewidth=2, zorder=10,
            )
            ax.annotate(
                f'Order {order_id} delivered', xy=delivered_marker_xy, xytext=(10, 10),
                textcoords='offset points', bbox=dict(boxstyle='round,pad=0.3', facecolor='lightgreen', alpha=0.8),
                fontsize=10, fontweight='bold', zorder=11
            )

        # Set up plot styling
        course_bounds = calculate_course_bounds(course_data)
        
        # Title and labels
        title = f"{course_name} - Order {order_id} Delivery\nGolfer {golfer_id} - Hole {hole_num}"
        
        if 'total_completion_time_s' in order:
            completion_time_min = order['total_completion_time_s'] / 60
            title += f" - Completion: {completion_time_min:.1f} min"
        # Append drive time, pre-return, and backlog queue delay if available
        if delivery_time_s > 0:
            title += f" — Drive: {delivery_time_s/60:.1f} min"
        if ds is not None:
            pre_return = float(ds.get('pre_return_time_s', 0.0) or 0.0)
            if pre_return > 0:
                title += f" — Return-to-clubhouse: {pre_return/60:.1f} min"
        if queue_delay_s > 0:
            title += f" — Queue: {queue_delay_s/60:.1f} min"
            
        ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
        ax.set_xlabel('Longitude', fontsize=12)
        ax.set_ylabel('Latitude', fontsize=12)
        
        # Set bounds with some padding
        if course_bounds:
            # calculate_course_bounds returns (lon_min, lon_max, lat_min, lat_max)
            lon_min, lon_max, lat_min, lat_max = course_bounds
            padding = 0.001
            ax.set_xlim(lon_min - padding, lon_max + padding)
            ax.set_ylim(lat_min - padding, lat_max + padding)
        
        ax.grid(True, alpha=0.3)
        # Build a concise legend without background layers or route start/end
        handles, labels = ax.get_legend_handles_labels()
        allowed = {
            'Clubhouse', 'Order Placed', 'Delivered', 'Delivery Path', 'Clubhouse to Route'
        }
        filtered = [(h, l) for h, l in zip(handles, labels) if l in allowed]
        if filtered:
            fh, fl = zip(*filtered)
            ax.legend(fh, fl, loc='upper right', fontsize=10)
        ax.set_aspect('equal')
        
        # Save the individual order map
        order_filename = f"order_{order_id}_hole_{hole_num}_delivery_map.png"
        save_path = output_dir / order_filename
        
        plt.tight_layout()
        plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='white')
        plt.close()
        
        saved_paths.append(save_path)
        logger.info("Saved individual order map: %s", save_path)
    
    logger.info("Generated %d individual order maps", len(saved_paths))
    return saved_paths


def render_delivery_plot(results: Dict, course_data: Dict, clubhouse_coords: Tuple[float, float],
                        golfer_coords: Optional[pd.DataFrame] = None, 
                        runner_coords: Optional[pd.DataFrame] = None,
                        cart_graph: Optional[nx.Graph] = None,
                        save_path: str | Path = "delivery_visualization.png",
                        course_name: str = "Golf Course",
                        style: str = "simple") -> Path:
    """
    Create a comprehensive delivery route visualization.
    
    Args:
        results: Simulation results dictionary
        course_data: Dictionary containing geospatial course data
        clubhouse_coords: Tuple of (longitude, latitude) for clubhouse
        golfer_coords: DataFrame with golfer position tracking (optional)
        runner_coords: DataFrame with runner position tracking (optional)
        save_path: Output file path
        course_name: Name of the golf course
        style: Visualization style ("simple" or "detailed")
        
    Returns:
        Path to saved visualization file
    """
    save_path = Path(save_path)
    
    logger.info("Creating delivery visualization: %s", save_path)
    
    # Create figure with single panel layout
    fig, ax = plt.subplots(1, 1, figsize=(16, 12))

    # Plot course features (boundary only for clean look)
    if style == "simple":
        plot_course_boundary(ax, course_data)
    else:
        plot_course_features(ax, course_data)
    
    # Plot cart network if available
    if cart_graph:
        plot_cart_network(ax, cart_graph, alpha=0.4)

    # Plot golfer path
    if golfer_coords is not None:
        plot_golfer_path(ax, golfer_coords, results)

    # Plot runner delivery route (pass cart_graph directly to avoid JSON serialization issues)
    plot_runner_route(ax, runner_coords, results, course_data, clubhouse_coords, cart_graph)

    # Plot key locations
    plot_key_locations(ax, results, clubhouse_coords, course_data)

    # Set up styling and bounds
    course_bounds = calculate_course_bounds(course_data)
    setup_plot_styling(ax, results, course_name, clubhouse_coords, course_bounds)

    # Save the plot
    save_path.parent.mkdir(parents=True, exist_ok=True)
    plt.tight_layout()
    plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()
    
    logger.info("Saved delivery visualization: %s (%.1f KB)", save_path, save_path.stat().st_size / 1024)
    return save_path


def create_timeline_visualization(results: Dict, save_path: str | Path = "timeline.png") -> Path:
    """Create a timeline showing key delivery events."""
    save_path = Path(save_path)
    
    fig, ax = plt.subplots(1, 1, figsize=(12, 4))
    
    # Key timestamps
    order_time = results.get('order_time_s', 0)
    prep_completed = results.get('prep_completed_s', 0) 
    delivered = results.get('delivered_s', 0)
    returned = results.get('runner_returned_s', 0)

    # Convert to minutes for readability
    times = [t / 60 for t in [order_time, prep_completed, delivered, returned] if t > 0]
    events = ['Order\nPlaced', 'Prep\nComplete', 'Delivery\nMade', 'Runner\nReturned'][:len(times)]
    colors = ['red', 'orange', 'green', 'blue'][:len(times)]

    # Plot timeline
    ax.scatter(times, [1] * len(times), c=colors, s=200, alpha=0.8)

    for i, (time, event, color) in enumerate(zip(times, events, colors)):
        ax.annotate(
            f'{event}\n{time:.1f} min',
            (time, 1),
            xytext=(0, 30),
            textcoords='offset points',
            ha='center',
            va='bottom',
            fontsize=9,
            bbox=dict(boxstyle="round,pad=0.3", facecolor=color, alpha=0.3),
        )

    # Connect with lines
    for i in range(len(times) - 1):
        ax.plot([times[i], times[i + 1]], [1, 1], 'k-', alpha=0.5, linewidth=2)

    ax.set_xlim(min(times) - 5, max(times) + 5)
    ax.set_ylim(0.5, 1.5)
    ax.set_xlabel('Time (minutes into round)')
    ax.set_title('Delivery Timeline', fontsize=14)
    ax.set_yticks([])
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close()
    
    logger.info("Saved timeline visualization: %s", save_path)
    return save_path
