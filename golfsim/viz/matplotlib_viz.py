"""
Matplotlib visualization utilities for golf delivery simulation.

This module provides reusable plotting functions for creating delivery route
visualizations, course maps, and simulation result plots.
"""

from __future__ import annotations

import json
import pickle
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import networkx as nx
import numpy as np
import pandas as pd
from shapely.geometry import LineString, Point

from ..logging import get_logger
from ..performance_logger import timed_visualization, timed_file_io

logger = get_logger(__name__)

# Set matplotlib style for better looking plots
plt.style.use('default')
plt.rcParams['figure.dpi'] = 300
plt.rcParams['font.size'] = 10
plt.rcParams['axes.titlesize'] = 14
plt.rcParams['axes.labelsize'] = 12
plt.rcParams['legend.fontsize'] = 10


# Global cache for course geospatial data
_COURSE_DATA_CACHE = {}

def clear_course_data_cache():
    """Clear the course data cache to free memory."""
    global _COURSE_DATA_CACHE
    _COURSE_DATA_CACHE.clear()
    logger.debug("Cleared course data cache")

def load_course_geospatial_data(course_dir: str | Path) -> Dict:
    """Load geospatial course data (holes, greens, cart paths, etc.) with caching."""
    course_path = Path(course_dir)
    cache_key = str(course_path.resolve())
    
    # Return cached data if available
    if cache_key in _COURSE_DATA_CACHE:
        logger.debug("Using cached course data for %s", course_path.name)
        return _COURSE_DATA_CACHE[cache_key]
    
    with timed_file_io("load_geospatial_data"):
        geojson_path = course_path / "geojson"
        
        course_data = {}
        
        # Load all available geospatial features
        geojson_files = {
            'course_polygon': 'course_polygon.geojson',
            'holes': 'generated/holes_geofenced.geojson',  # Use the geofenced version
            'cart_paths': 'cart_paths.geojson',
            'greens': 'greens.geojson',
            'tees': 'tees.geojson',
        }
        
        for feature_name, filename in geojson_files.items():
            file_path = geojson_path / filename
            if file_path.exists():
                try:
                    with timed_file_io(f"load_{feature_name}_geojson"):
                        course_data[feature_name] = gpd.read_file(file_path).to_crs(4326)
                    logger.debug("Loaded %s: %d features", feature_name, len(course_data[feature_name]))
                except Exception as e:
                    logger.warning("Failed to load %s: %s", file_path, e)
        
        # Cache the loaded data
        _COURSE_DATA_CACHE[cache_key] = course_data
        logger.debug("Cached course data for %s", course_path.name)
        
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

    # Mark start position with blue circle
    ax.plot(
        lons[0], lats[0],
        'o',
        markersize=12,
        color='blue',
        label='Golfer Start (Tee 1)',
        markeredgecolor='darkblue',
        markeredgewidth=2,
        zorder=10,
    )


