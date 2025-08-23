from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
import pandas as pd
import networkx as nx

from golfsim.simulation.tracks import interpolate_path_points
from golfsim.routing.networks import nearest_node


def generate_runner_coordinates_from_events(
    events_df: pd.DataFrame,
    golfer_coords_df: pd.DataFrame,
    clubhouse_coords: Tuple[float, float],
    cart_graph: nx.Graph,
) -> List[Dict[str, Any]]:
    """
    Generate runner GPS coordinates based on event timestamps and golfer locations.
    
    This function reads the events to find exact delivery start, complete, and return
    timestamps, then uses the golfer's location at delivery time as the target.
    It generates smooth GPS points along the cart path at 60-second intervals.
    
    Args:
        events_df: DataFrame with simulation events
        golfer_coords_df: DataFrame with golfer coordinates 
        clubhouse_coords: (longitude, latitude) of clubhouse
        cart_graph: NetworkX graph with cart paths
        
    Returns:
        List of runner coordinate dictionaries
    """
    runner_coords = []
    
    # Add initial clubhouse coordinates from service start until first delivery
    service_events = events_df[events_df['action'] == 'service_opened'].copy()
    delivery_events = events_df[
        events_df['action'].isin(['delivery_start', 'delivery_complete', 'arrived_clubhouse']) &
        events_df['order_id'].notna()
    ].copy()
    
    if not service_events.empty:
        service_start_ts = int(service_events.iloc[0]['timestamp_s'])
        runner_id = str(service_events.iloc[0].get('runner_id', 'runner_1'))
        
        # Find the first delivery start time
        first_delivery_ts = service_start_ts
        if not delivery_events.empty:
            first_delivery_start = delivery_events[delivery_events['action'] == 'delivery_start']
            if not first_delivery_start.empty:
                first_delivery_ts = int(first_delivery_start.iloc[0]['timestamp_s'])
        
        # Generate clubhouse coordinates from service start to first delivery
        clubhouse_lon, clubhouse_lat = clubhouse_coords
        for ts in range(service_start_ts, first_delivery_ts, 60):
            runner_coords.append({
                "id": runner_id,
                "latitude": clubhouse_lat,
                "longitude": clubhouse_lon,
                "timestamp": ts,
                "type": "runner",
                "hole": "clubhouse",
            })
    
    if delivery_events.empty:
        return runner_coords
    
    # Process each order
    for order_id in delivery_events['order_id'].unique():
        if pd.isna(order_id):
            continue
            
        order_events = delivery_events[delivery_events['order_id'] == order_id].copy()
        
        # Get the three key events for this order
        start_events = order_events[order_events['action'] == 'delivery_start']
        complete_events = order_events[order_events['action'] == 'delivery_complete'] 
        return_events = order_events[order_events['action'] == 'arrived_clubhouse']
        
        if start_events.empty or complete_events.empty or return_events.empty:
            continue
            
        start_event = start_events.iloc[0]
        complete_event = complete_events.iloc[0]
        return_event = return_events.iloc[0]
        
        start_ts = int(start_event['timestamp_s'])
        complete_ts = int(complete_event['timestamp_s'])
        return_ts = int(return_event['timestamp_s'])
        runner_id = str(start_event.get('runner_id', 'runner_1'))
        
        # Handle hole number with NaN protection
        hole_val = start_event.get('hole', 0)
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
        
        # Use the golfer's exact timestamp and coordinates as the delivery target
        delivery_timestamp = int(golfer_location['timestamp'])
        delivery_target = (float(golfer_location['longitude']), float(golfer_location['latitude']))
        
        # Log the timing for debugging
        time_diff = abs(delivery_timestamp - complete_ts)
        print(f"Order {order_id}: Original delivery at {complete_ts}, using golfer point at {delivery_timestamp} (diff: {time_diff}s)")
        
        # Generate delivery path coordinates
        try:
            # Find nearest nodes in cart graph
            clubhouse_node = nearest_node(cart_graph, clubhouse_coords[0], clubhouse_coords[1])
            delivery_node = nearest_node(cart_graph, delivery_target[0], delivery_target[1])
            
            if clubhouse_node is not None and delivery_node is not None:
                # Calculate delivery path - from departure to golfer's exact timestamp
                delivery_path_nodes = nx.shortest_path(cart_graph, clubhouse_node, delivery_node)
                delivery_path_coords = [
                    (float(cart_graph.nodes[n]['x']), float(cart_graph.nodes[n]['y'])) 
                    for n in delivery_path_nodes
                ]
                
                # Generate delivery coordinates using the golfer's exact timestamp as target
                delivery_coords = interpolate_path_points(
                    delivery_path_coords,
                    start_ts,
                    float(delivery_timestamp - start_ts),
                    runner_id,
                    hole_num
                )
                runner_coords.extend(delivery_coords)
                
                # Calculate return path - from golfer's timestamp to return timestamp
                return_path_nodes = nx.shortest_path(cart_graph, delivery_node, clubhouse_node)
                return_path_coords = [
                    (float(cart_graph.nodes[n]['x']), float(cart_graph.nodes[n]['y']))
                    for n in return_path_nodes
                ]
                
                # Generate return coordinates using exact return timestamp
                return_coords = interpolate_path_points(
                    return_path_coords,
                    delivery_timestamp,
                    float(return_ts - delivery_timestamp),
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
