"""
Beverage cart metrics calculation for simulation analysis.

This module provides comprehensive metrics calculation for bev-cart only simulations,
including revenue, orders, tips, coverage, and golfer interaction metrics.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
import math

logger = logging.getLogger(__name__)


@dataclass
class BevCartMetrics:
    """Comprehensive metrics for beverage cart simulation."""
    
    # Revenue metrics
    revenue_per_round: float
    average_order_value: float
    total_revenue: float
    
    # Order metrics
    order_penetration_rate: float
    orders_per_cart_hour: float
    total_orders: int
    unique_customers: int
    
    # Tip metrics
    tip_rate: float
    tips_per_order: float
    total_tips: float
    
    # Coverage metrics
    holes_covered_per_hour: float
    minutes_per_hole_per_cart: float
    total_holes_covered: int
    
    # Customer metrics
    golfer_repeat_rate: float
    average_orders_per_customer: float
    customers_with_multiple_orders: int
    
    # Visibility metrics
    golfer_visibility_interval_minutes: float
    total_visibility_events: int
    
    # Service window metrics
    service_hours: float
    rounds_in_service_window: int
    
    # Metadata
    simulation_id: str
    cart_id: str


def calculate_bev_cart_metrics(
    sales_data: List[Dict[str, Any]],
    coordinates: List[Dict[str, Any]],
    golfer_data: Optional[List[Dict[str, Any]]] = None,
    service_start_s: int = 7200,  # 9 AM
    service_end_s: int = 36000,   # 5 PM
    simulation_id: str = "unknown",
    cart_id: str = "bev_cart_1",
    tip_rate_percentage: float = 15.0,  # Default 15% tip rate
    proximity_threshold_m: float = 70.0,  # 70m proximity for visibility
    proximity_duration_s: int = 30,  # 30 seconds minimum for visibility event
) -> BevCartMetrics:
    """
    Calculate comprehensive metrics for beverage cart simulation.
    
    Args:
        sales_data: List of sales records with timestamp_s, price, group_id, hole_num
        coordinates: List of GPS coordinates with timestamp, latitude, longitude, current_hole
        golfer_data: Optional golfer GPS data for visibility calculations
        service_start_s: Service start time in seconds since 7 AM
        service_end_s: Service end time in seconds since 7 AM
        simulation_id: Unique identifier for this simulation
        cart_id: Cart identifier
        tip_rate_percentage: Tip rate as percentage of order value
        proximity_threshold_m: Distance threshold for golfer visibility (meters)
        proximity_duration_s: Minimum duration for visibility event (seconds)
        
    Returns:
        BevCartMetrics object with all calculated metrics
    """
    
    # Calculate service window metrics
    service_hours = (service_end_s - service_start_s) / 3600.0
    rounds_in_service_window = max(1, int(service_hours / 3.0))  # Assume 3 hours per round
    
    # Revenue and order metrics
    total_revenue = sum(sale.get("price", 0.0) for sale in sales_data)
    total_orders = len(sales_data)
    revenue_per_round = total_revenue / rounds_in_service_window if rounds_in_service_window > 0 else 0.0
    average_order_value = total_revenue / total_orders if total_orders > 0 else 0.0
    
    # Tip calculations
    tip_rate = tip_rate_percentage / 100.0
    total_tips = total_revenue * tip_rate
    tips_per_order = total_tips / total_orders if total_orders > 0 else 0.0
    
    # Order penetration rate (unique customers / rounds)
    unique_customers = len(set(sale.get("group_id") for sale in sales_data))
    order_penetration_rate = unique_customers / rounds_in_service_window if rounds_in_service_window > 0 else 0.0
    
    # Orders per cart hour
    orders_per_cart_hour = total_orders / service_hours if service_hours > 0 else 0.0
    
    # Coverage metrics
    holes_covered = _calculate_holes_covered(coordinates)
    holes_covered_per_hour = holes_covered / service_hours if service_hours > 0 else 0.0
    minutes_per_hole_per_cart = (service_hours * 60) / holes_covered if holes_covered > 0 else 0.0
    
    # Customer repeat metrics
    customer_order_counts = _calculate_customer_order_counts(sales_data)
    customers_with_multiple_orders = sum(1 for count in customer_order_counts.values() if count >= 2)
    golfer_repeat_rate = customers_with_multiple_orders / unique_customers if unique_customers > 0 else 0.0
    average_orders_per_customer = sum(customer_order_counts.values()) / len(customer_order_counts) if customer_order_counts else 0.0
    
    # Visibility metrics
    visibility_interval, visibility_events = _calculate_visibility_metrics(
        coordinates, golfer_data, proximity_threshold_m, proximity_duration_s
    )
    
    return BevCartMetrics(
        revenue_per_round=revenue_per_round,
        average_order_value=average_order_value,
        total_revenue=total_revenue,
        order_penetration_rate=order_penetration_rate,
        orders_per_cart_hour=orders_per_cart_hour,
        total_orders=total_orders,
        unique_customers=unique_customers,
        tip_rate=tip_rate,
        tips_per_order=tips_per_order,
        total_tips=total_tips,
        holes_covered_per_hour=holes_covered_per_hour,
        minutes_per_hole_per_cart=minutes_per_hole_per_cart,
        total_holes_covered=holes_covered,
        golfer_repeat_rate=golfer_repeat_rate,
        average_orders_per_customer=average_orders_per_customer,
        customers_with_multiple_orders=customers_with_multiple_orders,
        golfer_visibility_interval_minutes=visibility_interval,
        total_visibility_events=visibility_events,
        service_hours=service_hours,
        rounds_in_service_window=rounds_in_service_window,
        simulation_id=simulation_id,
        cart_id=cart_id,
    )


def _calculate_holes_covered(coordinates: List[Dict[str, Any]]) -> int:
    """Calculate total number of unique holes covered by the cart."""
    if not coordinates:
        return 0
    
    holes_covered = set()
    for coord in coordinates:
        hole = coord.get("current_hole") or coord.get("hole")
        if hole and isinstance(hole, (int, float)):
            holes_covered.add(int(hole))
    
    return len(holes_covered)


def _calculate_customer_order_counts(sales_data: List[Dict[str, Any]]) -> Dict[int, int]:
    """Calculate how many orders each customer placed."""
    customer_counts = {}
    for sale in sales_data:
        group_id = sale.get("group_id")
        if group_id is not None:
            customer_counts[group_id] = customer_counts.get(group_id, 0) + 1
    return customer_counts


def _calculate_visibility_metrics(
    cart_coordinates: List[Dict[str, Any]],
    golfer_data: Optional[List[Dict[str, Any]]],
    proximity_threshold_m: float,
    proximity_duration_s: int
) -> Tuple[float, int]:
    """
    Calculate golfer visibility metrics based on GPS proximity.
    
    Returns:
        Tuple of (average_visibility_interval_minutes, total_visibility_events)
    """
    if not golfer_data or not cart_coordinates:
        return 0.0, 0
    
    visibility_events = []
    
    # Group golfer data by timestamp for efficient processing
    golfer_by_time = {}
    for golfer_point in golfer_data:
        timestamp = golfer_point.get("timestamp")
        if timestamp:
            if timestamp not in golfer_by_time:
                golfer_by_time[timestamp] = []
            golfer_by_time[timestamp].append(golfer_point)
    
    # Check each cart position for nearby golfers
    for cart_point in cart_coordinates:
        cart_timestamp = cart_point.get("timestamp")
        cart_lat = cart_point.get("latitude")
        cart_lon = cart_point.get("longitude")
        
        if not all([cart_timestamp, cart_lat, cart_lon]):
            continue
        
        # Find golfers at the same timestamp
        if cart_timestamp in golfer_by_time:
            for golfer_point in golfer_by_time[cart_timestamp]:
                golfer_lat = golfer_point.get("latitude")
                golfer_lon = golfer_point.get("longitude")
                
                if golfer_lat and golfer_lon:
                    distance = _calculate_distance_m(
                        cart_lat, cart_lon, golfer_lat, golfer_lon
                    )
                    
                    if distance <= proximity_threshold_m:
                        visibility_events.append({
                            "timestamp": cart_timestamp,
                            "distance_m": distance,
                            "cart_lat": cart_lat,
                            "cart_lon": cart_lon,
                            "golfer_lat": golfer_lat,
                            "golfer_lon": golfer_lon,
                        })
    
    # Calculate average interval between visibility events
    if len(visibility_events) < 2:
        return 0.0, len(visibility_events)
    
    # Sort by timestamp and calculate intervals
    visibility_events.sort(key=lambda x: x["timestamp"])
    intervals = []
    
    for i in range(1, len(visibility_events)):
        interval_s = visibility_events[i]["timestamp"] - visibility_events[i-1]["timestamp"]
        if interval_s >= proximity_duration_s:  # Only count if duration threshold met
            intervals.append(interval_s)
    
    if not intervals:
        return 0.0, len(visibility_events)
    
    average_interval_s = sum(intervals) / len(intervals)
    average_interval_minutes = average_interval_s / 60.0
    
    return average_interval_minutes, len(visibility_events)


def _calculate_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two GPS coordinates in meters using Haversine formula."""
    R = 6371000  # Earth's radius in meters
    
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)
    
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = (math.sin(dlat/2)**2 + 
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return R * c


def summarize_bev_cart_metrics(metrics_list: List[BevCartMetrics]) -> Dict[str, Any]:
    """
    Summarize metrics across multiple simulations.
    
    Args:
        metrics_list: List of BevCartMetrics objects
        
    Returns:
        Dictionary with summary statistics for all metrics
    """
    if not metrics_list:
        return {}
    
    summary = {
        "total_simulations": len(metrics_list),
        "metrics": {}
    }
    
    # Get all metric names from the first object
    metric_names = [field.name for field in BevCartMetrics.__dataclass_fields__.values()]
    
    for metric_name in metric_names:
        values = [getattr(metrics, metric_name) for metrics in metrics_list]
        
        # Filter out non-numeric values
        numeric_values = [v for v in values if isinstance(v, (int, float)) and not math.isnan(v)]
        
        if numeric_values:
            summary["metrics"][metric_name] = {
                "mean": sum(numeric_values) / len(numeric_values),
                "min": min(numeric_values),
                "max": max(numeric_values),
                "sum": sum(numeric_values),
                "count": len(numeric_values),
                "total_simulations": len(metrics_list),
            }
        else:
            summary["metrics"][metric_name] = {
                "mean": 0.0,
                "min": 0.0,
                "max": 0.0,
                "sum": 0.0,
                "count": 0,
                "total_simulations": len(metrics_list)
            }
    
    return summary


def format_metrics_report(metrics: BevCartMetrics) -> str:
    """Format metrics into a readable report string."""
    # Top 10 key metrics for quick scanning
    lines = [
        f"# Beverage Cart Metrics Report - {metrics.simulation_id}",
        f"Cart ID: {metrics.cart_id}",
        "",
        "## Top 10 Metrics",
        f"- Revenue per Round (RPR): ${metrics.revenue_per_round:.2f}",
        f"- Total Revenue: ${metrics.total_revenue:.2f}",
        f"- Total Orders: {metrics.total_orders}",
        f"- Average Order Value (AOV): ${metrics.average_order_value:.2f}",
        f"- Orders per Cart Hour: {metrics.orders_per_cart_hour:.2f}",
        f"- Order Penetration Rate: {metrics.order_penetration_rate:.2f}",
        f"- Total Tips: ${metrics.total_tips:.2f}",
        f"- Holes Covered per Hour: {metrics.holes_covered_per_hour:.2f}",
        f"- Minutes per Hole per Cart: {metrics.minutes_per_hole_per_cart:.1f}",
        f"- Total Visibility Events: {metrics.total_visibility_events}",
        "",
        "## Revenue Metrics",
        f"- Revenue per Round (RPR): ${metrics.revenue_per_round:.2f}",
        f"- Average Order Value (AOV): ${metrics.average_order_value:.2f}",
        f"- Total Revenue: ${metrics.total_revenue:.2f}",
        f"- Total Tips: ${metrics.total_tips:.2f}",
        f"- Tip Rate: {metrics.tip_rate:.1%}",
        f"- Tips per Order: ${metrics.tips_per_order:.2f}",
        "",
        "## Order Metrics",
        f"- Total Orders: {metrics.total_orders}",
        f"- Unique Customers: {metrics.unique_customers}",
        f"- Order Penetration Rate: {metrics.order_penetration_rate:.2f}",
        f"- Orders per Cart Hour: {metrics.orders_per_cart_hour:.2f}",
        "",
        "## Coverage Metrics",
        f"- Total Holes Covered: {metrics.total_holes_covered}",
        f"- Holes Covered per Hour: {metrics.holes_covered_per_hour:.2f}",
        f"- Minutes per Hole per Cart: {metrics.minutes_per_hole_per_cart:.1f}",
        "",
        "## Customer Metrics",
        f"- Customers with Multiple Orders: {metrics.customers_with_multiple_orders}",
        f"- Golfer Repeat Rate: {metrics.golfer_repeat_rate:.1%}",
        f"- Average Orders per Customer: {metrics.average_orders_per_customer:.2f}",
        "",
        "## Visibility Metrics",
        f"- Total Visibility Events: {metrics.total_visibility_events}",
        f"- Average Visibility Interval: {metrics.golfer_visibility_interval_minutes:.1f} minutes",
        "",
        "## Service Window",
        f"- Service Hours: {metrics.service_hours:.1f}",
        f"- Rounds in Service Window: {metrics.rounds_in_service_window}",
    ]
    
    return "\n".join(lines)


def format_summary_report(summary: Dict[str, Any]) -> str:
    """Format summary statistics into a readable report string."""
    lines = [
        f"# Beverage Cart Metrics Summary",
        f"Total Simulations: {summary.get('total_simulations', 0)}",
        "",
    ]
    
    metrics = summary.get("metrics", {})
    
    # Group metrics by category
    categories = {
        "Revenue": ["revenue_per_round", "average_order_value", "total_revenue", "total_tips", "tip_rate", "tips_per_order"],
        "Orders": ["total_orders", "unique_customers", "order_penetration_rate", "orders_per_cart_hour"],
        "Coverage": ["total_holes_covered", "holes_covered_per_hour", "minutes_per_hole_per_cart"],
        "Customers": ["customers_with_multiple_orders", "golfer_repeat_rate", "average_orders_per_customer"],
        "Visibility": ["total_visibility_events", "golfer_visibility_interval_minutes"],
        "Service": ["service_hours", "rounds_in_service_window"]
    }
    
    for category, metric_names in categories.items():
        lines.append(f"## {category} Metrics")
        for metric_name in metric_names:
            if metric_name in metrics:
                metric_data = metrics[metric_name]
                if metric_name in ["tip_rate", "golfer_repeat_rate", "order_penetration_rate"]:
                    # Format as percentage
                    lines.append(f"- {metric_name.replace('_', ' ').title()}: {metric_data['mean']:.1%} (min: {metric_data['min']:.1%}, max: {metric_data['max']:.1%})")
                elif metric_name in ["total_orders", "unique_customers", "total_holes_covered", "customers_with_multiple_orders", "total_visibility_events", "rounds_in_service_window"]:
                    # Format as integers
                    lines.append(f"- {metric_name.replace('_', ' ').title()}: mean={metric_data['mean']:.0f}, sum={metric_data['sum']:.0f} (min: {metric_data['min']:.0f}, max: {metric_data['max']:.0f})")
                else:
                    # Format as decimals
                    # For monetary or rate per hour metrics, include sum as well
                    if metric_name in ["total_revenue", "total_tips"]:
                        lines.append(f"- {metric_name.replace('_', ' ').title()}: mean=${metric_data['mean']:.2f}, sum=${metric_data['sum']:.2f} (min: ${metric_data['min']:.2f}, max: ${metric_data['max']:.2f})")
                    else:
                        lines.append(f"- {metric_name.replace('_', ' ').title()}: mean={metric_data['mean']:.2f}, sum={metric_data['sum']:.2f} (min: {metric_data['min']:.2f}, max: {metric_data['max']:.2f})")
        lines.append("")
    
    return "\n".join(lines)