def plot_runner_route(ax, runner_df: Optional[pd.DataFrame], results: Dict, course_data: Dict, clubhouse_coords: Tuple[float, float], cart_graph=None):
    """
    Plot the runner's delivery route and return the coordinates used for plotting.
    
    Returns:
        A tuple of (outbound_coords, return_coords)
    """
    
    outbound_coords = []
    return_coords = []

    # Priority 1: Use actual routing data from simulation if available
    if 'trip_to_golfer' in results and 'trip_back' in results:
        trip_to_golfer = results['trip_to_golfer']
        trip_back = results['trip_back']
        
        if 'nodes' in trip_to_golfer and len(trip_to_golfer['nodes']) > 1:
            # Plot the actual route taken to golfer
            
            for node in trip_to_golfer['nodes']:
                # Handle both node ID format and coordinate pair format
                if isinstance(node, (list, tuple)) and len(node) == 2:
                    # Direct coordinate pair: [lon, lat]
                    outbound_coords.append((node[0], node[1]))
                elif cart_graph and node in cart_graph.nodes:
                    # Node ID that needs lookup in cart graph
                    node_data = cart_graph.nodes[node]
                    if 'x' in node_data and 'y' in node_data:
                        outbound_coords.append((node_data['x'], node_data['y']))
            
            if len(outbound_coords) > 1:
                xs, ys = zip(*outbound_coords)
                ax.plot(
                    xs, ys,
                    color='orange',
                    linewidth=4,
                    alpha=0.8,
                    linestyle='-',
                    label='Delivery Route (Cart Path)',
                    zorder=6,
                )
                _add_path_arrows(ax, outbound_coords)
        
        if 'nodes' in trip_back and len(trip_back['nodes']) > 1:
            # Plot the actual return route
            
            for node in trip_back['nodes']:
                # Handle both node ID format and coordinate pair format
                if isinstance(node, (list, tuple)) and len(node) == 2:
                    # Direct coordinate pair: [lon, lat]
                    return_coords.append((node[0], node[1]))
                elif cart_graph and node in cart_graph.nodes:
                    # Node ID that needs lookup in cart graph
                    node_data = cart_graph.nodes[node]
                    if 'x' in node_data and 'y' in node_data:
                        return_coords.append((node_data['x'], node_data['y']))
            
            if len(return_coords) > 1:
                xs, ys = zip(*return_coords)
                ax.plot(
                    xs, ys,
                    color='purple',
                    linewidth=3,
                    alpha=0.6,
                    linestyle='--',
                    label='Return Route (Cart Path)',
                    zorder=5,
                )
        return outbound_coords, return_coords
    
    # Priority 2: Fallback to cart path routing approximation
    if cart_graph is not None:
        orders = results.get('orders', [])
        # If no orders, check for single delivery simulation results
        if not orders and "order_hole" in results:
            orders = [{"hole_num": results["order_hole"]}]

        delivery_stats = results.get('delivery_stats', [])
        
        if not orders:
            return [], []
            
        # Get hole locations for approximation
        hole_locations = {}
        if 'holes' in course_data:
            holes_gdf = course_data['holes']
            for _, row in holes_gdf.iterrows():
                hole_locations[row['hole']] = (row.geometry.centroid.x, row.geometry.centroid.y)

        for i, order in enumerate(orders):
            hole_num = order.get('hole_num')
            hole_location = hole_locations.get(hole_num)
            
            if not hole_location:
                continue

            try:
                # Find nearest nodes in cart graph
                clubhouse_node = _find_nearest_cart_node(cart_graph, clubhouse_coords)
                hole_node = _find_nearest_cart_node(cart_graph, hole_location)

                if clubhouse_node and hole_node:
                    try:
                        path = nx.shortest_path(cart_graph, clubhouse_node, hole_node, weight='length')
                        
                        path_coords = []
                        for node in path:
                            node_data = cart_graph.nodes[node]
                            if 'x' in node_data and 'y' in node_data:
                                path_coords.append((node_data['x'], node_data['y']))
                        
                        if len(path_coords) > 1:
                            outbound_coords.extend(path_coords)
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
                            _add_path_arrows(ax, path_coords)

                    except (nx.NetworkXNoPath, nx.NodeNotFound):
                        # Fallback to straight line if no path is found
                        ax.plot(
                            [clubhouse_coords[0], hole_location[0]], 
                            [clubhouse_coords[1], hole_location[1]],
                            color='red',
                            linewidth=2,
                            alpha=0.8,
                            linestyle='--',
                            label='Delivery Route (Fallback)' if i == 0 else "",
                            zorder=6,
                        )
                        outbound_coords.append(clubhouse_coords)
                        outbound_coords.append(hole_location)

            except Exception as e:
                logger.warning(f"Could not render delivery route using cart graph fallback: {e}")
        
        return outbound_coords, return_coords

    # Priority 3: Fallback to raw runner coordinates if provided
    if runner_df is not None and not runner_df.empty:
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
                label='Delivery Runner Path (GPS)',
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
            outbound_coords.extend(list(zip(runner_positions['longitude'], runner_positions['latitude'])))
            return outbound_coords, return_coords

    # Priority 4: Fallback to a straight line from clubhouse to delivery location
    else:
        # Try to find delivery location from results
        predicted_delivery = results.get('predicted_delivery_location', [None, None])
        if predicted_delivery[0] is not None:
            start_point = (clubhouse_coords[0], clubhouse_coords[1])
            end_point = (predicted_delivery[0], predicted_delivery[1])
            
            ax.plot([start_point[0], end_point[0]], [start_point[1], end_point[1]],
                    color='orange', linewidth=4, alpha=0.8, linestyle='-',
                    label='Delivery Route (Fallback)', zorder=6)
            
            outbound_coords.append(start_point)
            outbound_coords.append(end_point)

    return outbound_coords, return_coords


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
    with timed_visualization("beverage_cart_plot"):
        course_dir = Path(course_dir)
        save_path = Path(save_path)

        course_data = load_course_geospatial_data(course_dir)

        with timed_visualization("create_matplotlib_figure"):
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
                    ax.plot(lons[0], lats[0], 'o', color='blue', markersize=8, label='Start', zorder=7)
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
        
        with timed_file_io("save_png", str(save_path.name)):
            fig.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='white')
        plt.close(fig)


