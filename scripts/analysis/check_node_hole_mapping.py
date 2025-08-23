from __future__ import annotations

import argparse
import pickle
from pathlib import Path

import geopandas as gpd
import networkx as nx
from shapely.geometry import Point


def main(
    course_dir: str = "courses/pinetree_country_club",
    nodes: list[int] | None = None,
) -> int:
    """
    Checks which hole polygon a given graph node is in.
    """
    if nodes is None:
        nodes = []
    
    # Load cart graph
    pkl_path = Path(course_dir) / "pkl" / "cart_graph.pkl"
    if not pkl_path.exists():
        print(f"ERROR: Missing graph: {pkl_path}")
        return 1
    with pkl_path.open("rb") as f:
        G: nx.Graph = pickle.load(f)

    # Load geofenced holes
    geojson_path = (
        Path(course_dir) / "geojson" / "generated" / "holes_geofenced.geojson"
    )
    if not geojson_path.exists():
        print(f"ERROR: Missing geofenced holes file: {geojson_path}")
        return 1
    holes_gdf = gpd.read_file(geojson_path, engine="pyogrio")

    print(f"Checking hole mapping for nodes: {nodes}...")

    # For each node, find the containing hole
    for node_id in nodes:
        if not G.has_node(node_id):
            print(f"Node {node_id} not found in the graph.")
            continue

        node_data = G.nodes[node_id]
        if "x" not in node_data or "y" not in node_data:
            print(f"Node {node_id} does not have coordinate attributes (x, y).")
            continue

        # Create a Shapely Point from the node's coordinates
        # Note: GeoJSON uses (longitude, latitude) which corresponds to (x, y)
        node_point = Point(node_data["x"], node_data["y"])

        found_hole = False
        for _, hole_row in holes_gdf.iterrows():
            if hole_row["geometry"].contains(node_point):
                print(
                    f"✓ Node {node_id} (coords: ({node_data['x']:.6f}, {node_data['y']:.6f})) is on Hole {hole_row['hole']}"
                )
                found_hole = True
                break
        
        if not found_hole:
            print(f"✗ Node {node_id} could not be mapped to any hole.")

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Check which hole a graph node belongs to."
    )
    parser.add_argument(
        "--course-dir",
        type=str,
        default="courses/pinetree_country_club",
        help="Path to the course directory.",
    )
    parser.add_argument(
        "nodes",
        metavar="N",
        type=int,
        nargs="+",
        help="Node ID(s) to check.",
    )
    args = parser.parse_args()
    
    raise SystemExit(main(course_dir=args.course_dir, nodes=args.nodes))
