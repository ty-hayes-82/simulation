"""
Beverage Cart Metrics Analysis Module

This module provides GM-priority metrics calculation for beverage cart simulations,
specifically designed for executive decision-making on course beverage service.

The executive-priority metrics include:
1. Revenue per Round - Headline financial impact per tee sheet
2. Total Revenue - Total financial impact
3. Orders per Cart Hour - Labor productivity and throughput
4. Order Penetration Rate - Attach rate; how broadly golfers convert
5. Average Order Value - Revenue intensity per transaction
6. Total Tips - Service quality indicator and staff satisfaction
7. Total Delivery Orders Conversion Count - Cross-selling to delivery service
8. Total Delivery Orders Conversion Revenue - Revenue from delivery cross-sell
9. Holes Covered per Hour - Route efficiency and coverage
10. Minutes per Hole per Cart - Operational efficiency metric
"""

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class BevCartMetrics:
    """Executive-priority metrics for beverage cart simulation (GM-ready)."""
    
    # Executive-priority metrics
    revenue_per_round: float
    total_revenue: float
    orders_per_cart_hour: float
    order_penetration_rate: float
    average_order_value: float
    total_tips: float
    total_delivery_orders_conversion_count: int
    total_delivery_orders_conversion_revenue: float
    holes_covered_per_hour: float
    minutes_per_hole_per_cart: float
    
    # Additional metrics for batch processing
    unique_customers: int
    tip_rate: float
    tips_per_order: float
    total_holes_covered: int
    golfer_repeat_rate: float
    average_orders_per_customer: float
    customers_with_multiple_orders: int
    golfer_visibility_interval_minutes: float
    total_visibility_events: int
    service_hours: float
    rounds_in_service_window: int
    
    # Simulation details and aggregates
    total_orders: int
    simulation_id: str
    cart_id: str


