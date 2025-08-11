from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_left
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, date, time, timedelta
import json
import random


# -------------------------
# Unit conversions
# -------------------------
def mph_to_mps(mph: float) -> float:
    return mph * 0.44704


def mps_to_mph(mps: float) -> float:
    return mps * 2.2369362920544


# -------------------------
# Geometry helpers
# -------------------------
def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6371000.0
    from math import radians, sin, cos, atan2, sqrt

    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlambda = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlambda / 2) ** 2
    c = 2 * atan2(sqrt(1 - a), sqrt(a))
    return R * c


def cumulative_distances(nodes: List[Tuple[float, float]]) -> List[float]:
    if len(nodes) < 2:
        raise ValueError("Need at least 2 nodes to form a path.")
    cum = [0.0]
    for i in range(1, len(nodes)):
        d = haversine_m(nodes[i - 1][0], nodes[i - 1][1], nodes[i][0], nodes[i][1])
        cum.append(cum[-1] + d)
    return cum


def pos_to_node_index(cum: List[float], s: float) -> int:
    i = bisect_left(cum, s)
    if i <= 0:
        return 0
    if i >= len(cum):
        return len(cum) - 1
    return i if abs(cum[i] - s) < abs(s - cum[i - 1]) else i - 1


# -------------------------
# GeoJSON loaders
# -------------------------
def load_nodes_geojson(path: str) -> List[Tuple[float, float]]:
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
        ordered_points.append((idx, seq, nid, lat, lon))

    if not ordered_points:
        raise ValueError("GeoJSON contains no Point features with valid coordinates.")

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
    inside = False
    n = len(ring)
    if n < 3:
        return False
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        intersects = ((y1 > lat) != (y2 > lat)) and (
            lon < (x2 - x1) * (lat - y1) / (y2 - y1 + 1e-15) + x1
        )
        if intersects:
            inside = not inside
    return inside


def point_in_polygon(lon: float, lat: float, polygon_with_holes: List[List[Tuple[float, float]]]) -> bool:
    if not polygon_with_holes:
        return False
    outer = polygon_with_holes[0]
    if not point_in_ring(lon, lat, outer):
        return False
    for hole_ring in polygon_with_holes[1:]:
        if point_in_ring(lon, lat, hole_ring):
            return False
    return True


def locate_hole_for_point(lon: float, lat: float, holes: List[Dict[str, Any]]) -> Optional[int]:
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


# -------------------------
# Core logic
# -------------------------
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
    groups_interval_min: float = 30.0,
) -> Dict[str, Any]:
    cum = cumulative_distances(nodes)
    L = cum[-1]

    v_g = mph_to_mps(v_fwd_mph)
    v_b = mph_to_mps(v_bwd_mph)
    if v_g <= 0 or v_b <= 0:
        raise ValueError("Speeds must be positive for crossing computation.")

    bev_t0 = datetime.combine(date.today(), parse_hhmm_or_hhmmss(bev_start_clock))
    group_start_abs = datetime.combine(date.today(), parse_hhmm_or_hhmmss(groups_start_clock))

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

            crossings_list.append(
                {
                    "t_cross_s": t_k,
                    "timestamp": bev_t0 + timedelta(seconds=t_k),
                    "node_index": idx,
                    "hole": hole_num,
                    "k_wraps": k,
                }
            )

        if not crossings_list:
            results.append(
                {
                    "group": group_idx,
                    "tee_time": bev_t0 + timedelta(seconds=t_g0),
                    "crossed": False,
                    "crossings": [],
                }
            )
            continue

        results.append(
            {
                "group": group_idx,
                "tee_time": bev_t0 + timedelta(seconds=t_g0),
                "crossed": True,
                "crossings": crossings_list,
            }
        )

    results_sorted = sorted(results, key=lambda r: r.get("tee_time"))
    for i, r in enumerate(results_sorted, start=1):
        r["group"] = i

    return {
        "bev_start": bev_t0,
        "course_length_m": L,
        "v_golfer_mph": v_fwd_mph,
        "v_bev_mph": v_bwd_mph,
        "groups": results_sorted,
    }


