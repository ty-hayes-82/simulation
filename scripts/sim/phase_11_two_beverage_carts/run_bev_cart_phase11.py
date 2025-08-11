from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import simpy

from golfsim.logging import init_logging
from golfsim.simulation.services import BeverageCartService
from golfsim.viz.matplotlib_viz import render_beverage_cart_plot
from golfsim.io.results import write_unified_coordinates_csv


def _write_combined_geojson(by_label_coords: Dict[str, List[Dict]], save_path: Path) -> None:
    """Write a single GeoJSON FeatureCollection with an 'id' property for the cart label."""
    features: List[Dict] = []
    for label, coords in by_label_coords.items():
        for c in coords:
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
                    "id": label,
                },
            }
            features.append(feat)
    fc = {"type": "FeatureCollection", "features": features}
    save_path.write_text(json.dumps(fc, indent=2), encoding="utf-8")


def _write_combined_csv(by_label_coords: Dict[str, List[Dict]], save_path: Path) -> None:
    """Write a single CSV combining all carts with an 'id' column."""
    headers = ["timestamp", "latitude", "longitude", "current_hole", "type", "id"]
    with save_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for label, coords in by_label_coords.items():
            for c in coords:
                writer.writerow(
                    {
                        "timestamp": int(c.get("timestamp", 0)),
                        "latitude": float(c.get("latitude", 0.0)),
                        "longitude": float(c.get("longitude", 0.0)),
                        "current_hole": int(c.get("current_hole", 0)),
                        "type": c.get("type", "bev_cart"),
                        "id": label,
                    }
                )


def _write_stats_md(results_by_cart: Dict[str, Dict], save_path: Path) -> None:
    lines: List[str] = ["# Phase 11 — Two beverage carts (per-run stats)", ""]
    for label, r in results_by_cart.items():
        lines.extend(
            [
                f"## Cart {label}",
                f"Points: {r.get('points', 0)}",
                f"First timestamp: {r.get('first', 'N/A')}",
                f"Last timestamp: {r.get('last', 'N/A')}",
                f"PNG: {r.get('png', '')}",
                f"GeoJSON: {r.get('geojson', '')}",
                f"CSV: {r.get('csv', '')}",
                "",
            ]
        )
    save_path.write_text("\n".join(lines), encoding="utf-8")


def run_once(run_idx: int, course_dir: str, output_root: Path) -> Dict:
    env = simpy.Environment()

    # Two carts in the same environment
    cart_specs: List[Tuple[str, str]] = [("A", "bev_cart_A"), ("B", "bev_cart_B")]
    services: Dict[str, BeverageCartService] = {}
    for label, cart_id in cart_specs:
        services[label] = BeverageCartService(
            env=env, course_dir=course_dir, cart_id=cart_id, track_coordinates=True
        )

    # Run until service end (both carts share the same window from config)
    # Use any service's end time since they are identical by config
    any_service = next(iter(services.values()))
    env.run(until=any_service.service_end_s)

    run_dir = output_root / f"sim_{run_idx:02d}"
    run_dir.mkdir(parents=True, exist_ok=True)

    results_by_cart: Dict[str, Dict] = {}
    combined_logs: List[Dict] = []

    for label, svc in services.items():
        # Accumulate logs with identifier for a single combined log per sim
        for entry in svc.activity_log:
            e = dict(entry)
            e["id"] = label
            combined_logs.append(e)

        results_by_cart[label] = {
            "run_idx": run_idx,
            "points": len(svc.coordinates),
            "first": int(svc.coordinates[0]["timestamp"]) if svc.coordinates else None,
            "last": int(svc.coordinates[-1]["timestamp"]) if svc.coordinates else None,
        }

    # Unified CSV only (disable GeoJSON for now)
    # Save with the expected filename for tests and aggregation
    # Note: Phase 11 is beverage carts only (no golfers), so visibility tracking won't apply
    write_unified_coordinates_csv(
        {k: services[k].coordinates for k in services.keys()},
        run_dir / "bev_cart_coordinates.csv",
    )

    # Write a single combined activity log for the simulation
    (run_dir / "bev_cart_activity_log.json").write_text(json.dumps(combined_logs, indent=2), encoding="utf-8")

    # Create one combined PNG per simulation for both carts
    all_coords: List[Dict] = []
    for lbl in services.keys():
        all_coords.extend(services[lbl].coordinates)
    render_beverage_cart_plot(all_coords, course_dir=course_dir, save_path=run_dir / "bev_cart_route.png")

    _write_stats_md(results_by_cart, run_dir / "stats.md")

    # Return compact result for summary aggregation
    return {
        "run_idx": run_idx,
        "A": results_by_cart.get("A", {}),
        "B": results_by_cart.get("B", {}),
    }


