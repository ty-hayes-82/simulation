"""
Coordinate and Track Generation Module

This module provides functions for generating GPS coordinate streams and tracks
for golfers, runners, and carts in the golf course simulation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Tuple, Any

from golfsim.simulation.phase_simulations import generate_golfer_track


def ease_in_out_cubic(x: float) -> float:
    """Cubic easing function for smooth acceleration and deceleration."""
    if x < 0.5:
        return 4 * x * x * x
    return 1 - pow(-2 * x + 2, 3) / 2


def generate_golfer_points_for_groups(course_dir: str, groups: List[Dict]) -> List[Dict]:
    """Generate golfer GPS points for all groups.
    
    Args:
        course_dir: Path to course directory
        groups: List of group dictionaries with 'tee_time_s' and 'group_id'
        
    Returns:
        List of GPS points with group_id and hole number added to each point
    """
    all_points: List[Dict] = []
    
    try:
        total_nodes = len(load_holes_connected_points(course_dir))
    except (FileNotFoundError, SystemExit):
        total_nodes = 18 * 12  # Fallback if file is missing or invalid
    # Clamp to a maximum of 300 nodes for golfer tracks
    effective_total_nodes = min(int(total_nodes), 300)
    nodes_per_hole = max(1.0, float(effective_total_nodes) / 18.0)

    for g in groups:
        tee_time_s = int(g["tee_time_s"])
        pts = generate_golfer_track(course_dir, tee_time_s) or []
        for p in pts:
            p["group_id"] = g["group_id"]
            
            # Calculate current hole based on timestamp
            time_since_tee_off_s = int(p["timestamp"]) - tee_time_s
            node_idx = time_since_tee_off_s // 60  # Each node represents 1 minute
            
            # Assign hole number, ensuring it's within 1-18
            hole = 1 + int(node_idx // nodes_per_hole)
            p["hole"] = max(1, min(18, hole))

        all_points.extend(pts)
        
    return all_points


def load_holes_connected_points(course_dir: str) -> List[Tuple[float, float]]:
    """Load Point features from holes_connected.geojson or holes_connected_updated.geojson sorted by node_id.

    Args:
        course_dir: Path to course directory
        
    Returns:
        List of (lon, lat) coordinates
        
    Raises:
        FileNotFoundError: If neither holes_connected file is found
        SystemExit: If the file is invalid or contains no valid points
    """
    # Try updated file first, then fall back to original
    updated_path = Path(course_dir) / "geojson" / "generated" / "holes_connected_updated.geojson"
    original_path = Path(course_dir) / "geojson" / "generated" / "holes_connected.geojson"
    
    path = None
    if updated_path.exists():
        path = updated_path
    elif original_path.exists():
        path = original_path
    else:
        raise FileNotFoundError(f"Neither holes_connected.geojson nor holes_connected_updated.geojson found")
    
    try:
        with path.open("r", encoding="utf-8") as f:
            gj = json.load(f)
    except Exception as e:  # noqa: BLE001
        raise SystemExit(f"Failed reading {path.name}: {e}")

    pts: Dict[int, Tuple[float, float]] = {}
    for feat in (gj.get("features") or []):
        if feat.get("geometry", {}).get("type") != "Point":
            continue

        geom = (feat or {}).get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        props = (feat or {}).get("properties") or {}
        
        # Support both old format (idx) and new format (node_id)
        node_id = None
        if "node_id" in props:
            try:
                node_id = int(props["node_id"])
            except Exception:
                continue
        elif "idx" in props:
            try:
                node_id = int(props["idx"])
            except Exception:
                continue
        else:
            continue
            
        coords = geom.get("coordinates") or []
        if not coords or len(coords) < 2:
            continue
        lon = float(coords[0])
        lat = float(coords[1])
        pts[node_id] = (lon, lat)

    if not pts:
        raise SystemExit(f"{path.name} contains no Point features with integer 'node_id' or 'idx'")

    ordered = [pts[i] for i in sorted(pts.keys())]
    return ordered


def generate_runner_to_golfer_rendezvous_points(
    runner_path_to_golfer: List[Tuple[float, float]],
    golfer_track: List[Dict[str, Any]],
    meet_time_s: int,
    runner_id: str,
    hole_num: int,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Generate runner coordinates to meet a golfer at a specific node and time.

    - Runner travels towards the golfer, who is moving one node per minute.
    - They meet exactly at `meet_time_s` at a shared node.
    - Runner's return trip begins from the meeting node.
    """
    # Find the golfer's position at the exact meeting time
    meet_point_geo = None
    for p in golfer_track:
        if int(p["timestamp"]) == meet_time_s:
            meet_point_geo = (p["longitude"], p["latitude"])
            break

    if meet_point_geo is None:
        # If no exact match, fallback to the closest point in time (optional)
        # For now, we assume an exact match is required.
        return [], -1

    # Find the node in the runner's path that is closest to the meeting point
    closest_node_idx = -1
    min_dist = float("inf")
    for i, node_geo in enumerate(runner_path_to_golfer):
        dist = (
            (node_geo[0] - meet_point_geo[0]) ** 2
            + (node_geo[1] - meet_point_geo[1]) ** 2
        )
        if dist < min_dist:
            min_dist = dist
            closest_node_idx = i

    if closest_node_idx == -1:
        return [], -1

    # Runner's path is truncated to the meeting node
    runner_path_to_meeting_node = runner_path_to_golfer[: closest_node_idx + 1]
    
    # Calculate runner's travel time to the meeting node (1 minute per node)
    runner_travel_time_s = len(runner_path_to_meeting_node) * 60
    
    # Determine when the runner should start to meet the golfer at meet_time_s
    runner_start_ts = meet_time_s - runner_travel_time_s

    # Generate coordinate points for the runner's outbound trip
    runner_coords = []
    for i, node_geo in enumerate(runner_path_to_meeting_node):
        timestamp = runner_start_ts + i * 60
        runner_coords.append({
            "id": runner_id,
            "latitude": node_geo[1],
            "longitude": node_geo[0],
            "timestamp": int(timestamp),
            "type": "delivery_runner",
            "hole": hole_num,
        })

    return runner_coords, closest_node_idx