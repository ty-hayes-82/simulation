"""
Heatmap visualization utilities for golf delivery simulation.

This module provides functions for creating heatmaps of order placement locations
on the golf course, color-coded by average delivery times.
"""

from __future__ import annotations

import json
from pathlib import Path
import os
from typing import Dict, List, Tuple, Optional, Any

import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from shapely.geometry import LineString, Point
import folium
from folium.plugins import HeatMap

from ..logging import get_logger
from .matplotlib_viz import load_course_geospatial_data, calculate_course_bounds

logger = get_logger(__name__)
# Optional basemap support
try:
    import contextily as cx  # type: ignore
    _HAS_CX = True
except Exception:
    cx = None  # type: ignore
    _HAS_CX = False



# Global cache for hole locations
_HOLE_LOCATIONS_CACHE = {}

def clear_heatmap_caches():
    """Clear all heatmap data caches to free memory."""
    global _HOLE_DATA_CACHE, _HOLE_LOCATIONS_CACHE
    _HOLE_DATA_CACHE.clear()
    _HOLE_LOCATIONS_CACHE.clear()
    logger.debug("Cleared heatmap data caches")

def load_hole_locations(course_dir: str | Path) -> Dict[int, Tuple[float, float]]:
    """Load hole locations from course GeoJSON files with caching.
    
    Args:
        course_dir: Path to course directory
        
    Returns:
        Dictionary mapping hole numbers to (longitude, latitude) coordinates
    """
    course_path = Path(course_dir)
    cache_key = str(course_path.resolve())
    
    # Return cached data if available
    if cache_key in _HOLE_LOCATIONS_CACHE:
        logger.debug("Using cached hole locations for %s", course_path.name)
        return _HOLE_LOCATIONS_CACHE[cache_key]
    
    holes_file = course_path / "geojson" / "holes.geojson"
    
    hole_locations = {}
    
    if holes_file.exists():
        try:
            holes_data = json.loads(holes_file.read_text(encoding="utf-8"))
            for feature in holes_data.get("features", []):
                props = feature.get("properties", {})
                raw_num = props.get("hole", props.get("ref"))
                try:
                    hole_num = int(raw_num) if raw_num is not None else None
                except (TypeError, ValueError):
                    hole_num = None
                    
                if hole_num and feature.get("geometry", {}).get("type") == "LineString":
                    coords = feature["geometry"]["coordinates"]
                    line = LineString(coords)
                    # Use midpoint of hole as order placement location
                    midpoint = line.interpolate(0.5, normalized=True)
                    hole_locations[hole_num] = (midpoint.x, midpoint.y)
                    
        except Exception as e:
            logger.error("Failed to load hole locations: %s", e)
    
    # Cache the loaded data
    _HOLE_LOCATIONS_CACHE[cache_key] = hole_locations
    logger.debug("Cached hole locations for %s (%d holes)", course_path.name, len(hole_locations))
            
    return hole_locations


def extract_order_data(results: Dict) -> List[Dict[str, Any]]:
    """Extract order placement data from simulation results.
    
    Args:
        results: Simulation results dictionary
        
    Returns:
        List of order data dictionaries with hole_num, drive_time, and coordinates
    """
    orders = results.get('orders', [])
    delivery_stats = results.get('delivery_stats', [])
    
    # Create a lookup dict to match orders with delivery stats by order_id
    delivery_stats_by_id = {}
    for stat in delivery_stats:
        order_id = stat.get('order_id')
        if order_id:
            delivery_stats_by_id[order_id] = stat
    
    order_data = []
    
    for i, order in enumerate(orders):
        order_id = order.get('order_id', f'order_{i}')

        # Only use true outbound drive time to the golfer. Ignore failed orders.
        drive_time_s = None
        stat = delivery_stats_by_id.get(order_id)
        # Prefer stats entry (most authoritative)
        if stat and 'delivery_time_s' in stat:
            drive_time_s = stat['delivery_time_s']
        # Fallback: if the order object itself has a delivery_time_s (rare)
        elif 'delivery_time_s' in order:
            drive_time_s = order['delivery_time_s']
        else:
            # If we still don't have an outbound drive time, skip this order. Do NOT
            # fall back to total completion or total drive time, which can include
            # queue and return components and distort the heatmap.
            status = str(order.get('status', '')).lower()
            if status != 'processed':
                # Ignore failed/unfinished orders for heatmap
                continue
            else:
                # Processed but missing explicit delivery_time_s; skip rather than
                # using total completion times which are not pure drive-to-golfer.
                continue

        # Choose the grouping hole number. Use delivered hole if available; otherwise
        # fall back to placed hole from stats, then order's original hole.
        hole_num: Optional[int] = None
        if stat is not None:
            delivered_hole = stat.get('hole_num')
            placed_hole_from_stats = stat.get('placed_hole_num')
            hole_num = delivered_hole if delivered_hole is not None else placed_hole_from_stats
        if hole_num is None:
            hole_num = order.get('hole_num')
        if hole_num is None:
            continue

        order_data.append({
            'hole_num': int(hole_num),
            'drive_time_s': drive_time_s,
            'drive_time_min': float(drive_time_s) / 60.0,
            'order_id': order_id,
            'golfer_group_id': order.get('golfer_group_id'),
            'order_time_s': order.get('order_time_s', 0)
        })
    
    return order_data


