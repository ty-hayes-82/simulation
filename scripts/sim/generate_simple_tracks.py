from __future__ import annotations

"""
Generate three simple tracks at 1-minute cadence using generated course nodes:
- Golfer: forward over geojson/generated/holes_connected.geojson Point nodes (idx ascending)
- Beverage cart: reverse over the same nodes (idx descending)
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


def load_holes_connected_points(course_dir: str) -> List[Tuple[int, float, float]]:
    """Load (idx, lon, lat) from geojson/generated/holes_connected.geojson Point features.

    Falls back to deriving from the first LineString vertices if Point features are absent.
    """
    path = Path(course_dir) / "geojson" / "generated" / "holes_connected.geojson"
    gdf = gpd.read_file(path).to_crs(4326)
    pts: List[Tuple[int, float, float]] = []
    for _, row in gdf.iterrows():
        if row.geometry is None:
            continue
        if getattr(row.geometry, "geom_type", None) == "Point" and ("idx" in row):
            try:
                idx = int(row["idx"])  # type: ignore[index]
            except Exception:
                continue
            pts.append((idx, float(row.geometry.x), float(row.geometry.y)))
    if not pts:
        # Fallback: use the first LineString's vertices if Points not present
        line_rows = gdf[gdf.geometry.type == "LineString"]
        if not line_rows.empty:
            coords = list(line_rows.iloc[0].geometry.coords)
            pts = [(i, float(lon), float(lat)) for i, (lon, lat) in enumerate(coords)]
    pts.sort(key=lambda t: t[0])
    return pts


def build_minute_points_from_connected(
    ordered_points: List[Tuple[int, float, float]],
    *, point_type: str,
) -> List[Dict]:
    """Create one GPS point per minute from a sequence of connected nodes.

    Assumes 1 node == 1 minute progression. Labels with 'type' passed in.
    """
    points: List[Dict] = []
    current_time_s = 0
    for _, lon, lat in ordered_points:
        points.append(
            {
                "timestamp": current_time_s,
                "longitude": lon,
                "latitude": lat,
                "type": point_type,
            }
        )
        current_time_s += 60
    return points


def generate_tracks(course_dir: str = "courses/pinetree_country_club") -> Dict[str, List[Dict]]:
    # Use holes_connected.geojson nodes for both golfer and bev-cart tracks
    connected = load_holes_connected_points(course_dir)
    golfer_points = build_minute_points_from_connected(connected, point_type="golfer")
    bev_points = build_minute_points_from_connected(list(reversed(connected)), point_type="bev_cart")

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