def simulate_meeting(
    nodes: List[Tuple[float, float]],
    v_fwd_mph: float,
    v_bwd_mph: float,
    dt_s: float = 1.0,
    meeting_threshold_m: float = 0.5,
    max_steps: int = 10_000_000,
) -> Dict[str, Any]:
    @dataclass
    class Agent:
        name: str
        s: float
        speed_mps: float
        direction: int
        start_time_s: float = 0.0

        def is_active(self, t: float) -> bool:
            return t >= self.start_time_s

    cum = cumulative_distances(nodes)
    total_length = cum[-1]

    fwd = Agent("golf_cart", s=0.0, speed_mps=mph_to_mps(v_fwd_mph), direction=+1, start_time_s=0.0)
    bwd = Agent("bev_cart", s=total_length, speed_mps=mph_to_mps(v_bwd_mph), direction=-1, start_time_s=0.0)

    if fwd.speed_mps + bwd.speed_mps <= 0:
        raise ValueError("Both carts have zero speed; they will never meet.")

    t = 0.0
    steps = 0

    while steps < max_steps:
        steps += 1

        if abs(bwd.s - fwd.s) <= meeting_threshold_m:
            s_meet = 0.5 * (bwd.s + fwd.s)
            idx = pos_to_node_index(cum, s_meet)
            return {
                "meeting_node_index": idx,
                "meeting_latlon": nodes[idx],
                "t_meet_s": t,
                "method": "threshold",
                "total_length_m": total_length,
                "steps": steps,
            }

        fwd_next = max(0.0, min(total_length, fwd.s + fwd.speed_mps * dt_s * fwd.direction))
        bwd_next = max(0.0, min(total_length, bwd.s + bwd.speed_mps * dt_s * bwd.direction))

        if fwd_next >= bwd_next:
            gap = bwd.s - fwd.s
            closing_speed = fwd.speed_mps + bwd.speed_mps
            t_star = gap / closing_speed
            s_meet = fwd.s + fwd.speed_mps * t_star * fwd.direction
            idx = pos_to_node_index(cum, s_meet)
            return {
                "meeting_node_index": idx,
                "meeting_latlon": nodes[idx],
                "t_meet_s": t + t_star,
                "method": "crossing",
                "total_length_m": total_length,
                "steps": steps,
            }

        t += dt_s
        fwd.s = fwd_next
        bwd.s = bwd_next

    raise RuntimeError("Max steps exceeded without a meeting. Check speeds or dt_s.")


# -------------------------
# High-level helpers for scripts
# -------------------------
def derive_mph_from_minutes(total_length_m: float, minutes: float) -> float:
    if minutes <= 0:
        raise ValueError("Duration minutes must be positive to derive speed.")
    meters_per_sec = total_length_m / (minutes * 60.0)
    return mps_to_mph(meters_per_sec)


def maybe_derive_speeds_from_config(
    nodes: List[Tuple[float, float]],
    config_json_path: Optional[str],
    v_fwd_mph: Optional[float],
    v_bwd_mph: Optional[float],
) -> Tuple[float, float]:
    v_fwd = v_fwd_mph
    v_bwd = v_bwd_mph
    try:
        total_length_m = cumulative_distances(nodes)[-1]
        if (v_fwd is None or v_bwd is None) and config_json_path:
            from pathlib import Path

            cfg_path = Path(config_json_path)
            if cfg_path.exists():
                cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
                g_min = float(cfg.get("golfer_18_holes_minutes"))
                b_min = float(cfg.get("bev_cart_18_holes_minutes"))
                if v_fwd is None:
                    v_fwd = derive_mph_from_minutes(total_length_m, g_min)
                if v_bwd is None:
                    v_bwd = derive_mph_from_minutes(total_length_m, b_min)
    except Exception:
        pass
    v_fwd = v_fwd if v_fwd is not None else 12.0
    v_bwd = v_bwd if v_bwd is not None else 10.0
    return float(v_fwd), float(v_bwd)


def compute_crossings_from_files(
    nodes_geojson: str,
    holes_geojson: Optional[str],
    config_json: Optional[str],
    v_fwd_mph: Optional[float],
    v_bwd_mph: Optional[float],
    bev_start: str,
    groups_start: str,
    groups_end: str,
    groups_count: int,
    random_seed: Optional[int],
    tee_mode: str = "interval",
    groups_interval_min: float = 30.0,
) -> Dict[str, Any]:
    try:
        nodes, node_holes = load_nodes_geojson_with_holes(nodes_geojson)
    except Exception:
        nodes = load_nodes_geojson(nodes_geojson)
        node_holes = None

    holes = None
    try:
        if holes_geojson:
            holes = load_holes_geojson(holes_geojson)
    except Exception:
        holes = None

    v_fwd, v_bwd = maybe_derive_speeds_from_config(nodes, config_json, v_fwd_mph, v_bwd_mph)

    return compute_crossings(
        nodes=nodes,
        v_fwd_mph=v_fwd,
        v_bwd_mph=v_bwd,
        bev_start_clock=bev_start,
        groups_start_clock=groups_start,
        groups_end_clock=groups_end,
        groups_count=groups_count,
        random_seed=random_seed,
        holes=holes,
        node_holes=node_holes,
        tee_mode=tee_mode,
        groups_interval_min=groups_interval_min,
    )


def serialize_crossings_summary(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "bev_start": result["bev_start"].isoformat(),
        "v_golfer_mph": result["v_golfer_mph"],
        "v_bev_mph": result["v_bev_mph"],
        "groups": [
            {
                "group": g["group"],
                "tee_time": g.get("tee_time").isoformat() if g.get("tee_time") else None,
                "crossed": g.get("crossed", False),
                "crossings": [
                    {
                        "timestamp": cr.get("timestamp").isoformat() if cr.get("timestamp") else None,
                        "node_index": cr.get("node_index"),
                        "hole": cr.get("hole"),
                        "k_wraps": cr.get("k_wraps"),
                    }
                    for cr in g.get("crossings", [])
                ],
            }
            for g in result.get("groups", [])
        ],
    }


def save_crossings_summary(path: str, result: Dict[str, Any]) -> None:
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    serializable = serialize_crossings_summary(result)
    p.write_text(json.dumps(serializable, indent=2), encoding="utf-8")


