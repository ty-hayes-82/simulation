#!/usr/bin/env python3
"""
Run end-to-end course setup for a golf course.

Pipeline (matching COURSE_SETUP_README.md):
  1) Extract course data from OpenStreetMap
  2) Generate holes connected path (and geofenced holes if needed)
  3) Build simplified cart network (apply shortcuts and clubhouse routes)
  4) Compute travel times (node_travel_times.json)
  5) Verify the build

Defaults provided for Idle Hour Country Club.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

import json
import geopandas as gpd  # type: ignore
import matplotlib.pyplot as plt  # type: ignore


def run_cmd(description: str, args: List[str]) -> None:
    print(f"\n=== {description} ===")
    print(" ", " ".join(args))
    proc = subprocess.run(args, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"Step failed ({description}). Exit code: {proc.returncode}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run end-to-end course setup pipeline")

    # Core identifiers
    parser.add_argument("--course", default="Idle Hour Country Club", help="Course name")
    parser.add_argument("--clubhouse-lat", type=float, default=38.027532, help="Clubhouse latitude")
    parser.add_argument("--clubhouse-lon", type=float, default=-84.469878, help="Clubhouse longitude")
    parser.add_argument("--course-dir", default="courses/idle_hour_country_club", help="Output course directory")

    # Extraction tuning
    parser.add_argument("--include-streets", action="store_true", default=True, help="Include nearby roads")
    parser.add_argument("--street-buffer", type=int, default=750, help="Street search buffer (m)")
    parser.add_argument("--course-buffer", type=int, default=100, help="Street filter distance to boundary (m)")

    # Network build tuning
    parser.add_argument(
        "--shortcuts",
        default="138-173,225-189,13-191,14-223,101-69,102-206,23-55",
        help="Comma-separated shortcut pairs (idxA-idxB,...)",
    )
    parser.add_argument(
        "--clubhouse-routes",
        default="115-114,1-2,116-117,239-238",
        help="Comma-separated clubhouse route pairs (idxA-idxB,...)",
    )
    parser.add_argument(
        "--save-png",
        default="outputs/cart_network.png",
        help="Relative or absolute path to save PNG network visualization",
    )
    parser.add_argument(
        "--interactive",
        action="store_true",
        default=True,
        help="Pause to review a labeled PNG and enter shortcuts/clubhouse routes",
    )
    parser.add_argument(
        "--no-interactive",
        dest="interactive",
        action="store_false",
        help="Run without prompting (use provided defaults)",
    )

    # Travel time speed (m/s)
    parser.add_argument("--speed", type=float, default=2.68, help="Runner speed m/s for travel-time calc")

    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    py = sys.executable
    course_dir = Path(args.course_dir)

    # Ensure course_dir exists
    course_dir.mkdir(parents=True, exist_ok=True)

    # Step 1 — Extract course data from OpenStreetMap
    extract_cmd = [
        py,
        str(root / "scripts/routing/extract_course_data.py"),
        "--course",
        args.course,
        "--clubhouse-lat",
        str(args.clubhouse_lat),
        "--clubhouse-lon",
        str(args.clubhouse_lon),
        "--street-buffer",
        str(args.street_buffer),
        "--course-buffer",
        str(args.course_buffer),
        "--output-dir",
        str(course_dir),
    ]
    if args.include_streets:
        extract_cmd.append("--include-streets")
    run_cmd("Step 1 — Extract course data", extract_cmd)

    # Step 2 — Generate holes connected path (ensures holes_connected.geojson exists)
    geofence_cmd = [
        py,
        str(root / "scripts/course_prep/geofence_holes.py"),
        "--boundary",
        str(course_dir / "geojson/course_polygon.geojson"),
        "--holes",
        str(course_dir / "geojson/holes.geojson"),
        "--generated_dir",
        "generated",
    ]
    run_cmd("Step 2 — Generate holes connected path", geofence_cmd)

    # Produce a labeled PNG of nodes to assist manual shortcut selection
    labeled_png_path = course_dir / "outputs" / "holes_nodes_labeled.png"
    _generate_labeled_nodes_png(course_dir, labeled_png_path)
    print(f"\n📍 Labeled nodes PNG written to: {labeled_png_path}")
    print("Open this image to identify node ids for shortcuts and clubhouse connections.")

    # Optionally prompt for custom shortcuts and clubhouse routes
    shortcuts_value = args.shortcuts
    clubhouse_routes_value = args.clubhouse_routes
    if args.interactive:
        try:
            print(f"\nEnter shortcuts (idxA-idxB, comma-separated). Press Enter to keep defaults: {shortcuts_value}")
            entered = input("Shortcuts: ").strip()
            if entered:
                shortcuts_value = entered
            print(f"Enter clubhouse routes (idxA-idxB, comma-separated). Press Enter to keep defaults: {clubhouse_routes_value}")
            entered2 = input("Clubhouse routes: ").strip()
            if entered2:
                clubhouse_routes_value = entered2
        except KeyboardInterrupt:
            print("\nInterrupted. Using defaults.")

    # Step 3 — Build simplified cart network with manual shortcuts and clubhouse routes
    build_cmd = [
        py,
        str(root / "scripts/routing/build_cart_network_from_holes_connected.py"),
        str(course_dir),
        "--save-png",
        args.save_png,
        "--shortcuts",
        shortcuts_value,
        "--clubhouse-routes",
        clubhouse_routes_value,
    ]
    run_cmd("Step 3 — Build simplified cart network", build_cmd)

    # Step 4 — Compute travel times
    travel_cmd = [
        py,
        str(root / "scripts/routing/generate_node_travel_times.py"),
        "--course-dir",
        str(course_dir),
        "--speed",
        str(args.speed),
    ]
    run_cmd("Step 4 — Compute travel times", travel_cmd)

    # Step 5 — Verify the build
    verify_cmd = [
        py,
        str(root / "scripts/routing/verify_cart_graph.py"),
        str(course_dir),
    ]
    run_cmd("Step 5 — Verify the build", verify_cmd)

    print("\n✅ Course setup pipeline completed successfully.")
    return 0


def _generate_labeled_nodes_png(course_dir: Path, save_path: Path) -> Optional[Path]:
    """Create a PNG that labels each node index from holes_connected.geojson for manual review."""
    try:
        nodes_path = course_dir / "geojson" / "generated" / "holes_connected.geojson"
        boundary_path = course_dir / "geojson" / "course_polygon.geojson"
        if not nodes_path.exists():
            print(f"WARNING: {nodes_path} not found; skipping labeled PNG generation")
            return None

        gdf = gpd.read_file(nodes_path).to_crs(4326)
        boundary = gpd.read_file(boundary_path).to_crs(4326) if boundary_path.exists() else None

        # Load clubhouse for context
        clubhouse_xy: Optional[Tuple[float, float]] = None
        cfg_path = course_dir / "config" / "simulation_config.json"
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
            clubhouse_xy = (float(cfg["clubhouse"]["longitude"]), float(cfg["clubhouse"]["latitude"]))
        except Exception:
            clubhouse_xy = None

        save_path.parent.mkdir(parents=True, exist_ok=True)
        fig, ax = plt.subplots(figsize=(12, 9))

        # Plot boundary
        if boundary is not None and len(boundary) > 0:
            try:
                for _, row in boundary.iterrows():
                    geom = row.geometry
                    x, y = geom.exterior.xy
                    ax.plot(x, y, color='lightgray', linewidth=1.2, alpha=0.9)
            except Exception:
                pass

        # Collect nodes and label (no dots per request)
        point_count = 0
        nodes: list[tuple[int, float, float]] = []  # (idx, lon, lat)
        for _, row in gdf.iterrows():
            geom = row.geometry
            if getattr(geom, 'geom_type', '') == 'Point':
                try:
                    idx = int(row.get('idx'))
                except Exception:
                    idx = None
                if idx is not None:
                    nodes.append((idx, float(geom.x), float(geom.y)))
                    ax.annotate(str(idx), (geom.x, geom.y), fontsize=6, color='black', ha='center', va='center')
                    point_count += 1

        # Clubhouse marker
        if clubhouse_xy is not None:
            ax.plot(clubhouse_xy[0], clubhouse_xy[1], 's', color='red', markersize=8, label='Clubhouse')
            ax.legend(loc='upper right')

        ax.set_aspect('equal', adjustable='box')
        ax.grid(True, alpha=0.2)
        ax.set_title(f"Holes-Connected Nodes (labeled) — {course_dir.name} | {point_count} points")

        # Compute shortcut recommendations based on proximity of non-consecutive nodes
        def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
            import math
            phi1 = math.radians(lat1)
            phi2 = math.radians(lat2)
            dphi = math.radians(lat2 - lat1)
            dlambda = math.radians(lon2 - lon1)
            a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
            c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
            return 6371000.0 * c

        rec_pairs: list[tuple[int, int, float]] = []
        if nodes:
            nodes_sorted = sorted(nodes, key=lambda t: t[0])
            idx_values = [n[0] for n in nodes_sorted]
            if idx_values:
                min_idx, max_idx = min(idx_values), max(idx_values)
            else:
                min_idx, max_idx = 0, 0
            # Brute-force nearest pairs (n ~ 240 → OK)
            for i in range(len(nodes_sorted)):
                ia, xa, ya = nodes_sorted[i]
                for j in range(i + 1, len(nodes_sorted)):
                    ib, xb, yb = nodes_sorted[j]
                    # Skip consecutive along the path (including wrap-around)
                    if abs(ia - ib) == 1 or {ia, ib} == {min_idx, max_idx}:
                        continue
                    d = _haversine_m(xa, ya, xb, yb)
                    rec_pairs.append((ia, ib, d))
            # Keep only very close pairs and sort
            threshold_m = 80.0
            rec_pairs = [p for p in rec_pairs if p[2] <= threshold_m]

            # Cluster collapse: for bunches like 3/4/5 vs 80/81/82, keep only the single closest
            # Use coarse index bins to approximate clusters
            BIN_SIZE = 3
            by_bin: dict[tuple[int, int], tuple[int, int, float]] = {}
            for a, b, d in rec_pairs:
                key = (a // BIN_SIZE, b // BIN_SIZE)
                prev = by_bin.get(key)
                if prev is None or d < prev[2]:
                    by_bin[key] = (a, b, d)
            rec_pairs = list(by_bin.values())

            # Greedy uniqueness: ensure each node appears at most once, picking closest first
            rec_pairs.sort(key=lambda t: t[2])
            used: set[int] = set()
            unique_pairs: list[tuple[int, int, float]] = []
            for a, b, d in rec_pairs:
                if a in used or b in used:
                    continue
                unique_pairs.append((a, b, d))
                used.add(a)
                used.add(b)

            # Limit to top N for readability
            rec_pairs = unique_pairs[:25]

        # Clubhouse nearest node suggestions
        clubhouse_nearest: list[tuple[int, float]] = []
        if clubhouse_xy is not None and nodes:
            for idx, x, y in nodes:
                clubhouse_nearest.append((idx, _haversine_m(clubhouse_xy[0], clubhouse_xy[1], x, y)))
            clubhouse_nearest.sort(key=lambda t: t[1])
            clubhouse_nearest = clubhouse_nearest[:4]

        # Save PNG
        fig.tight_layout()
        fig.savefig(save_path, dpi=300, bbox_inches='tight', facecolor='white')
        plt.close(fig)

        # Write recommendations to a helper file
        try:
            out_txt = course_dir / "outputs" / "shortcut_recommendations.txt"
            out_txt.parent.mkdir(parents=True, exist_ok=True)
            with out_txt.open("w", encoding="utf-8") as f:
                f.write("Recommended shortcut pairs (<= 80m):\n")
                if rec_pairs:
                    for a, b, d in rec_pairs:
                        f.write(f"- {a}-{b} (~{d:.1f} m)\n")
                    f.write("\nCSV: ")
                    f.write(",".join([f"{a}-{b}" for a, b, _ in rec_pairs]))
                    f.write("\n")
                else:
                    f.write("(none within threshold)\n")
                f.write("\nNearest clubhouse node indices:\n")
                if clubhouse_nearest:
                    f.write(", ".join([f"{idx} (~{dist:.1f} m)" for idx, dist in clubhouse_nearest]))
                    f.write("\n")
                else:
                    f.write("(unavailable)\n")
            # Also print a brief summary to console
            if rec_pairs:
                print("\nSuggested shortcut pairs (<=80m):")
                print(", ".join([f"{a}-{b}" for a, b, _ in rec_pairs]))
            if clubhouse_nearest:
                print("Nearest clubhouse nodes:", ", ".join([str(idx) for idx, _ in clubhouse_nearest]))
            print(f"Details written to: {out_txt}")
        except Exception as _:
            pass
        return save_path
    except Exception as e:
        print(f"WARNING: Failed to generate labeled nodes PNG: {e}")
        return None


if __name__ == "__main__":
    raise SystemExit(main())


