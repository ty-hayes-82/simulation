#!/usr/bin/env python3
"""
Build a cart-path network graph strictly from cart_paths.geojson linework.

Key behavior:
- Reads cart path LineStrings/MultiLineStrings and preserves explicit connectivity
  (no auto-connecting across gaps by default).
- Nodes/splits lines at actual geometric intersections so forks and 4-way stops
  become graph junctions.
- Computes edge lengths in meters and stores node coordinates (x=lon, y=lat).
- Optionally saves segmented/noded GeoJSON for debugging and splits/saves the two
  largest loop components separately.

Outputs:
- pkl/cart_graph.pkl (combined network)
- Optionally pkl/cart_graph_loop_A.pkl and pkl/cart_graph_loop_B.pkl for the two
  largest components if --split-loops is enabled.
"""

from __future__ import annotations

import argparse
import json
import pickle
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import geopandas as gpd
import networkx as nx
from shapely.geometry import LineString, MultiLineString, Point
import matplotlib.pyplot as plt

from golfsim.viz.matplotlib_viz import (
    load_course_geospatial_data,
    plot_course_features,
    plot_cart_network,
)
from shapely.ops import snap, unary_union

from golfsim.logging import init_logging


# ----------------------------- Data structures -----------------------------


@dataclass(frozen=True)
class Clubhouse:
    longitude: float
    latitude: float


# ----------------------------- Geometry helpers ----------------------------


def _flatten_lines(geoms: Iterable) -> List[LineString]:
    lines: List[LineString] = []
    for geom in geoms:
        if geom is None:
            continue
        if isinstance(geom, LineString):
            lines.append(geom)
        elif isinstance(geom, MultiLineString):
            lines.extend([part for part in geom.geoms if isinstance(part, LineString)])
    return lines


