#!/usr/bin/env python3
"""
Build a cart network graph from holes_connected.geojson or holes_connected_updated.geojson.

This script loads the GeoJSON file containing nodes and connections, builds a NetworkX graph,
and saves it as a pickle file for use in simulations.

Node 0 is assumed to be the clubhouse where all deliveries start from.
"""

from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
from typing import Dict, List, Tuple

import geopandas as gpd
import networkx as nx

from golfsim.logging import init_logging


# ----------------------------- Helpers -------------------------------------


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Calculate haversine distance in meters between two lat/lon points."""
    import math
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return 6371000.0 * c


def _ensure_output_dirs(course_dir: Path) -> Path:
    """Ensure pkl directory exists."""
    pkl_dir = course_dir / "pkl"
    pkl_dir.mkdir(parents=True, exist_ok=True)
    return pkl_dir


def _load_holes_connected_data(course_dir: Path) -> Tuple[List[Tuple[int, float, float]], List[Tuple[int, int]]]:
    """Load nodes and connections from holes_connected GeoJSON files.
    
    Returns:
        Tuple of (nodes, connections) where:
        - nodes: List of (node_id, lon, lat)
        - connections: List of (node_a, node_b) pairs extracted from LineString features
    """
    # Try updated file first, then fall back to original
    updated_path = course_dir / "geojson" / "generated" / "holes_connected_updated.geojson"
    original_path = course_dir / "geojson" / "generated" / "holes_connected.geojson"
    
    if updated_path.exists():
        path = updated_path
        print(f"Using updated file: {path}")
    elif original_path.exists():
        path = original_path
        print(f"Using original file: {path}")
    else:
        raise FileNotFoundError(f"Neither {updated_path} nor {original_path} exists")
    
    # Load as JSON first to handle the format better
    try:
        with open(path, 'r', encoding='utf-8') as f:
            geojson_data = json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse GeoJSON file {path}: {e}")
    
    nodes: List[Tuple[int, float, float]] = []
    node_coords = {}  # Map node_id to (lon, lat) for connection matching
    connections: List[Tuple[int, int]] = []
    
    # First pass: collect all nodes
    for feature in geojson_data.get("features", []):
        if (feature.get("geometry", {}).get("type") == "Point" and 
            "node_id" in feature.get("properties", {})):
            
            try:
                props = feature["properties"]
                node_id = int(props["node_id"])
                coords = feature["geometry"]["coordinates"]
                lon, lat = float(coords[0]), float(coords[1])
                nodes.append((node_id, lon, lat))
                node_coords[node_id] = (lon, lat)
            except (ValueError, TypeError, KeyError) as e:
                print(f"Warning: Skipping invalid node feature: {e}")
                continue
    
    # Second pass: extract connections from LineString features
    for feature in geojson_data.get("features", []):
        if (feature.get("geometry", {}).get("type") == "LineString" and
            feature.get("properties", {}).get("feature_type") == "connection"):
            
            try:
                coords = feature["geometry"]["coordinates"]
                if len(coords) >= 2:  # Handle both 2-point and multi-point lines
                    tolerance = 1e-5  # Tolerance for coordinate matching
                    
                    # Find all nodes that match coordinates in this LineString
                    matched_nodes = []
                    for i, coord in enumerate(coords):
                        coord_lon, coord_lat = float(coord[0]), float(coord[1])
                        
                        for node_id, (node_lon, node_lat) in node_coords.items():
                            if (abs(node_lon - coord_lon) < tolerance and 
                                abs(node_lat - coord_lat) < tolerance):
                                matched_nodes.append((i, node_id))
                                break
                    
                    # Create connections between consecutive matched nodes
                    for i in range(len(matched_nodes) - 1):
                        _, node_a = matched_nodes[i]
                        _, node_b = matched_nodes[i + 1]
                        
                        if node_a != node_b:
                            # Add connection (avoid duplicates by ensuring node_a < node_b)
                            if node_a < node_b:
                                connections.append((node_a, node_b))
                            else:
                                connections.append((node_b, node_a))
                    
                    # Warn if we couldn't match all coordinates
                    if len(matched_nodes) != len(coords):
                        unmatched = len(coords) - len(matched_nodes)
                        print(f"Warning: Could not match {unmatched}/{len(coords)} coordinates in LineString")
                        
            except (ValueError, TypeError, KeyError, IndexError) as e:
                print(f"Warning: Skipping invalid LineString feature: {e}")
                continue
    
    # Remove duplicate connections
    connections = list(set(connections))
    
    nodes.sort(key=lambda t: t[0])
    print(f"Loaded {len(nodes)} nodes and {len(connections)} connections from LineStrings")
    return nodes, connections


def build_graph_from_holes_connected(course_dir: Path) -> nx.Graph:
    """Build a cart network graph from holes_connected GeoJSON files."""
    pkl_dir = _ensure_output_dirs(course_dir)
    
    # Load nodes and connections from GeoJSON
    nodes, connections = _load_holes_connected_data(course_dir)
    
    if not nodes:
        raise RuntimeError("No nodes found in holes_connected GeoJSON files")
    
    # Create NetworkX graph
    G = nx.Graph()
    G.graph["crs"] = "EPSG:4326"
    
    # Add nodes
    for node_id, lon, lat in nodes:
        G.add_node(node_id, x=float(lon), y=float(lat))
        # Mark node 0 as clubhouse
        if node_id == 0:
            G.nodes[node_id]["kind"] = "clubhouse"
    
    # Add edges based on connections
    for node_a, node_b in connections:
        if node_a in G and node_b in G:
            # Calculate distance
            lon_a = G.nodes[node_a]["x"]
            lat_a = G.nodes[node_a]["y"]
            lon_b = G.nodes[node_b]["x"]
            lat_b = G.nodes[node_b]["y"]
            distance = _haversine_m(lon_a, lat_a, lon_b, lat_b)
            G.add_edge(node_a, node_b, length=float(distance))
        else:
            print(f"Warning: Skipping connection {node_a}-{node_b}, nodes not found in graph")
    
    # Save as pickle file
    pkl_path = pkl_dir / "cart_graph.pkl"
    with open(pkl_path, "wb") as f:
        pickle.dump(G, f)
    
    # Report
    total_nodes = G.number_of_nodes()
    total_edges = G.number_of_edges()
    clubhouse_node = 0 if 0 in G else None
    print(f"Built cart network graph: {total_nodes} nodes, {total_edges} edges")
    print(f"Clubhouse node: {clubhouse_node}")
    print(f"Saved to: {pkl_path}")
    
    return G


# ----------------------------- CLI -----------------------------------------


def main() -> int:
    """Main entry point for the script."""
    init_logging()
    parser = argparse.ArgumentParser(
        description="Build cart network graph from holes_connected GeoJSON files and save as pickle"
    )
    parser.add_argument(
        "course_dir", 
        nargs="?", 
        default="courses/pinetree_country_club", 
        help="Course directory containing geojson/generated/ folder"
    )
    
    args = parser.parse_args()
    course_path = Path(args.course_dir)
    
    try:
        G = build_graph_from_holes_connected(course_path)
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
