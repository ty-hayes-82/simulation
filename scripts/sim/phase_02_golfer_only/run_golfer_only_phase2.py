from __future__ import annotations

import csv
import json
from datetime import datetime
import random
from pathlib import Path
from typing import Dict, List

from golfsim.logging import init_logging
from golfsim.viz.matplotlib_viz import render_beverage_cart_plot
from golfsim.io.results import write_unified_coordinates_csv
from golfsim.config.loaders import load_tee_times_config


def _write_geojson(coordinates: List[Dict], save_path: Path) -> None:
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
                "type": c.get("type", "golfer"),
                "current_hole": int(c.get("current_hole", 0)),
            },
        }
        features.append(feat)
    fc = {"type": "FeatureCollection", "features": features}
    save_path.write_text(json.dumps(fc, indent=2), encoding="utf-8")


def _write_csv(coordinates: List[Dict], save_path: Path) -> None:
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
                    "type": c.get("type", "golfer"),
                    "current_hole": int(c.get("current_hole", 0)),
                }
            )


def _write_stats_md(points: List[Dict], save_path: Path) -> None:
    times = [int(p.get("timestamp", 0)) for p in points] if points else []
    lines = [
        "# Golfer-only Run Stats",
        "",
        f"Points: {len(points)}",
        f"First timestamp: {times[0] if times else 'NA'}",
        f"Last timestamp: {times[-1] if times else 'NA'}",
    ]
    save_path.write_text("\n".join(lines), encoding="utf-8")


def _choose_random_tee_time_s(course_dir: str) -> int:
    """Choose a random tee time (seconds since 07:00 baseline) from tee_times_config.json.
    Prefers 'testing_rainy_day' if available; otherwise uses the first scenario.
    """
    cfg = load_tee_times_config(course_dir)
    scenarios = cfg.scenarios or {}
    # Prefer testing_rainy_day for determinism in small runs
    scenario_key = "testing_rainy_day" if "testing_rainy_day" in scenarios else next(iter(scenarios.keys()))
    scenario = scenarios[scenario_key]
    hourly = scenario.get("hourly_golfers", {})
    # Filter hours with at least 1 golfer
    candidates = [h for h, n in hourly.items() if (isinstance(n, int) and n > 0)]
    if not candidates:
        candidates = list(hourly.keys())
    if not candidates:
        # Fallback to 09:00
        return (9 - 7) * 3600
    choice = random.choice(candidates)
    try:
        hh, mm = choice.split(":")
        return (int(hh) - 7) * 3600 + int(mm) * 60
    except Exception:
        return (9 - 7) * 3600


def run_once(run_idx: int, course_dir: str, output_root: Path) -> Dict:
    # Generate golfer-only track at 60s cadence using hole geometries
    # Import lazily to avoid heavy deps at module import time
    import runpy

    script_path = Path("scripts/sim/generate_simple_tracks.py").resolve()
    module_dict = runpy.run_path(str(script_path))
    generate_tracks = module_dict["generate_tracks"]
    tracks = generate_tracks(course_dir)
    golfer_points: List[Dict] = tracks.get("golfer", [])

    # Offset timestamps to a random tee time drawn from tee_times_config
    tee_time_s = _choose_random_tee_time_s(course_dir)
    for p in golfer_points:
        p["timestamp"] = int(p.get("timestamp", 0)) + int(tee_time_s)

    run_dir = output_root / f"sim_{run_idx:02d}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Raw JSON for completeness
    coords_json = run_dir / "golfer_coordinates.json"
    coords_json.write_text(json.dumps(golfer_points, indent=2), encoding="utf-8")

    # PNG (reuse beverage cart renderer for a simple path plot; set title)
    png_path = run_dir / "golfer_route.png"
    render_beverage_cart_plot(golfer_points, course_dir=course_dir, save_path=png_path, title="Golfer Route")

    # Unified CSV only (disable GeoJSON for now)
    # Note: Phase 2 is golfer-only (no beverage carts), so visibility tracking won't apply
    csv_path = run_dir / "coordinates.csv"
    write_unified_coordinates_csv({"golfer_1": golfer_points}, csv_path)

    # Stats
    _write_stats_md(golfer_points, run_dir / "stats.md")

    return {
        "run_idx": run_idx,
        "points": len(golfer_points),
        "first": int(golfer_points[0]["timestamp"]) if golfer_points else None,
        "last": int(golfer_points[-1]["timestamp"]) if golfer_points else None,
        "png": str(png_path),
        "geojson": "",
        "csv": str(csv_path),
    }


def write_summary_md(results: List[Dict], output_root: Path) -> None:
    if not results:
        return
    points = [r.get("points", 0) for r in results]
    firsts = [r.get("first", 0) for r in results]
    lasts = [r.get("last", 0) for r in results]

    lines = [
        "# Phase 2 — Golfer only (5-run summary)",
        "",
        f"Runs: {len(results)}",
        f"Coordinates per run: min={min(points)}, max={max(points)}, mean={sum(points)/len(points):.1f}",
        f"First timestamps: min={min(firsts)}, max={max(firsts)}",
        f"Last timestamps: min={min(lasts)}, max={max(lasts)}",
        "",
        "## Artifacts",
        *[
            (
                f"- Run {r['run_idx']:02d}: PNG={r['png']} | CSV={r['csv']}"
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
    output_root = Path("outputs") / f"{ts}_phase_02"
    output_root.mkdir(parents=True, exist_ok=True)

    all_results: List[Dict] = []
    for i in range(1, 6):
        res = run_once(i, course_dir, output_root)
        all_results.append(res)

    write_summary_md(all_results, output_root)


if __name__ == "__main__":
    main()