def calculate_bev_cart_metrics(
    sales_data: List[Dict[str, Any]],
    coordinates: List[Dict[str, Any]],
    golfer_data: Optional[List[Dict[str, Any]]] = None,
    delivery_conversion_data: Optional[List[Dict[str, Any]]] = None,
    service_start_s: int = 7200,  # 9 AM
    service_end_s: int = 36000,   # 5 PM
    simulation_id: str = "unknown",
    cart_id: str = "bev_cart_1",
    tip_rate_percentage: float = 15.0,  # Default 15% tip rate
    proximity_threshold_m: float = 70.0,  # 70m proximity for visibility
    proximity_duration_s: int = 30,  # 30 seconds minimum for visibility event
) -> BevCartMetrics:
    """
    Calculate executive-priority metrics for beverage cart simulation.
    """
    
    # Calculate service window metrics
    service_hours = (service_end_s - service_start_s) / 3600.0
    rounds_in_service_window = max(1, int(service_hours / 3.0))  # Assume 3 hours per round
    
    # Revenue and order metrics
    total_revenue = sum(sale.get("price", 0.0) for sale in sales_data)
    total_orders = len(sales_data)
    revenue_per_round = total_revenue / rounds_in_service_window if rounds_in_service_window > 0 else 0.0
    average_order_value = total_revenue / total_orders if total_orders > 0 else 0.0
    
    # Orders per cart hour
    orders_per_cart_hour = total_orders / service_hours if service_hours > 0 else 0.0
    
    # Order penetration rate (unique customers / rounds)
    unique_customers = len(set(sale.get("group_id") for sale in sales_data))
    order_penetration_rate = unique_customers / rounds_in_service_window if rounds_in_service_window > 0 else 0.0
    
    # Tip calculations
    tip_rate = tip_rate_percentage / 100.0
    total_tips = total_revenue * tip_rate
    
    # Delivery conversion metrics
    delivery_conversion_data = delivery_conversion_data or []
    total_delivery_orders_conversion_count = len(delivery_conversion_data)
    total_delivery_orders_conversion_revenue = sum(
        order.get("price", 0.0) for order in delivery_conversion_data
    )
    
    # Coverage metrics
    holes_covered = _calculate_holes_covered(coordinates)
    holes_covered_per_hour = holes_covered / service_hours if service_hours > 0 else 0.0
    minutes_per_hole_per_cart = (service_hours * 60) / holes_covered if holes_covered > 0 else 0.0
    
    # Additional metrics for batch processing
    tips_per_order = total_tips / total_orders if total_orders > 0 else 0.0
    
    # Customer behavior metrics
    customer_order_counts = _calculate_customer_order_counts(sales_data)
    customers_with_multiple_orders = sum(1 for count in customer_order_counts.values() if count > 1)
    average_orders_per_customer = sum(customer_order_counts.values()) / len(customer_order_counts) if customer_order_counts else 0.0
    golfer_repeat_rate = customers_with_multiple_orders / len(customer_order_counts) if customer_order_counts else 0.0
    
    # Visibility metrics
    visibility_interval_minutes, total_visibility_events = _calculate_visibility_metrics(
        coordinates, golfer_data, proximity_threshold_m, proximity_duration_s
    )
    
    return BevCartMetrics(
        revenue_per_round=revenue_per_round,
        total_revenue=total_revenue,
        orders_per_cart_hour=orders_per_cart_hour,
        order_penetration_rate=order_penetration_rate,
        average_order_value=average_order_value,
        total_tips=total_tips,
        total_delivery_orders_conversion_count=total_delivery_orders_conversion_count,
        total_delivery_orders_conversion_revenue=total_delivery_orders_conversion_revenue,
        holes_covered_per_hour=holes_covered_per_hour,
        minutes_per_hole_per_cart=minutes_per_hole_per_cart,
        # Additional metrics
        unique_customers=unique_customers,
        tip_rate=tip_rate,
        tips_per_order=tips_per_order,
        total_holes_covered=holes_covered,
        golfer_repeat_rate=golfer_repeat_rate,
        average_orders_per_customer=average_orders_per_customer,
        customers_with_multiple_orders=customers_with_multiple_orders,
        golfer_visibility_interval_minutes=visibility_interval_minutes,
        total_visibility_events=total_visibility_events,
        service_hours=service_hours,
        rounds_in_service_window=rounds_in_service_window,
        # Simulation details
        total_orders=total_orders,
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
    Summarize executive-priority metrics across multiple runs.
    """
    if not metrics_list:
        return {}

    def _mm(arr: List[float]) -> Dict[str, float]:
        return {"mean": statistics.mean(arr), "min": min(arr), "max": max(arr)} if arr else {"mean": 0.0, "min": 0.0, "max": 0.0}

    summaries: Dict[str, Any] = {}

    # Executive metrics
    summaries["revenue_per_round"] = _mm([m.revenue_per_round for m in metrics_list])
    summaries["total_revenue"] = _mm([m.total_revenue for m in metrics_list])
    summaries["orders_per_cart_hour"] = _mm([m.orders_per_cart_hour for m in metrics_list])
    summaries["order_penetration_rate"] = _mm([m.order_penetration_rate for m in metrics_list])
    summaries["average_order_value"] = _mm([m.average_order_value for m in metrics_list])
    summaries["total_tips"] = _mm([m.total_tips for m in metrics_list])
    summaries["total_delivery_orders_conversion_count"] = _mm([float(m.total_delivery_orders_conversion_count) for m in metrics_list])
    summaries["total_delivery_orders_conversion_revenue"] = _mm([m.total_delivery_orders_conversion_revenue for m in metrics_list])
    summaries["holes_covered_per_hour"] = _mm([m.holes_covered_per_hour for m in metrics_list])
    summaries["minutes_per_hole_per_cart"] = _mm([m.minutes_per_hole_per_cart for m in metrics_list])

    # Totals
    summaries["total_orders_sum"] = sum(m.total_orders for m in metrics_list)
    summaries["total_revenue_sum"] = sum(m.total_revenue for m in metrics_list)
    summaries["total_delivery_conversion_count_sum"] = sum(m.total_delivery_orders_conversion_count for m in metrics_list)
    summaries["total_delivery_conversion_revenue_sum"] = sum(m.total_delivery_orders_conversion_revenue for m in metrics_list)

    return summaries


def format_metrics_report(metrics: BevCartMetrics) -> str:
    """Format executive-priority beverage cart metrics as a GM-ready markdown report."""
    report = f"""# Beverage Cart Executive Metrics

## Executive Priority Ranking (Most Persuasive First)
1. **Revenue per Round**: ${metrics.revenue_per_round:.2f}
2. **Total Revenue**: ${metrics.total_revenue:.2f}
3. **Orders per Cart Hour**: {metrics.orders_per_cart_hour:.2f}
4. **Order Penetration Rate**: {metrics.order_penetration_rate:.2f}
5. **Average Order Value**: ${metrics.average_order_value:.2f}
6. **Total Tips**: ${metrics.total_tips:.2f}
7. **Total Delivery Orders Conversion Count**: {metrics.total_delivery_orders_conversion_count}
8. **Total Delivery Orders Conversion Revenue**: ${metrics.total_delivery_orders_conversion_revenue:.2f}
9. **Holes Covered per Hour**: {metrics.holes_covered_per_hour:.2f}
10. **Minutes per Hole per Cart**: {metrics.minutes_per_hole_per_cart:.1f}

## Simulation Details
- Simulation ID: {metrics.simulation_id}
- Cart ID: {metrics.cart_id}
- Total Orders: {metrics.total_orders}

> Tip: Lead with 1–5 to show revenue and efficiency, use 6–8 to prove service quality and cross-selling, and close with 9–10 as the operational story.
"""
    return report


def format_summary_report(summaries: Dict[str, Any], num_runs: int) -> str:
    """Format executive-priority metrics summary as a markdown report."""
    report = f"""# Beverage Cart Metrics Summary

## Summary Statistics (Across {num_runs} Runs)
- Revenue per Round — Mean: ${summaries.get('revenue_per_round', {}).get('mean', 0):.2f} (Range: ${summaries.get('revenue_per_round', {}).get('min', 0):.2f}–${summaries.get('revenue_per_round', {}).get('max', 0):.2f})
- Total Revenue — Mean: ${summaries.get('total_revenue', {}).get('mean', 0):.2f}
- Orders per Cart Hour — Mean: {summaries.get('orders_per_cart_hour', {}).get('mean', 0):.2f}
- Order Penetration Rate — Mean: {summaries.get('order_penetration_rate', {}).get('mean', 0):.2f}
- Average Order Value — Mean: ${summaries.get('average_order_value', {}).get('mean', 0):.2f}
- Total Tips — Mean: ${summaries.get('total_tips', {}).get('mean', 0):.2f}
- Delivery Orders Conversion Count — Mean: {summaries.get('total_delivery_orders_conversion_count', {}).get('mean', 0):.0f}
- Delivery Orders Conversion Revenue — Mean: ${summaries.get('total_delivery_orders_conversion_revenue', {}).get('mean', 0):.2f}
- Holes Covered per Hour — Mean: {summaries.get('holes_covered_per_hour', {}).get('mean', 0):.2f}
- Minutes per Hole per Cart — Mean: {summaries.get('minutes_per_hole_per_cart', {}).get('mean', 0):.1f} min

## Aggregate Totals
- Total Revenue: ${summaries.get('total_revenue_sum', 0):.2f}
- Total Orders: {summaries.get('total_orders_sum', 0)}
- Total Delivery Conversion Count: {summaries.get('total_delivery_conversion_count_sum', 0)}
- Total Delivery Conversion Revenue: ${summaries.get('total_delivery_conversion_revenue_sum', 0):.2f}
"""
    return report