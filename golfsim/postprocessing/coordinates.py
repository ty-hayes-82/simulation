from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
import math
import pandas as pd
import networkx as nx

from golfsim.simulation.tracks import interpolate_path_points
from golfsim.routing.networks import nearest_node


def generate_runner_coordinates_from_events(
    events_df: pd.DataFrame,
    golfer_coords_df: pd.DataFrame,
    clubhouse_coords: Tuple[float, float],
    cart_graph: nx.Graph,
    runner_speed_mps: float,
) -> List[Dict[str, Any]]:
    """
    Generate runner GPS coordinates based on event timestamps and golfer locations.
    
    This function reads the events to find exact delivery complete timestamps and
    delivery locations, snaps those locations to the cart graph, then back-calculates
    the delivery departure time using a constant runner speed and the routed path
    distance (no map shortcuts). It generates smooth GPS points along the cart
    path at 60-second intervals, and places the delivery point exactly on the
    snapped graph node at the delivery timestamp.
    
    Args:
        events_df: DataFrame with simulation events
        golfer_coords_df: DataFrame with golfer coordinates 
        clubhouse_coords: (longitude, latitude) of clubhouse
        cart_graph: NetworkX graph with cart paths
        
    Returns:
        List of runner coordinate dictionaries
    """
    runner_coords = []
    
    # Focus only on movement-related events; avoid pre-departure clubhouse idling points
    delivery_events = events_df[
        events_df['action'].isin(['delivery_start', 'delivery_complete', 'arrived_clubhouse']) &
        events_df['order_id'].notna()
    ].copy()
    
    if delivery_events.empty:
        return runner_coords
    
    # Helper to compute polyline length in meters based on lon/lat tuples
    def _path_length_m(coords: List[Tuple[float, float]]) -> float:
        if not coords or len(coords) < 2:
            return 0.0
        total = 0.0
        # Use simple meters-per-degree conversion; consistent with rest of codebase
        for i in range(len(coords) - 1):
            x0, y0 = coords[i]
            x1, y1 = coords[i + 1]
            dx_m = (float(x1) - float(x0)) * 111139.0
            dy_m = (float(y1) - float(y0)) * 111139.0
            total += math.hypot(dx_m, dy_m)
        return total

    # Process each order
    for order_id in delivery_events['order_id'].unique():
        if pd.isna(order_id):
            continue
            
        order_events = delivery_events[delivery_events['order_id'] == order_id].copy()
        
        # Get the three key events for this order
        complete_events = order_events[order_events['action'] == 'delivery_complete'] 
        # Return event may be missing or delayed; we'll compute return timing via speed
        return_events = order_events[order_events['action'] == 'arrived_clubhouse']
        
        if complete_events.empty:
            continue
            
        complete_event = complete_events.iloc[0]
        # If we have a return event, we'll use it for anchoring the end of return; otherwise we compute it
        return_event = return_events.iloc[0] if not return_events.empty else None
        
        complete_ts = int(complete_event['timestamp_s'])
        runner_id = str(complete_event.get('runner_id', 'runner_1'))
        
        # Handle hole number with NaN protection
        hole_val = complete_event.get('hole', 0)
        if pd.isna(hole_val) or hole_val is None:
            hole_num = 0
        else:
            try:
                hole_num = int(hole_val)
            except (ValueError, TypeError):
                hole_num = 0
        
        # Find the closest golfer GPS point to the delivery complete timestamp
        time_diffs = abs(golfer_coords_df['timestamp'] - complete_ts)
        closest_idx = time_diffs.idxmin()
        golfer_location = golfer_coords_df.loc[closest_idx]
        
        # Use the golfer's coordinates as the delivery target (snap to graph node)
        delivery_target = (float(golfer_location['longitude']), float(golfer_location['latitude']))
        
        # Log the timing for debugging
        golfer_timestamp = int(golfer_location['timestamp'])
        time_diff = abs(golfer_timestamp - complete_ts)
        print(f"Order {order_id}: Delivery at {complete_ts}, using golfer location from {golfer_timestamp} (diff: {time_diff}s)")
        
        # Generate delivery path coordinates
        try:
            # Find nearest nodes in cart graph
            clubhouse_node = nearest_node(cart_graph, clubhouse_coords[0], clubhouse_coords[1])
            delivery_node = nearest_node(cart_graph, delivery_target[0], delivery_target[1])
            
            if clubhouse_node is not None and delivery_node is not None:
                # Calculate delivery path - from departure to actual delivery complete time
                delivery_path_nodes = nx.shortest_path(cart_graph, clubhouse_node, delivery_node)
                delivery_path_coords = [
                    (float(cart_graph.nodes[n]['x']), float(cart_graph.nodes[n]['y'])) 
                    for n in delivery_path_nodes
                ]
                
                # Back-calculate departure time using constant speed and path length
                path_len_m = _path_length_m(delivery_path_coords)
                travel_out_s = float(path_len_m) / float(max(runner_speed_mps, 0.001))
                start_ts = int(complete_ts - travel_out_s)

                # Generate delivery coordinates using derived timing (constant speed)
                delivery_coords = interpolate_path_points(
                    delivery_path_coords,
                    start_ts,
                    float(travel_out_s),
                    runner_id,
                    hole_num
                )
                runner_coords.extend(delivery_coords)

                # Add a point at the exact delivery time using the snapped delivery node coordinate
                delivery_lon = float(cart_graph.nodes[delivery_node]['x'])
                delivery_lat = float(cart_graph.nodes[delivery_node]['y'])
                runner_coords.append({
                    "id": runner_id,
                    "latitude": delivery_lat,
                    "longitude": delivery_lon,
                    "timestamp": complete_ts,
                    "type": "runner",
                    "hole": hole_num,
                })
                
                # Calculate return path - from delivery complete to return timestamp
                return_path_nodes = nx.shortest_path(cart_graph, delivery_node, clubhouse_node)
                return_path_coords = [
                    (float(cart_graph.nodes[n]['x']), float(cart_graph.nodes[n]['y']))
                    for n in return_path_nodes
                ]
                
                # Generate return coordinates using constant speed
                return_len_m = _path_length_m(return_path_coords)
                travel_back_s = float(return_len_m) / float(max(runner_speed_mps, 0.001))
                return_coords = interpolate_path_points(
                    return_path_coords,
                    complete_ts,
                    float(travel_back_s),
                    runner_id,
                    hole_num
                )
                runner_coords.extend(return_coords)
                
        except Exception as e:
            print(f"Warning: Failed to generate coordinates for order {order_id}: {e}")
            continue
    
    # Add clubhouse coordinates for waiting periods between orders and after final order
    if delivery_events.empty:
        return runner_coords
    
    # Sort runner coordinates by timestamp to identify gaps
    runner_coords.sort(key=lambda x: x['timestamp'])
    
    # Find gaps between deliveries and fill with clubhouse coordinates
    clubhouse_lon, clubhouse_lat = clubhouse_coords
    filled_coords = []

    # 1) Pre-fill from service opening to first runner point at the clubhouse
    if runner_coords:
        first_ts = int(runner_coords[0]['timestamp'])
        # Prefer explicit service_opened event; otherwise fall back to first runner ts
        service_open_events = events_df[events_df['action'] == 'service_opened']
        if not service_open_events.empty:
            service_open_ts = int(service_open_events.iloc[0]['timestamp_s'])
        else:
            # If unavailable, do not back-fill before the first runner point
            service_open_ts = first_ts

        if service_open_ts < first_ts:
            runner_id_for_prefill = str(runner_coords[0].get('id', 'runner_1'))
            for ts in range(service_open_ts, first_ts, 60):
                filled_coords.append({
                    "id": runner_id_for_prefill,
                    "latitude": clubhouse_lat,
                    "longitude": clubhouse_lon,
                    "timestamp": int(ts),
                    "type": "runner",
                    "hole": "clubhouse",
                })
    
    for i, coord in enumerate(runner_coords):
        filled_coords.append(coord)
        
        # Check if there's a gap to the next coordinate
        if i < len(runner_coords) - 1:
            current_ts = coord['timestamp']
            next_ts = runner_coords[i + 1]['timestamp']
            
            # If there's a gap of more than 60 seconds, fill with clubhouse coordinates
            if next_ts - current_ts > 60:
                for ts in range(current_ts + 60, next_ts, 60):
                    filled_coords.append({
                        "id": coord['id'],
                        "latitude": clubhouse_lat,
                        "longitude": clubhouse_lon,
                        "timestamp": ts,
                        "type": "runner",
                        "hole": "clubhouse",
                    })
    
    # Add final clubhouse coordinates after the last delivery until end of service
    if filled_coords:
        last_coord = filled_coords[-1]
        last_ts = last_coord['timestamp']
        runner_id = last_coord['id']
        
        # Find service end time or add a reasonable buffer
        service_end_events = events_df[events_df['action'] == 'service_closed']
        if not service_end_events.empty:
            service_end_ts = int(service_end_events.iloc[0]['timestamp_s'])
        else:
            # Add 1 hour buffer after last delivery
            service_end_ts = last_ts + 3600
        
        # Fill remaining time with clubhouse coordinates
        for ts in range(last_ts + 60, service_end_ts, 60):
            filled_coords.append({
                "id": runner_id,
                "latitude": clubhouse_lat,
                "longitude": clubhouse_lon,
                "timestamp": ts,
                "type": "runner",
                "hole": "clubhouse",
            })
    
    return filled_coords
