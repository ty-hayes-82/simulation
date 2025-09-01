from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple, Optional
import math
import pandas as pd
import networkx as nx

from golfsim.routing.networks import nearest_node


def generate_runner_coordinates_from_events(
    events_df: pd.DataFrame,
    golfer_coords_df: pd.DataFrame,
    clubhouse_coords: Tuple[float, float],
    cart_graph: nx.Graph,
    runner_speed_mps: float,
    num_runners: int,
    delivery_stats_df: Optional[pd.DataFrame] = None,
    order_timing_df: Optional[pd.DataFrame] = None,
) -> List[Dict[str, Any]]:
    """
    Generate runner GPS coordinates based on event timestamps and golfer locations.
    
    This function reads the events to find exact delivery complete timestamps and
    delivery locations, snaps those locations to the cart graph, then back-calculates
    the delivery departure time using a constant runner speed and the routed path
    distance (no map shortcuts). It generates smooth GPS points along the cart
    path at 60-second intervals, and places the delivery point exactly on the
    snapped graph node at the delivery timestamp.

    When delivery_stats_df and order_timing_df are provided, prefers the exact
    routed node-index paths captured during simulation (trip_to_golfer.nodes and
    trip_back.nodes). In that mode, coordinates are generated at per-node times
    based on segment length and runner speed, resulting in sub-minute intervals
    that exactly follow the node path. Hole numbers are not used to determine the
    path in this mode; timing is anchored by departure and delivery/return
    timestamps.
    
    Args:
        events_df: DataFrame with simulation events
        golfer_coords_df: DataFrame with golfer coordinates 
        clubhouse_coords: (longitude, latitude) of clubhouse
        cart_graph: NetworkX graph with cart paths
        
    Returns:
        List of runner coordinate dictionaries
    """
    runner_coords = []

    # Helper: normalize node IDs to match the cart_graph's node key type
    def _coerce_node_id(value: Any, target_type: type) -> Any:
        try:
            if target_type is int:
                if isinstance(value, str):
                    s = value.strip()
                    if s.lstrip("-").isdigit():
                        return int(s)
                    return value
                return int(value)
            if target_type is str:
                return str(value)
        except Exception:
            pass
        return value

    def _normalize_nodes(nodes: List[Any], graph: nx.Graph) -> List[Any]:
        if not nodes:
            return []
        # Determine desired key type from existing graph nodes (default to int)
        try:
            sample_key = next(iter(graph.nodes))
            target_type = type(sample_key)
        except Exception:
            target_type = int

        normalized: List[Any] = []
        for n in nodes:
            # First, attempt to convert string numbers to int
            if isinstance(n, str):
                s = n.strip()
                if s.lstrip("-").isdigit():
                    n = int(s)
            
            nn = _coerce_node_id(n, target_type)
            # If still not present, try the opposite common coercion
            if nn not in graph.nodes:
                try:
                    if isinstance(nn, int):
                        alt = str(nn)
                        if alt in graph.nodes:
                            nn = alt
                    elif isinstance(nn, str):
                        s = nn.strip()
                        if s.lstrip("-").isdigit():
                            alt_i = int(s)
                            if alt_i in graph.nodes:
                                nn = alt_i
                except Exception:
                    pass
            normalized.append(nn)
        return normalized
    
    # Add a point for each runner at the clubhouse when service opens
    service_open_events = events_df[events_df["action"] == "service_opened"]
    if not service_open_events.empty:
        service_open_ts = int(service_open_events.iloc[0]["timestamp_s"])
        clubhouse_lon, clubhouse_lat = clubhouse_coords
        for i in range(1, num_runners + 1):
            runner_id = f"runner_{i}"
            runner_coords.append(
                {
                    "id": runner_id,
                    "latitude": clubhouse_lat,
                    "longitude": clubhouse_lon,
                    "timestamp": service_open_ts,
                    "type": "runner",
                    "hole": "clubhouse",
                }
            )

    # Focus only on movement-related events for path generation
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

    def _nodes_to_points(
        nodes: List[Any],
        start_ts: int,
        end_ts: Optional[int],
        runner_id: str,
        hole_hint: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Convert a list of graph node IDs into timestamped coordinates.

        - Uses cart_graph node positions ('x','y')
        - Computes per-edge times from segment lengths and runner_speed_mps
        - Scales to match end_ts if provided
        - Emits a point at every node (sub-minute resolution as needed)
        """
        if not nodes or len(nodes) < 1:
            return []

        # Build coordinate list for nodes
        # Normalize node IDs to match graph keys before lookup
        nodes = _normalize_nodes(list(nodes), cart_graph)
        try:
            coords: List[Tuple[float, float]] = [
                (float(cart_graph.nodes[n]['x']), float(cart_graph.nodes[n]['y'])) for n in nodes
            ]
        except Exception:
            return []

        # Compute per-segment distances
        seg_lengths: List[float] = []
        for i in range(len(coords) - 1):
            x0, y0 = coords[i]
            x1, y1 = coords[i + 1]
            dx_m = (float(x1) - float(x0)) * 111139.0
            dy_m = (float(y1) - float(y0)) * 111139.0
            seg_lengths.append(math.hypot(dx_m, dy_m))

        total_len = sum(seg_lengths)
        if total_len <= 0.0:
            # Emit single point at start
            x0, y0 = coords[0]
            return [{
                "id": runner_id,
                "latitude": y0,
                "longitude": x0,
                "timestamp": int(start_ts),
                "type": "runner",
                "hole": hole_hint if hole_hint is not None else 0,
            }]

        # Compute raw per-segment times from speed
        raw_times = [max(0.001, L / max(0.001, float(runner_speed_mps))) for L in seg_lengths]
        total_time = sum(raw_times)

        # If an explicit end_ts is provided, scale times to fit exactly
        if end_ts is not None and end_ts > start_ts and total_time > 0:
            scale = float(end_ts - start_ts) / float(total_time)
        else:
            scale = 1.0
        seg_times = [t * scale for t in raw_times]

        # Emit a coordinate at each node boundary
        points: List[Dict[str, Any]] = []
        t_cursor = float(start_ts)
        for i, (x, y) in enumerate(coords):
            ts_i = int(round(t_cursor)) if i == 0 else int(round(t_cursor))
            points.append({
                "id": runner_id,
                "latitude": y,
                "longitude": x,
                "timestamp": ts_i,
                "type": "runner",
                "hole": hole_hint if hole_hint is not None else 0,
            })
            if i < len(seg_times):
                t_cursor += float(seg_times[i])

        # Ensure the last timestamp aligns exactly to end_ts if provided
        if end_ts is not None and points:
            points[-1]["timestamp"] = int(end_ts)
        return points

    # If detailed delivery stats are provided, use their node-index paths for precise timing
    if delivery_stats_df is not None and isinstance(delivery_stats_df, pd.DataFrame) and not delivery_stats_df.empty:
        stats_by_order = delivery_stats_df.set_index(delivery_stats_df['order_id'].astype(str) if 'order_id' in delivery_stats_df.columns else pd.Series(dtype=str), drop=False)
        timing_by_order = None
        if order_timing_df is not None and isinstance(order_timing_df, pd.DataFrame) and not order_timing_df.empty:
            timing_by_order = order_timing_df.set_index(order_timing_df['order_id'].astype(str) if 'order_id' in order_timing_df.columns else pd.Series(dtype=str), drop=False)

        for oid in list(stats_by_order.index.unique()):
            try:
                row = stats_by_order.loc[oid]
            except Exception:
                continue

            # Handle multi-row selection
            if isinstance(row, pd.DataFrame) and not row.empty:
                row = row.iloc[0]

            order_id = str(row.get('order_id', oid))
            runner_id = str(row.get('runner_id', 'runner_1'))
            hole_hint = None
            try:
                hole_hint = int(row.get('hole_num')) if row.get('hole_num') is not None else None
            except Exception:
                hole_hint = None

            # Determine timing anchors
            delivered_ts = None
            if 'delivered_at_time_s' in row and pd.notna(row['delivered_at_time_s']):
                delivered_ts = int(row['delivered_at_time_s'])
            elif timing_by_order is not None and order_id in timing_by_order.index:
                try:
                    delivered_ts = int(timing_by_order.loc[order_id].get('delivery_timestamp_s'))
                except Exception:
                    delivered_ts = None

            # Departure time
            depart_ts = None
            if timing_by_order is not None and order_id in timing_by_order.index:
                try:
                    depart_ts = int(timing_by_order.loc[order_id].get('departure_time_s'))
                except Exception:
                    depart_ts = None
            if depart_ts is None and delivered_ts is not None:
                # Fallback: back-calc using delivery_time_s if available
                try:
                    depart_ts = int(delivered_ts - float(row.get('delivery_time_s', 0)))
                except Exception:
                    depart_ts = None

            # Return end time (optional)
            return_end_ts = None
            if timing_by_order is not None and order_id in timing_by_order.index:
                try:
                    return_end_ts = int(timing_by_order.loc[order_id].get('return_timestamp_s'))
                except Exception:
                    return_end_ts = None

            # Extract node paths if present
            to_nodes = []
            back_nodes = []
            try:
                t2g = row.get('trip_to_golfer')
                if isinstance(t2g, dict) and 'nodes' in t2g:
                    to_nodes = list(t2g.get('nodes') or [])
            except Exception:
                to_nodes = []
            try:
                tb = row.get('trip_back')
                if isinstance(tb, dict) and 'nodes' in tb:
                    back_nodes = list(tb.get('nodes') or [])
            except Exception:
                back_nodes = []

            # Normalize extracted node IDs for both paths
            to_nodes = _normalize_nodes(to_nodes, cart_graph)
            back_nodes = _normalize_nodes(back_nodes, cart_graph)

            # Outbound path via captured nodes
            if to_nodes and depart_ts is not None and delivered_ts is not None and delivered_ts > depart_ts:
                outbound_points = _nodes_to_points(to_nodes, int(depart_ts), int(delivered_ts), runner_id, hole_hint)
                runner_coords.extend(outbound_points)
            else:
                # Fallback: reconstruct from nearest nodes based on golfer position at delivery
                # Find delivery target from golfer coords near delivered_ts
                if delivered_ts is None:
                    # Obtain from event
                    order_events = delivery_events[delivery_events['order_id'].astype(str) == str(order_id)]
                    complete_events = order_events[order_events['action'] == 'delivery_complete']
                    if not complete_events.empty:
                        delivered_ts = int(complete_events.iloc[0]['timestamp_s'])
                if delivered_ts is None:
                    continue
                time_diffs = abs(golfer_coords_df['timestamp'] - delivered_ts)
                closest_idx = time_diffs.idxmin()
                golfer_location = golfer_coords_df.loc[closest_idx]
                delivery_target = (float(golfer_location['longitude']), float(golfer_location['latitude']))
                try:
                    clubhouse_node = nearest_node(cart_graph, clubhouse_coords[0], clubhouse_coords[1])
                    delivery_node = nearest_node(cart_graph, delivery_target[0], delivery_target[1])
                    if clubhouse_node is not None and delivery_node is not None:
                        delivery_path_nodes = nx.shortest_path(cart_graph, clubhouse_node, delivery_node)
                        if depart_ts is None:
                            # Estimate depart_time from speed and path length
                            coords = [(float(cart_graph.nodes[n]['x']), float(cart_graph.nodes[n]['y'])) for n in delivery_path_nodes]
                            travel_out_s = _path_length_m(coords) / max(0.001, float(runner_speed_mps))
                            # Align to minute boundary not required; use exact
                            depart_ts = int(delivered_ts - travel_out_s)
                        outbound_points = _nodes_to_points(delivery_path_nodes, int(depart_ts), int(delivered_ts), runner_id, hole_hint)
                        runner_coords.extend(outbound_points)
                except Exception:
                    pass

            # Return path via captured nodes if available
            if back_nodes and delivered_ts is not None:
                # If no explicit end, compute by speed
                if return_end_ts is None:
                    try:
                        coords = [(float(cart_graph.nodes[n]['x']), float(cart_graph.nodes[n]['y'])) for n in back_nodes]
                        travel_back_s = _path_length_m(coords) / max(0.001, float(runner_speed_mps))
                        return_end_ts = int(delivered_ts + travel_back_s)
                    except Exception:
                        return_end_ts = None
                
                # Ensure the return trip starts exactly at the delivery timestamp
                return_start_ts = int(delivered_ts)
                
                return_points = _nodes_to_points(back_nodes, return_start_ts, int(return_end_ts) if return_end_ts else None, runner_id, hole_hint)
                runner_coords.extend(return_points)
        # After building from stats, continue to clubhouse fill below
    else:
        # Legacy fallback: derive paths from golfer locations and shortest paths, sampled at 60s
        for order_id in delivery_events['order_id'].unique():
            if pd.isna(order_id):
                continue
            order_events = delivery_events[delivery_events['order_id'] == order_id].copy()
            complete_events = order_events[order_events['action'] == 'delivery_complete']
            return_events = order_events[order_events['action'] == 'arrived_clubhouse']
            if complete_events.empty:
                continue
            complete_event = complete_events.iloc[0]
            # return_event is not strictly needed in legacy mode
            # return_event = return_events.iloc[0] if not return_events.empty else None
            complete_ts = int(complete_event['timestamp_s'])
            runner_id = str(complete_event.get('runner_id', 'runner_1'))
            # Find the closest golfer GPS point to the delivery complete timestamp
            time_diffs = abs(golfer_coords_df['timestamp'] - complete_ts)
            closest_idx = time_diffs.idxmin()
            golfer_location = golfer_coords_df.loc[closest_idx]
            delivery_target = (float(golfer_location['longitude']), float(golfer_location['latitude']))
            # Generate delivery path coordinates via shortest path
            try:
                clubhouse_node = nearest_node(cart_graph, clubhouse_coords[0], clubhouse_coords[1])
                delivery_node = nearest_node(cart_graph, delivery_target[0], delivery_target[1])
                if clubhouse_node is not None and delivery_node is not None:
                    delivery_path_nodes = nx.shortest_path(cart_graph, clubhouse_node, delivery_node)
                    delivery_path_coords = [
                        (float(cart_graph.nodes[n]['x']), float(cart_graph.nodes[n]['y']))
                        for n in delivery_path_nodes
                    ]
                    path_len_m = _path_length_m(delivery_path_coords)
                    travel_out_s = float(path_len_m) / float(max(runner_speed_mps, 0.001))
                    dispatch_ts = int(complete_ts - travel_out_s)
                    # No minute rounding; use exact timing
                    start_ts = int(dispatch_ts)

                    # Use _nodes_to_points for coordinate generation
                    delivery_coords = _nodes_to_points(delivery_path_nodes, start_ts, complete_ts, runner_id, 0)
                    runner_coords.extend(delivery_coords)

                    # Return path
                    return_path_nodes = nx.shortest_path(cart_graph, delivery_node, clubhouse_node)
                    return_len_m = _path_length_m([
                        (float(cart_graph.nodes[n]['x']), float(cart_graph.nodes[n]['y']))
                        for n in return_path_nodes
                    ])
                    travel_back_s = float(return_len_m) / float(max(runner_speed_mps, 0.001))
                    
                    # Use _nodes_to_points for return path
                    return_coords = _nodes_to_points(return_path_nodes, complete_ts, int(complete_ts + travel_back_s), runner_id, 0)
                    runner_coords.extend(return_coords)
            except Exception:
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
