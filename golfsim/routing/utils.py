from __future__ import annotations

from pathlib import Path
import pickle

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
    holes_gdf = gpd.read_file(geojson_path, engine="pyogrio")

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
