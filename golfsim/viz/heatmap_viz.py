"""
Heatmap visualization utilities for golf delivery simulation.

This module provides functions for creating heatmaps of order placement locations
on the golf course, color-coded by average delivery times.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any

import geopandas as gpd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from matplotlib.colors import LinearSegmentedColormap
from shapely.geometry import LineString, Point

from ..logging import get_logger
from .matplotlib_viz import load_course_geospatial_data, calculate_course_bounds

logger = get_logger(__name__)


def load_hole_locations(course_dir: str | Path) -> Dict[int, Tuple[float, float]]:
    """Load hole locations from course GeoJSON files.
    
    Args:
        course_dir: Path to course directory
        
    Returns:
        Dictionary mapping hole numbers to (longitude, latitude) coordinates
    """
    course_path = Path(course_dir)
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
            
    return hole_locations


def extract_order_data(results: Dict) -> List[Dict[str, Any]]:
    """Extract order placement data from simulation results.
    
    Args:
        results: Simulation results dictionary
        
    Returns:
        List of order data dictionaries with hole_num, delivery_time, and coordinates
    """
    orders = results.get('orders', [])
    delivery_stats = results.get('delivery_stats', [])
    
    order_data = []
    
    for i, order in enumerate(orders):
        hole_num = order.get('hole_num')
        if hole_num is None:
            continue
            
        # Get delivery time - try multiple sources
        delivery_time_s = None
        
        # First try from order itself
        if 'total_completion_time_s' in order:
            delivery_time_s = order['total_completion_time_s']
        # Then try from delivery stats
        elif i < len(delivery_stats) and 'total_completion_time_s' in delivery_stats[i]:
            delivery_time_s = delivery_stats[i]['total_completion_time_s']
        
        if delivery_time_s is not None:
            order_data.append({
                'hole_num': hole_num,
                'delivery_time_s': delivery_time_s,
                'delivery_time_min': delivery_time_s / 60.0,
                'order_id': order.get('order_id', f'order_{i}'),
                'golfer_group_id': order.get('golfer_group_id'),
                'order_time_s': order.get('order_time_s', 0)
            })
    
    return order_data


def calculate_delivery_time_stats(order_data: List[Dict[str, Any]]) -> Dict[int, Dict[str, float]]:
    """Calculate delivery time statistics for each hole.
    
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
        orders_by_hole[hole_num].append(order['delivery_time_min'])
    
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


def load_geofenced_holes(course_dir: str | Path) -> Dict[int, Any]:
    """Load geofenced hole polygons from course data as shapely geometries.

    Supports Polygon and MultiPolygon features. Returns a mapping of
    hole number to shapely geometry.
    """
    course_path = Path(course_dir)
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

            if "hole" not in gdf.columns:
                logger.warning("holes_geofenced.geojson missing 'hole' property")
            else:
                for _, row in gdf.iterrows():
                    hole = row.get("hole")
                    geom = row.geometry
                    if hole is None or geom is None:
                        continue
                    try:
                        hole_int = int(hole)
                    except Exception:
                        continue
                    hole_polygons[hole_int] = geom
        except Exception as e:
            logger.error("Failed to load geofenced holes: %s", e)

    return hole_polygons


