"""
Beverage cart pass detection and sales simulation.

This module provides functions for simulating beverage cart sales based on
pass events when the cart encounters golfer groups on the course.
"""

from __future__ import annotations

import random
from typing import Any, Dict, List, Optional


def simulate_beverage_cart_sales(
    course_dir: str,
    groups: List[Dict[str, Any]],
    pass_order_probability: float,
    price_per_order: float,
    minutes_between_holes: float = 2.0,
    minutes_per_hole: Optional[float] = None,
    golfer_points: Optional[List[Dict]] = None,
    crossings_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:

    """
    Simulate beverage cart sales based on actual crossing events.
    
    Args:
        course_dir: Path to course configuration
        groups: List of golfer groups with group_id, tee_time_s, num_golfers
        pass_order_probability: Probability of order on each crossing
        price_per_order: Price per order in dollars
        minutes_between_holes: Time between holes
        minutes_per_hole: Time per hole (optional)
        golfer_points: GPS points for golfers (optional)
        crossings_data: Crossings computation result from crossings service
        
    Returns:
        Dictionary with sales, revenue, pass_intervals_per_group, activity_log, metadata
    """
    sales: List[Dict[str, Any]] = []
    pass_intervals_per_group: Dict[str, List] = {}
    activity_log: List[Dict[str, Any]] = []
    
    total_revenue = 0.0
    
    # If we have crossings data, use it to determine sales opportunities
    if crossings_data and crossings_data.get("groups"):
        for crossing_group in crossings_data["groups"]:
            group_id = str(crossing_group["group"])
            crossings = crossing_group.get("crossings", [])
            
            # Initialize pass intervals for this group
            pass_intervals_per_group[group_id] = []
            
            last_crossing_time = None
            for crossing in crossings:
                timestamp = crossing.get("timestamp")
                if timestamp:
                    # Convert timestamp to seconds since 7 AM baseline
                    if hasattr(timestamp, 'hour'):
                        crossing_timestamp_s = ((timestamp.hour - 7) * 3600 + 
                                              timestamp.minute * 60 + 
                                              timestamp.second)
                    else:
                        crossing_timestamp_s = crossing.get("t_cross_s", 0)
                    
                    # Record pass interval
                    if last_crossing_time is not None:
                        interval = crossing_timestamp_s - last_crossing_time
                        pass_intervals_per_group[group_id].append(int(interval))
                    last_crossing_time = crossing_timestamp_s
                    
                    # Probabilistic order placement at each crossing
                    if random.random() < pass_order_probability:
                        hole_num = crossing.get("hole") or 1
                        sale = {
                            "group_id": int(group_id),
                            "hole_num": hole_num,
                            "timestamp_s": int(crossing_timestamp_s),
                            "price": price_per_order,
                        }
                        sales.append(sale)
                        total_revenue += price_per_order
                        
                        activity_log.append({
                            "timestamp_s": int(crossing_timestamp_s),
                            "event": "sale",
                            "group_id": int(group_id),
                            "hole_num": hole_num,
                            "revenue": price_per_order,
                        })
    else:
        # Fallback: simulate without crossings data (legacy behavior)
        for group in groups:
            group_id = str(group["group_id"])
            tee_time_s = group["tee_time_s"]
            
            # Initialize pass intervals for this group
            pass_intervals_per_group[group_id] = []
            
            # Simulate 2-3 potential pass events during the round
            num_passes = random.randint(2, 3)
            
            last_pass_offset = 0
            round_duration_s = 216 * 60  # 216 minutes total
            
            for pass_idx in range(num_passes):
                # Random hole between 1-18
                hole_num = random.randint(1, 18)
                
                # Calculate pass time ensuring we don't exceed round duration
                min_time = last_pass_offset + (1800 if pass_idx > 0 else 0)  # At least 30 min apart after first
                max_time = round_duration_s
                
                if min_time >= max_time:
                    # Not enough time left for another pass
                    break
                    
                pass_time_offset = random.randint(min_time, max_time)
                pass_timestamp_s = tee_time_s + pass_time_offset
                
                # Record pass interval (time since last pass)
                if pass_idx > 0:
                    interval = pass_time_offset - last_pass_offset
                    pass_intervals_per_group[group_id].append(interval)
                last_pass_offset = pass_time_offset
                
                # Probabilistic order placement
                if random.random() < pass_order_probability:
                    sale = {
                        "group_id": group["group_id"],
                        "hole_num": hole_num,
                        "timestamp_s": pass_timestamp_s,
                        "price": price_per_order,
                    }
                    sales.append(sale)
                    total_revenue += price_per_order
                    
                    activity_log.append({
                        "timestamp_s": pass_timestamp_s,
                        "event": "sale",
                        "group_id": group["group_id"],
                        "hole_num": hole_num,
                        "revenue": price_per_order,
                    })
    
    # Sort sales by timestamp
    sales.sort(key=lambda x: x["timestamp_s"])
    activity_log.sort(key=lambda x: x["timestamp_s"])
    
    return {
        "success": True,
        "sales": sales,
        "revenue": total_revenue,
        "pass_intervals_per_group": pass_intervals_per_group,
        "activity_log": activity_log,
        "metadata": {
            "pass_order_probability": pass_order_probability,
            "price_per_order": price_per_order,
            "service_start_s": 7200,  # 9 AM
            "service_end_s": 36000,   # 17 PM (10 hours after 7 AM)
            "groups": groups,
        },
    }