def write_summary_md(results: List[Dict], output_root: Path) -> None:
    if not results:
        return

    points_A = [r.get("A", {}).get("points", 0) for r in results]
    points_B = [r.get("B", {}).get("points", 0) for r in results]

    lines = [
        "# Phase 11 — Two beverage carts (5-run summary)",
        "",
        f"Runs: {len(results)}",
        f"Coordinates per run (Cart A): min={min(points_A)}, max={max(points_A)}, mean={sum(points_A)/len(points_A):.1f}",
        f"Coordinates per run (Cart B): min={min(points_B)}, max={max(points_B)}, mean={sum(points_B)/len(points_B):.1f}",
        "",
        "## Artifacts",
    ]

    for r in results:
        ridx = r.get("run_idx", 0)
        a = r.get("A", {})
        b = r.get("B", {})
        lines.append(
            f"- Run {ridx:02d} — PNG_A={a.get('png','')} | PNG_B={b.get('png','')} | Combined GEOJSON/CSV present"
        )

    lines.append("")
    (output_root / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def write_phase_level_combined_artifacts(output_root: Path) -> None:
    """Aggregate all sim_* combined files into a single CSV/GeoJSON/PNG/activity log at phase root."""
    # Collect files from each sim dir
    sim_dirs = sorted([p for p in output_root.glob("sim_*") if p.is_dir()])
    all_rows: List[Dict] = []
    all_features: List[Dict] = []
    all_coords: List[Dict] = []
    all_logs: List[Dict] = []

    import csv as _csv
    import json as _json

    for sim_dir in sim_dirs:
        run_name = sim_dir.name
        # CSV
        csv_path = sim_dir / "bev_cart_coordinates.csv"
        if csv_path.exists():
            with csv_path.open("r", encoding="utf-8") as f:
                reader = _csv.DictReader(f)
                for row in reader:
                    row = dict(row)
                    row["run"] = run_name
                    all_rows.append(row)
                    # Build coord dict for PNG from row
                    try:
                        all_coords.append(
                            {
                                "longitude": float(row.get("longitude", 0.0)),
                                "latitude": float(row.get("latitude", 0.0)),
                                "timestamp": int(float(row.get("timestamp", 0))),
                            }
                        )
                    except Exception:
                        pass
        # GeoJSON
        geo_path = sim_dir / "bev_cart_route.geojson"
        if geo_path.exists():
            try:
                data = _json.loads(geo_path.read_text(encoding="utf-8"))
                for feat in data.get("features", []):
                    feat = dict(feat)
                    props = dict(feat.get("properties", {}))
                    props["run"] = run_name
                    feat["properties"] = props
                    all_features.append(feat)
            except Exception:
                pass
        # Activity logs per cart (optional)
        for label in ("A", "B"):
            log_path = sim_dir / f"bev_cart_{label}_activity_log.json"
            if log_path.exists():
                try:
                    entries = _json.loads(log_path.read_text(encoding="utf-8"))
                    for e in entries:
                        e = dict(e)
                        e["id"] = label
                        e["run"] = run_name
                        all_logs.append(e)
                except Exception:
                    pass

    # Write combined CSV
    if all_rows:
        headers = list({k for row in all_rows for k in row.keys()})
        # Ensure stable header order
        preferred = ["timestamp", "latitude", "longitude", "current_hole", "type", "id", "run"]
        headers = preferred + [h for h in headers if h not in preferred]
        with (output_root / "bev_cart_coordinates.csv").open("w", newline="", encoding="utf-8") as f:
            writer = _csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for row in all_rows:
                writer.writerow(row)

    # Write combined GeoJSON
    if all_features:
        fc = {"type": "FeatureCollection", "features": all_features}
        (output_root / "bev_cart_route.geojson").write_text(_json.dumps(fc, indent=2), encoding="utf-8")

    # Write combined activity log
    if all_logs:
        (output_root / "bev_cart_activity_log.json").write_text(_json.dumps(all_logs, indent=2), encoding="utf-8")

    # Write single combined PNG
    if all_coords:
        render_beverage_cart_plot(all_coords, course_dir=output_root.parent / ".." / "courses" / "pinetree_country_club", save_path=output_root / "bev_cart_route.png")


def main() -> None:
    init_logging("INFO")
    course_dir = "courses/pinetree_country_club"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path("outputs") / f"{ts}_phase_11"
    output_root.mkdir(parents=True, exist_ok=True)

    all_results: List[Dict] = []
    for i in range(1, 6):
        result = run_once(i, course_dir, output_root)
        all_results.append(result)

    write_summary_md(all_results, output_root)
    write_phase_level_combined_artifacts(output_root)


if __name__ == "__main__":
    main()


