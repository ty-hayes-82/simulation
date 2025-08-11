"""
Running totals calculation for beverage cart metrics.

This module provides utilities to calculate and track running totals for orders,
revenue, and performance metrics that can be added to GPS coordinate files.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def calculate_running_totals(
    sales_data: List[Dict[str, Any]], 
    service_start_s: int = 7200,  # 9 AM (2 hours after 7 AM baseline)
    service_end_s: int = 36000    # 5 PM (10 hours after 7 AM baseline)
) -> Dict[int, Dict[str, float]]:
    """
    Calculate running totals for beverage cart metrics based on sales data.
    
    Args:
        sales_data: List of sales records with timestamp_s, price, group_id, hole_num
        service_start_s: Service start time in seconds since 7 AM
        service_end_s: Service end time in seconds since 7 AM
        
    Returns:
        Dictionary mapping timestamp_s to running totals:
        {
            timestamp_s: {
                "total_orders": int,
                "total_revenue": float, 
                "avg_per_order": float,
                "revenue_per_hour": float
            }
        }
    """
    if not sales_data:
        return {}
    
    # Sort sales by timestamp
    sorted_sales = sorted(sales_data, key=lambda x: x.get("timestamp_s", 0))
    
    running_totals = {}
    cumulative_orders = 0
    cumulative_revenue = 0.0
    
    for sale in sorted_sales:
        timestamp_s = sale.get("timestamp_s", 0)
        price = float(sale.get("price", 0.0))
        
        # Update cumulative values
        cumulative_orders += 1
        cumulative_revenue += price
        
        # Calculate metrics
        avg_per_order = cumulative_revenue / cumulative_orders if cumulative_orders > 0 else 0.0
        
        # Calculate revenue per hour based on elapsed service time
        elapsed_hours = max((timestamp_s - service_start_s) / 3600.0, 0.1)  # Avoid division by zero
        revenue_per_hour = cumulative_revenue / elapsed_hours
        
        running_totals[timestamp_s] = {
            "total_orders": cumulative_orders,
            "total_revenue": round(cumulative_revenue, 2),
            "avg_per_order": round(avg_per_order, 2),
            "revenue_per_hour": round(revenue_per_hour, 2)
        }
    
    return running_totals


def get_running_totals_at_timestamp(
    running_totals: Dict[int, Dict[str, float]], 
    timestamp_s: int
) -> Dict[str, float]:
    """
    Get the most recent running totals at or before a given timestamp.
    
    Args:
        running_totals: Dictionary from calculate_running_totals()
        timestamp_s: Target timestamp in seconds since 7 AM
        
    Returns:
        Dictionary with total_orders, total_revenue, avg_per_order, revenue_per_hour
        Returns zeros if no sales have occurred by this timestamp
    """
    if not running_totals:
        return {
            "total_orders": 0,
            "total_revenue": 0.0,
            "avg_per_order": 0.0,
            "revenue_per_hour": 0.0
        }
    
    # Find the most recent timestamp at or before the target
    valid_timestamps = [ts for ts in running_totals.keys() if ts <= timestamp_s]
    
    if not valid_timestamps:
        return {
            "total_orders": 0,
            "total_revenue": 0.0,
            "avg_per_order": 0.0,
            "revenue_per_hour": 0.0
        }
    
    latest_timestamp = max(valid_timestamps)
    return running_totals[latest_timestamp].copy()


def enhance_coordinates_with_running_totals(
    coordinates: List[Dict[str, Any]], 
    sales_data: List[Dict[str, Any]],
    cart_id_filter: Optional[str] = None,
    service_start_s: int = 7200,
    service_end_s: int = 36000
) -> List[Dict[str, Any]]:
    """
    Enhance GPS coordinate records with running total columns for beverage cart.
    
    Args:
        coordinates: List of GPS coordinate records
        sales_data: List of sales records  
        cart_id_filter: Only enhance coordinates for this cart ID (e.g. "bev_cart_1")
        service_start_s: Service start time in seconds since 7 AM
        service_end_s: Service end time in seconds since 7 AM
        
    Returns:
        Enhanced coordinates list with additional columns:
        - total_orders: Running count of orders
        - total_revenue: Running total revenue in dollars
        - avg_per_order: Average revenue per order
        - revenue_per_hour: Revenue per hour of service
    """
    if not coordinates:
        return []
    
    # Calculate running totals from sales data
    running_totals = calculate_running_totals(sales_data, service_start_s, service_end_s)
    
    enhanced_coords = []
    cart_coords_enhanced = 0
    
    for coord in coordinates:
        enhanced_coord = coord.copy()
        
        # Check if this coordinate should be enhanced
        coord_id = coord.get("id", "")
        coord_type = coord.get("type", "")
        
        should_enhance = False
        if cart_id_filter:
            should_enhance = coord_id == cart_id_filter
        else:
            # Enhance if it's a beverage cart coordinate
            should_enhance = (coord_type in ["bev_cart", "bevcart"] or "bev_cart" in coord_id)
        
        if should_enhance:
            cart_coords_enhanced += 1
            timestamp_s = coord.get("timestamp", 0)
            totals = get_running_totals_at_timestamp(running_totals, timestamp_s)
            
            # Add running total columns
            enhanced_coord.update({
                "total_orders": totals["total_orders"],
                "total_revenue": totals["total_revenue"], 
                "avg_per_order": totals["avg_per_order"],
                "revenue_per_hour": totals["revenue_per_hour"]
            })
        else:
            # Add empty columns for non-cart entities to maintain CSV structure
            enhanced_coord.update({
                "total_orders": "",
                "total_revenue": "",
                "avg_per_order": "",
                "revenue_per_hour": ""
            })
        
        enhanced_coords.append(enhanced_coord)
    
    if cart_coords_enhanced > 0:
        logger.info("Enhanced %d beverage cart coordinates with running totals", cart_coords_enhanced)
    
    return enhanced_coords


def log_running_totals_summary(sales_data: List[Dict[str, Any]]) -> None:
    """
    Log a summary of running totals for debugging/monitoring.
    
    Args:
        sales_data: List of sales records
    """
    if not sales_data:
        logger.info("No sales data available for running totals summary")
        return
    
    running_totals = calculate_running_totals(sales_data)
    
    if not running_totals:
        logger.info("No running totals calculated")
        return
    
    # Get final totals
    final_timestamp = max(running_totals.keys())
    final_totals = running_totals[final_timestamp]
    
    logger.info(
        "Running totals summary - Orders: %d, Revenue: $%.2f, Avg/Order: $%.2f, $/Hour: $%.2f",
        final_totals["total_orders"],
        final_totals["total_revenue"], 
        final_totals["avg_per_order"],
        final_totals["revenue_per_hour"]
    )
