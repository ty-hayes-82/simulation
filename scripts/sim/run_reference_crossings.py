from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Use shared crossings utilities
from golfsim.simulation.crossings import (
    load_nodes_geojson_with_holes,
    load_nodes_geojson,
    load_holes_geojson,
    compute_crossings,
    cumulative_distances,
    derive_mph_from_minutes,
)

try:
    # Optional: project logging if available
    from golfsim.logging import init_logging
except Exception:  # pragma: no cover - optional
    def init_logging(_level: str = "INFO") -> None:  # fallback noop
        return None


def main() -> None:
    init_logging("INFO")

    parser = argparse.ArgumentParser(description="Crossings demo using reference logic (no modifications).")
    parser.add_argument(
        "--nodes_geojson",
        type=str,
        default="courses/pinetree_country_club/geojson/generated/lcm_course_nodes.geojson",
        help="GeoJSON FeatureCollection with ordered Point nodes."
    )
    parser.add_argument(
        "--holes_geojson",
        type=str,
        default="courses/pinetree_country_club/geojson/generated/holes_geofenced.geojson",
        help="GeoJSON FeatureCollection with hole polygons (Polygon/MultiPolygon) and 'hole' property."
    )
    parser.add_argument(
        "--config_json",
        type=str,
        default="courses/pinetree_country_club/config/simulation_config.json",
        help="Config JSON with golfer_18_holes_minutes and bev_cart_18_holes_minutes (optional)."
    )
    parser.add_argument("--v_fwd_mph", type=float, default=None, help="Override golfer speed (1->18) in mph.")
    parser.add_argument("--v_bwd_mph", type=float, default=None, help="Override beverage cart speed (18->1) in mph.")
    parser.add_argument("--bev_start", type=str, default="08:00:00")
    parser.add_argument("--groups_start", type=str, default="09:00:00")
    parser.add_argument("--groups_end", type=str, default="10:00:00")
    parser.add_argument("--groups_count", type=int, default=4)
    parser.add_argument("--random_seed", type=int, default=123)
    parser.add_argument("--tee_mode", type=str, choices=["interval", "random"], default="interval")
    parser.add_argument("--groups_interval_min", type=float, default=30.0)
    parser.add_argument("--out_dir", type=str, default=None, help="Optional output directory for summary files.")
    args = parser.parse_args()

    # Load nodes with hole mapping if available
    nodes: List[Tuple[float, float]]
    node_holes: Optional[List[Optional[int]]] = None
    try:
        nodes, node_holes = load_nodes_geojson_with_holes(args.nodes_geojson)
    except Exception:
        nodes = load_nodes_geojson(args.nodes_geojson)

    # Optional holes polygons (fallback if node_holes missing)
    holes = None
    try:
        holes = load_holes_geojson(args.holes_geojson)
    except Exception:
        holes = None

    # Derive speeds from config if not provided
    v_fwd = args.v_fwd_mph
    v_bwd = args.v_bwd_mph
    try:
        if v_fwd is None or v_bwd is None:
            total_length_m = cumulative_distances(nodes)[-1]
            if args.config_json and Path(args.config_json).exists():
                cfg = json.loads(Path(args.config_json).read_text(encoding="utf-8"))
                g_min = float(cfg.get("golfer_18_holes_minutes"))
                b_min = float(cfg.get("bev_cart_18_holes_minutes"))
                if v_fwd is None:
                    v_fwd = derive_mph_from_minutes(total_length_m, g_min)
                if v_bwd is None:
                    v_bwd = derive_mph_from_minutes(total_length_m, b_min)
    except Exception:
        pass

    # Sensible fallbacks if still None
    v_fwd = v_fwd if v_fwd is not None else 12.0
    v_bwd = v_bwd if v_bwd is not None else 10.0

    # Compute crossings using the shared reference logic
    result = compute_crossings(
        nodes=nodes,
        v_fwd_mph=v_fwd,
        v_bwd_mph=v_bwd,
        bev_start_clock=args.bev_start,
        groups_start_clock=args.groups_start,
        groups_end_clock=args.groups_end,
        groups_count=args.groups_count,
        random_seed=args.random_seed,
        holes=holes,
        node_holes=node_holes,
        tee_mode=args.tee_mode,
        groups_interval_min=args.groups_interval_min,
    )

    # Print concise console output
    print(f"Beverage cart start: {result['bev_start'].isoformat(sep=' ')}")
    for g in sorted(result["groups"], key=lambda r: r.get("tee_time")):
        tee = g.get("tee_time")
        if not g.get("crossed", True):
            print(f"Group {g['group']} tee {tee.isoformat(sep=' ')}: no crossings")
            continue
        for cr in g.get("crossings", []):
            node_idx = cr.get("node_index")
            ts = cr.get("timestamp")
            hole_disp = cr.get("hole") if cr.get("hole") is not None else "unknown"
            print(f"Group {g['group']} | node {node_idx} | {ts.isoformat(sep=' ')} | hole {hole_disp}")

    # Optional outputs
    out_dir = Path(args.out_dir) if args.out_dir else Path("outputs") / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_reference_crossings"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Write a minimal JSON summary
    summary_path = out_dir / "crossings_summary.json"
    serializable = {
        "bev_start": result["bev_start"].isoformat(),
        "v_golfer_mph": result["v_golfer_mph"],
        "v_bev_mph": result["v_bev_mph"],
        "groups": [
            {
                "group": g["group"],
                "tee_time": g.get("tee_time").isoformat() if g.get("tee_time") else None,
                "crossed": g.get("crossed", False),
                "crossings": [
                    {
                        "timestamp": cr.get("timestamp").isoformat() if cr.get("timestamp") else None,
                        "node_index": cr.get("node_index"),
                        "hole": cr.get("hole"),
                        "k_wraps": cr.get("k_wraps"),
                    }
                    for cr in g.get("crossings", [])
                ],
            }
            for g in result.get("groups", [])
        ],
    }
    summary_path.write_text(json.dumps(serializable, indent=2), encoding="utf-8")
    print(f"Saved crossings summary: {summary_path}")


if __name__ == "__main__":
    main()


