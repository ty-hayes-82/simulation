from typing import List, Tuple, Optional, Union
from pathlib import Path


def seconds_to_clock_str(sec_since_7am: int) -> str:
    total = max(0, int(sec_since_7am))
    hh = 7 + (total // 3600)
    mm = (total % 3600) // 60
    ss = total % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def distribute_counts_by_fraction(total: int, fractions: List[float]) -> List[int]:
    """Turn fractional shares into integer counts that sum to total.

    Uses largest-remainder method for stable rounding.
    """
    total = int(total)
    if total <= 0 or not fractions:
        return [0 for _ in fractions]
    # Normalize if user provided percentages that don't sum to 1
    s = sum(max(0.0, float(x)) for x in fractions)
    if s <= 0:
        return [0 for _ in fractions]
    shares = [max(0.0, float(x)) / s for x in fractions]
    raw = [total * x for x in shares]
    floors = [int(x) for x in raw]
    remainder = total - sum(floors)
    # Assign remaining by largest fractional parts
    frac_parts = sorted(((i, raw[i] - floors[i]) for i in range(len(raw))), key=lambda t: t[1], reverse=True)
    for i in range(remainder):
        floors[frac_parts[i % len(floors)][0]] += 1
    return floors


def time_str_to_seconds(time_str: str) -> int:
    hour, minute = map(int, time_str.split(":"))
    return (hour - 7) * 3600 + minute * 60


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    import math
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return 6371000.0 * c


def load_connected_points(course_dir: str) -> Tuple[List[Tuple[float, float]], List[Optional[int]]]:
    """Load per-minute loop points from holes_connected.geojson.

    Returns:
        (coords_lonlat, hole_numbers)
    """
    import json
    # Local imports to avoid module-level dependency cycles
    try:
        from golfsim.simulation.crossings import load_holes_geojson, locate_hole_for_point  # type: ignore
    except Exception:
        load_holes_geojson = None  # type: ignore
        locate_hole_for_point = None  # type: ignore
    coords: List[Tuple[float, float]] = []
    hole_nums: List[Optional[int]] = []
    path = Path(course_dir) / "geojson" / "generated" / "holes_connected.geojson"
    if not path.exists():
        return [], []
    data = json.loads(path.read_text(encoding="utf-8"))
    features = data.get("features", []) if isinstance(data, dict) else []
    # Optional hole polygons for labeling when Point properties absent
    holes_fc = None
    try:
        if load_holes_geojson is not None:
            holes_path = Path(course_dir) / "geojson" / "generated" / "holes_geofenced.geojson"
            if holes_path.exists():
                holes_fc = load_holes_geojson(str(holes_path))
    except Exception:
        holes_fc = None

    # Use Point features only (no LineString resampling) and use embedded hole labels or polygon fallback
    for feat in features:
        if not isinstance(feat, dict):
            continue
        geom = feat.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        coords_xy = geom.get("coordinates") or []
        if not isinstance(coords_xy, (list, tuple)) or len(coords_xy) < 2:
            continue
        lon = float(coords_xy[0])
        lat = float(coords_xy[1])
        props = feat.get("properties") or {}
        hn = (
            props.get("hole_number")
            or props.get("hole")
            or props.get("hole_num")
            or props.get("current_hole")
        )
        hole_num = None
        try:
            hole_num = int(hn) if hn is not None else None
        except Exception:
            hole_num = None
        if hole_num is None and holes_fc is not None and locate_hole_for_point is not None:
            try:
                hole_num = locate_hole_for_point(lon=lon, lat=lat, holes=holes_fc)
            except Exception:
                hole_num = None
        coords.append((lon, lat))
        hole_nums.append(hole_num)
    return coords, hole_nums


from datetime import datetime

def generate_standardized_output_name(
    mode: str,
    num_bev_carts: int = 0,
    num_runners: int = 0,
    num_golfers: int = 0,
    tee_scenario: str = None,
    hole: int = None,
) -> str:
    """Generate standardized, mode-specific output directory names.

    Examples:
      - bev-carts:         {timestamp}_bevcart_only_{carts}_carts
      - bev-with-golfers:  {timestamp}_bev_with_golfers_{carts}_carts_{groups}_groups[_scenario]
      - delivery-runner:   {timestamp}_delivery_runner_{runners}_runners[_scenario][_groups_groups]
      - golfers-only:      {timestamp}_golfers_only_{groups}_groups
      - single-golfer:     {timestamp}_single_golfer_[hole{N}|randomhole]
    """
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    mode_key = str(mode or "").lower()

    # bev-cart only
    if mode_key == "bev-carts":
        parts = [ts, "bevcart_only"]
        if num_bev_carts > 0:
            parts.append(f"{int(num_bev_carts)}_carts")
        return "_".join(parts)

    # bev with golfers
    if mode_key == "bev-with-golfers":
        parts = [ts, "bev_with_golfers", f"{max(1, int(num_bev_carts))}_carts", f"{int(num_golfers)}_groups"]
        if tee_scenario and tee_scenario.lower() not in {"none", "manual"}:
            parts.append(tee_scenario)
        return "_".join(parts)

    # delivery runner
    if mode_key == "delivery-runner":
        parts = [ts, "delivery_runner", f"{int(num_runners)}_runners"]
        if tee_scenario and tee_scenario.lower() not in {"none", "manual"}:
            parts.append(tee_scenario)
        if int(num_golfers) > 0:
            parts.append(f"{int(num_golfers)}_groups")
        return "_".join(parts)

    # golfers only
    if mode_key == "golfers-only":
        parts = [ts, "golfers_only", f"{int(num_golfers)}_groups"]
        return "_".join(parts)
    
    # fallback
    return f"{ts}_{mode_key}_unspecified"