def render_bev_cart_crossings(
    course_dir: str | Path,
    crossings_data: Optional[Dict[str, Any]],
    sales_result: Optional[Dict[str, Any]],
    save_path: str | Path,
    bev_points: Optional[List[Dict]] = None,
    title: str = "Beverage Cart Passes",
) -> None:
    """Render a map of beverage cart/golfer crossings with sale markers.

    - Blue dot with white outline (larger): crossing where a sale occurred
    - Red dot (smaller): crossing with no sale

    Uses node_index from crossings_data to locate each crossing on
    holes_connected.geojson. Optionally overlays the bev-cart path.
    """
    with timed_visualization("bev_cart_crossings_plot"):
        course_dir = Path(course_dir)
        save_path = Path(save_path)

        course_data = load_course_geospatial_data(course_dir)

        # Prepare nodes from holes_connected to place crossing points
        nodes_lonlat: List[Tuple[float, float]] = []
        try:
            # Import locally to avoid viz<->simulation circular deps at module import time
            from ..simulation.crossings import load_nodes_geojson_with_holes  # type: ignore
            nodes_path = course_dir / "geojson" / "generated" / "holes_connected.geojson"
            if nodes_path.exists():
                nodes, _node_holes = load_nodes_geojson_with_holes(str(nodes_path))
                # load_nodes_geojson_with_holes returns (lat, lon) tuples
                nodes_lonlat = [(lon, lat) for (lat, lon) in nodes]
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to load holes_connected nodes for crossings viz: %s", e)

        with timed_visualization("create_matplotlib_figure"):
            fig, ax = plt.subplots(figsize=(10, 8))

            # Course for context
            plot_course_features(ax, course_data, include_holes=True, include_greens=True)

            # Optional: overlay beverage cart path for context
            if bev_points:
                try:
                    lons = [p.get("longitude") for p in bev_points if p.get("longitude") is not None]
                    lats = [p.get("latitude") for p in bev_points if p.get("latitude") is not None]
                    if len(lons) > 1:
                        ax.plot(lons, lats, color="purple", linewidth=2, alpha=0.5, label="Beverage Cart", zorder=4)
                except Exception:
                    pass

            # Build sale lookup keyed by (group_id, hole_num, t_quant)
            sale_keys = set()
            bev_start_base_s: Optional[int] = None
            if isinstance(sales_result, dict):
                try:
                    meta = sales_result.get("metadata", {}) or {}
                    bev_start_base_s = int(meta.get("service_start_s")) if meta.get("service_start_s") is not None else None
                except Exception:
                    bev_start_base_s = None
                try:
                    for s in sales_result.get("sales", []) or []:
                        gid = int(s.get("group_id")) if s.get("group_id") is not None else None
                        hole = int(s.get("hole_num")) if s.get("hole_num") is not None else None
                        ts7 = int(s.get("timestamp_s")) if s.get("timestamp_s") is not None else None
                        if gid is None or hole is None or ts7 is None:
                            continue
                        if bev_start_base_s is not None:
                            t_norm = ts7 - bev_start_base_s
                        else:
                            t_norm = ts7  # best-effort
                        # Quantize to nearest minute to allow for minor discrepancies
                        t_q = int(round(float(t_norm) / 60.0) * 60)
                        sale_keys.add((gid, hole, t_q))
                except Exception:
                    pass

            # Plot crossings as red (no sale) and blue-with-white-outline (sale) dots
            num_sales = 0
            num_cross = 0
            if isinstance(crossings_data, dict):
                try:
                    groups = crossings_data.get("groups", []) or []
                    # Attempt to infer bev start baseline from crossings if not present in sales metadata
                    if bev_start_base_s is None and crossings_data.get("bev_start") is not None:
                        try:
                            t = crossings_data.get("bev_start")
                            # seconds since 7am baseline
                            bev_start_base_s = (t.hour - 7) * 3600 + t.minute * 60 + t.second  # type: ignore[attr-defined]
                        except Exception:
                            bev_start_base_s = None

                    for g in groups:
                        gid = int(g.get("group", 0) or 0)
                        for cr in g.get("crossings", []) or []:
                            idx = cr.get("node_index")
                            t_cross = cr.get("t_cross_s")
                            hole = cr.get("hole")
                            if idx is None or not isinstance(idx, int) or idx < 0:
                                continue
                            # Get lon/lat for node index
                            if nodes_lonlat and 0 <= idx < len(nodes_lonlat):
                                lon, lat = nodes_lonlat[idx]
                            else:
                                # If nodes are unavailable, skip plotting this crossing
                                continue

                            num_cross += 1
                            sold_here = False
                            try:
                                if bev_start_base_s is not None and isinstance(t_cross, (int, float)):
                                    t_q = int(round(float(t_cross) / 60.0) * 60)
                                    sold_here = (gid, int(hole) if hole is not None else -1, t_q) in sale_keys
                            except Exception:
                                sold_here = False

                            if sold_here:
                                num_sales += 1
                                ax.scatter(
                                    [lon], [lat],
                                    s=80,
                                    marker='o',
                                    facecolors="#1f77b4",
                                    edgecolors="white",
                                    linewidths=1.5,
                                    zorder=6,
                                )
                            else:
                                ax.scatter(
                                    [lon], [lat],
                                    s=24,
                                    marker='o',
                                    facecolors="#d62728",
                                    edgecolors='none',
                                    alpha=0.95,
                                    zorder=5,
                                )
                except Exception as e:  # noqa: BLE001
                    logger.warning("Failed plotting crossings: %s", e)

            # Legend handles
            from matplotlib.lines import Line2D
            legend_elems = [
                Line2D([0], [0], marker='o', color='w', label='Sale', markerfacecolor='#1f77b4', markeredgecolor='white', markeredgewidth=1.5, markersize=10),
                Line2D([0], [0], marker='o', color='w', label='No sale', markerfacecolor='#d62728', markersize=6),
            ]
            ax.legend(handles=legend_elems, loc='upper right')

            # Bounds and styling
            lon_min, lon_max, lat_min, lat_max = calculate_course_bounds(course_data)
            ax.set_xlim(lon_min, lon_max)
            ax.set_ylim(lat_min, lat_max)
            ax.set_xlabel('Longitude')
            ax.set_ylabel('Latitude')
            ax.xaxis.set_major_formatter(mticker.ScalarFormatter(useMathText=False))
            ax.yaxis.set_major_formatter(mticker.ScalarFormatter(useMathText=False))
            ax.ticklabel_format(style='plain', axis='both', useOffset=False)
            ax.set_aspect('equal', adjustable='box')
            if title:
                ax.set_title(f"{title} — Crossings: {num_cross}, Sales: {num_sales}")
            ax.grid(True, alpha=0.2)

        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.tight_layout()
        with timed_file_io("save_png", str(save_path.name)):
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


