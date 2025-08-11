
from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_left
from math import radians, sin, cos, atan2, sqrt
from typing import List, Tuple, Optional, Dict, Any
import json
from datetime import datetime, date, time, timedelta
import random
import csv
import argparse

# -------------------------
# Geometry helpers
# -------------------------
def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two lat/lon points in meters."""
    R = 6371000.0
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi/2)**2 + cos(phi1)*cos(phi2)*sin(dlambda/2)**2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c

def cumulative_distances(nodes: List[Tuple[float, float]]) -> List[float]:
    """Cumulative along-path distances (meters) for each node (0 at first node)."""
    if len(nodes) < 2:
        raise ValueError("Need at least 2 nodes to form a path.")
    cum = [0.0]
    for i in range(1, len(nodes)):
        d = haversine_m(nodes[i-1][0], nodes[i-1][1], nodes[i][0], nodes[i][1])
        cum.append(cum[-1] + d)
    return cum

def pos_to_node_index(cum: List[float], s: float) -> int:
    """Nearest node index to a continuous position s (meters along the path)."""
    i = bisect_left(cum, s)
    if i <= 0:
        return 0
    if i >= len(cum):
        return len(cum) - 1
    return i if abs(cum[i] - s) < abs(s - cum[i-1]) else i - 1

# -------------------------
# Simulation
# -------------------------
@dataclass
class Agent:
    name: str
    s: float              # position along the path in meters in [0, total_length]
    speed_mps: float      # non-negative speed (m/s)
    direction: int        # +1 moves from node 0 -> end, -1 from end -> node 0
    start_time_s: float = 0.0

    def is_active(self, t: float) -> bool:
        return t >= self.start_time_s

def mph_to_mps(mph: float) -> float:
    return mph * 0.44704

def mps_to_mph(mps: float) -> float:
    return mps * 2.2369362920544

def simulate_meeting(
    nodes: List[Tuple[float, float]],
    v_fwd_mph: float,
    v_bwd_mph: float,
    dt_s: float = 1.0,
    meeting_threshold_m: float = 0.5,
    groups: Optional[List[Dict[str, Any]]] = None,
    max_steps: int = 10_000_000
) -> Dict[str, Any]:
    """
    Discrete-time simulation (no closed-form math) of two carts starting at opposite
    ends of a path and moving towards each other. Returns the node index where they meet
    (nearest node to the exact continuous meeting point), meeting time, and lat/lon.
    - nodes: list of (lat, lon) path vertices, ordered from Hole 1 start (node 0) to Hole 18 end (node N-1).
    - v_fwd_mph: speed of the golf cart moving 1 -> 18 (mph).
    - v_bwd_mph: speed of the beverage cart moving 18 -> 1 (mph).
    - dt_s: simulation time step in seconds (e.g., 0.5–2.0 is fine).
    - meeting_threshold_m: optional snap threshold for "already close" detection.
    - groups: optional list of extra agents to simulate (they don't affect the meeting yet).
              dict keys: name, start_node_index, speed_mph, start_time_s, direction (+1/-1)
    """
    cum = cumulative_distances(nodes)
    total_length = cum[-1]

    fwd = Agent("golf_cart", s=0.0,           speed_mps=mph_to_mps(v_fwd_mph), direction=+1, start_time_s=0.0)
    bwd = Agent("bev_cart",  s=total_length,  speed_mps=mph_to_mps(v_bwd_mph), direction=-1, start_time_s=0.0)

    # Optional extra groups
    extra_agents: List[Agent] = []
    if groups:
        for g in groups:
            idx = max(0, min(len(nodes)-1, int(g.get("start_node_index", 0))))
            s0 = cum[idx]
            extra_agents.append(
                Agent(
                    name=g.get("name", f"group_{len(extra_agents)+1}"),
                    s=s0,
                    speed_mps=mph_to_mps(float(g.get("speed_mph", 3.0))),
                    direction=int(g.get("direction", +1)),
                    start_time_s=float(g.get("start_time_s", 0.0))
                )
            )

    if fwd.speed_mps + bwd.speed_mps <= 0:
        raise ValueError("Both carts have zero speed; they will never meet.")

    t = 0.0
    steps = 0

    while steps < max_steps:
        steps += 1

        # If already very close, snap
        if abs(bwd.s - fwd.s) <= meeting_threshold_m:
            s_meet = 0.5 * (bwd.s + fwd.s)
            idx = pos_to_node_index(cum, s_meet)
            return {
                "meeting_node_index": idx,
                "meeting_latlon": nodes[idx],
                "t_meet_s": t,
                "method": "threshold",
                "total_length_m": total_length,
                "steps": steps
            }

        # propose next positions
        fwd_next = max(0.0, min(total_length, fwd.s + fwd.speed_mps * dt_s * fwd.direction))
        bwd_next = max(0.0, min(total_length, bwd.s + bwd.speed_mps * dt_s * bwd.direction))

        # crossing this step?
        if fwd_next >= bwd_next:
            gap = bwd.s - fwd.s             # meters, > 0
            closing_speed = fwd.speed_mps + bwd.speed_mps
            t_star = gap / closing_speed    # seconds within this step
            s_meet = fwd.s + fwd.speed_mps * t_star * fwd.direction
            idx = pos_to_node_index(cum, s_meet)
            return {
                "meeting_node_index": idx,
                "meeting_latlon": nodes[idx],
                "t_meet_s": t + t_star,
                "method": "crossing",
                "total_length_m": total_length,
                "steps": steps
            }

        # advance simulation
        t += dt_s
        fwd.s = fwd_next
        bwd.s = bwd_next

        # update extra groups (no interactions yet)
        for ag in extra_agents:
            if ag.is_active(t):
                next_pos = max(0.0, min(total_length, ag.s + ag.speed_mps * dt_s * ag.direction))
                ag.s = next_pos

    raise RuntimeError("Max steps exceeded without a meeting. Check speeds or dt_s.")

# -------------------------
# Minimal CLI for quick runs
# -------------------------
def load_nodes_csv(path: str, lat_col: str = "lat", lon_col: str = "lon") -> List[Tuple[float, float]]:
    nodes: List[Tuple[float, float]] = []
    with open(path, "r", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nodes.append((float(row[lat_col]), float(row[lon_col])))
    if len(nodes) < 2:
        raise ValueError("CSV must contain at least 2 rows with lat/lon.")
    return nodes

def load_nodes_geojson(path: str) -> List[Tuple[float, float]]:
    """
    Load nodes from a GeoJSON file. Expects a FeatureCollection of Point features.
    Coordinates in GeoJSON are [lon, lat]; we convert to (lat, lon).
    Sorts features by properties.sequence_position if available, otherwise by properties.node_id.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # Collect features
    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        features = data.get("features", [])
    elif isinstance(data, dict) and data.get("type") == "Feature":
        features = [data]
    else:
        raise ValueError("Unsupported GeoJSON structure: expected FeatureCollection or Feature")

    def coerce_float(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def coerce_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    # Extract candidate points with ordering hints
    ordered_points: List[Tuple[int, Optional[float], Optional[int], float, float]] = []
    for idx, feat in enumerate(features):
        if not isinstance(feat, dict):
            continue
        geom = feat.get("geometry") or {}
        if not isinstance(geom, dict) or geom.get("type") != "Point":
            continue
        coords = geom.get("coordinates")
        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        props = feat.get("properties") or {}
        seq = coerce_float(props.get("sequence_position"))
        nid = coerce_int(props.get("node_id"))
        # Store with a stable fallback key (original index)
        ordered_points.append((idx, seq, nid, lat, lon))

    if not ordered_points:
        raise ValueError("GeoJSON contains no Point features with valid coordinates.")

    # Sort: by sequence_position if present, else node_id, else original index
    def sort_key(item: Tuple[int, Optional[float], Optional[int], float, float]):
        original_index, seq_opt, node_id_opt, _lat, _lon = item
        if seq_opt is not None:
            return (0, seq_opt)
        if node_id_opt is not None:
            return (1, node_id_opt)
        return (2, original_index)

    ordered_points.sort(key=sort_key)
    nodes = [(lat, lon) for (_i, _s, _n, lat, lon) in ordered_points]
    if len(nodes) < 2:
        raise ValueError("GeoJSON must contain at least 2 Point features with coordinates.")
    return nodes

def load_nodes_geojson_with_holes(path: str) -> Tuple[List[Tuple[float, float]], List[Optional[int]]]:
    """
    Like load_nodes_geojson, but also returns a parallel list of hole numbers per node
    if available from properties.hole_number; otherwise None entries.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and data.get("type") == "FeatureCollection":
        features = data.get("features", [])
    elif isinstance(data, dict) and data.get("type") == "Feature":
        features = [data]
    else:
        raise ValueError("Unsupported GeoJSON structure: expected FeatureCollection or Feature")

    def coerce_float(value: Any) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def coerce_int(value: Any) -> Optional[int]:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    temp: List[Tuple[int, Optional[float], Optional[int], float, float, Optional[int]]] = []
    for idx, feat in enumerate(features):
        if not isinstance(feat, dict):
            continue
        geom = feat.get("geometry") or {}
        if not isinstance(geom, dict) or geom.get("type") != "Point":
            continue
        coords = geom.get("coordinates")
        if not isinstance(coords, (list, tuple)) or len(coords) < 2:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        props = feat.get("properties") or {}
        seq = coerce_float(props.get("sequence_position"))
        nid = coerce_int(props.get("node_id"))
        hole_num = coerce_int(props.get("hole_number"))
        temp.append((idx, seq, nid, lat, lon, hole_num))

    if not temp:
        raise ValueError("GeoJSON contains no Point features with valid coordinates.")

    def sort_key(item: Tuple[int, Optional[float], Optional[int], float, float, Optional[int]]):
        original_index, seq_opt, node_id_opt, _lat, _lon, _h = item
        if seq_opt is not None:
            return (0, seq_opt)
        if node_id_opt is not None:
            return (1, node_id_opt)
        return (2, original_index)

    temp.sort(key=sort_key)
    nodes = [(lat, lon) for (_i, _s, _n, lat, lon, _h) in temp]
    node_holes: List[Optional[int]] = [h for (_i, _s, _n, _lat, _lon, h) in temp]
    return nodes, node_holes

def load_holes_geojson(path: str) -> List[Dict[str, Any]]:
    """
    Load geofenced holes from a GeoJSON FeatureCollection. Each feature should be a
    Polygon or MultiPolygon with properties including 'hole' (1..18).
    Returns a list of dicts with keys: 'hole' (int), 'polygons' (list of polygons),
    where each polygon is a list of rings, and each ring is a list of (lon, lat) tuples.
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise ValueError("holes GeoJSON must be a FeatureCollection")

    features = data.get("features", [])
    holes: List[Dict[str, Any]] = []
    for feat in features:
        if not isinstance(feat, dict):
            continue
        props = feat.get("properties") or {}
        hole_num_raw = props.get("hole")
        try:
            hole_num = int(hole_num_raw) if hole_num_raw is not None else None
        except (TypeError, ValueError):
            hole_num = None
        geom = feat.get("geometry") or {}
        geom_type = geom.get("type")
        coords = geom.get("coordinates")
        if hole_num is None or geom_type not in {"Polygon", "MultiPolygon"}:
            continue

        polygons: List[List[List[Tuple[float, float]]]] = []
        if geom_type == "Polygon":
            # coords: [ ring1, ring2, ... ], each ring is [[lon,lat], ...]
            rings = []
            for ring in coords:
                rings.append([(float(x), float(y)) for x, y in ring])
            polygons.append(rings)
        else:  # MultiPolygon
            for poly in coords:
                rings = []
                for ring in poly:
                    rings.append([(float(x), float(y)) for x, y in ring])
                polygons.append(rings)

        holes.append({"hole": hole_num, "polygons": polygons})

    if not holes:
        raise ValueError("No valid hole polygons found in holes GeoJSON")
    return holes

def point_in_ring(lon: float, lat: float, ring: List[Tuple[float, float]]) -> bool:
    """Ray casting point-in-polygon test for a single ring. Returns True if inside or on edge."""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        # Check if point is on a horizontal boundary or vertex alignment
        # Ray cast: consider edges where y between lat
        intersects = ((y1 > lat) != (y2 > lat)) and (
            lon < (x2 - x1) * (lat - y1) / (y2 - y1 + 1e-15) + x1
        )
        if intersects:
            inside = not inside
    return inside

def point_in_polygon(lon: float, lat: float, polygon_with_holes: List[List[Tuple[float, float]]]) -> bool:
    """
    polygon_with_holes: [outer_ring, hole1, hole2, ...]. Inside if in outer and not in any hole.
    """
    if not polygon_with_holes:
        return False
    outer = polygon_with_holes[0]
    if not point_in_ring(lon, lat, outer):
        return False
    # Exclude if inside any interior hole
    for hole_ring in polygon_with_holes[1:]:
        if point_in_ring(lon, lat, hole_ring):
            return False
    return True

def locate_hole_for_point(lon: float, lat: float, holes: List[Dict[str, Any]]) -> Optional[int]:
    """Return the hole number containing the point, or None if not found."""
    for h in holes:
        for polygon in h["polygons"]:
            if point_in_polygon(lon, lat, polygon):
                return int(h["hole"])
    return None

def parse_hhmm_or_hhmmss(value: str) -> time:
    parts = [int(p) for p in value.split(":")]
    if len(parts) == 2:
        return time(parts[0], parts[1], 0)
    return time(parts[0], parts[1], parts[2])

def compute_crossings(
    nodes: List[Tuple[float, float]],
    v_fwd_mph: float,
    v_bwd_mph: float,
    bev_start_clock: str,
    groups_start_clock: str,
    groups_end_clock: str,
    groups_count: int,
    random_seed: Optional[int],
    holes: Optional[List[Dict[str, Any]]],
    node_holes: Optional[List[Optional[int]]] = None,
    tee_mode: str = "interval",
    groups_interval_min: float = 30.0
) -> Dict[str, Any]:
    """
    Closed-form crossing computation for a looping beverage cart (18->1 repeatedly)
    and multiple golfer groups (1->18, single lap), with random tee times.
    Returns dict with per-group crossing details including timestamp and hole.
    """
    cum = cumulative_distances(nodes)
    L = cum[-1]

    v_g = mph_to_mps(v_fwd_mph)
    v_b = mph_to_mps(v_bwd_mph)
    if v_g <= 0 or v_b <= 0:
        raise ValueError("Speeds must be positive for crossing computation.")

    # Time zero is bev start
    bev_t0 = datetime.combine(date.today(), parse_hhmm_or_hhmmss(bev_start_clock))
    group_start_abs = datetime.combine(date.today(), parse_hhmm_or_hhmmss(groups_start_clock))

    # Build tee times (seconds since bev start)
    t_g0_list: List[float] = []
    if tee_mode == "interval":
        for i in range(groups_count):
            tee_abs = group_start_abs + timedelta(minutes=groups_interval_min * i)
            t_g0_list.append(max(0.0, (tee_abs - bev_t0).total_seconds()))
    else:
        group_end_abs = datetime.combine(date.today(), parse_hhmm_or_hhmmss(groups_end_clock))
        if group_end_abs <= group_start_abs:
            raise ValueError("groups_end_clock must be after groups_start_clock")
        window_start_s = (group_start_abs - bev_t0).total_seconds()
        window_end_s = (group_end_abs - bev_t0).total_seconds()
        if window_end_s <= 0:
            raise ValueError("Group window ends before bev starts; adjust times.")
        rng = random.Random(random_seed)
        for _ in range(groups_count):
            t_g0_list.append(rng.uniform(max(0.0, window_start_s), window_end_s))

    results: List[Dict[str, Any]] = []
    for group_idx in range(1, groups_count + 1):
        t_g0 = t_g0_list[group_idx - 1]
        t_finish = t_g0 + L / v_g

        # Determine k range that can produce valid crossings while the group is on course
        # t_k = (L*(k+1) + v_g*t_g0) / (v_g + v_b) ∈ [t_g0, t_finish]
        # Solve upper bound for k: t_k ≤ t_finish → k ≤ ((v_g+v_b)*t_finish - v_g*t_g0)/L - 1
        k_upper_float = ((v_g + v_b) * t_finish - v_g * t_g0) / L - 1.0
        k_max = int(k_upper_float) if k_upper_float >= 0 else -1

        crossings_list: List[Dict[str, Any]] = []
        for k in range(0, k_max + 1):
            t_k = (L * (k + 1) + v_g * t_g0) / (v_g + v_b)
            if t_k < t_g0 - 1e-9 or t_k > t_finish + 1e-9:
                continue
            s_meet = v_g * (t_k - t_g0)
            s_meet = max(0.0, min(L, s_meet))
            idx = pos_to_node_index(cum, s_meet)
            lat, lon = nodes[idx]
            hole_num: Optional[int] = None
            if node_holes is not None and 0 <= idx < len(node_holes) and node_holes[idx] is not None:
                hole_num = int(node_holes[idx])
            elif holes is not None:
                hole_num = locate_hole_for_point(lon=lon, lat=lat, holes=holes)

            crossings_list.append({
                "t_cross_s": t_k,
                "timestamp": bev_t0 + timedelta(seconds=t_k),
                "node_index": idx,
                "hole": hole_num,
                "k_wraps": k
            })

        if not crossings_list:
            results.append({
                "group": group_idx,
                "tee_time": bev_t0 + timedelta(seconds=t_g0),
                "crossed": False,
                "crossings": []
            })
            continue

        results.append({
            "group": group_idx,
            "tee_time": bev_t0 + timedelta(seconds=t_g0),
            "crossed": True,
            "crossings": crossings_list
        })

    # Renumber groups so that Group 1 is always earliest tee, then 2, etc.
    results_sorted = sorted(results, key=lambda r: r.get("tee_time"))
    for i, r in enumerate(results_sorted, start=1):
        r["group"] = i

    return {
        "bev_start": bev_t0,
        "course_length_m": L,
        "v_golfer_mph": v_fwd_mph,
        "v_bev_mph": v_bwd_mph,
        "groups": results_sorted
    }

def main():
    parser = argparse.ArgumentParser(description="Simulate beverage cart (18->1) and golf cart (1->18) meeting point along a GPS path.")
    parser.add_argument("--nodes_csv", type=str, required=False, help="CSV with columns 'lat' and 'lon' (ordered along the course).")
    parser.add_argument(
        "--nodes_geojson",
        type=str,
        required=False,
        default="courses/pinetree_country_club/geojson/generated/lcm_course_nodes.geojson",
        help="GeoJSON FeatureCollection containing ordered Point features for course nodes."
    )
    parser.add_argument(
        "--holes_geojson",
        type=str,
        required=False,
        default="courses/pinetree_country_club/geojson/generated/holes_geofenced.geojson",
        help="GeoJSON FeatureCollection containing hole polygons (Polygon/MultiPolygon) with 'hole' property."
    )
    parser.add_argument(
        "--config_json",
        type=str,
        required=False,
        default="courses/pinetree_country_club/config/simulation_config.json",
        help="Simulation config JSON to derive speeds from 18-hole durations."
    )
    parser.add_argument("--v_fwd_mph", type=Optional[float], default=None, help="Override forward (golfer) speed 1->18 in mph. If omitted, derived from config.")
    parser.add_argument("--v_bwd_mph", type=Optional[float], default=None, help="Override backward (bev cart) speed 18->1 in mph. If omitted, derived from config.")
    parser.add_argument("--dt_s", type=float, default=1.0, help="Simulation time step in seconds.")
    parser.add_argument(
        "--start_time",
        type=str,
        default="09:00:00",
        help="Clock start time for both carts in HH:MM or HH:MM:SS (local, today)."
    )
    parser.add_argument("--bev_start", type=str, default="08:00:00", help="Beverage cart start clock time (HH:MM or HH:MM:SS). Overrides --start_time for bev only.")
    parser.add_argument("--groups_start", type=str, default="09:00:00", help="Tee time for first group (or start of random window).")
    parser.add_argument("--groups_end", type=str, default="10:00:00", help="Latest tee time for random groups (ignored in interval mode).")
    parser.add_argument("--groups_count", type=int, default=4, help="Number of random golfer groups to simulate.")
    parser.add_argument("--random_seed", type=int, default=123, help="Seed for reproducible random tee times (used in random mode).")
    parser.add_argument("--tee_mode", type=str, choices=["interval", "random"], default="interval", help="How to generate group tee times.")
    parser.add_argument("--groups_interval_min", type=float, default=30.0, help="Minutes between consecutive groups when tee_mode=interval.")
    args = parser.parse_args()

    nodes: List[Tuple[float, float]]
    node_holes: Optional[List[Optional[int]]] = None
    # Prefer GeoJSON if provided (or default exists), otherwise CSV, otherwise synthetic
    try:
        if args.nodes_geojson:
            # Try to load with per-node hole numbers if available
            try:
                nodes, node_holes = load_nodes_geojson_with_holes(args.nodes_geojson)
            except Exception:
                nodes = load_nodes_geojson(args.nodes_geojson)
        elif args.nodes_csv:
            nodes = load_nodes_csv(args.nodes_csv)
        else:
            raise FileNotFoundError
    except Exception:
        # Fallback: a simple synthetic path
        lat0, lon0 = 37.0, -122.0
        nodes = [(lat0 + i * 0.0001, lon0 + i * 0.0001) for i in range(240)]

    # Load hole polygons if provided
    holes: Optional[List[Dict[str, Any]]] = None
    try:
        if args.holes_geojson:
            holes = load_holes_geojson(args.holes_geojson)
    except Exception:
        holes = None

    # Derive speeds from config if not explicitly provided
    # Compute total path length in meters
    try:
        cum_for_speed = cumulative_distances(nodes)
        total_length_m_for_speed = cum_for_speed[-1]
    except Exception:
        total_length_m_for_speed = None

    def derive_mph_from_minutes(total_length_m: float, minutes: float) -> float:
        if minutes <= 0:
            raise ValueError("Duration minutes must be positive to derive speed.")
        meters_per_sec = total_length_m / (minutes * 60.0)
        return mps_to_mph(meters_per_sec)

    derived_v_fwd_mph: Optional[float] = None
    derived_v_bwd_mph: Optional[float] = None
    if total_length_m_for_speed is not None and args.config_json:
        try:
            with open(args.config_json, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            golfer_minutes = float(cfg.get("golfer_18_holes_minutes"))
            bev_minutes = float(cfg.get("bev_cart_18_holes_minutes"))
            derived_v_fwd_mph = derive_mph_from_minutes(total_length_m_for_speed, golfer_minutes)
            derived_v_bwd_mph = derive_mph_from_minutes(total_length_m_for_speed, bev_minutes)
        except Exception:
            derived_v_fwd_mph = None
            derived_v_bwd_mph = None

    # Choose speeds: CLI override > config-derived > sensible fallback
    v_fwd_mph_to_use = args.v_fwd_mph if args.v_fwd_mph is not None else (derived_v_fwd_mph if derived_v_fwd_mph is not None else 12.0)
    v_bwd_mph_to_use = args.v_bwd_mph if args.v_bwd_mph is not None else (derived_v_bwd_mph if derived_v_bwd_mph is not None else 10.0)

    result = simulate_meeting(
        nodes=nodes,
        v_fwd_mph=v_fwd_mph_to_use,
        v_bwd_mph=v_bwd_mph_to_use,
        dt_s=args.dt_s
    )

    idx = result["meeting_node_index"]
    lat, lon = result["meeting_latlon"]
    t_s = result["t_meet_s"]
    print(f"Meeting node index: {idx}")
    print(f"Meeting lat,lon: {lat:.6f}, {lon:.6f}")
    print(f"Meeting time: {t_s:.1f} seconds ({t_s/60:.2f} minutes)")
    print(f"Method: {result['method']}, Steps: {result['steps']}, Path length: {result['total_length_m']:.1f} m")
    print(f"Speeds used (mph): golfer_fwd={v_fwd_mph_to_use:.2f}, bev_cart_bwd={v_bwd_mph_to_use:.2f}")

    # Compute meeting timestamp from start_time (today, local time)
    try:
        # Parse HH:MM or HH:MM:SS
        parts = [int(p) for p in args.start_time.split(":")]
        if len(parts) == 2:
            hh, mm = parts
            ss = 0
        else:
            hh, mm, ss = parts[0], parts[1], parts[2]
        start_dt = datetime.combine(date.today(), time(hh, mm, ss))
        meet_dt = start_dt + timedelta(seconds=float(t_s))
        print(f"Start time: {start_dt.isoformat(sep=' ')}")
        print(f"Meeting timestamp: {meet_dt.isoformat(sep=' ')}")
    except Exception:
        pass

    # Locate hole for meeting point if holes were loaded
    if holes is not None or node_holes is not None:
        # Note: polygons are in (lon, lat). We have (lat, lon) -> convert
        hole_num: Optional[int] = None
        if node_holes is not None and 0 <= idx < len(node_holes) and node_holes[idx] is not None:
            hole_num = int(node_holes[idx])
        elif holes is not None:
            hole_num = locate_hole_for_point(lon=lon, lat=lat, holes=holes)
        if hole_num is not None:
            print(f"Meeting hole: {hole_num}")
        else:
            print("Meeting hole: not found in geofences")

    # Multi-group crossings with looping bev cart
    print("\nCrossings with looping bev cart and random groups:")
    crossings = compute_crossings(
        nodes=nodes,
        v_fwd_mph=v_fwd_mph_to_use,
        v_bwd_mph=v_bwd_mph_to_use,
        bev_start_clock=args.bev_start,
        groups_start_clock=args.groups_start,
        groups_end_clock=args.groups_end,
        groups_count=args.groups_count,
        random_seed=args.random_seed,
        holes=holes,
        node_holes=node_holes,
        tee_mode=args.tee_mode,
        groups_interval_min=args.groups_interval_min
    )
    print(f"Beverage cart start: {crossings['bev_start'].isoformat(sep=' ')}")
    groups_sorted = sorted(crossings["groups"], key=lambda g: g.get("tee_time"))
    for g in groups_sorted:
        tee = g.get("tee_time")
        if not g.get("crossed", True):
            print(f"Group {g['group']} tee {tee.isoformat(sep=' ')}: no crossings")
            continue
        # Only show node number, timestamp, hole for each crossing
        for cr in g.get("crossings", []):
            node_idx = cr.get("node_index")
            ts = cr.get("timestamp")
            hole_disp = cr.get("hole") if cr.get("hole") is not None else "unknown"
            print(f"Group {g['group']} | node {node_idx} | {ts.isoformat(sep=' ')} | hole {hole_disp}")

if __name__ == "__main__":
    main()