def calculate_delivery_time_stats(order_data: List[Dict[str, Any]]) -> Dict[int, Dict[str, float]]:
    """Calculate drive time statistics for each hole.
    
    Args:
        order_data: List of order data dictionaries
        
    Returns:
        Dictionary mapping hole numbers to stats (avg_time, min_time, max_time, count)
    """
    hole_stats = {}
    
    # Group orders by hole
    orders_by_hole = {}
    for order in order_data:
        hole_num = order['hole_num']
        if hole_num not in orders_by_hole:
            orders_by_hole[hole_num] = []
        orders_by_hole[hole_num].append(order['drive_time_min'])
    
    # Calculate stats for each hole
    for hole_num, times in orders_by_hole.items():
        hole_stats[hole_num] = {
            'avg_time': np.mean(times),
            'min_time': np.min(times),
            'max_time': np.max(times),
            'count': len(times),
            'std_time': np.std(times) if len(times) > 1 else 0.0
        }
    
    return hole_stats


# Global cache for hole data
_HOLE_DATA_CACHE = {}

def load_geofenced_holes(course_dir: str | Path) -> Dict[int, Any]:
    """Load geofenced hole polygons from course data as shapely geometries with caching.

    Supports Polygon and MultiPolygon features. Returns a mapping of
    hole number to shapely geometry.
    """
    course_path = Path(course_dir)
    cache_key = str(course_path.resolve())
    
    # Return cached data if available
    if cache_key in _HOLE_DATA_CACHE:
        logger.debug("Using cached hole data for %s", course_path.name)
        return _HOLE_DATA_CACHE[cache_key]
    
    # Use the actual geofenced holes file, not the original holes linestrings
    holes_file = course_path / "geojson" / "generated" / "holes_geofenced.geojson"

    hole_polygons: Dict[int, Any] = {}

    if holes_file.exists():
        try:
            gdf = gpd.read_file(holes_file)
            # Normalize CRS to 4326 just in case
            try:
                gdf = gdf.to_crs(4326)
            except Exception:
                pass

            # Check for 'hole' or 'ref' property
            hole_col = None
            if "hole" in gdf.columns:
                hole_col = "hole"
            elif "ref" in gdf.columns:
                hole_col = "ref"
            else:
                logger.warning("holes_geofenced.geojson missing 'hole' or 'ref' property")
                return hole_polygons

            for _, row in gdf.iterrows():
                hole = row.get(hole_col)
                geom = row.geometry
                if hole is None or geom is None:
                    continue
                try:
                    hole_int = int(hole)
                    # Geofenced holes should already be polygons, no buffering needed
                    hole_polygons[hole_int] = geom
                except Exception:
                    continue
        except Exception as e:
            logger.error("Failed to load geofenced holes: %s", e)
    else:
        # Fallback to original holes.geojson if geofenced version doesn't exist
        logger.warning("Geofenced holes file not found: %s, falling back to original holes.geojson", holes_file)
        fallback_file = course_path / "geojson" / "holes.geojson"
        if fallback_file.exists():
            try:
                gdf = gpd.read_file(fallback_file)
                try:
                    gdf = gdf.to_crs(4326)
                except Exception:
                    pass

                hole_col = None
                if "hole" in gdf.columns:
                    hole_col = "hole"
                elif "ref" in gdf.columns:
                    hole_col = "ref"
                else:
                    logger.warning("holes.geojson missing 'hole' or 'ref' property")
                    return hole_polygons

                for _, row in gdf.iterrows():
                    hole = row.get(hole_col)
                    geom = row.geometry
                    if hole is None or geom is None:
                        continue
                    try:
                        hole_int = int(hole)
                        # If it's a LineString (hole centerline), create a buffer around it
                        if hasattr(geom, 'geom_type') and geom.geom_type == 'LineString':
                            # Create a buffer around the line (approximately 50m radius)
                            # Convert to meters approximately (rough conversion for lat/lon)
                            buffer_deg = 50 / 111000  # roughly 50m in degrees
                            hole_polygons[hole_int] = geom.buffer(buffer_deg)
                        else:
                            # Already a polygon
                            hole_polygons[hole_int] = geom
                    except Exception:
                        continue
            except Exception as e:
                logger.error("Failed to load fallback holes: %s", e)

    # Cache the loaded data
    _HOLE_DATA_CACHE[cache_key] = hole_polygons
    logger.debug("Cached hole data for %s (%d holes)", course_path.name, len(hole_polygons))
    
    return hole_polygons


