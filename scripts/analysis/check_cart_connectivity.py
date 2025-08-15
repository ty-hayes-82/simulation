#!/usr/bin/env python3
from __future__ import annotations

import argparse
import pickle
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple
from datetime import datetime

import networkx as nx


def _nearest_node_simple(G: nx.Graph, lon: float, lat: float):
    """Return nearest node by simple Euclidean distance over 'x','y' attributes."""
    if G is None or G.number_of_nodes() == 0:
        return None
    best = None
    best_d = float("inf")
    for node_id, data in G.nodes(data=True):
        x = data.get("x")
        y = data.get("y")
        if x is None or y is None:
            continue
        dx = float(x) - float(lon)
        dy = float(y) - float(lat)
        d2 = dx * dx + dy * dy
        if d2 < best_d:
            best_d = d2
            best = node_id
    return best


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Compute great-circle distance in meters between two lon/lat points."""
    from math import atan2, cos, radians, sin, sqrt

    R = 6371000.0  # meters
    dlon = radians(lon2 - lon1)
    dlat = radians(lat2 - lat1)
    a = (
        sin(dlat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    )
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


def find_clubhouse_node(G: nx.Graph, clubhouse: Tuple[float, float]):
    """Prefer explicit clubhouse node if present; otherwise nearest node."""
    # Look for a node tagged as the clubhouse
    for node_id, data in G.nodes(data=True):
        if data.get("kind") == "clubhouse":
            return node_id
    # Fallback to nearest
    lon, lat = clubhouse
    return _nearest_node_simple(G, lon, lat)


def describe_components(
    G: nx.Graph, clubhouse_node, clubhouse: Tuple[float, float]
) -> Dict[str, object]:
    components: Iterable[set] = nx.connected_components(G)
    comp_list = [set(comp) for comp in components]

    total_nodes = G.number_of_nodes()
    total_edges = G.number_of_edges()

    # Identify which component contains the clubhouse
    clubhouse_comp_index: Optional[int] = None
    for idx, comp in enumerate(comp_list):
        if clubhouse_node in comp:
            clubhouse_comp_index = idx
            break

    result: Dict[str, object] = {
        "total_nodes": total_nodes,
        "total_edges": total_edges,
        "num_components": len(comp_list),
        "clubhouse_component_index": clubhouse_comp_index,
        "clubhouse_component_size": 0,
        "all_nodes_reachable_from_clubhouse": False,
        "other_components": [],  # list of dicts with size and nearest distance to clubhouse
    }

    if clubhouse_comp_index is None:
        return result

    clubhouse_comp = comp_list[clubhouse_comp_index]
    result["clubhouse_component_size"] = len(clubhouse_comp)
    result["all_nodes_reachable_from_clubhouse"] = len(clubhouse_comp) == total_nodes

    # For each other component, compute nearest distance to clubhouse
    lon_c, lat_c = clubhouse
    other_components = []
    for idx, comp in enumerate(comp_list):
        if idx == clubhouse_comp_index:
            continue
        best_d = float("inf")
        best_node = None
        for node in comp:
            nd = G.nodes[node]
            x = float(nd.get("x"))
            y = float(nd.get("y"))
            d = haversine_m(lon_c, lat_c, x, y)
            if d < best_d:
                best_d = d
                best_node = node
        other_components.append(
            {
                "component_index": idx,
                "size": len(comp),
                "nearest_node": best_node,
                "nearest_distance_m": best_d,
            }
        )

    result["other_components"] = sorted(
        other_components, key=lambda x: x["nearest_distance_m"]
    )

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check if all cart-path nodes are connected to the clubhouse"
    )
    parser.add_argument(
        "--course-dir",
        default=str(Path("courses") / "pinetree_country_club"),
        help="Course directory containing config/ and pkl/cart_graph.pkl",
    )
    parser.add_argument(
        "--out-dir",
        default=str(Path("outputs")),
        help="Directory to save outputs (report/PNG)",
    )
    parser.add_argument(
        "--save-report",
        action="store_true",
        help="Save a text report with connectivity details",
    )
    parser.add_argument(
        "--save-png",
        action="store_true",
        help="Save a PNG rendering of the cart network highlighting the clubhouse",
    )
    parser.add_argument(
        "--report-name",
        default=None,
        help="Optional report filename (defaults to timestamped)",
    )
    parser.add_argument(
        "--png-name",
        default=None,
        help="Optional PNG filename (defaults to timestamped)",
    )
    args = parser.parse_args()

    course_dir = Path(args.course_dir)
    out_dir = Path(args.out_dir)
    cart_pkl = course_dir / "pkl" / "cart_graph.pkl"

    if not cart_pkl.exists():
        print(f"ERROR: Cart graph not found: {cart_pkl}")
        return 2

    # Load clubhouse coordinates directly from JSON config
    cfg_path = course_dir / "config" / "simulation_config.json"
    if not cfg_path.exists():
        print(f"ERROR: Config not found: {cfg_path}")
        return 3
    import json
    try:
        data = json.loads(cfg_path.read_text())
        clubhouse_raw = data["clubhouse"]
        clubhouse = (float(clubhouse_raw["longitude"]), float(clubhouse_raw["latitude"]))
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: Failed to load clubhouse from config: {e}")
        return 3

    # Load graph
    try:
        with cart_pkl.open("rb") as f:
            G: nx.Graph = pickle.load(f)
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: Failed to load cart_graph.pkl: {e}")
        return 3

    if G is None or G.number_of_nodes() == 0:
        print("ERROR: Cart graph is empty")
        return 4

    # Identify clubhouse node
    clubhouse_node = find_clubhouse_node(G, clubhouse)
    if clubhouse_node is None:
        print("ERROR: Could not identify a clubhouse node or nearest node in the graph")
        return 5

    stats = describe_components(G, clubhouse_node, clubhouse)
    print(
        f"Graph: {stats['total_nodes']} nodes, {stats['total_edges']} edges, {stats['num_components']} component(s)"
    )

    all_ok = bool(stats["all_nodes_reachable_from_clubhouse"])
    if all_ok:
        print("YES: All cart-path nodes are connected to the clubhouse component.")
        print(
            f"Clubhouse component size: {stats['clubhouse_component_size']} / {stats['total_nodes']} nodes"
        )

    if not all_ok:
        print("NO: Not all cart-path nodes are connected to the clubhouse component.")
        print(
            f"Clubhouse component size: {stats['clubhouse_component_size']} / {stats['total_nodes']} nodes"
        )
        print("Other disconnected components:")
        for comp in stats["other_components"]:
            node_id = comp["nearest_node"]
            d_m = comp["nearest_distance_m"]
            size = comp["size"]
            if node_id is None:
                print(f"  - Component {comp['component_index']}: size={size}, nearest_distance_m=NA")
            else:
                nd = G.nodes[node_id]
                x = nd.get("x")
                y = nd.get("y")
                print(
                    f"  - Component {comp['component_index']}: size={size}, nearest_distance_m={d_m:.1f}, nearest_node=({x:.6f},{y:.6f})"
                )

    # Save requested outputs
    if args.save_report or args.save_png:
        out_dir.mkdir(parents=True, exist_ok=True)

    if args.save_report:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_name = args.report_name or f"cart_connectivity_{course_dir.name}_{ts}.txt"
        report_path = out_dir / report_name
        lines = []
        lines.append(f"Course: {course_dir.name}")
        lines.append(f"Clubhouse: lon={clubhouse[0]:.6f}, lat={clubhouse[1]:.6f}")
        lines.append(
            f"Graph: {stats['total_nodes']} nodes, {stats['total_edges']} edges, {stats['num_components']} component(s)"
        )
        lines.append("Status: " + ("ALL_CONNECTED" if all_ok else "DISCONNECTED_COMPONENTS_PRESENT"))
        lines.append(
            f"Clubhouse component size: {stats['clubhouse_component_size']} / {stats['total_nodes']}"
        )
        if not all_ok:
            lines.append("Other components (nearest distance to clubhouse):")
            for comp in stats["other_components"]:
                node_id = comp["nearest_node"]
                size = comp["size"]
                d_m = comp["nearest_distance_m"]
                if node_id is None:
                    lines.append(f"  - idx={comp['component_index']} size={size} nearest_distance_m=NA")
                else:
                    nd = G.nodes[node_id]
                    x = nd.get("x")
                    y = nd.get("y")
                    lines.append(
                        f"  - idx={comp['component_index']} size={size} nearest_distance_m={d_m:.1f} nearest_node=({x:.6f},{y:.6f})"
                    )
        report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Saved report: {report_path}")

    if args.save_png:
        try:
            import matplotlib.pyplot as plt
        except Exception as e:  # noqa: BLE001
            print(f"ERROR: matplotlib unavailable for PNG output: {e}")
            return 6 if all_ok else 1

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        png_name = args.png_name or f"cart_connectivity_{course_dir.name}_{ts}.png"
        png_path = out_dir / png_name

        fig, ax = plt.subplots(1, 1, figsize=(12, 10))
        for u, v in G.edges():
            ux, uy = float(G.nodes[u]["x"]), float(G.nodes[u]["y"])
            vx, vy = float(G.nodes[v]["x"]), float(G.nodes[v]["y"])
            ax.plot([ux, vx], [uy, vy], color="#c0c0c0", linewidth=0.8, alpha=0.7)
        ax.plot(
            clubhouse[0],
            clubhouse[1],
            marker="o",
            color="#2ca02c",
            markersize=10,
            label="Clubhouse",
        )
        ax.set_aspect("equal", adjustable="box")
        ax.set_title(
            f"Cart Path Connectivity — {course_dir.name}\n"
            + ("All connected" if all_ok else "Disconnected components present"),
            fontsize=12,
        )
        ax.set_xlabel("Longitude")
        ax.set_ylabel("Latitude")
        ax.grid(True, alpha=0.3)
        ax.legend(loc="best")
        fig.tight_layout()
        fig.savefig(png_path, dpi=200)
        plt.close(fig)
        print(f"Saved PNG: {png_path}")

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())