def create_course_heatmap(results: Dict,
                         course_dir: str | Path,
                         save_path: str | Path,
                         title: str = "Golf Course Order Delivery Time Heatmap",
                         grid_resolution: int = 100,
                         colormap: str = 'RdYlGn_r') -> Path:
    """Create a heatmap visualization of order delivery times across the golf course.
    
    Args:
        results: Simulation results dictionary
        course_dir: Path to course directory containing geojson data
        save_path: Output PNG path
        title: Plot title
        grid_resolution: Resolution of the heatmap grid (unused in polygon mode)
        colormap: Matplotlib colormap name
        
    Returns:
        Path to saved heatmap file
    """
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info("Creating course heatmap: %s", save_path)
    
    # Load course data and hole geometries
    course_data = load_course_geospatial_data(course_dir)
    hole_polygons = load_geofenced_holes(course_dir)
    hole_locations = load_hole_locations(course_dir)
    course_bounds = calculate_course_bounds(course_data)
    
    # Extract order data and calculate statistics
    order_data = extract_order_data(results)
    hole_stats = calculate_delivery_time_stats(order_data)
    
    if not order_data:
        logger.warning("No order data found for heatmap")
        # Create a simple course plot without heatmap
        fig, ax = plt.subplots(figsize=(12, 10))
        if 'course_polygon' in course_data:
            course_poly = course_data['course_polygon']
            course_poly.plot(ax=ax, color='lightgreen', alpha=0.3, edgecolor='darkgreen')
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
    from matplotlib.cm import get_cmap
    
    if hole_stats:
        # Get delivery time range for color normalization
        delivery_times = [stats['avg_time'] for stats in hole_stats.values()]
        min_time = min(delivery_times)
        max_time = max(delivery_times)
        
        # Create colormap and normalization
        cmap = get_cmap(colormap)
        norm = Normalize(vmin=min_time, vmax=max_time)
        
        # Build a GeoDataFrame from geofenced holes so we can plot polygons (incl. MultiPolygon)
        holes_gdf = gpd.GeoDataFrame(
            {"hole": list(hole_polygons.keys()), "geometry": list(hole_polygons.values())},
            crs="EPSG:4326",
        )

        # Map avg time per hole
        hole_to_avg = {h: s["avg_time"] for h, s in hole_stats.items()}
        holes_gdf["avg_time"] = holes_gdf["hole"].map(hole_to_avg)

        # Plot polygons colored by avg_time; holes without data are rendered via missing_kwds
        holes_gdf.plot(
            ax=ax,
            column="avg_time",
            cmap=colormap,
            vmin=min_time,
            vmax=max_time,
            edgecolor="black",
            linewidth=1.2,
            alpha=0.8,
            legend=False,
            missing_kwds={"color": "lightgray", "edgecolor": "gray", "alpha": 0.25},
            zorder=5,
        )

        # Annotate each hole at a representative point
        for _, row in holes_gdf.iterrows():
            geom = row.geometry
            if geom is None:
                continue
            rep_pt = geom.representative_point()
            hole_num = int(row["hole"]) if pd.notna(row["hole"]) else None
            if pd.notna(row["avg_time"]):
                avg_time = float(row["avg_time"])  # type: ignore[arg-type]
                ax.annotate(
                    f"{hole_num}\n{avg_time:.1f}min",
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
                    f"{hole_num}",
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
        cbar = plt.colorbar(sm, ax=ax, shrink=0.8, aspect=30)
        cbar.set_label('Average Delivery Time (minutes)', fontsize=12)
    
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
        avg_delivery_time = np.mean([o['delivery_time_min'] for o in order_data])
        min_delivery_time = np.min([o['delivery_time_min'] for o in order_data])
        max_delivery_time = np.max([o['delivery_time_min'] for o in order_data])
        
        subtitle = (f"{total_orders} orders | "
                   f"Avg: {avg_delivery_time:.1f} min | "
                   f"Range: {min_delivery_time:.1f}-{max_delivery_time:.1f} min")
    else:
        subtitle = "No orders processed"
    
    ax.set_title(f"{title}\n{subtitle}", fontsize=14, weight='bold')
    ax.set_xlabel('Longitude', fontsize=12)
    ax.set_ylabel('Latitude', fontsize=12)
    ax.grid(True, alpha=0.3)
    ax.set_aspect('equal')
    
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
    """Create a text summary of delivery statistics by hole.
    
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
    summary_lines.append("Golf Course Delivery Statistics Summary")
    summary_lines.append("=" * 50)
    summary_lines.append("")
    
    # Overall statistics
    if order_data:
        total_orders = len(order_data)
        avg_time = np.mean([o['delivery_time_min'] for o in order_data])
        min_time = np.min([o['delivery_time_min'] for o in order_data])
        max_time = np.max([o['delivery_time_min'] for o in order_data])
        
        summary_lines.extend([
            f"Total Orders: {total_orders}",
            f"Average Delivery Time: {avg_time:.1f} minutes",
            f"Minimum Delivery Time: {min_time:.1f} minutes", 
            f"Maximum Delivery Time: {max_time:.1f} minutes",
            ""
        ])
    else:
        summary_lines.extend([
            "No orders found in simulation results",
            ""
        ])
    
    # Per-hole statistics
    if hole_stats:
        summary_lines.append("Delivery Times by Hole:")
        summary_lines.append("-" * 30)
        
        # Sort holes by average delivery time (descending)
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
        logger.info("Saved delivery statistics summary: %s", save_path)
    
    return summary_text