def load_all_heatmap_data(course_dir: str | Path) -> Tuple[Dict, Dict[int, Any], Dict[int, Tuple[float, float]], Tuple[float, float, float, float]]:
    """Load all heatmap data efficiently in one function to avoid redundant operations.
    
    Args:
        course_dir: Path to course directory
        
    Returns:
        Tuple of (course_data, hole_polygons, hole_locations, course_bounds)
    """
    course_data = load_course_geospatial_data(course_dir)
    hole_polygons = load_geofenced_holes(course_dir)
    hole_locations = load_hole_locations(course_dir)
    course_bounds = calculate_course_bounds(course_data)
    
    return course_data, hole_polygons, hole_locations, course_bounds

def create_course_heatmap(results: Dict,
                         course_dir: str | Path,
                         save_path: str | Path,
                         title: str = "Golf Course Order Drive Time Heatmap",
                         grid_resolution: int = 100,
                         colormap: str = 'white_to_red',
                         preloaded_data: Optional[Tuple] = None) -> Path:
    """Create a heatmap visualization of order drive times across the golf course.
    
    Args:
        results: Simulation results dictionary
        course_dir: Path to course directory containing geojson data
        save_path: Output PNG path
        title: Plot title
        grid_resolution: Resolution of the heatmap grid (unused in polygon mode)
        colormap: Matplotlib colormap name
        preloaded_data: Optional preloaded data to avoid reloading (course_data, hole_polygons, hole_locations, course_bounds)
        
    Returns:
        Path to saved heatmap file
    """
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info("Creating course heatmap: %s", save_path)
    
    # Load course data and hole geometries (or use preloaded data)
    if preloaded_data:
        course_data, hole_polygons, hole_locations, course_bounds = preloaded_data
    else:
        course_data, hole_polygons, hole_locations, course_bounds = load_all_heatmap_data(course_dir)
    
    # Extract order data and calculate statistics
    order_data = extract_order_data(results)
    hole_stats = calculate_delivery_time_stats(order_data)
    

    
    if not order_data:
        logger.warning("No order data found for heatmap")
        # Create a simple course plot without heatmap
        fig, ax = plt.subplots(figsize=(12, 10))
        if 'course_polygon' in course_data:
            course_poly = course_data['course_polygon']
            course_poly.plot(ax=ax, color='lightgray', alpha=0.3, edgecolor='gray')
        ax.set_title(f"{title}\n(No order data available)")
        ax.set_xlabel('Longitude')
        ax.set_ylabel('Latitude')
        plt.tight_layout()
        plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='white')
        plt.close(fig)
        return save_path
    
    # Create the plot
    fig, ax = plt.subplots(figsize=(14, 12))
    
    # Plot course boundary
    if 'course_polygon' in course_data:
        course_poly = course_data['course_polygon']
        course_poly.plot(ax=ax, color='lightgray', alpha=0.2, edgecolor='black', linewidth=1.5)
    
    # Create colormap and normalization for delivery times
    from matplotlib.colors import Normalize
    
    if hole_stats:
        # Fixed scale: 0 minutes (white) to 10 minutes (red). Values outside are clamped.
        fixed_min_time = 0.0
        fixed_max_time = 10.0

        # Create custom white-to-red colormap or use provided colormap
        if colormap == 'white_to_red' or colormap == 'RdYlBu_r':
            # Create custom white-to-bright-red colormap
            from matplotlib.colors import LinearSegmentedColormap
            # Ensure the high end is bright red (#ff0000)
            colors = ['white', '#ffe6e6', '#ffcccc', '#ff9999', '#ff6666', '#ff3333', '#ff0000']
            cmap = LinearSegmentedColormap.from_list('white_to_red', colors, N=256)
        else:
            cmap = plt.get_cmap(colormap)
        norm = Normalize(vmin=fixed_min_time, vmax=fixed_max_time)
        
        # Build a GeoDataFrame from geofenced holes so we can plot polygons (incl. MultiPolygon)
        holes_gdf = gpd.GeoDataFrame(
            {"hole": list(hole_polygons.keys()), "geometry": list(hole_polygons.values())},
            crs="EPSG:4326",
        )

        # Map avg time per hole (clamped to fixed range for consistent coloring)
        def _clamp(v: float, lo: float, hi: float) -> float:
            try:
                return max(lo, min(hi, float(v)))
            except Exception:
                return lo
        hole_to_avg = {h: _clamp(s["avg_time"], fixed_min_time, fixed_max_time) for h, s in hole_stats.items()}
        holes_gdf["avg_time"] = holes_gdf["hole"].map(hole_to_avg)

        # Split holes into those with data and those without
        holes_with_data = holes_gdf[holes_gdf["avg_time"].notna()]
        holes_without_data = holes_gdf[holes_gdf["avg_time"].isna()]
        
        # Plot holes with data using the colormap
        if not holes_with_data.empty:
            holes_with_data.plot(
                ax=ax,
                column="avg_time",
                cmap=cmap,
                vmin=fixed_min_time,
                vmax=fixed_max_time,
                edgecolor="black",
                linewidth=1.2,
                alpha=0.8,
                aspect=None,  # Disable automatic aspect ratio calculation
                legend=False,
                zorder=5,
            )
        
        # Plot holes without data with diagonal hatching
        if not holes_without_data.empty:
            holes_without_data.plot(
                ax=ax,
                color="lightgray",
                edgecolor="gray",
                linewidth=1.0,
                alpha=0.3,
                hatch="///",  # Diagonal lines
                aspect=None,
                legend=False,
                zorder=4,
            )

        # Annotate each hole at a representative point with enhanced hover-like information
        for _, row in holes_gdf.iterrows():
            geom = row.geometry
            if geom is None:
                continue
            rep_pt = geom.representative_point()
            hole_num = int(row["hole"]) if pd.notna(row["hole"]) else None
            if pd.notna(row["avg_time"]):
                avg_time = float(row["avg_time"])  # type: ignore[arg-type]
                
                # Get additional statistics for this hole
                hole_specific_stats = hole_stats.get(hole_num, {})
                count = hole_specific_stats.get('count', 0)
                min_time = hole_specific_stats.get('min_time', 0)
                max_time = hole_specific_stats.get('max_time', 0)
                std_time = hole_specific_stats.get('std_time', 0)
                
                # Create enhanced annotation with detailed stats
                main_text = f"Hole {hole_num}\nAvg: {avg_time:.1f}min"
                detail_text = f"Orders: {count}\nRange: {min_time:.1f}-{max_time:.1f}min"
                if count > 1:
                    detail_text += f"\nStd Dev: {std_time:.1f}min"
                
                # Main annotation (always visible)
                ax.annotate(
                    main_text,
                    (rep_pt.x, rep_pt.y),
                    fontsize=9,
                    weight="bold",
                    ha="center",
                    va="center",
                    color="white",
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="black", alpha=0.65, edgecolor="white"),
                    zorder=10,
                )
                
                # Add detailed stats as a smaller annotation nearby (simulating hover info)
                offset_x = 0.0002  # Small offset to avoid overlap
                offset_y = -0.0002
                ax.annotate(
                    detail_text,
                    (rep_pt.x + offset_x, rep_pt.y + offset_y),
                    fontsize=7,
                    ha="left",
                    va="top",
                    color="darkblue",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor="lightyellow", alpha=0.8, edgecolor="darkblue"),
                    zorder=9,
                )
            else:
                ax.annotate(
                    f"Hole {hole_num}",
                    (rep_pt.x, rep_pt.y),
                    fontsize=9,
                    ha="center",
                    va="center",
                    color="gray",
                    weight="bold",
                    zorder=6,
                )
        
        # Add colorbar
        from matplotlib.cm import ScalarMappable
        sm = ScalarMappable(norm=norm, cmap=cmap)
        sm.set_array([])
        try:
            cbar = plt.colorbar(sm, ax=ax, shrink=0.8, aspect=30)
            cbar.set_label('Average Drive Time to Golfer (minutes)', fontsize=12)
            try:
                cbar.set_ticks([0, 2, 4, 6, 8, 10])
                cbar.set_ticklabels(['0', '2', '4', '6', '8', '10'])
            except Exception:
                pass
        except Exception as e:
            logger.warning("Failed to create colorbar: %s, trying without aspect ratio", e)
            try:
                cbar = plt.colorbar(sm, ax=ax, shrink=0.8)
                cbar.set_label('Average Drive Time to Golfer (minutes)', fontsize=12)
            except Exception as e2:
                logger.warning("Failed to create colorbar entirely: %s", e2)
    
    else:
        # No delivery data - just show hole polygons in gray
        for hole_num, polygon in hole_polygons.items():
            x_coords, y_coords = polygon.exterior.xy
            ax.fill(x_coords, y_coords, color='lightgray', alpha=0.3, 
                   edgecolor='gray', linewidth=1, zorder=3)
            
            centroid = polygon.centroid
            ax.annotate(f'{hole_num}',
                       (centroid.x, centroid.y), fontsize=9, ha='center', va='center',
                       color='gray', weight='bold', zorder=4)
    
    # Set bounds and styling
    lon_min, lon_max, lat_min, lat_max = course_bounds
    margin = 0.05
    lon_margin = (lon_max - lon_min) * margin
    lat_margin = (lat_max - lat_min) * margin
    ax.set_xlim(lon_min - lon_margin, lon_max + lon_margin)
    ax.set_ylim(lat_min - lat_margin, lat_max + lat_margin)
    
    # Calculate summary statistics
    total_orders = len(order_data)
    if order_data:
        avg_drive_time = np.mean([o['drive_time_min'] for o in order_data])
        min_drive_time = np.min([o['drive_time_min'] for o in order_data])
        max_drive_time = np.max([o['drive_time_min'] for o in order_data])
        
        subtitle = (f"{total_orders} orders | "
                   f"Avg drive time: {avg_drive_time:.1f} min | "
                   f"Range: {min_drive_time:.1f}-{max_drive_time:.1f} min")
    else:
        subtitle = "No orders processed"
    
    ax.set_title(f"{title}\n{subtitle}", fontsize=14, weight='bold')
    ax.set_xlabel('Longitude', fontsize=12)
    ax.set_ylabel('Latitude', fontsize=12)
    ax.grid(True, alpha=0.3)
    
    # Set aspect ratio with error handling
    try:
        ax.set_aspect('equal')
    except ValueError as e:
        logger.warning("Failed to set equal aspect ratio: %s, using auto instead", e)
        ax.set_aspect('auto')
    
    # Format axes
    ax.xaxis.set_major_formatter(mticker.ScalarFormatter(useMathText=False))
    ax.yaxis.set_major_formatter(mticker.ScalarFormatter(useMathText=False))
    ax.ticklabel_format(style='plain', axis='both', useOffset=False)
    
    plt.tight_layout()
    plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    
    logger.info("Saved course heatmap: %s (%.1f KB)", 
                save_path, save_path.stat().st_size / 1024)
    
    return save_path


