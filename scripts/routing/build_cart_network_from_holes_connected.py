#!/usr/bin/env python3
"""
Build a simplified cart network graph from generated/holes_connected.geojson.

This builder uses the pre-connected holes path (indexed points) as the base
loop and optionally adds a small set of hard-coded shortcuts by point index.

Outputs:
- pkl/cart_graph.pkl (default)
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
from shapely.geometry import Point
import matplotlib.pyplot as plt

from golfsim.viz.matplotlib_viz import (
    load_course_geospatial_data,
    plot_course_features,
    plot_cart_network,
)

from golfsim.logging import init_logging


# ----------------------------- Data structures -----------------------------


@dataclass(frozen=True)
class Clubhouse:
    longitude: float
    latitude: float


# ----------------------------- Helpers -------------------------------------


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    import math
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return 6371000.0 * c


def _load_simulation_config(course_dir: Path) -> Dict:
    cfg_path = course_dir / "config" / "simulation_config.json"
    return json.loads(cfg_path.read_text(encoding="utf-8"))


def _load_clubhouse(course_dir: Path) -> Clubhouse:
    cfg = _load_simulation_config(course_dir)
    lat = float(cfg["clubhouse"]["latitude"])  # type: ignore[index]
    lon = float(cfg["clubhouse"]["longitude"])  # type: ignore[index]
    return Clubhouse(longitude=lon, latitude=lat)


def _ensure_output_dirs(course_dir: Path) -> Tuple[Path, Path]:
    geojson_dir = course_dir / "geojson"
    pkl_dir = course_dir / "pkl"
    geojson_dir.mkdir(parents=True, exist_ok=True)
    pkl_dir.mkdir(parents=True, exist_ok=True)
    return geojson_dir, pkl_dir


def _load_holes_connected_points(course_dir: Path) -> List[Tuple[int, float, float]]:
    """Return list of (idx, lon, lat) from generated/holes_connected.geojson Points.

    The file contains a LineString (index path) and a set of Point features with
    an "idx" property that enumerates the sampling along the loop. We build our
    nodes from these indexed Points for stable addressing.
    """
    path = course_dir / "geojson" / "generated" / "holes_connected.geojson"
    gdf = gpd.read_file(path).to_crs(4326)

    pts: List[Tuple[int, float, float]] = []
    for _, row in gdf.iterrows():
        if isinstance(row.geometry, Point) and ("idx" in row):
            idx = int(row["idx"])  # type: ignore[index]
            lon = float(row.geometry.x)
            lat = float(row.geometry.y)
            pts.append((idx, lon, lat))

    if not pts:
        # Fallback: derive from first LineString vertices if points missing
        line_rows = gdf[gdf.geometry.type == "LineString"]
        if not line_rows.empty:
            coords = list(line_rows.iloc[0].geometry.coords)
            pts = [(i, float(lon), float(lat)) for i, (lon, lat) in enumerate(coords)]

    pts.sort(key=lambda t: t[0])
    return pts


def _label_junction_types(G: nx.Graph) -> None:
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


def _ensure_clubhouse_node(G: nx.Graph, clubhouse: Clubhouse):
    node_id = (round(float(clubhouse.longitude), 7), round(float(clubhouse.latitude), 7))
    if node_id not in G:
        G.add_node(node_id, x=float(clubhouse.longitude), y=float(clubhouse.latitude), kind="clubhouse")
    else:
        G.nodes[node_id]["kind"] = "clubhouse"
    return node_id


def _auto_connect_clubhouse(G: nx.Graph, clubhouse: Clubhouse, max_distance_m: float = 500.0) -> int:
    """Connect clubhouse to nearest graph node if within threshold. Returns added edges count (0 or 1)."""
    if G.number_of_nodes() == 0:
        return 0
    clubhouse_node = _ensure_clubhouse_node(G, clubhouse)
    best_node = None
    best_dist = float("inf")
    for n, data in G.nodes(data=True):
        if n == clubhouse_node:
            continue
        x = data.get("x")
        y = data.get("y")
        if x is None or y is None:
            continue
        d = _haversine_m(clubhouse.longitude, clubhouse.latitude, float(x), float(y))
        if d < best_dist:
            best_dist = d
            best_node = n
    if best_node is not None and best_dist <= float(max_distance_m):
        if not G.has_edge(clubhouse_node, best_node):
            G.add_edge(clubhouse_node, best_node, length=float(best_dist), clubhouse_link=True)
            return 1
    return 0


# ----------------------------- Build graph ---------------------------------


def build_graph_from_holes_connected(
    course_dir: Path,
    add_shortcuts: bool = True,
    close_loop: bool = True,
    save_graph: bool = True,
    output_name: str = "cart_graph.pkl",
    save_png: Optional[Path] = None,
    auto_connect_clubhouse: bool = True,
    max_connection_distance_m: float = 500.0,
) -> nx.Graph:
    """Build a simplified cart graph from holes_connected points and optional shortcuts."""
    geojson_dir, pkl_dir = _ensure_output_dirs(course_dir)

    clubhouse = _load_clubhouse(course_dir)
    pts = _load_holes_connected_points(course_dir)
    if not pts:
        raise RuntimeError("holes_connected.geojson contains no usable Points or LineString coordinates")

    # Create base graph nodes by idx
    G = nx.Graph()
    G.graph["crs"] = "EPSG:4326"

    for idx, lon, lat in pts:
        G.add_node(int(idx), x=float(lon), y=float(lat), idx=int(idx))

    # Connect consecutive indices along the loop path
    for i in range(len(pts) - 1):
        idx_a, lon_a, lat_a = pts[i]
        idx_b, lon_b, lat_b = pts[i + 1]
        d = _haversine_m(lon_a, lat_a, lon_b, lat_b)
        if not G.has_edge(idx_a, idx_b):
            G.add_edge(idx_a, idx_b, length=float(d))

    # Close loop if requested: last -> first
    if close_loop and len(pts) >= 2:
        idx_first, lon_f, lat_f = pts[0]
        idx_last, lon_l, lat_l = pts[-1]
        # Only add if distinct indices
        if idx_last != idx_first:
            d = _haversine_m(lon_l, lat_l, lon_f, lat_f)
            if not G.has_edge(idx_last, idx_first):
                G.add_edge(idx_last, idx_first, length=float(d))

    # Add requested shortcut edges by (idx_a, idx_b)
    if add_shortcuts:
        default_shortcuts: List[Tuple[int, int]] = [
            (233, 201),
            (209, 191),
            (40, 65),
            (39, 67),
        ]
        for a, b in default_shortcuts:
            if a in G and b in G:
                ax = float(G.nodes[a]["x"])
                ay = float(G.nodes[a]["y"])
                bx = float(G.nodes[b]["x"])
                by = float(G.nodes[b]["y"])
                d = _haversine_m(ax, ay, bx, by)
                if not G.has_edge(a, b):
                    G.add_edge(a, b, length=float(d), shortcut=True)

    # Label junctions
    _label_junction_types(G)

    # Optionally connect clubhouse to graph
    if auto_connect_clubhouse:
        # allow config override
        cfg = _load_simulation_config(course_dir)
        net_params = cfg.get("network_params", {}) if isinstance(cfg, dict) else {}
        try:
            max_conn_m = float(net_params.get("max_connection_distance_m", max_connection_distance_m))
        except Exception:
            max_conn_m = max_connection_distance_m

        # Always ensure one nearest connection (backward compatible)
        added = _auto_connect_clubhouse(G, clubhouse, max_distance_m=max_conn_m)
        if added:
            print(f"Auto-connected clubhouse to nearest node (<= {float(max_conn_m):.0f} m)")

        # New: Explicitly connect clubhouse to specific indices when requested
        # This supports true multi-way junction at the clubhouse for direct routing
        indices_to_connect: List[int] = []
        try:
            explicit = net_params.get("connect_clubhouse_to_indices")
            if isinstance(explicit, list):
                indices_to_connect = [int(i) for i in explicit if isinstance(i, (int, float, str))]
        except Exception:
            indices_to_connect = []

        # Fallback for Pinetree default: ensure connection to node 120 (after hole 9),
        # and also connect to indices at the clubhouse coordinate (0 and 239) to form a 4-way.
        if not indices_to_connect and course_dir.name == "pinetree_country_club":
            indices_to_connect = [120, 0, 239]

        # Create edges from clubhouse to the requested indices (if present in graph)
        if indices_to_connect:
            # Ensure clubhouse exists as a node
            clubhouse_node = _ensure_clubhouse_node(G, clubhouse)
            for idx in indices_to_connect:
                if idx in G and not G.has_edge(clubhouse_node, idx):
                    try:
                        ax = float(G.nodes[idx]["x"])
                        ay = float(G.nodes[idx]["y"])
                        d = _haversine_m(clubhouse.longitude, clubhouse.latitude, ax, ay)
                        G.add_edge(clubhouse_node, idx, length=float(d), clubhouse_link=True)
                    except Exception:
                        # Best-effort: skip if node lacks coordinates
                        continue

    # Save pickle
    if save_graph:
        out_pkl = pkl_dir / output_name
        with out_pkl.open("wb") as f:
            pickle.dump(G, f)

    # Optional PNG rendering
    if save_png is not None:
        _render_graph_png(course_dir, G, save_png)

    # Brief report
    total_nodes = G.number_of_nodes()
    total_edges = G.number_of_edges()
    forks = sum(1 for n in G.nodes if G.nodes[n].get("junction") == "fork")
    four_way = sum(1 for n in G.nodes if G.nodes[n].get("junction") == "four_way")
    print(f"Built holes-connected graph: {total_nodes} nodes, {total_edges} edges")
    print(f"Junctions: forks={forks}, four_way={four_way}")

    return G


def _render_graph_png(course_dir: Path, cart_graph: nx.Graph, save_path: Path) -> None:
    course_data = load_course_geospatial_data(course_dir)
    fig, ax = plt.subplots(1, 1, figsize=(16, 12))
    plot_course_features(ax, course_data)
    plot_cart_network(ax, cart_graph, alpha=0.6, color='steelblue')
    ax.set_title(f"{course_dir.name.replace('_', ' ').title()} - Holes-Connected Network")
    save_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(save_path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


# ----------------------------- CLI -----------------------------------------


def main() -> int:
    init_logging()
    parser = argparse.ArgumentParser(description="Build simplified network from generated/holes_connected.geojson")
    parser.add_argument("course_dir", nargs="?", default="courses/pinetree_country_club", help="Course directory")
    parser.add_argument("--no-shortcuts", action="store_true", help="Disable adding hard-coded shortcut links")
    parser.add_argument("--no-close-loop", action="store_true", help="Do not add closing edge between last and first index")
    parser.add_argument("--no-clubhouse", action="store_true", help="Do not auto-connect clubhouse to nearest node")
    parser.add_argument("--output-name", type=str, default="cart_graph.pkl", help="Output pickle filename")
    parser.add_argument("--save-png", type=str, default=None, help="Optional path to save PNG visualization (e.g., outputs/cart_network.png)")

    args = parser.parse_args()
    course_path = Path(args.course_dir)
    save_png_path: Optional[Path] = Path(args.save_png) if args.save_png else None
    if save_png_path is not None and not save_png_path.is_absolute():
        save_png_path = course_path / save_png_path

    try:
        build_graph_from_holes_connected(
            course_dir=course_path,
            add_shortcuts=not args.no_shortcuts,
            close_loop=not args.no_close_loop,
            save_graph=True,
            output_name=args.output_name,
            save_png=save_png_path,
            auto_connect_clubhouse=not args.no_clubhouse,
        )
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