def plot_key_locations(ax, results: Dict, clubhouse_coords: Tuple[float, float], course_data: Dict, cart_graph: Optional[nx.Graph] = None):
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
            # Robust hole id detection: prefer 'hole', then 'ref', else index+1
            hole_id_val = hole.get('hole', None)
            if hole_id_val is None:
                hole_id_val = hole.get('ref', str(idx + 1))
            try:
                hole_id = int(hole_id_val)
            except Exception:
                hole_id = idx + 1

            # Derive a point for the hole regardless of geometry type
            geom = hole.geometry
            pt = None
            try:
                if hasattr(geom, 'geom_type') and geom.geom_type == "LineString":
                    pt = geom.interpolate(0.5, normalized=True)
                elif hasattr(geom, 'centroid'):
                    pt = geom.centroid
            except Exception:
                pt = None
            if pt is not None:
                hole_locations[int(hole_id)] = (pt.x, pt.y)
    
    for i, order in enumerate(orders):
        # First try to get golfer position when order was placed (if available from single-golfer sim)
        golfer_coords = results.get('golfer_coordinates', [])
        order_time = order.get('order_time_s', 0)
        
        order_position = None
        for coord in golfer_coords:
            if coord.get('timestamp') == order_time:
                order_position = (coord.get('longitude'), coord.get('latitude'))
                break
        
        # If no exact coordinates, use placed_hole_num from per-order stats or orders_all when available,
        # else estimate where golfer was when order was placed (typically 1-3 holes prior)
        if not order_position:
            # Delivered hole from per-order stats or order record
            delivered_hole = None
            if delivery_stats and i < len(delivery_stats):
                try:
                    delivered_hole = int(delivery_stats[i].get('hole_num')) if delivery_stats[i].get('hole_num') is not None else None
                except Exception:
                    delivered_hole = None
            if delivered_hole is None:
                delivered_hole = order.get('hole_num')

            # Prefer explicit placed_hole_num if provided by the simulator
            placed_hole_num = None
            if delivery_stats and i < len(delivery_stats):
                try:
                    placed_hole_num = delivery_stats[i].get('placed_hole_num')
                    placed_hole_num = int(placed_hole_num) if placed_hole_num is not None else None
                except Exception:
                    placed_hole_num = None
            # Fallback: find matching order in orders_all to get placed hole at order time
            if placed_hole_num is None:
                try:
                    orders_all = results.get('orders_all') or []
                    oid = order.get('order_id')
                    for oa in orders_all:
                        if oa.get('order_id') == oid:
                            ph = oa.get('hole_num')
                            placed_hole_num = int(ph) if ph is not None else None
                            break
                except Exception:
                    placed_hole_num = placed_hole_num

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
                    if placed_hole_num and placed_hole_num in hole_locations:
                        order_position = hole_locations[placed_hole_num]
                    else:
                        # Estimate golfer was ~2 holes before delivery when they placed order
                        estimated_order_hole = None
                        try:
                            estimated_order_hole = max(1, int(delivered_hole) - 2) if delivered_hole else None
                        except Exception:
                            estimated_order_hole = None
                        if estimated_order_hole and estimated_order_hole in hole_locations:
                            order_position = hole_locations[estimated_order_hole]
                        elif delivered_hole and delivered_hole in hole_locations:
                            # Fallback to delivered hole if estimation fails
                            order_position = hole_locations[delivered_hole]
        
        if order_position:
            # Mark where order was placed (gold circle with black edge)
            ax.plot(
                order_position[0], order_position[1],
                'o',
                markersize=12,
                color='#FFD700',  # gold
                label='Order Placed' if i == 0 else "",
                markeredgecolor='#000000',
                markeredgewidth=1.8,
                zorder=100,
            )
            
            # Add order number annotation with placement info (prefer explicit placed_hole_num)
            try:
                placed_hole_for_label = None
                if delivery_stats and i < len(delivery_stats):
                    ph = delivery_stats[i].get('placed_hole_num')
                    placed_hole_for_label = int(ph) if ph is not None else None
                if placed_hole_for_label is None:
                    # Estimate from delivered hole if not provided
                    delivered_hole_label = None
                    try:
                        delivered_hole_label = int(delivered_hole) if delivered_hole is not None else None
                    except Exception:
                        delivered_hole_label = None
                    placed_hole_for_label = max(1, (delivered_hole_label or 1) - 2)
            except Exception:
                placed_hole_for_label = 1
            annotation_text = f'Order {order.get("order_id", i+1)}\n(placed ~hole {placed_hole_for_label})'
            
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
            color='blue',
            label='Delivery Location',
            markeredgecolor='darkblue',
            markeredgewidth=2,
            zorder=10,
        )
    else:
        # For multi-golfer sims, show delivery locations per order
        for i, order in enumerate(orders):
            # Prefer exact endpoint from trip_to_golfer if available and cart_graph provided
            delivery_xy = None
            try:
                per_stat = delivery_stats[i] if delivery_stats and i < len(delivery_stats) else None
            except Exception:
                per_stat = None
            if per_stat and isinstance(per_stat, dict):
                trip_to = per_stat.get('trip_to_golfer')
                if trip_to and isinstance(trip_to.get('nodes'), list) and len(trip_to['nodes']) > 0:
                    last = trip_to['nodes'][-1]
                    if isinstance(last, (list, tuple)) and len(last) == 2:
                        delivery_xy = (float(last[0]), float(last[1]))
                    elif cart_graph is not None and last in cart_graph.nodes:
                        nd = cart_graph.nodes[last]
                        if 'x' in nd and 'y' in nd:
                            delivery_xy = (float(nd['x']), float(nd['y']))
            if delivery_xy is None:
                # Fallback to hole centroid
                delivered_hole = None
                try:
                    if per_stat:
                        delivered_hole = int(per_stat.get('hole_num')) if per_stat.get('hole_num') is not None else None
                except Exception:
                    delivered_hole = None
                if delivered_hole is None:
                    delivered_hole = order.get('hole_num')
                if delivered_hole and delivered_hole in hole_locations:
                    delivery_xy = hole_locations[delivered_hole]
            if delivery_xy is not None:
                ax.plot(
                    delivery_xy[0], delivery_xy[1],
                    'D',  # Diamond shape for delivery
                    markersize=13,
                    color='#2E8B57',  # sea green
                    label='Delivery Location' if i == 0 else "",
                    markeredgecolor='#004225',
                    markeredgewidth=2,
                    zorder=100,
                )