def create_delivery_statistics_summary(results: Dict, 
                                     hole_polygons: Dict[int, Any],
                                     save_path: Optional[str | Path] = None) -> str:
    """Create a text summary of drive time statistics by hole.
    
    Args:
        results: Simulation results dictionary
        hole_polygons: Dictionary mapping hole numbers to polygon geometries
        save_path: Optional path to save summary text file
        
    Returns:
        Summary text string
    """
    order_data = extract_order_data(results)
    hole_stats = calculate_delivery_time_stats(order_data)
    
    summary_lines = []
    summary_lines.append("Golf Course Drive Time Statistics Summary")
    summary_lines.append("=" * 50)
    summary_lines.append("")
    
    # Overall statistics
    if order_data:
        total_orders = len(order_data)
        avg_time = np.mean([o['drive_time_min'] for o in order_data])
        min_time = np.min([o['drive_time_min'] for o in order_data])
        max_time = np.max([o['drive_time_min'] for o in order_data])
        
        summary_lines.extend([
            f"Total Orders: {total_orders}",
            f"Average Drive Time: {avg_time:.1f} minutes",
            f"Minimum Drive Time: {min_time:.1f} minutes", 
            f"Maximum Drive Time: {max_time:.1f} minutes",
            ""
        ])
    else:
        summary_lines.extend([
            "No orders found in simulation results",
            ""
        ])
    
    # Per-hole statistics
    if hole_stats:
        summary_lines.append("Drive Times by Hole:")
        summary_lines.append("-" * 30)
        
        # Sort holes by average drive time (descending)
        sorted_holes = sorted(hole_stats.items(), key=lambda x: x[1]['avg_time'], reverse=True)
        
        for hole_num, stats in sorted_holes:
            summary_lines.append(
                f"Hole {hole_num:2d}: {stats['avg_time']:5.1f} min avg "
                f"({stats['min_time']:4.1f}-{stats['max_time']:4.1f} range, "
                f"{stats['count']} orders)"
            )
    
    summary_text = "\n".join(summary_lines)
    
    if save_path:
        save_path = Path(save_path)
        save_path.parent.mkdir(parents=True, exist_ok=True)
        save_path.write_text(summary_text, encoding='utf-8')
        logger.info("Saved drive time statistics summary: %s", save_path)
    
    return summary_text


