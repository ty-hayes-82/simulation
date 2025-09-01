from __future__ import annotations

import csv
import pickle
from pathlib import Path
from typing import Dict, List, Tuple

import networkx as nx
import pytest

from golfsim.config.loaders import load_simulation_config
from golfsim.simulation.orchestration import run_delivery_runner_simulation


REPO_ROOT = Path(__file__).resolve().parents[1]
COURSE_DIR = REPO_ROOT / "courses" / "pinetree_country_club"


def _meters_distance_point_to_segment(px: float, py: float, x0: float, y0: float, x1: float, y1: float) -> float:
    # Convert lon/lat degrees to meters using a constant scale (sufficient for small extents)
    def to_m(x: float, y: float) -> Tuple[float, float]:
        return (x * 111_139.0, y * 111_139.0)

    pxm, pym = to_m(px, py)
    x0m, y0m = to_m(x0, y0)
    x1m, y1m = to_m(x1, y1)

    vx = x1m - x0m
    vy = y1m - y0m
    wx = pxm - x0m
    wy = pym - y0m

    seg_len2 = vx * vx + vy * vy
    if seg_len2 <= 0.0:
        # Degenerate segment: distance to start point
        dx = pxm - x0m
        dy = pym - y0m
        return (dx * dx + dy * dy) ** 0.5

    t = max(0.0, min(1.0, (wx * vx + wy * vy) / seg_len2))
    projx = x0m + t * vx
    projy = y0m + t * vy
    dx = pxm - projx
    dy = pym - projy
    return (dx * dx + dy * dy) ** 0.5


def _nearest_node_id(G: nx.Graph, lon: float, lat: float) -> Tuple[object, float]:
    best_id = None
    best_d = None
    for nid in G.nodes:
        try:
            x = float(G.nodes[nid]["x"])  # lon
            y = float(G.nodes[nid]["y"])  # lat
        except Exception:
            continue
        d = _meters_distance_point_to_segment(lon, lat, x, y, x, y)
        if best_d is None or d < best_d:
            best_d = d
            best_id = nid
    return best_id, float(best_d or 0.0)


def _load_cart_graph(course_dir: Path) -> nx.Graph:
    pkl_path = course_dir / "pkl" / "cart_graph.pkl"
    with pkl_path.open("rb") as f:
        G: nx.Graph = pickle.load(f)
    return G


@pytest.mark.slow
def test_delivery_pair_alignment_and_runner_points_on_graph(tmp_path: Path):
    # 1) Run a tiny delivery-runner simulation to produce outputs
    cfg = load_simulation_config(str(COURSE_DIR))
    # Ensure required runtime attributes when loaded from JSON-only config
    cfg.course_dir = str(COURSE_DIR)
    try:
        from golfsim.config.models import SpeedSettings  # type: ignore
        if isinstance(getattr(cfg, "speeds", None), dict):
            cfg.speeds = SpeedSettings(**cfg.speeds)  # type: ignore[arg-type]
    except Exception:
        pass
    cfg.output_dir = tmp_path / "test_coords_alignment"
    cfg.num_runs = 1
    cfg.groups_count = 1
    cfg.num_runners = 1
    cfg.minimal_outputs = False
    cfg.delivery_total_orders = 1
    cfg.no_heatmap = True  # speed

    result = run_delivery_runner_simulation(cfg)
    assert isinstance(result, dict)

    run_dir = cfg.output_dir / "run_01"
    coords_csv = run_dir / "coordinates.csv"
    filtered_csv = run_dir / "coordinates_delivery_points.csv"

    assert coords_csv.exists(), "coordinates.csv not found"
    assert filtered_csv.exists(), "coordinates_delivery_points.csv not found"

    # 2) Validate pair alignment: exactly 2 flagged rows per order, same ts and lat/lon
    by_order: Dict[str, List[Dict[str, str]]] = {}
    with filtered_csv.open("r", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            if str(row.get("is_delivery_event", "")).lower() in ("true", "1", "yes"):
                oid = str(row.get("order_id", ""))
                by_order.setdefault(oid, []).append(row)

    # At least one order flagged
    assert by_order, "No flagged delivery rows found"
    for oid, rows in by_order.items():
        assert len(rows) == 2, f"Order {oid} should have exactly 2 flagged rows (golfer and runner)"
        ts_vals = {r.get("timestamp") for r in rows}
        assert len(ts_vals) == 1, f"Order {oid} flagged rows must share identical timestamp"
        ll_vals = {(r.get("latitude"), r.get("longitude")) for r in rows}
        assert len(ll_vals) == 1, f"Order {oid} flagged rows must share identical lat/lon"
        types = {str(r.get("type", "")) for r in rows}
        assert {"golfer", "runner"}.issubset(types), f"Order {oid} must include both golfer and runner rows"

    # 3) Validate all runner points lie on graph nodes or along edges (within tolerance)
    G = _load_cart_graph(COURSE_DIR)
    tol_m = 3.0

    with coords_csv.open("r", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            if str(row.get("type", "")).lower() != "runner":
                continue
            try:
                lat = float(row.get("latitude", 0.0))
                lon = float(row.get("longitude", 0.0))
            except Exception:
                pytest.fail("Runner coordinate missing or invalid lat/lon")

            # Check nearest node proximity or proximity to an incident edge
            nid, d_node = _nearest_node_id(G, lon, lat)
            assert nid is not None, "Nearest node not found"
            if d_node <= tol_m:
                continue

            # Check distance to any edge incident to nearest node
            x0 = float(G.nodes[nid]["x"])
            y0 = float(G.nodes[nid]["y"])
            best_edge_d = None
            for nbr in G.neighbors(nid):
                try:
                    x1 = float(G.nodes[nbr]["x"])  # lon
                    y1 = float(G.nodes[nbr]["y"])  # lat
                except Exception:
                    continue
                d_seg = _meters_distance_point_to_segment(lon, lat, x0, y0, x1, y1)
                best_edge_d = d_seg if best_edge_d is None or d_seg < best_edge_d else best_edge_d

            assert best_edge_d is not None and best_edge_d <= tol_m, (
                f"Runner point not on graph within {tol_m}m (min node dist={d_node:.2f}m, min incident edge dist={best_edge_d or 1e9:.2f}m)"
            )


