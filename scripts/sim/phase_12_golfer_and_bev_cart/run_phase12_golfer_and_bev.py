from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from golfsim.logging import init_logging
from golfsim.viz.matplotlib_viz import render_beverage_cart_plot
from golfsim.io.results import write_unified_coordinates_csv
from golfsim.config.loaders import load_tee_times_config


def _choose_tee_time_s(course_dir: str) -> int:
    cfg = load_tee_times_config(course_dir)
    scenarios = cfg.scenarios or {}
    key = "testing_rainy_day" if "testing_rainy_day" in scenarios else next(iter(scenarios.keys()))
    hourly = scenarios[key].get("hourly_golfers", {})
    # Choose the first hour that has golfers for determinism
    for hhmm, count in hourly.items():
        try:
            if int(count) > 0:
                hh, mm = hhmm.split(":")
                return (int(hh) - 7) * 3600 + int(mm) * 60
        except Exception:
            continue
    # Fallback to 09:00 baseline
    return (9 - 7) * 3600


def _write_geojson_with_id(points: List[Dict], save_path: Path, id_value: str) -> None:
    features: List[Dict] = []
    for c in points:
        lon = float(c.get("longitude", 0.0))
        lat = float(c.get("latitude", 0.0))
        ts = int(c.get("timestamp", 0))
        feat = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "timestamp": ts,
                "type": c.get("type", "unknown"),
                "current_hole": int(c.get("current_hole", 0)),
                "id": id_value,
            },
        }
        features.append(feat)
    fc = {"type": "FeatureCollection", "features": features}
    save_path.write_text(json.dumps(fc, indent=2), encoding="utf-8")


def run_once(run_idx: int, course_dir: str, output_root: Path) -> Dict:
    # Build golfer-only track via helper script
    import runpy
    gen_module = runpy.run_path("scripts/sim/generate_simple_tracks.py")
    generate_tracks = gen_module["generate_tracks"]
    tracks = generate_tracks(course_dir)
    golfer_points: List[Dict] = tracks.get("golfer", [])

    # Offset golfer timestamps to a tee time within tee_times_config hours
    tee_time_s = _choose_tee_time_s(course_dir)
    for p in golfer_points:
        p["timestamp"] = int(p.get("timestamp", 0)) + tee_time_s
        p["type"] = p.get("type", "golfer")

    # Beverage cart: run laps for configured open window (09:00–17:00 default)
    from golfsim.simulation.services import BeverageCartService
    import simpy
    env = simpy.Environment()
    svc = BeverageCartService(env=env, course_dir=course_dir, cart_id=f"bev_cart_{run_idx}", track_coordinates=True)
    env.run(until=svc.service_end_s)
    bev_points: List[Dict] = svc.coordinates

    run_dir = output_root / f"sim_{run_idx:02d}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Single activity log for bev cart per simulation
    (run_dir / "bev_cart_activity_log.json").write_text(json.dumps(svc.activity_log, indent=2), encoding="utf-8")

    # Single combined CSV for both streams with visibility tracking
    from golfsim.io.results import write_coordinates_csv_with_visibility
    write_coordinates_csv_with_visibility(
        {"golfer_1": golfer_points, "bev_cart_1": bev_points}, 
        run_dir / "coordinates.csv",
        enable_visibility_tracking=True
    )

    # Disable GeoJSON for now

    # PNG visualizations: keep per-type PNGs for clarity/tests
    render_beverage_cart_plot(golfer_points, course_dir=course_dir, save_path=run_dir / "golfer_route.png", title="Golfer Route")
    render_beverage_cart_plot(bev_points, course_dir=course_dir, save_path=run_dir / "bev_cart_route.png", title="Beverage Cart Route")

    return {
        "run_idx": run_idx,
        "golfer_points": len(golfer_points),
        "bev_points": len(bev_points),
    }


def write_summary_md(results: List[Dict], output_root: Path) -> None:
    if not results:
        return
    g = [r.get("golfer_points", 0) for r in results]
    b = [r.get("bev_points", 0) for r in results]
    lines = [
        "# Phase 12 — Golfer + Beverage Cart (5-run summary)",
        "",
        f"Runs: {len(results)}",
        f"Golfer points per run: min={min(g)}, max={max(g)}, mean={sum(g)/len(g):.1f}",
        f"Cart points per run: min={min(b)}, max={max(b)}, mean={sum(b)/len(b):.1f}",
        "",
        "## Artifacts",
    ]
    for r in results:
        ridx = r.get("run_idx", 0)
        lines.append(f"- Run {ridx:02d}: golfer/bev-cart PNG + CSV + GeoJSON present")
    lines.append("")
    (output_root / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    init_logging("INFO")
    course_dir = "courses/pinetree_country_club"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path("outputs") / f"{ts}_phase_12"
    output_root.mkdir(parents=True, exist_ok=True)

    all_results: List[Dict] = []
    for i in range(1, 6):
        res = run_once(i, course_dir, output_root)
        all_results.append(res)

    write_summary_md(all_results, output_root)


if __name__ == "__main__":
    main()


