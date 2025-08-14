#!/usr/bin/env python3
"""
Connect two 9-hole loops into one connected loop network graph and
ensure all cart paths near the clubhouse are connected to the clubhouse.

Behavior:
- Loads cart path LineStrings from cart_paths.geojson and builds a NetworkX graph
  using each LineString's vertices as nodes and segments as edges (no auto-noding).
- Reads clubhouse coordinates from config/simulation_config.json.
- Adds a clubhouse node and connects all nearby cart-path nodes within a radius.
- Saves the connected graph (PKL) and a GeoJSON with added clubhouse connection segments.

This script is non-interactive and uses project logging.
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
from pathlib import Path
from typing import List, Tuple

import geopandas as gpd
import pandas as pd
import networkx as nx
from shapely.geometry import LineString, Point

from golfsim.logging import init_logging, get_logger
from golfsim.data.osm_ingest import build_cartpath_graph
from utils.cli import add_course_dir_argument, add_log_level_argument


logger = get_logger(__name__)


DEGREE_TO_METERS = 111_139.0


def _load_simulation_config(course_dir: Path) -> dict:
    config_path = course_dir / "config" / "simulation_config.json"
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_course_polygon(course_dir: Path):
    poly_path = course_dir / "geojson" / "course_polygon.geojson"
    gdf = gpd.read_file(poly_path).to_crs(4326)
    return gdf.geometry.iloc[0]


def _add_clubhouse_node(G: nx.Graph, lon: float, lat: float):
    node_id = (round(lon, 7), round(lat, 7))
    if node_id not in G:
        G.add_node(node_id, x=lon, y=lat, is_clubhouse=True)
    else:
        # Ensure attribute present
        G.nodes[node_id]["is_clubhouse"] = True
    return node_id


def _meters_between(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1 = Point(lon1, lat1)
    p2 = Point(lon2, lat2)
    return p1.distance(p2) * DEGREE_TO_METERS


def _nodes_within_radius(
    G: nx.Graph, center_lon: float, center_lat: float, radius_m: float
) -> List[Tuple[float, float]]:
    matches: List[Tuple[float, float]] = []
    for node in G.nodes():
        data = G.nodes[node]
        x = data.get("x")
        y = data.get("y")
        if x is None or y is None:
            continue
        dist_m = _meters_between(center_lon, center_lat, x, y)
        if dist_m <= radius_m:
            matches.append(node)
    return matches


def _connect_clubhouse(
    G: nx.Graph, clubhouse_node, nearby_nodes: List, clubhouse_lon: float, clubhouse_lat: float
) -> int:
    added = 0
    for node in nearby_nodes:
        # Skip if already identical
        if node == clubhouse_node:
            continue
        nx_data = G.nodes[node]
        length_m = _meters_between(clubhouse_lon, clubhouse_lat, nx_data["x"], nx_data["y"])
        G.add_edge(clubhouse_node, node, length=length_m, clubhouse_connection=True)
        added += 1
    return added


def _save_graph(G: nx.Graph, pkl_path: Path) -> None:
    pkl_path.parent.mkdir(parents=True, exist_ok=True)
    with open(pkl_path, "wb") as f:
        pickle.dump(G, f)


def _save_geojson_with_connections(
    cart_paths_path: Path,
    connections: List[Tuple[Tuple[float, float], Tuple[float, float]]],
    output_path: Path,
) -> None:
    # Load existing cart paths
    base = gpd.read_file(cart_paths_path).to_crs(4326)
    base = base[base.geometry.type == "LineString"].copy()

    # Create GeoDataFrame for connection segments
    if connections:
        conn_lines = [LineString([Point(a[0], a[1]), Point(b[0], b[1])]) for a, b in connections]
        conn_gdf = gpd.GeoDataFrame(
            {"type": ["clubhouse_connection"] * len(conn_lines)}, geometry=conn_lines, crs="EPSG:4326"
        )
        combined = gpd.GeoDataFrame(pd.concat([base, conn_gdf], ignore_index=True))
    else:
        combined = base

    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_file(output_path, driver="GeoJSON")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Convert two 9-hole loops into one connected graph and connect all paths near the clubhouse."
        )
    )
    add_log_level_argument(parser)
    add_course_dir_argument(parser)
    parser.add_argument(
        "--radius-m",
        type=float,
        default=75.0,
        help="Radius in meters to connect cart-path nodes to the clubhouse (default: 75m)",
    )
    parser.add_argument(
        "--ensure-one",
        action="store_true",
        default=True,
        help="Ensure at least one clubhouse connection by linking the nearest node if none are within radius.",
    )
    parser.add_argument(
        "--save-graph",
        action="store_true",
        default=True,
        help="Save the connected NetworkX graph as PKL in course pkl/ directory.",
    )
    parser.add_argument(
        "--save-geojson",
        action="store_true",
        default=True,
        help="Save a GeoJSON that includes clubhouse connection segments.",
    )

    args = parser.parse_args()
    init_logging(args.log_level)

    course_dir = Path(args.course_dir)
    cart_paths_path = course_dir / "geojson" / "cart_paths.geojson"
    course_poly = _load_course_polygon(course_dir)

    # Load clubhouse coordinates
    sim_cfg = _load_simulation_config(course_dir)
    clubhouse_lat = sim_cfg.get("clubhouse", {}).get("latitude", 0.0)
    clubhouse_lon = sim_cfg.get("clubhouse", {}).get("longitude", 0.0)

    logger.info(
        "Clubhouse from config: lon=%.6f lat=%.6f | radius=%.1fm",
        clubhouse_lon,
        clubhouse_lat,
        args.radius_m,
    )

    # Build graph using only the provided LineStrings (no auto-noding beyond vertices)
    G = build_cartpath_graph(course_poly, cartpath_geojson=str(cart_paths_path))
    logger.info("Initial graph: %d nodes, %d edges, %d component(s)", G.number_of_nodes(), G.number_of_edges(), nx.number_connected_components(G))

    # Add clubhouse node and connect nearby nodes
    clubhouse_node = _add_clubhouse_node(G, clubhouse_lon, clubhouse_lat)
    nearby = _nodes_within_radius(G, clubhouse_lon, clubhouse_lat, args.radius_m)

    # If requested, ensure at least one connection by linking the nearest node
    if not nearby and args.ensure_one and G.number_of_nodes() > 0:
        # Find nearest by metric distance
        best = None
        best_dist = float("inf")
        for node in G.nodes():
            x = G.nodes[node].get("x")
            y = G.nodes[node].get("y")
            if x is None or y is None:
                continue
            d = _meters_between(clubhouse_lon, clubhouse_lat, x, y)
            if d < best_dist:
                best_dist = d
                best = node
        if best is not None:
            nearby = [best]
            logger.warning(
                "No nodes within %.1fm; forcing connection to nearest node at %.1fm",
                args.radius_m,
                best_dist,
            )

    connections_added = _connect_clubhouse(G, clubhouse_node, nearby, clubhouse_lon, clubhouse_lat)
    logger.info("Added %d clubhouse connection edge(s)", connections_added)

    # Report connectivity
    comps_after = nx.number_connected_components(G)
    logger.info("Graph after connections: %d nodes, %d edges, %d component(s)", G.number_of_nodes(), G.number_of_edges(), comps_after)

    # Outputs
    if args.save_graph:
        graph_out = course_dir / "pkl" / "connected_cart_graph.pkl"
        _save_graph(G, graph_out)
        logger.info("Saved connected graph -> %s", graph_out)

    if args.save_geojson:
        # Create lines from clubhouse to each connected node we just added
        connections = []
        for node in nearby:
            if node == clubhouse_node:
                continue
            nx_data = G.nodes[node]
            connections.append(((clubhouse_lon, clubhouse_lat), (nx_data["x"], nx_data["y"])))
        geojson_out = course_dir / "geojson" / "cart_paths_clubhouse_connected.geojson"
        try:
            _save_geojson_with_connections(cart_paths_path, connections, geojson_out)
            logger.info("Saved clubhouse-connected GeoJSON -> %s", geojson_out)
        except Exception as e:
            logger.error("Failed to save GeoJSON with clubhouse connections: %s", e)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())