def create_interactive_course_heatmap(results: Dict,
                                    course_dir: str | Path,
                                    save_path: str | Path,
                                    title: str = "Interactive Golf Course Order Drive Time Heatmap",
                                    preloaded_data: Optional[Tuple] = None) -> Path:
    """Create an interactive HTML heatmap with hover tooltips showing detailed order statistics.
    
    Args:
        results: Simulation results dictionary
        course_dir: Path to course directory containing geojson data
        save_path: Output HTML path
        title: Map title
        preloaded_data: Optional preloaded data to avoid reloading (course_data, hole_polygons, hole_locations, course_bounds)
        
    Returns:
        Path to saved interactive heatmap file
    """
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info("Creating interactive course heatmap: %s", save_path)
    
    # Load course data and hole geometries (or use preloaded data)
    if preloaded_data:
        course_data, hole_polygons, hole_locations, course_bounds = preloaded_data
    else:
        course_data, hole_polygons, hole_locations, course_bounds = load_all_heatmap_data(course_dir)
    
    # Extract order data and calculate statistics
    order_data = extract_order_data(results)
    hole_stats = calculate_delivery_time_stats(order_data)
    
    if not order_data:
        logger.warning("No order data found. Creating empty interactive heatmap.")
        hole_stats = {}
    
    # Calculate map center and zoom
    lon_min, lon_max, lat_min, lat_max = course_bounds
    center_lat = (lat_min + lat_max) / 2
    center_lon = (lon_min + lon_max) / 2
    
    # Create the folium map
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=15,
        tiles='OpenStreetMap'
    )
    
    # Add course boundary if available
    if 'course_polygon' in course_data:
        for poly in course_data['course_polygon']:
            if hasattr(poly, 'exterior'):
                coords = [[lat, lon] for lon, lat in poly.exterior.coords]
                folium.Polygon(
                    locations=coords,
                    color='lightgray',
                    weight=2,
                    fillColor='lightgray',
                    fillOpacity=0.1,
                    popup="Course Boundary"
                ).add_to(m)
    
    # Add cart paths if available
    if 'cart_paths' in course_data:
        for path in course_data['cart_paths']:
            if hasattr(path, 'coords'):
                coords = [[lat, lon] for lon, lat in path.coords]
                folium.PolyLine(
                    locations=coords,
                    color='gray',
                    weight=1,
                    opacity=0.5,
                    popup="Cart Path"
                ).add_to(m)
    
    # Define color scale for holes based on average drive time
    if hole_stats:
        avg_times = [stats['avg_time'] for stats in hole_stats.values()]
        min_time = min(avg_times)
        max_time = max(avg_times)
        time_range = max_time - min_time if max_time > min_time else 1.0
    else:
        min_time = max_time = time_range = 0
    
    # Add holes with interactive tooltips
    for hole_num, polygon in hole_polygons.items():
        # Get hole statistics
        stats = hole_stats.get(hole_num, {})
        
        if stats:
            avg_time = stats['avg_time']
            count = stats['count']
            min_time_hole = stats['min_time']
            max_time_hole = stats['max_time']
            std_time = stats['std_time']
            
            # Color based on average drive time (red = longer, green = shorter)
            if time_range > 0:
                color_intensity = (avg_time - min_time) / time_range
                # Create color from green (fast) to red (slow)
                red = int(255 * color_intensity)
                green = int(255 * (1 - color_intensity))
                blue = 0
                color = f'#{red:02x}{green:02x}{blue:02x}'
                fill_opacity = 0.6
            else:
                color = '#ffff00'  # Yellow for single data point
                fill_opacity = 0.4
            
            # Create detailed popup with hover information
            popup_text = f"""
            <div style="font-family: Arial, sans-serif; font-size: 12px;">
                <h4 style="margin: 0 0 10px 0; color: #333;">Hole {hole_num}</h4>
                <table style="border-collapse: collapse; width: 100%;">
                    <tr><td><b>Average Time:</b></td><td style="text-align: right;">{avg_time:.1f} min</td></tr>
                    <tr><td><b>Order Count:</b></td><td style="text-align: right;">{count}</td></tr>
                    <tr><td><b>Min Time:</b></td><td style="text-align: right;">{min_time_hole:.1f} min</td></tr>
                    <tr><td><b>Max Time:</b></td><td style="text-align: right;">{max_time_hole:.1f} min</td></tr>
                    {f'<tr><td><b>Std Dev:</b></td><td style="text-align: right;">{std_time:.1f} min</td></tr>' if count > 1 else ''}
                </table>
            </div>
            """
            
            # Create tooltip for hover
            tooltip_text = f"Hole {hole_num}: {avg_time:.1f}min avg ({count} orders)"
            
        else:
            # No data for this hole
            color = '#cccccc'
            fill_opacity = 0.2
            popup_text = f"<b>Hole {hole_num}</b><br>No delivery data"
            tooltip_text = f"Hole {hole_num}: No delivery data"
        
        # Convert polygon coordinates for folium (lat, lon format)
        if hasattr(polygon, 'exterior'):
            coords = [[lat, lon] for lon, lat in polygon.exterior.coords]
            
            folium.Polygon(
                locations=coords,
                color='black',
                weight=1,
                fillColor=color,
                fillOpacity=fill_opacity,
                popup=folium.Popup(popup_text, max_width=300),
                tooltip=tooltip_text
            ).add_to(m)
        
        # Add hole number marker at centroid
        if hasattr(polygon, 'centroid'):
            centroid = polygon.centroid
            folium.Marker(
                location=[centroid.y, centroid.x],
                popup=popup_text,
                tooltip=tooltip_text,
                icon=folium.DivIcon(
                    html=f'<div style="font-size: 12px; font-weight: bold; color: white; text-shadow: 1px 1px 1px black;">{hole_num}</div>',
                    icon_size=(30, 30),
                    icon_anchor=(15, 15)
                )
            ).add_to(m)
    
    # Add title
    title_html = f'''
    <div style="position: fixed; 
                top: 10px; left: 50px; width: 300px; height: 60px; 
                background-color: white; border:2px solid grey; z-index:9999; 
                font-size:14px; font-weight: bold;
                padding: 10px;
                ">
    <h4 style="margin: 0;">{title}</h4>
    <p style="margin: 5px 0 0 0; font-size: 12px; font-weight: normal;">
        Hover over holes for detailed delivery statistics
    </p>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(title_html))
    
    # Add legend
    if hole_stats:
        legend_html = f'''
        <div style="position: fixed; 
                    bottom: 50px; left: 50px; width: 200px; height: 100px; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:12px;
                    padding: 10px;
                    ">
        <h5 style="margin: 0 0 10px 0;">Drive Time Legend</h5>
        <div style="display: flex; align-items: center; margin-bottom: 5px;">
            <div style="width: 15px; height: 15px; background-color: #00ff00; margin-right: 5px;"></div>
            <span>Fast ({min_time:.1f} min)</span>
        </div>
        <div style="display: flex; align-items: center;">
            <div style="width: 15px; height: 15px; background-color: #ff0000; margin-right: 5px;"></div>
            <span>Slow ({max_time:.1f} min)</span>
        </div>
        <p style="margin: 5px 0 0 0; font-size: 10px;">
            Total: {len(order_data)} orders across {len(hole_stats)} holes
        </p>
        </div>
        '''
        m.get_root().html.add_child(folium.Element(legend_html))
    
    # Save the map
    m.save(str(save_path))
    
    logger.info("Saved interactive course heatmap: %s (%.1f KB)", 
                save_path, save_path.stat().st_size / 1024)
    
    return save_path


def create_course_heatmap_from_hole_avgs(hole_to_avg: Dict[int, float],
                                        course_dir: str | Path,
                                        save_path: str | Path,
                                        title: str = "Average Drive Time Heatmap (Aggregated)",
                                        colormap: str = 'white_to_red',
                                        use_basemap: bool = True,
                                        basemap_provider: str = 'auto',
                                        mapbox_token: Optional[str] = None) -> Path:
    """Create a course heatmap directly from per-hole average minutes.

    Args:
        hole_to_avg: Mapping of hole number -> average minutes to golfer
        course_dir: Course directory
        save_path: Output PNG path
        title: Plot title
        colormap: Matplotlib colormap name

    Returns:
        Path to saved heatmap file
    """
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)

    course_data, hole_polygons, hole_locations, course_bounds = load_all_heatmap_data(course_dir)

    fig, ax = plt.subplots(figsize=(14, 12))

    from matplotlib.colors import Normalize
    fixed_min_time = 0.0
    fixed_max_time = 10.0

    if colormap == 'white_to_red' or colormap == 'RdYlBu_r':
        from matplotlib.colors import LinearSegmentedColormap
        colors = ['white', '#ffe6e6', '#ffcccc', '#ff9999', '#ff6666', '#ff3333', '#ff0000']
        cmap = LinearSegmentedColormap.from_list('white_to_red', colors, N=256)
    else:
        cmap = plt.get_cmap(colormap)
    norm = Normalize(vmin=fixed_min_time, vmax=fixed_max_time)

    holes_gdf = gpd.GeoDataFrame(
        {"hole": list(hole_polygons.keys()), "geometry": list(hole_polygons.values())},
        crs="EPSG:4326",
    )
    holes_gdf["avg_time"] = holes_gdf["hole"].map(lambda h: hole_to_avg.get(int(h)) if h is not None else None)
    # Reproject to Web Mercator if using basemap
    did_reproject = False
    if use_basemap and _HAS_CX:
        try:
            holes_gdf = holes_gdf.to_crs(epsg=3857)
            did_reproject = True
        except Exception:
            did_reproject = False

    # Plot course polygon beneath holes if available
    if 'course_polygon' in course_data:
        course_poly = course_data['course_polygon']
        try:
            if did_reproject and hasattr(course_poly, 'to_crs'):
                course_poly = course_poly.to_crs(epsg=3857)
        except Exception:
            pass
        try:
            course_poly.plot(ax=ax, color='lightgray', alpha=0.2, edgecolor='black', linewidth=1.5)
        except Exception:
            pass

    holes_with_data = holes_gdf[holes_gdf["avg_time"].notna()]
    holes_without_data = holes_gdf[holes_gdf["avg_time"].isna()]

    if not holes_with_data.empty:
        holes_with_data.plot(
            ax=ax,
            column="avg_time",
            cmap=cmap,
            vmin=fixed_min_time,
            vmax=fixed_max_time,
            edgecolor="black",
            linewidth=1.2,
            alpha=0.85,
            aspect=None,
            legend=False,
            zorder=5,
        )

    if not holes_without_data.empty:
        holes_without_data.plot(
            ax=ax,
            color="lightgray",
            edgecolor="gray",
            linewidth=1.0,
            alpha=0.3,
            hatch="///",
            aspect=None,
            legend=False,
            zorder=4,
        )

    # Annotate holes with avg
    for _, row in holes_gdf.iterrows():
        geom = row.geometry
        if geom is None:
            continue
        rep_pt = geom.representative_point()
        hole_num = int(row["hole"]) if pd.notna(row["hole"]) else None
        if pd.notna(row.get("avg_time")):
            avg_time = float(row["avg_time"])  # type: ignore[arg-type]
            ax.annotate(
                f"Hole {hole_num}\nAvg: {avg_time:.1f}min",
                (rep_pt.x, rep_pt.y),
                fontsize=9,
                weight="bold",
                ha="center",
                va="center",
                color="white",
                bbox=dict(boxstyle="round,pad=0.3", facecolor="black", alpha=0.65, edgecolor="white"),
                zorder=10,
            )
        else:
            ax.annotate(
                f"Hole {hole_num}",
                (rep_pt.x, rep_pt.y),
                fontsize=9,
                ha="center",
                va="center",
                color="gray",
                weight="bold",
                zorder=6,
            )

    from matplotlib.cm import ScalarMappable
    sm = ScalarMappable(norm=norm, cmap=cmap)
    sm.set_array([])
    try:
        cbar = plt.colorbar(sm, ax=ax, shrink=0.8, aspect=30)
        cbar.set_label('Average Drive Time to Golfer (minutes)', fontsize=12)
        try:
            cbar.set_ticks([0, 2, 4, 6, 8, 10])
            cbar.set_ticklabels(['0', '2', '4', '6', '8', '10'])
        except Exception:
            pass
    except Exception as e:
        logger.warning("Failed to create colorbar: %s", e)

    if did_reproject and not holes_gdf.empty:
        xmin, ymin, xmax, ymax = holes_gdf.total_bounds
        margin_ratio = 0.05
        xmar = (xmax - xmin) * margin_ratio
        ymar = (ymax - ymin) * margin_ratio
        ax.set_xlim(xmin - xmar, xmax + xmar)
        ax.set_ylim(ymin - ymar, ymax + ymar)
    else:
        lon_min, lon_max, lat_min, lat_max = course_bounds
        margin = 0.05
        lon_margin = (lon_max - lon_min) * margin
        lat_margin = (lat_max - lat_min) * margin
        ax.set_xlim(lon_min - lon_margin, lon_max + lon_margin)
        ax.set_ylim(lat_min - lat_margin, lat_max + lat_margin)

    # Add basemap beneath if available/desirable
    if use_basemap and _HAS_CX:
        try:
            source = None
            if basemap_provider == 'auto':
                # Prefer Mapbox if token present, else Carto Positron
                token_env = mapbox_token or os.environ.get('MAPBOX_TOKEN') or os.environ.get('MAPBOX_API_KEY')
                if token_env:
                    # Mapbox Streets style
                    url = f"https://api.mapbox.com/styles/v1/mapbox/streets-v11/tiles/256/{{z}}/{{x}}/{{y}}@2x?access_token={token_env}"
                    source = {
                        'url': url,
                        'attribution': '© Mapbox © OpenStreetMap contributors',
                        'name': 'Mapbox Streets'
                    }
                else:
                    source = cx.providers.CartoDB.Positron  # type: ignore
            elif basemap_provider == 'mapbox-streets':
                token_env = mapbox_token or os.environ.get('MAPBOX_TOKEN') or os.environ.get('MAPBOX_API_KEY')
                if token_env:
                    url = f"https://api.mapbox.com/styles/v1/mapbox/streets-v11/tiles/256/{{z}}/{{x}}/{{y}}@2x?access_token={token_env}"
                    source = {
                        'url': url,
                        'attribution': '© Mapbox © OpenStreetMap contributors',
                        'name': 'Mapbox Streets'
                    }
                else:
                    source = cx.providers.CartoDB.Positron  # type: ignore
            elif basemap_provider == 'carto-positron':
                source = cx.providers.CartoDB.Positron  # type: ignore
            elif basemap_provider == 'stamen-toner':
                source = cx.providers.Stamen.Toner  # type: ignore
            else:
                source = cx.providers.CartoDB.Positron  # type: ignore

            if source is not None:
                cx.add_basemap(ax, source=source, crs=holes_gdf.crs)  # type: ignore
        except Exception as e:
            logger.warning("Failed to add basemap: %s", e)

    ax.set_title(title, fontsize=14, weight='bold')
    ax.set_xlabel('Longitude', fontsize=12)
    ax.set_ylabel('Latitude', fontsize=12)
    ax.grid(True, alpha=0.3)
    try:
        ax.set_aspect('equal')
    except ValueError:
        ax.set_aspect('auto')

    plt.tight_layout()
    plt.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='white')
    plt.close(fig)

    logger.info("Saved averaged course heatmap: %s (%.1f KB)", save_path, save_path.stat().st_size / 1024)
    return save_path