def setup_plot_styling(ax, results: Dict, course_name: str, clubhouse_coords: Tuple[float, float], 
                       course_bounds: Tuple[float, float, float, float]):
    """Configure plot titles, labels, legends, and aspect ratio."""

    title = f'{course_name} - Golf Delivery Simulation'

    # Handle single delivery simulation results
    if results.get("simulation_type") == "improved_single":
        service_time_min = float(results.get('total_service_time_s', 0) or 0) / 60.0
        distance_m = float(results.get('delivery_distance_m', 0) or 0)
        # Break out time components for the header
        prep_min = float(results.get('prep_time_s', 0) or 0) / 60.0
        delay_min = float(results.get('runner_busy_delay_s', 0.0) or 0.0) / 60.0
        # Show drive time to golfer only (not out+back)
        drive_time_s = 0.0
        if isinstance(results.get('trip_to_golfer'), dict):
            drive_time_s = float(results['trip_to_golfer'].get('time_s', 0) or 0)
        elif isinstance(results.get('delivery_travel_time_s'), (int, float)):
            # Fallback: if only aggregate is present, show half as an approximation
            drive_time_s = float(results.get('delivery_travel_time_s', 0.0)) / 2.0
        drive_min = float(drive_time_s) / 60.0

        title += (
            "\n1 Order Delivered | "
            f"Prep: {prep_min:.1f} min | "
            f"Delay: {delay_min:.1f} min | "
            f"Drive: {drive_min:.1f} min | "
            f"Total: {service_time_min:.1f} min | "
            f"Distance: {distance_m:.0f}m"
        )
    # Handle multi-order simulation results from run_unified_simulation
    elif 'orders' in results and 'delivery_stats' in results:
        orders = results.get('orders', [])
        delivery_stats = results.get('delivery_stats', [])
        num_orders = len(orders)
        num_delivered = len([o for o in orders if o.get('status') == 'processed'])
        num_failed = num_orders - num_delivered
        
        title += f'\n{num_orders} orders total: {num_delivered} delivered, {num_failed} failed'

        if delivery_stats:
            avg_time_min = np.mean([d.get('total_completion_time_s', 0) for d in delivery_stats]) / 60
            total_dist_km = sum(d.get('delivery_distance_m', 0) for d in delivery_stats) / 1000
            title += f'\nAverage order time: {avg_time_min:.1f} min, Total distance: {total_dist_km:.1f} km'
    # Fallback for empty/unknown results
    else:
        title += '\n0 orders total: 0 delivered, 0 failed\nAverage order time: 0.0 min, Total distance: 0m'

    ax.set_title(title, fontsize=16, weight='bold')

    # Set plot bounds and aspect ratio
    lon_min, lon_max, lat_min, lat_max = course_bounds
    # Add some margin for better visualization
    lon_margin = (lon_max - lon_min) * 0.08
    lat_margin = (lat_max - lat_min) * 0.08
    ax.set_xlim(lon_min - lon_margin, lon_max + lon_margin)
    ax.set_ylim(lat_min - lat_margin, lat_max + lat_margin)

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


