from __future__ import annotations

"""
Generate three simple tracks at 1-minute cadence using hole geometries:
- Golfer: holes 1→18, 12 minutes per hole, 2 minutes transfer between holes
- Beverage cart: holes 18→1, same timing but reverse order
- Cart path coverage: iterate cart path graph nodes in index order (no timing guarantees)

Outputs JSON files under outputs/simple_tracks/ with identical schema for golfer and bev-cart.
"""

import json
from pathlib import Path
from typing import Dict, List, Tuple

import geopandas as gpd
from shapely.geometry import LineString, Point


def _interpolate_along_linestring(line: LineString, fraction: float) -> Tuple[float, float]:
    if not isinstance(line, LineString) or len(line.coords) == 0:
        return (0.0, 0.0)
    if fraction <= 0:
        x, y = line.coords[0]
        return (x, y)
    if fraction >= 1:
        x, y = line.coords[-1]
        return (x, y)
    pt = line.interpolate(fraction, normalized=True)
    return (pt.x, pt.y)


def load_hole_lines(course_dir: str) -> Dict[int, LineString]:
    holes_path = Path(course_dir) / "geojson" / "holes.geojson"
    gdf = gpd.read_file(holes_path).to_crs(4326)
    hole_lines: Dict[int, LineString] = {}
    for _, row in gdf.iterrows():
        ref = row.get("hole", row.get("ref"))
        try:
            hole_num = int(ref)
        except (TypeError, ValueError):
            continue
        if row.geometry.geom_type == "LineString":
            hole_lines[hole_num] = row.geometry
    return hole_lines


def build_minute_points(
    lines_in_order: List[Tuple[int, LineString]],
    minutes_per_hole: int = 12,
    minutes_between_holes: int = 2,
) -> List[Dict]:
    points: List[Dict] = []
    current_time_s = 0
    for idx, (hole, line) in enumerate(lines_in_order):
        # Hole play minutes
        for m in range(minutes_per_hole):
            frac = 0.0 if m == 0 and len(points) == 0 else (m / max(minutes_per_hole - 1, 1))
            lon, lat = _interpolate_along_linestring(line, frac)
            points.append(
                {
                    "timestamp": current_time_s,
                    "longitude": lon,
                    "latitude": lat,
                    "current_hole": hole,
                    "type": "hole",
                }
            )
            current_time_s += 60
        # Transfer between holes (2 minutes) except after last
        if idx < len(lines_in_order) - 1:
            this_end = Point(line.coords[-1])
            next_line = lines_in_order[idx + 1][1]
            next_start = Point(next_line.coords[0])
            transfer = LineString([(this_end.x, this_end.y), (next_start.x, next_start.y)])
            for m in range(minutes_between_holes):
                frac = 0.0 if m == 0 else (m / max(minutes_between_holes - 1, 1))
                lon, lat = _interpolate_along_linestring(transfer, frac)
                points.append(
                    {
                        "timestamp": current_time_s,
                        "longitude": lon,
                        "latitude": lat,
                        "current_hole": hole,
                        "type": "transfer",
                    }
                )
                current_time_s += 60
    return points


def generate_tracks(course_dir: str = "courses/pinetree_country_club") -> Dict[str, List[Dict]]:
    hole_lines = load_hole_lines(course_dir)
    ordered = [hole_lines[i] for i in sorted(hole_lines.keys()) if i in hole_lines]
    ordered_pairs = [(i, hole_lines[i]) for i in sorted(hole_lines.keys())]
    reverse_pairs = [(i, hole_lines[i]) for i in sorted(hole_lines.keys(), reverse=True)]

    golfer_points = build_minute_points(ordered_pairs, minutes_per_hole=12, minutes_between_holes=2)
    bev_points = build_minute_points(reverse_pairs, minutes_per_hole=12, minutes_between_holes=2)

    # Cart path coverage (simple: dump node coordinates in sequence order)
    cart_points: List[Dict] = []
    try:
        import pickle
        import networkx as nx  # noqa: F401  # for type context
        cart_graph_path = Path(course_dir) / "pkl" / "cart_graph.pkl"
        if cart_graph_path.exists():
            with open(cart_graph_path, "rb") as f:
                cart_graph = pickle.load(f)
            t = 0
            for node in cart_graph.nodes():
                data = cart_graph.nodes[node]
                if "x" in data and "y" in data:
                    cart_points.append(
                        {
                            "timestamp": t,
                            "longitude": float(data["x"]),
                            "latitude": float(data["y"]),
                            "node_id": str(node),
                            "type": "cart_path_node",
                        }
                    )
                    t += 60
    except Exception:
        pass

    return {
        "golfer": golfer_points,
        "bev_cart": bev_points,
        "cart_path": cart_points,
    }


def main() -> None:
    course_dir = "courses/pinetree_country_club"
    tracks = generate_tracks(course_dir)
    out_dir = Path("outputs/simple_tracks")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "golfer.json").write_text(json.dumps(tracks["golfer"], indent=2))
    (out_dir / "bev_cart.json").write_text(json.dumps(tracks["bev_cart"], indent=2))
    (out_dir / "cart_path_nodes.json").write_text(json.dumps(tracks["cart_path"], indent=2))
    print(
        f"Wrote golfer={len(tracks['golfer'])} bev_cart={len(tracks['bev_cart'])} cart_nodes={len(tracks['cart_path'])}"
    )


if __name__ == "__main__":
    main()