def _node_linework(seg_src: gpd.GeoDataFrame, snap_tolerance_m: float) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Return (seg_gdf_lonlat, seg_gdf_proj).

    Steps:
    - Project to EPSG:3857 for stable metric operations
    - Snap to union within tolerance to close micro-gaps at intended junctions
    - unary_union to node/split at all intersections
    - Decompose to individual LineStrings
    - Return segments in both 4326 (lon/lat) and 3857 (projected) for length
    """
    if seg_src.empty:
        return seg_src, seg_src

    src_proj = seg_src.to_crs(3857)
    flat = _flatten_lines(src_proj.geometry)
    if not flat:
        return seg_src, src_proj

    union_geom = unary_union(flat)
    snapped = [snap(geom, union_geom, snap_tolerance_m) for geom in flat]
    noded = unary_union(snapped)

    if isinstance(noded, LineString):
        segs_proj = [noded]
    elif isinstance(noded, MultiLineString):
        segs_proj = list(noded.geoms)
    else:
        # Fallback: collect any lineal parts
        segs_proj = []
        try:
            for part in noded.geoms:  # type: ignore[attr-defined]
                if isinstance(part, LineString):
                    segs_proj.append(part)
                elif isinstance(part, MultiLineString):
                    segs_proj.extend(list(part.geoms))
        except Exception:
            segs_proj = []

    segs_proj_gdf = gpd.GeoDataFrame({"segment_id": list(range(len(segs_proj)))}, geometry=segs_proj, crs="EPSG:3857")
    segs_lonlat_gdf = segs_proj_gdf.to_crs(4326)
    return segs_lonlat_gdf, segs_proj_gdf


# ----------------------------- Graph builders ------------------------------


def _add_segment_to_graph(G: nx.Graph, seg_lonlat: LineString, seg_proj: LineString) -> None:
    coords_ll: List[Tuple[float, float]] = list(seg_lonlat.coords)
    coords_xy: List[Tuple[float, float]] = list(seg_proj.coords)
    if len(coords_ll) < 2 or len(coords_xy) != len(coords_ll):
        return
    for i in range(len(coords_ll) - 1):
        lon1, lat1 = coords_ll[i]
        lon2, lat2 = coords_ll[i + 1]
        x1, y1 = coords_xy[i]
        x2, y2 = coords_xy[i + 1]
        node_a = (round(float(lon1), 7), round(float(lat1), 7))
        node_b = (round(float(lon2), 7), round(float(lat2), 7))
        if node_a not in G:
            G.add_node(node_a, x=float(lon1), y=float(lat1))
        if node_b not in G:
            G.add_node(node_b, x=float(lon2), y=float(lat2))
        if not G.has_edge(node_a, node_b):
            length_m = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
            G.add_edge(node_a, node_b, length=float(length_m))


def build_graph_from_segments(segments_lonlat: gpd.GeoDataFrame, segments_proj: gpd.GeoDataFrame) -> nx.Graph:
    G = nx.Graph()
    G.graph["crs"] = "EPSG:4326"

    # Align rows by segment_id
    proj_by_id: Dict[int, LineString] = {}
    if "segment_id" in segments_proj.columns:
        for _, row in segments_proj.iterrows():
            proj_by_id[int(row["segment_id"])] = row.geometry

    for _, row in segments_lonlat.iterrows():
        seg_id = int(row.get("segment_id", -1))
        seg_lonlat = row.geometry
        seg_proj = proj_by_id.get(seg_id, None)
        if not isinstance(seg_lonlat, LineString) or not isinstance(seg_proj, LineString):
            continue
        _add_segment_to_graph(G, seg_lonlat, seg_proj)

    return G


def label_junction_types(G: nx.Graph) -> None:
    for node in G.nodes():
        degree = G.degree(node)
        if degree <= 1:
            jt = "endpoint"
        elif degree == 2:
            jt = "pass_through"
        elif degree == 3:
            jt = "fork"
        elif degree == 4:
            jt = "four_way"
        else:
            jt = "multi_way"
        G.nodes[node]["junction"] = jt


def describe_components(G: nx.Graph, clubhouse: Optional[Clubhouse]) -> List[Dict[str, object]]:
    comps = []
    for idx, comp_nodes in enumerate(sorted(nx.connected_components(G), key=len, reverse=True)):
        comp_nodes_list = list(comp_nodes)
        stats: Dict[str, object] = {
            "component_index": idx,
            "num_nodes": len(comp_nodes_list),
            "num_edges": int(nx.subgraph(G, comp_nodes_list).number_of_edges()),
        }
        if clubhouse is not None and comp_nodes_list:
            # Distance from clubhouse to nearest node in this component (straight-line meters)
            min_d = float("inf")
            for n in comp_nodes_list:
                nd = G.nodes[n]
                d = _haversine_m(clubhouse.longitude, clubhouse.latitude, float(nd["x"]), float(nd["y"]))
                if d < min_d:
                    min_d = d
            stats["nearest_to_clubhouse_m"] = min_d
        comps.append(stats)
    return comps


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    import math
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return 6371000.0 * c


# ----------------------------- IO / Config ---------------------------------


def _load_simulation_config(course_dir: Path) -> Dict:
    cfg_path = course_dir / "config" / "simulation_config.json"
    return json.loads(cfg_path.read_text(encoding="utf-8"))


def _load_clubhouse(course_dir: Path) -> Clubhouse:
    cfg = _load_simulation_config(course_dir)
    lat = float(cfg["clubhouse"]["latitude"])  # type: ignore[index]
    lon = float(cfg["clubhouse"]["longitude"])  # type: ignore[index]
    return Clubhouse(longitude=lon, latitude=lat)


def _load_cart_paths(course_dir: Path) -> gpd.GeoDataFrame:
    geojson_path = course_dir / "geojson" / "cart_paths.geojson"
    gdf = gpd.read_file(geojson_path)
    return gdf.to_crs(4326)


def _ensure_output_dirs(course_dir: Path) -> Tuple[Path, Path]:
    geojson_dir = course_dir / "geojson"
    pkl_dir = course_dir / "pkl"
    geojson_dir.mkdir(parents=True, exist_ok=True)
    pkl_dir.mkdir(parents=True, exist_ok=True)
    return geojson_dir, pkl_dir


# ----------------------------- Main build flow -----------------------------


def connect_clubhouse_to_nearby_endpoints(
    G: nx.Graph,
    clubhouse: Clubhouse,
    radius_m: float = 100.0,
) -> int:
    """Connect the clubhouse node to all endpoint nodes within radius_m.

    Endpoint nodes are nodes with degree == 1. Returns the number of edges added.
    """
    if G is None or G.number_of_nodes() == 0:
        return 0
    clubhouse_node = _ensure_clubhouse_node(G, clubhouse)
    lon_c, lat_c = clubhouse.longitude, clubhouse.latitude
    added = 0
    for node_id, data in G.nodes(data=True):
        if node_id == clubhouse_node:
            continue
        if G.degree(node_id) != 1:
            continue
        x = data.get("x")
        y = data.get("y")
        if x is None or y is None:
            continue
        d = _haversine_m(lon_c, lat_c, float(x), float(y))
        if d <= float(radius_m):
            if not G.has_edge(clubhouse_node, node_id):
                G.add_edge(clubhouse_node, node_id, length=float(d), clubhouse_link=True)
                added += 1
    return added


def _ensure_clubhouse_node(G: nx.Graph, clubhouse: Clubhouse):
    node_id = (round(float(clubhouse.longitude), 7), round(float(clubhouse.latitude), 7))
    if node_id not in G:
        G.add_node(node_id, x=float(clubhouse.longitude), y=float(clubhouse.latitude), kind="clubhouse")
    else:
        G.nodes[node_id]["kind"] = "clubhouse"
    return node_id


def auto_connect_clubhouse_to_components(G: nx.Graph, clubhouse: Clubhouse, max_distance_m: float = 500.0) -> int:
    """Connect the clubhouse to each disconnected component within a distance threshold.

    Adds straight edges from the clubhouse node to the nearest node in each other component,
    using haversine distance as edge length. Returns number of edges added.
    """
    if G.number_of_nodes() == 0:
        return 0
    clubhouse_node = _ensure_clubhouse_node(G, clubhouse)
    components = list(nx.connected_components(G))
    # Identify component that already contains clubhouse (if any)
    clubhouse_comp_index = None
    for idx, comp in enumerate(components):
        if clubhouse_node in comp:
            clubhouse_comp_index = idx
            break
    connections_added = 0
    for idx, comp in enumerate(components):
        if idx == clubhouse_comp_index:
            continue
        # Find nearest node in this component
        best_node = None
        best_dist = float("inf")
        for n in comp:
            nd = G.nodes[n]
            x = nd.get("x")
            y = nd.get("y")
            if x is None or y is None:
                continue
            d = _haversine_m(clubhouse.longitude, clubhouse.latitude, float(x), float(y))
            if d < best_dist:
                best_dist = d
                best_node = n
        if best_node is not None and best_dist <= max_distance_m:
            if not G.has_edge(clubhouse_node, best_node):
                G.add_edge(clubhouse_node, best_node, length=float(best_dist), clubhouse_link=True)
                connections_added += 1
    return connections_added


def build_cart_graph_from_geojson(
    course_dir: Path,
    snap_tolerance_m: float = 1.5,
    save_graph: bool = True,
    save_debug_geojson: bool = False,
    split_loops: bool = True,
    output_name: str = "cart_graph.pkl",
    auto_connect_clubhouse: Optional[bool] = None,
    max_connection_distance_m: Optional[float] = None,
) -> nx.Graph:
    geojson_dir, pkl_dir = _ensure_output_dirs(course_dir)

    clubhouse = _load_clubhouse(course_dir)
    src = _load_cart_paths(course_dir)

    # Keep only LineString/MultiLineString
    src = src[src.geometry.type.isin(["LineString", "MultiLineString"])].copy()
    if src.empty:
        raise RuntimeError("cart_paths.geojson contains no LineString geometry")

    # Node/split at intersections
    seg_lonlat, seg_proj = _node_linework(src, snap_tolerance_m=snap_tolerance_m)

    # Build graph exactly from segments
    G = build_graph_from_segments(seg_lonlat, seg_proj)
    label_junction_types(G)

    # Optionally auto-connect clubhouse to loops/components based on config/params
    cfg = _load_simulation_config(course_dir)
    net_params = cfg.get("network_params", {}) if isinstance(cfg, dict) else {}
    ac_enabled = auto_connect_clubhouse
    if ac_enabled is None:
        ac_enabled = bool(net_params.get("auto_connect_clubhouse", True))
    max_conn_m = max_connection_distance_m
    if max_conn_m is None:
        try:
            max_conn_m = float(net_params.get("max_connection_distance_m", 500.0))
        except Exception:
            max_conn_m = 500.0
    if ac_enabled:
        added = auto_connect_clubhouse_to_components(G, clubhouse, max_distance_m=float(max_conn_m))
        if added:
            print(f"Auto-connected clubhouse to {added} component(s) (<= {float(max_conn_m):.0f} m)")

    # Additionally connect clubhouse to all nearby endpoints to ensure multi-way junction
    try:
        endpoint_radius_m = float(net_params.get("connect_endpoints_to_clubhouse_m", 100.0))
    except Exception:
        endpoint_radius_m = 100.0
    added_eps = connect_clubhouse_to_nearby_endpoints(G, clubhouse, radius_m=endpoint_radius_m)
    if added_eps:
        print(f"Connected clubhouse to {added_eps} nearby endpoint(s) (<= {endpoint_radius_m:.0f} m)")

    # Re-label junctions after any new links
    label_junction_types(G)

    # Save debug noded linework if requested
    if save_debug_geojson:
        out_geojson = geojson_dir / "cart_paths_noded.geojson"
        seg_lonlat.to_file(out_geojson, driver="GeoJSON")

    # Save combined graph
    if save_graph:
        out_pkl = pkl_dir / output_name
        with out_pkl.open("wb") as f:
            pickle.dump(G, f)

    # Optionally split into two largest loop components and save
    if split_loops:
        components = sorted(nx.connected_components(G), key=len, reverse=True)
        if len(components) >= 2:
            compA_nodes = list(components[0])
            compB_nodes = list(components[1])
            GA = nx.subgraph(G, compA_nodes).copy()
            GB = nx.subgraph(G, compB_nodes).copy()
            # Persist with loop labels for clarity
            GA.graph["loop_label"] = "loop_A"
            GB.graph["loop_label"] = "loop_B"
            with (pkl_dir / "cart_graph_loop_A.pkl").open("wb") as fA:
                pickle.dump(GA, fA)
            with (pkl_dir / "cart_graph_loop_B.pkl").open("wb") as fB:
                pickle.dump(GB, fB)

    # Brief build report (print only; logs are kept simple text per project rules)
    comps = describe_components(G, clubhouse)
    total_nodes = G.number_of_nodes()
    total_edges = G.number_of_edges()
    fork_nodes = sum(1 for n in G.nodes if G.nodes[n].get("junction") == "fork")
    four_way_nodes = sum(1 for n in G.nodes if G.nodes[n].get("junction") == "four_way")
    print(f"Built cart graph: {total_nodes} nodes, {total_edges} edges")
    print(f"Junctions: forks={fork_nodes}, four_way={four_way_nodes}")
    print(f"Components: {len(comps)}")
    for c in comps[:4]:
        near = c.get("nearest_to_clubhouse_m")
        near_str = f", nearest_to_clubhouse_m={near:.1f}" if isinstance(near, float) else ""
        print(f"  - comp {c['component_index']}: nodes={c['num_nodes']}, edges={c['num_edges']}{near_str}")

    return G


def render_cart_graph_png(course_dir: Path, cart_graph: nx.Graph, save_path: Path) -> None:
    course_data = load_course_geospatial_data(course_dir)
    fig, ax = plt.subplots(1, 1, figsize=(16, 12))
    plot_course_features(ax, course_data)
    plot_cart_network(ax, cart_graph, alpha=0.6, color='steelblue')
    ax.set_title(f"{course_dir.name.replace('_', ' ').title()} - Cart Path Network")
    save_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(save_path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def main() -> int:
    init_logging()
    parser = argparse.ArgumentParser(description="Build cart-path network from cart_paths.geojson")
    parser.add_argument("course_dir", nargs="?", default="courses/pinetree_country_club", help="Course directory")
    parser.add_argument("--snap-tol-m", type=float, default=1.5, help="Snap tolerance in meters for noding/splitting")
    parser.add_argument("--save-graph", action="store_true", default=True, help="Save combined graph pickle")
    parser.add_argument("--debug-geojson", action="store_true", default=False, help="Save noded/segmented GeoJSON for inspection")
    parser.add_argument("--split-loops", action="store_true", default=True, help="Save two largest components as loop A/B")
    parser.add_argument("--output-name", type=str, default="cart_graph.pkl", help="Output pickle filename for combined graph")
    parser.add_argument("--save-png", type=str, default=None, help="Optional path to save PNG visualization (e.g., outputs/cart_network.png)")

    args = parser.parse_args()
    course_path = Path(args.course_dir)
    try:
        G = build_cart_graph_from_geojson(
            course_dir=course_path,
            snap_tolerance_m=args.snap_tol_m,
            save_graph=args.save_graph,
            save_debug_geojson=args.debug_geojson,
            split_loops=args.split_loops,
            output_name=args.output_name,
        )
        if args.save_png:
            out_png = Path(args.save_png)
            # If relative, place under course_dir by default
            if not out_png.is_absolute():
                out_png = course_path / out_png
            render_cart_graph_png(course_path, G, out_png)
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