def render_single_delivery_plot(order: Dict, order_index: int, results: Dict, course_data: Dict, 
                               clubhouse_coords: Tuple[float, float],
                               golfer_coords: Optional[pd.DataFrame] = None, 
                               runner_coords: Optional[pd.DataFrame] = None,
                               cart_graph: Optional[nx.Graph] = None,
                               save_path: str | Path = "delivery_order.png",
                               course_name: str = "Golf Course",
                               style: str = "simple") -> Path:
    """
    Create a visualization for a single delivery order.
    
    Args:
        order: Individual order dictionary
        order_index: Index of the order in the full results
        results: Full simulation results dictionary  
        course_data: Dictionary containing geospatial course data
        clubhouse_coords: Tuple of (longitude, latitude) for clubhouse
        golfer_coords: DataFrame with golfer position tracking (optional)
        runner_coords: DataFrame with runner position tracking (optional)
        cart_graph: NetworkX graph for cart paths (optional)
        save_path: Output file path
        course_name: Name of the golf course
        style: Visualization style ("simple" or "detailed")
        
    Returns:
        Path to saved visualization file
    """
    save_path = Path(save_path)
    
    logger.info("Creating single delivery visualization: %s", save_path)
    
    # Create a modified results dict for single order
    single_order_results = results.copy()
    single_order_results['orders'] = [order]
    
    # Filter delivery stats for this specific order if available
    delivery_stats = results.get('delivery_stats', [])
    if delivery_stats and order_index < len(delivery_stats):
        single_order_results['delivery_stats'] = [delivery_stats[order_index]]
        # Promote per-order routing data to the top-level keys expected by plot_runner_route
        try:
            per_order_stats = delivery_stats[order_index]
            trip_to_golfer = per_order_stats.get('trip_to_golfer') if isinstance(per_order_stats, dict) else None
            trip_back = per_order_stats.get('trip_back') if isinstance(per_order_stats, dict) else None
            if trip_to_golfer:
                single_order_results['trip_to_golfer'] = trip_to_golfer
            if trip_back:
                single_order_results['trip_back'] = trip_back
        except Exception:
            # Non-fatal: keep going without promoted routing data
            pass
    else:
        single_order_results['delivery_stats'] = []
    
    # Filter runner coordinates for this specific delivery if available
    filtered_runner_coords = None
    if runner_coords is not None and len(runner_coords) > 0:
        # Try to filter based on order timing or runner assignment
        order_time = order.get('order_time_s', 0)
        # For now, include all runner coordinates - could be refined later
        # to show only the coordinates during this specific delivery
        filtered_runner_coords = runner_coords
    
    # Create figure with single panel layout
    fig, ax = plt.subplots(1, 1, figsize=(16, 12))

    # Plot course features
    if style == "simple":
        plot_course_boundary(ax, course_data)
    else:
        plot_course_features(ax, course_data)
    
    # Plot cart network if available
    if cart_graph:
        plot_cart_network(ax, cart_graph, alpha=0.4)

    # Plot golfer path (if this is part of a golfer simulation)
    if golfer_coords is not None:
        plot_golfer_path(ax, golfer_coords, single_order_results)

    # Plot runner delivery route for this specific order
    plot_runner_route(ax, filtered_runner_coords, single_order_results, course_data, clubhouse_coords, cart_graph)

    # Plot key locations for this order (pass cart_graph to resolve exact delivery endpoint)
    plot_key_locations(ax, single_order_results, clubhouse_coords, course_data, cart_graph)

    # Set up styling and bounds
    course_bounds = calculate_course_bounds(course_data)
    setup_plot_styling(ax, single_order_results, course_name, clubhouse_coords, course_bounds)

    # Update title to reflect single order with timing information
    order_id = order.get('order_id', order_index + 1)
    hole_num = order.get('hole_num', 'Unknown')
    
    # Ensure order_id is displayed properly
    try:
        order_id_display = int(order_id) if order_id is not None else order_index + 1
    except (ValueError, TypeError):
        order_id_display = order_index + 1
    
    # Build title with timing information if available
    title = f'{course_name} - Delivery Order #{order_id_display} (Hole {hole_num})'
    
    # Add timing information if delivery stats are available
    if single_order_results.get('delivery_stats'):
        delivery_stat = single_order_results['delivery_stats'][0]
        
        # Extract timing components
        total_time_s = delivery_stat.get('total_completion_time_s', 0)
        prep_time_s = delivery_stat.get('prep_time_s', 0)
        delivery_time_s = delivery_stat.get('delivery_time_s', 0)
        queue_wait_s = delivery_stat.get('queue_wait_time_s', 0)
        distance_m = delivery_stat.get('delivery_distance_m', 0)
        
        # Convert to minutes
        total_time_min = total_time_s / 60.0
        prep_time_min = prep_time_s / 60.0
        delivery_time_min = delivery_time_s / 60.0
        queue_wait_min = queue_wait_s / 60.0
        
        # Add timing details to title
        title += (
            f"\nPrep: {prep_time_min:.1f} min | "
            f"Queue: {queue_wait_min:.1f} min | "
            f"Drive: {delivery_time_min:.1f} min | "
            f"Total: {total_time_min:.1f} min | "
            f"Distance: {distance_m:.0f}m"
        )
    
    ax.set_title(title)

    plt.tight_layout()
    with timed_file_io("save_png", str(save_path.name)):
        plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close(fig)

    logger.info("Saved single delivery visualization: %s (%.1f KB)", 
                save_path, save_path.stat().st_size / 1024)
    return save_path


