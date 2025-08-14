import sys
import json
import pickle
import argparse
from pathlib import Path
from typing import List, Tuple
import math

import geopandas as gpd
import pandas as pd
import networkx as nx
from shapely.geometry import Point, LineString, MultiLineString
from shapely.ops import unary_union, snap

from golfsim.data.osm_ingest import build_cartpath_graph
from golfsim.logging import init_logging

def haversine_distance(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    R = 6371000
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

def get_endpoints(gdf: gpd.GeoDataFrame) -> List[Tuple[Tuple[float, float], Tuple[float, float], int]]:
    endpoints = []
    for idx, row in gdf.iterrows():
        if row.geometry.geom_type == 'LineString':
            coords = list(row.geometry.coords)
            start = (coords[0][0], coords[0][1])
            end = (coords[-1][0], coords[-1][1])
            endpoints.append((start, end, idx))
    return endpoints

def bridge_gaps(gdf: gpd.GeoDataFrame, max_gap_m: float = 10.0) -> gpd.GeoDataFrame:
    endpoints = get_endpoints(gdf)
    added = 0
    new_features = []
    
    for i in range(len(endpoints)):
        for j in range(i+1, len(endpoints)):
            start1, end1, idx1 = endpoints[i]
            start2, end2, idx2 = endpoints[j]
            
            # Check all combinations of endpoints
            pairs = [(end1, start2), (end1, end2), (start1, start2), (start1, end2)]
            for p1, p2 in pairs:
                dist = haversine_distance(p1[0], p1[1], p2[0], p2[1])
                if 0 < dist <= max_gap_m:
                    new_line = LineString([p1, p2])
                    new_feature = {
                        'geometry': new_line,
                        'properties': {'type': 'bridge'}
                    }
                    new_features.append(new_feature)
                    added += 1
                    break  # Add only one bridge per pair
    
    if new_features:
        new_gdf = gpd.GeoDataFrame(new_features)
        new_gdf.crs = gdf.crs
        gdf = gpd.GeoDataFrame(pd.concat([gdf, new_gdf], ignore_index=True))
    
    print(f"Added {added} bridge connections")
    return gdf

def segment_cart_paths(gdf: gpd.GeoDataFrame, snap_tolerance_m: float = 1.5) -> gpd.GeoDataFrame:
    """
    Node the input LineStrings so that they are split at all intersections and
    snapped within a small tolerance. Returns a GeoDataFrame of noded segments.

    Steps (in metric CRS for reliable tolerances):
    - Project to EPSG:3857
    - Snap all lines to the union to close small gaps at endpoints
    - Unary union to node linework (split at intersections)
    - Decompose to individual LineStrings and return to EPSG:4326
    """
    if len(gdf) == 0:
        return gdf

    lines = gdf[gdf.geometry.type.isin(["LineString", "MultiLineString"])].copy()
    if len(lines) == 0:
        return gdf

    # Work in meters
    lines_proj = lines.to_crs(3857)

    # Flatten MultiLineStrings for processing
    flattened = []
    for geom in lines_proj.geometry:
        if geom is None:
            continue
        if geom.geom_type == "LineString":
            flattened.append(geom)
        elif geom.geom_type == "MultiLineString":
            flattened.extend(list(geom.geoms))

    if not flattened:
        return gdf

    # Snap geometries to their union within tolerance to close small gaps
    union_geom = unary_union(flattened)
    snapped = [snap(geom, union_geom, snap_tolerance_m) for geom in flattened]

    # Node the linework: unary_union of linework will create noded segments
    noded = unary_union(snapped)

    # Decompose to individual LineStrings
    if isinstance(noded, LineString):
        seg_geoms = [noded]
    elif isinstance(noded, MultiLineString):
        seg_geoms = list(noded.geoms)
    else:
        # Fallback: collect any lineal geometries from a GeometryCollection
        seg_geoms = []
        try:
            for part in noded.geoms:  # type: ignore[attr-defined]
                if isinstance(part, LineString):
                    seg_geoms.append(part)
                elif isinstance(part, MultiLineString):
                    seg_geoms.extend(list(part.geoms))
        except Exception:
            seg_geoms = []

    if not seg_geoms:
        # If noding failed somehow, return original
        return gdf

    seg_gdf = gpd.GeoDataFrame({"segment_id": list(range(len(seg_geoms)))}, geometry=seg_geoms, crs=lines_proj.crs)
    seg_gdf = seg_gdf.to_crs(4326)
    return seg_gdf

def find_open_endpoints(graph: nx.Graph) -> List:
    return [node for node in graph.nodes() if graph.degree(node) == 1]

def connect_endpoint_pairs(graph: nx.Graph, max_distance_m: float = 5.0) -> int:
    """
    Connect only true endpoints (degree==1) across small gaps, respecting geometry.
    Returns number of edges added.
    """
    endpoints = find_open_endpoints(graph)
    if not endpoints:
        return 0

    added = 0
    used = set()
    for i in range(len(endpoints)):
        n1 = endpoints[i]
        if n1 in used:
            continue
        x1, y1 = graph.nodes[n1]['x'], graph.nodes[n1]['y']
        best = None
        best_dist = float('inf')
        for j in range(i + 1, len(endpoints)):
            n2 = endpoints[j]
            if n2 in used:
                continue
            # Only bridge if in different components
            if nx.has_path(graph, n1, n2):
                continue
            x2, y2 = graph.nodes[n2]['x'], graph.nodes[n2]['y']
            dist = haversine_distance(x1, y1, x2, y2)
            if dist < best_dist:
                best_dist = dist
                best = n2
        if best is not None and best_dist <= max_distance_m:
            graph.add_edge(n1, best, length=best_dist, bridge=True)
            used.add(n1)
            used.add(best)
            added += 1
    if added > 0:
        print(f"Connected {added} endpoint pair(s) within {max_distance_m} m")
    return added

def handle_forks_and_intersections(graph: nx.Graph):
    """
    Deprecated: keep original fork geometry. This function is retained for
    backward compatibility but does nothing now.
    """
    return

def build_perfect_cart_network(
    course_dir: Path,
    max_gap_m: float = 10.0,
    save_graph: bool = True,
    save_modified_geojson: bool = False,
    snap_tolerance_m: float = 1.5,
    save_segmented_geojson: bool = True,
) -> nx.Graph:
    geojson_dir = course_dir / "geojson"
    pkl_dir = course_dir / "pkl"
    
    # Load GeoJSON directly
    geojson_path = geojson_dir / "cart_paths.geojson"
    gdf = gpd.read_file(geojson_path).to_crs(4326)
    print(f"Loaded GeoJSON with {len(gdf)} features")

    # Node/split into smaller segments for reliable connectivity
    seg_gdf = segment_cart_paths(gdf, snap_tolerance_m=snap_tolerance_m)
    print(f"Segmented into {len(seg_gdf)} noded segments (snap tol {snap_tolerance_m}m)")

    # Bridge small gaps between endpoints (optional, keeps geometry explicit)
    if max_gap_m and max_gap_m > 0:
        seg_gdf = bridge_gaps(seg_gdf, max_gap_m)

    build_path = None
    if save_segmented_geojson:
        segmented_path = geojson_dir / "cart_paths_connected.geojson"
        seg_gdf.to_file(segmented_path, driver='GeoJSON')
        print(f"Saved segmented+bridged GeoJSON to {segmented_path}")
        build_path = str(segmented_path)
    elif save_modified_geojson:
        modified_path = geojson_dir / "cart_paths_bridged.geojson"
        seg_gdf.to_file(modified_path, driver='GeoJSON')
        print(f"Saved modified GeoJSON to {modified_path}")
        build_path = str(modified_path)
    else:
        # Fallback to original
        build_path = str(geojson_path)
    
    course_poly_gdf = gpd.read_file(geojson_dir / "course_polygon.geojson").to_crs(4326)
    course_polygon = course_poly_gdf.geometry.iloc[0]
    
    cart_graph = build_cartpath_graph(course_polygon, build_path)

    # Connect only true endpoints across small gaps; avoid arbitrary cross-links
    connect_endpoint_pairs(cart_graph, max_distance_m=max_gap_m)
    
    if save_graph:
        output_path = pkl_dir / "perfect_cart_graph.pkl"
        with open(output_path, 'wb') as f:
            pickle.dump(cart_graph, f)
        print(f"Saved perfect graph to {output_path}")
    
    return cart_graph

def main():
    init_logging()
    parser = argparse.ArgumentParser(description="Build perfect cart path network")
    parser.add_argument("course_dir", nargs="?", default="courses/pinetree_country_club")
    parser.add_argument("--max-gap", type=float, default=10.0, help="Max distance (m) for bridging gaps")
    parser.add_argument("--save-graph", action="store_true", default=True)
    parser.add_argument("--save-geojson", action="store_true", default=False, help="(Deprecated) Save modified GeoJSON")
    parser.add_argument("--snap-tol", type=float, default=1.5, help="Snap tolerance in meters for noding/splitting")
    parser.add_argument("--save-segmented", action="store_true", default=True, help="Save segmented+bridged GeoJSON for debugging")
    
    args = parser.parse_args()
    course_path = Path(args.course_dir)
    build_perfect_cart_network(
        course_path,
        args.max_gap,
        args.save_graph,
        args.save_geojson,
        snap_tolerance_m=args.snap_tol,
        save_segmented_geojson=args.save_segmented,
    )

if __name__ == "__main__":
    main()
