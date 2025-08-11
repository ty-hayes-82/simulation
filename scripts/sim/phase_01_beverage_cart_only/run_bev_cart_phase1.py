from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict

import simpy

from golfsim.logging import init_logging
from golfsim.simulation.services import BeverageCartService
from golfsim.viz.matplotlib_viz import render_beverage_cart_plot
from golfsim.io.results import write_unified_coordinates_csv


def _write_geojson(coordinates: List[Dict], save_path: Path) -> None:
    """
    Write a simple GeoJSON FeatureCollection of Point features for the beverage cart track.
    """
    features = []
    for c in coordinates:
        lon = float(c.get("longitude", 0.0))
        lat = float(c.get("latitude", 0.0))
        ts = int(c.get("timestamp", 0))
        feat = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "timestamp": ts,
                "type": c.get("type", "bev_cart"),
                "current_hole": int(c.get("current_hole", 0)),
            },
        }
        features.append(feat)
    fc = {"type": "FeatureCollection", "features": features}
    save_path.write_text(json.dumps(fc, indent=2), encoding="utf-8")


def _write_csv(coordinates: List[Dict], save_path: Path) -> None:
    """
    Write GPS coordinates to CSV with headers.
    """
    fieldnames = ["timestamp", "latitude", "longitude", "type", "current_hole"]
    with save_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for c in coordinates:
            writer.writerow(
                {
                    "timestamp": int(c.get("timestamp", 0)),
                    "latitude": float(c.get("latitude", 0.0)),
                    "longitude": float(c.get("longitude", 0.0)),
                    "type": c.get("type", "bev_cart"),
                    "current_hole": int(c.get("current_hole", 0)),
                }
            )


def _write_stats_md(results: Dict, save_path: Path) -> None:
    lines = [
        "# Beverage Cart Run Stats",
        "",
        f"Points: {results.get('points', 0)}",
        f"First timestamp: {results.get('first', 'NA')}",
        f"Last timestamp: {results.get('last', 'NA')}",
    ]
    save_path.write_text("\n".join(lines), encoding="utf-8")


def run_once(run_idx: int, course_dir: str, output_root: Path) -> Dict:
    env = simpy.Environment()
    svc = BeverageCartService(env=env, course_dir=course_dir, cart_id=f"bev_cart_{run_idx}", track_coordinates=True)
    env.run(until=svc.service_end_s)

    run_dir = output_root / f"sim_{run_idx:02d}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Raw JSON artifacts for completeness
    coords_json_path = run_dir / "bev_cart_coordinates.json"
    log_json_path = run_dir / "bev_cart_activity_log.json"
    coords_json_path.write_text(json.dumps(svc.coordinates, indent=2), encoding="utf-8")
    log_json_path.write_text(json.dumps(svc.activity_log, indent=2), encoding="utf-8")

    # Always render a PNG for cart locations
    png_path = run_dir / "bev_cart_route.png"
    render_beverage_cart_plot(svc.coordinates, course_dir=course_dir, save_path=png_path)

    # Unified CSV only (disable GeoJSON for now)
    # Note: Phase 1 is beverage cart-only (no golfers), so visibility tracking won't apply
    csv_path = run_dir / "coordinates.csv"
    write_unified_coordinates_csv({svc.cart_id: svc.coordinates}, csv_path)

    result: Dict = {
        "run_idx": run_idx,
        "points": len(svc.coordinates),
        "first": int(svc.coordinates[0]["timestamp"]) if svc.coordinates else None,
        "last": int(svc.coordinates[-1]["timestamp"]) if svc.coordinates else None,
        "png": str(png_path),
        "geojson": "",
        "csv": str(csv_path),
    }
    _write_stats_md(result, run_dir / "stats.md")
    return result


def write_summary_md(results: List[Dict], output_root: Path) -> None:
    if not results:
        return
    points = [r.get("points", 0) for r in results]
    firsts = [r.get("first", 0) for r in results]
    lasts = [r.get("last", 0) for r in results]

    lines = [
        "# Phase 1 — Beverage cart only (5-run summary)",
        "",
        f"Runs: {len(results)}",
        f"Coordinates per run: min={min(points)}, max={max(points)}, mean={sum(points)/len(points):.1f}",
        f"First timestamps: min={min(firsts)}, max={max(firsts)} (expect >= 7200)",
        f"Last timestamps: min={min(lasts)}, max={max(lasts)} (expect <= 36000)",
        "",
        "## Artifacts",
        *[
            (
                f"- Run {r['run_idx']:02d}: PNG={r['png']} | GEOJSON={r['geojson']} | CSV={r['csv']}"
            )
            for r in results
        ],
        "",
    ]
    (output_root / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    init_logging("INFO")
    course_dir = "courses/pinetree_country_club"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path("outputs") / f"{ts}_phase_01"
    output_root.mkdir(parents=True, exist_ok=True)

    all_results: List[Dict] = []
    for i in range(1, 6):
        result = run_once(i, course_dir, output_root)
        all_results.append(result)

    write_summary_md(all_results, output_root)


if __name__ == "__main__":
    main()