def render_individual_delivery_plots(results: Dict, course_data: Dict, clubhouse_coords: Tuple[float, float],
                                   golfer_coords: Optional[pd.DataFrame] = None, 
                                   runner_coords: Optional[pd.DataFrame] = None,
                                   cart_graph: Optional[nx.Graph] = None,
                                   output_dir: str | Path = ".",
                                   filename_prefix: str = "delivery_order",
                                   course_name: str = "Golf Course",
                                   style: str = "simple") -> List[Path]:
    """
    Create individual visualization files for each delivery order.
    
    Args:
        results: Simulation results dictionary
        course_data: Dictionary containing geospatial course data
        clubhouse_coords: Tuple of (longitude, latitude) for clubhouse
        golfer_coords: DataFrame with golfer position tracking (optional)
        runner_coords: DataFrame with runner position tracking (optional)
        cart_graph: NetworkX graph for cart paths (optional)
        output_dir: Directory to save individual PNG files
        filename_prefix: Prefix for individual PNG filenames
        course_name: Name of the golf course
        style: Visualization style ("simple" or "detailed")
        
    Returns:
        List of paths to saved visualization files
    """
    with timed_visualization("individual_delivery_plots"):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        orders = results.get('orders', [])
        if not orders:
            logger.info("No orders found, skipping individual delivery visualizations")
            return []
        
        saved_paths = []
        
        for i, order in enumerate(orders):
            order_id = order.get('order_id', i + 1)
            hole_num = order.get('hole_num', 'unknown')
            
            # Ensure order_id is an integer for formatting
            try:
                order_id_int = int(order_id) if order_id is not None else i + 1
            except (ValueError, TypeError):
                order_id_int = i + 1
            
            # Create filename: delivery_order_001_hole_5.png
            filename = f"{filename_prefix}_{order_id_int:03d}_hole_{hole_num}.png"
            save_path = output_dir / filename
            
            try:
                # Generate individual delivery plot
                saved_path = render_single_delivery_plot(
                order=order,
                order_index=i,
                results=results,
                course_data=course_data,
                clubhouse_coords=clubhouse_coords,
                golfer_coords=golfer_coords,
                runner_coords=runner_coords,
                cart_graph=cart_graph,
                save_path=save_path,
                course_name=course_name,
                style=style
                )
                saved_paths.append(saved_path)
                logger.info("Created individual delivery visualization %d/%d: %s", 
                           i + 1, len(orders), saved_path.name)
                
            except Exception as e:
                logger.warning("Failed to create individual visualization for order %d: %s", 
                              order_id, e)
        
        logger.info("Created %d individual delivery visualizations in %s", 
                    len(saved_paths), output_dir)
        return saved_paths


