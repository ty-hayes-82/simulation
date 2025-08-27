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
    nodes_per_hole = max(1.0, float(total_nodes) / 18.0)

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


def interpolate_path_points(
    path_pts: List[Tuple[float, float]],
    start_ts: int,
    duration_s: float,
    runner_id: str,
    hole_num: int,
) -> List[Dict[str, Any]]:
    """Interpolate along a path at fixed 60-second timestamps.

    - Matches the golfer animation cadence (one point every 60 seconds)
    - Produces points from the first minute boundary at/after start_ts
      through the last minute boundary at/before (start_ts + duration_s)
    """
    sampled: List[Dict[str, Any]] = []
    if not path_pts or duration_s <= 0:
        return sampled

    total_time_s = float(duration_s)
    segments = max(1, len(path_pts) - 1)

    first_tick = int(((int(start_ts) + 59) // 60) * 60)
    last_tick = int(((int(start_ts) + int(total_time_s)) // 60) * 60)
    if last_tick < first_tick:
        return sampled

    timestamps = list(range(first_tick, last_tick + 1, 60))
    if int(start_ts + duration_s) not in timestamps:
        timestamps.append(int(start_ts + duration_s))
    
    for t in sorted(timestamps):
        progress = (float(t) - float(start_ts)) / total_time_s
        if progress < 0.0:
            progress = 0.0
        elif progress > 1.0:
            progress = 1.0

        eased_progress = ease_in_out_cubic(progress)

        pos = eased_progress * float(segments)
        seg_idx = int(pos) if pos < segments else segments - 1
        local_frac = pos - float(seg_idx)

        x0, y0 = path_pts[seg_idx]
        x1, y1 = path_pts[min(seg_idx + 1, len(path_pts) - 1)]
        lon = x0 + local_frac * (x1 - x0)
        lat = y0 + local_frac * (y1 - y0)

        sampled.append({
            "id": runner_id,
            "latitude": lat,
            "longitude": lon,
            "timestamp": int(t),
            "type": "delivery_runner",
            "hole": hole_num,
        })

    return sampled