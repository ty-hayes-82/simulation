"""
Pass detection utilities for beverage cart simulations.

This module provides functions for detecting when beverage carts pass golfer groups
and related time formatting utilities.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def format_time_from_baseline(seconds_since_7am: int) -> str:
    """
    Format seconds since 7 AM baseline into HH:MM time string.
    
    Args:
        seconds_since_7am: Seconds elapsed since 7:00 AM
        
    Returns:
        Time string in HH:MM format
    """
    total_seconds = max(0, int(seconds_since_7am))
    hours = 7 + (total_seconds // 3600)
    minutes = (total_seconds % 3600) // 60
    return f"{hours:02d}:{minutes:02d}"


def extract_pass_events_from_sales_data(sales_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Extract pass events from sales simulation data.
    
    Args:
        sales_data: Result from simulate_beverage_cart_sales
        
    Returns:
        List of pass event dictionaries with timestamp_s, hole_num, etc.
    """
    pass_events: List[Dict[str, Any]] = []
    
    # Extract from sales (actual orders placed)
    for sale in sales_data.get("sales", []):
        pass_events.append({
            "timestamp_s": sale.get("timestamp_s"),
            "hole_num": sale.get("hole_num"),
            "event_type": "sale",
            "group_id": sale.get("group_id"),
        })
    
    # Could also extract from activity log for non-sale passes
    for activity in sales_data.get("activity_log", []):
        if activity.get("event") == "pass_no_sale":
            pass_events.append({
                "timestamp_s": activity.get("timestamp_s"),
                "hole_num": activity.get("hole_num"),
                "event_type": "pass_no_sale",
                "group_id": activity.get("group_id"),
            })
    
    # Sort by timestamp
    pass_events.sort(key=lambda x: x.get("timestamp_s", 0))
    return pass_events


def compute_group_hole_at_time(
    group: Dict[str, Any],
    timestamp_s: int,
    minutes_per_hole: float = 12.0,
) -> int:
    """
    Compute which hole a golfer group is on at a given time.
    
    Args:
        group: Group dictionary with tee_time_s
        timestamp_s: Time to check
        minutes_per_hole: Minutes spent per hole
        
    Returns:
        Hole number (1-18), clamped to valid range
    """
    tee_time_s = group.get("tee_time_s", 0)
    elapsed_s = max(0, timestamp_s - tee_time_s)
    elapsed_holes = elapsed_s / (minutes_per_hole * 60.0)
    hole_num = int(elapsed_holes) + 1
    return max(1, min(18, hole_num))


def find_proximity_pass_events(
    tee_time_s: int,
    beverage_cart_points: List[Dict],
    golfer_points: List[Dict],
    proximity_threshold_m: float = 100.0,
    min_pass_interval_s: int = 1200,
    minutes_per_hole: float = 12.0,
) -> List[Dict[str, Any]]:
    """
    Find pass events based on GPS proximity between beverage cart and golfers.
    
    Args:
        tee_time_s: When golfer group started
        beverage_cart_points: List of beverage cart GPS coordinates
        golfer_points: List of golfer GPS coordinates  
        proximity_threshold_m: Distance threshold for considering a "pass"
        min_pass_interval_s: Minimum time between passes
        minutes_per_hole: Minutes per hole for hole estimation
        
    Returns:
        List of pass event dictionaries
    """
    from math import radians, sin, cos, atan2, sqrt
    
    def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        R = 6371000.0
        phi1, phi2 = radians(lat1), radians(lat2)
        dphi = radians(lat2 - lat1)
        dlambda = radians(lon2 - lon1)
        a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
        c = 2 * atan2(sqrt(a), sqrt(1 - a))
        return R * c
    
    pass_events: List[Dict[str, Any]] = []
    last_pass_time = 0
    
    # Create timestamp-indexed lookups
    bev_by_time = {p.get("timestamp", 0): p for p in beverage_cart_points}
    golfer_by_time = {p.get("timestamp", 0): p for p in golfer_points}
    
    # Find common timestamps
    common_times = sorted(set(bev_by_time.keys()) & set(golfer_by_time.keys()))
    
    for timestamp in common_times:
        if timestamp < tee_time_s:
            continue
            
        # Skip if too soon after last pass
        if timestamp - last_pass_time < min_pass_interval_s:
            continue
            
        bev_point = bev_by_time[timestamp]
        golfer_point = golfer_by_time[timestamp]
        
        # Calculate distance
        bev_lat = bev_point.get("latitude", 0.0)
        bev_lon = bev_point.get("longitude", 0.0)
        golfer_lat = golfer_point.get("latitude", 0.0)
        golfer_lon = golfer_point.get("longitude", 0.0)
        
        distance_m = haversine_m(bev_lat, bev_lon, golfer_lat, golfer_lon)
        
        if distance_m <= proximity_threshold_m:
            # Estimate hole number
            elapsed_s = timestamp - tee_time_s
            hole_num = max(1, min(18, int(elapsed_s / (minutes_per_hole * 60)) + 1))
            
            pass_events.append({
                "timestamp_s": timestamp,
                "hole_num": hole_num,
                "distance_m": distance_m,
                "event_type": "proximity_pass",
            })
            
            last_pass_time = timestamp
    
    return pass_events