def render_delivery_plot(
    results: Dict,
    course_data: Dict,
    clubhouse_coords: Tuple[float, float],
    golfer_coords: Optional[pd.DataFrame] = None, 
    runner_coords: Optional[pd.DataFrame] = None,
    cart_graph: Optional[nx.Graph] = None,
    save_path: Optional[Path] = None,
    course_name: Optional[str] = None,
    style: str = "simple",
    save_debug_coords_path: Optional[Path] = None
):
    """
    Main function to render a delivery plot for single or multiple deliveries.
    
    Args:
        results: Simulation results dictionary
        course_data: Dictionary containing geospatial course data
        clubhouse_coords: Tuple of (longitude, latitude) for clubhouse
        golfer_coords: DataFrame with golfer position tracking (optional)
        runner_coords: DataFrame with runner position tracking (optional)
        save_path: Output file path
        course_name: Name of the golf course
        style: Visualization style ("simple" or "detailed")
        save_debug_coords_path: Optional path to save debug coordinates
    """
    with timed_visualization("delivery_plot"):
        save_path = Path(save_path) if save_path else None
        save_debug_coords_path = Path(save_debug_coords_path) if save_debug_coords_path else None

        logger.info("Creating delivery visualization: %s", save_path)
        
        # Create figure with single panel layout
        with timed_visualization("create_matplotlib_figure"):
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
    outbound_coords, return_coords = plot_runner_route(ax, runner_coords, results, course_data, clubhouse_coords, cart_graph)

    # Plot key locations
    plot_key_locations(ax, results, clubhouse_coords, course_data, cart_graph)

    # Set up styling and bounds
    course_bounds = calculate_course_bounds(course_data)
    setup_plot_styling(ax, results, course_name, clubhouse_coords, course_bounds)

    # Save the plot
    if save_path:
        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(save_path, dpi=150, bbox_inches='tight')
        logger.info(f"Saved delivery visualization: {save_path} ({save_path.stat().st_size / 1024:.1f} KB)")
    
    # Save debug coordinates if path is provided
    if save_debug_coords_path:
        all_coords = []
        if outbound_coords:
            for i, (lon, lat) in enumerate(outbound_coords):
                all_coords.append({'type': 'outbound', 'seq': i, 'lon': lon, 'lat': lat})
        if return_coords:
            for i, (lon, lat) in enumerate(return_coords):
                all_coords.append({'type': 'return', 'seq': i, 'lon': lon, 'lat': lat})
        
        if all_coords:
            try:
                import pandas as pd
                df = pd.DataFrame(all_coords)
                df.to_csv(save_debug_coords_path, index=False)
                logger.info(f"Saved visualization debug coordinates to: {save_debug_coords_path}")
            except Exception as e:
                logger.error(f"Failed to save visualization debug coordinates: {e}")

    plt.close(fig)


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
    colors = ['red', 'orange', 'blue', 'lightblue'][:len(times)]

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


def create_folium_delivery_map(results: Dict, course_data: Dict, output_path: Path):
    """
    Creates an interactive Folium map of the delivery route.
    """
    import folium
    
    # Get center of the map from course boundary if available
    if 'boundary' in course_data and hasattr(course_data['boundary'], 'centroid'):
        center_lat = course_data['boundary'].centroid.y
        center_lon = course_data['boundary'].centroid.x
    else:
        # Fallback to clubhouse or a default location
        clubhouse_coords = results.get('runner_start_position', [-84.5928, 34.0379])
        center_lon, center_lat = clubhouse_coords[0], clubhouse_coords[1]

    m = folium.Map(location=[center_lat, center_lon], zoom_start=15)

    # Add course boundary
    if 'boundary' in course_data:
        folium.GeoJson(course_data['boundary'], name='Course Boundary').add_to(m)

    # Function to extract path coordinates
    def get_path_coords(trip_data):
        coords = []
        if 'nodes' in trip_data:
            for node in trip_data['nodes']:
                if isinstance(node, (list, tuple)) and len(node) == 2:
                    coords.append((node[1], node[0]))  # lat, lon
                elif isinstance(node, dict) and 'y' in node and 'x' in node:
                    coords.append((node['y'], node['x']))
        return coords

    # Add trip to golfer
    if 'trip_to_golfer' in results:
        points = get_path_coords(results['trip_to_golfer'])
        if points:
            folium.PolyLine(points, color="orange", weight=5, opacity=0.8, tooltip="Delivery Route").add_to(m)

    # Add trip back
    if 'trip_back' in results:
        points = get_path_coords(results['trip_back'])
        if points:
            folium.PolyLine(points, color="purple", weight=3, opacity=0.8, dash_array='5, 5', tooltip="Return Route").add_to(m)
        
    m.save(str(output_path))
    logger.info(f"Saved Folium map to: {output_path}")
