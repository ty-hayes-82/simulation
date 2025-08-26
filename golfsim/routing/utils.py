from __future__ import annotations

from pathlib import Path
import pickle
import json

import geopandas as gpd
import networkx as nx
from shapely.geometry import Point


def get_hole_for_node(node_id: int, course_dir: str | Path) -> int | None:
    """
    Finds which hole a given graph node is in.
    """
    course_dir = Path(course_dir)
    
    # Load cart graph
    pkl_path = course_dir / "pkl" / "cart_graph.pkl"
    if not pkl_path.exists():
        return None
    with pkl_path.open("rb") as f:
        G: nx.Graph = pickle.load(f)

    # Load geofenced holes
    geojson_path = course_dir / "geojson" / "generated" / "holes_geofenced.geojson"
    if not geojson_path.exists():
        return None
    # Load geofenced holes robustly: prefer pyogrio when available, fall back to default engine,
    # and finally to manual JSON parsing to avoid crashes on some environments.
    holes_gdf = None
    try:
        holes_gdf = gpd.read_file(geojson_path, engine="pyogrio")
    except Exception:
        try:
            holes_gdf = gpd.read_file(geojson_path)
        except Exception:
            try:
                data = json.loads(geojson_path.read_text(encoding="utf-8"))
                # GeoJSON FeatureCollection expected
                features = data.get("features", []) if isinstance(data, dict) else []
                if features:
                    from shapely.geometry import shape  # local import to avoid heavy import at module load
                    geoms = []
                    holes = []
                    for feat in features:
                        if not isinstance(feat, dict):
                            continue
                        props = feat.get("properties", {}) or {}
                        geom = feat.get("geometry")
                        try:
                            hole_num = int(props.get("hole", props.get("ref")))
                        except Exception:
                            hole_num = None
                        if geom is None or hole_num is None:
                            continue
                        try:
                            geoms.append(shape(geom))
                            holes.append(hole_num)
                        except Exception:
                            continue
                    if geoms:
                        import geopandas as _gpd
                        holes_gdf = _gpd.GeoDataFrame({"hole": holes, "geometry": geoms}, crs="EPSG:4326")
            except Exception:
                holes_gdf = None

    if holes_gdf is None:
        return None

    if not G.has_node(node_id):
        return None

    node_data = G.nodes[node_id]
    if "x" not in node_data or "y" not in node_data:
        return None

    node_point = Point(node_data["x"], node_data["y"])

    for _, hole_row in holes_gdf.iterrows():
        if hole_row["geometry"].contains(node_point):
            return int(hole_row["hole"])
    
    return None
