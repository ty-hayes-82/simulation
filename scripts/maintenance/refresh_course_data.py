#!/usr/bin/env python3
"""
Refresh an existing course's extracted files under courses/<course_id>/.

Steps:
1) Resolve the course directory by --course-id (must exist under courses/)
2) Load clubhouse coordinates from config/simulation_config.json
3) Clear generated artifacts (geojson/, pkl/, route_summary.json)
4) Re-run the extractor with the same process and options

Example:
    python scripts/maintenance/refresh_course_data.py \
        --course-id keswick_hall \
        --radius-km 2.0 \
        --pitch-radius-yards 200 \
        --water-radius-yards 200 \
        --simplify 5
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from golfsim.config.loaders import load_simulation_config


def _ensure_course_dir(course_id: str) -> Path:
    root = Path(__file__).parent.parent.parent
    courses_dir = root / "courses"
    course_dir = courses_dir / course_id
    if not course_dir.exists() or not course_dir.is_dir():
        raise FileNotFoundError(f"Course directory not found: {course_dir}")
    return course_dir


def _load_clubhouse_latlon(course_dir: Path) -> tuple[float, float]:
    cfg = load_simulation_config(course_dir)
    try:
        lon, lat = cfg.clubhouse  # loaders returns (lon, lat)
        return float(lat), float(lon)
    except Exception as e:  # noqa: BLE001
        raise ValueError(
            f"Invalid clubhouse coordinates in {course_dir}/config/simulation_config.json: {e}"
        )


def _derive_course_name(course_id: str, course_dir: Path) -> str:
    # Prefer explicit course_name from config if present
    try:
        config_path = course_dir / "config" / "simulation_config.json"
        if config_path.exists():
            with config_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            name = data.get("course_name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    except Exception:
        pass
    # Fallback: prettify the folder name
    return course_id.replace("_", " ").title()


def _clean_generated_files(course_dir: Path, dry_run: bool) -> None:
    geojson_dir = course_dir / "geojson"
    pkl_dir = course_dir / "pkl"
    route_summary = course_dir / "route_summary.json"

    for path in (geojson_dir, pkl_dir):
        if path.exists() and path.is_dir():
            if dry_run:
                print(f"[dry-run] Would remove directory: {path}")
            else:
                shutil.rmtree(path, ignore_errors=True)
                print(f"Removed directory: {path}")

    if route_summary.exists():
        if dry_run:
            print(f"[dry-run] Would remove file: {route_summary}")
        else:
            try:
                route_summary.unlink()
                print(f"Removed file: {route_summary}")
            except Exception:
                pass


def _build_extractor_cmd(
    course_name: str,
    clubhouse_lat: float,
    clubhouse_lon: float,
    radius_km: float,
    pitch_radius_yards: float,
    water_radius_yards: float,
    output_dir: Path,
    simplify: float | None,
    geofence_step: float | None,
    geofence_smooth: float | None,
    geofence_max_points: int | None,
) -> list[str]:
    root = Path(__file__).parent.parent.parent
    extractor = root / "scripts" / "routing" / "extract_course_data.py"
    cmd: list[str] = [
        sys.executable,
        str(extractor),
        "--course",
        course_name,
        "--clubhouse-lat",
        str(float(clubhouse_lat)),
        "--clubhouse-lon",
        str(float(clubhouse_lon)),
        "--radius-km",
        str(float(radius_km)),
        "--include-sports-pitch",
        "--pitch-radius-yards",
        str(float(pitch_radius_yards)),
        "--include-water",
        "--water-radius-yards",
        str(float(water_radius_yards)),
        "--output-dir",
        str(output_dir),
    ]

    if simplify is not None:
        cmd.extend(["--simplify", str(float(simplify))])
    if geofence_step is not None:
        cmd.extend(["--geofence-step", str(float(geofence_step))])
    if geofence_smooth is not None:
        cmd.extend(["--geofence-smooth", str(float(geofence_smooth))])
    if geofence_max_points is not None:
        cmd.extend(["--geofence-max-points", str(int(geofence_max_points))])

    return cmd


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh extracted files for an existing course")
    parser.add_argument("--course-id", required=True, help="Folder name under courses/, e.g., keswick_hall")
    parser.add_argument("--course-name", default=None, help="Readable course name for OSM search; defaults from config or folder name")
    parser.add_argument("--radius-km", type=float, default=2.0, help="OSM search radius in km (default: 2.0)")
    parser.add_argument("--pitch-radius-yards", type=float, default=200.0, help="Radius for sports pitches from clubhouse (yards)")
    parser.add_argument("--water-radius-yards", type=float, default=200.0, help="Radius for pools/water from clubhouse (yards)")
    parser.add_argument("--simplify", nargs="?", type=float, const=5.0, default=5.0, help="Simplification tolerance in meters (default 5.0; use flag alone to apply 5.0)")
    parser.add_argument("--geofence-step", type=float, default=None, help="Densify step (meters) override")
    parser.add_argument("--geofence-smooth", type=float, default=None, help="Smoothing distance (meters) override")
    parser.add_argument("--geofence-max-points", type=int, default=None, help="Max seed points per hole override")
    parser.add_argument("--dry-run", action="store_true", help="Show actions without modifying files")
    parser.add_argument("--skip-clean", action="store_true", help="Do not remove existing generated files before regenerating")

    args = parser.parse_args()

    course_dir = _ensure_course_dir(args.course_id)
    clubhouse_lat, clubhouse_lon = _load_clubhouse_latlon(course_dir)
    course_name = args.course_name or _derive_course_name(args.course_id, course_dir)

    print(f"Course: {course_name}  (id={args.course_id})")
    print(f"Clubhouse: lat={clubhouse_lat}, lon={clubhouse_lon}")
    print(f"Directory: {course_dir}")

    if not args.skip_clean:
        _clean_generated_files(course_dir, args.dry_run)
    else:
        print("Skipping clean step (--skip-clean)")

    cmd = _build_extractor_cmd(
        course_name=course_name,
        clubhouse_lat=clubhouse_lat,
        clubhouse_lon=clubhouse_lon,
        radius_km=args.radius_km,
        pitch_radius_yards=args.pitch_radius_yards,
        water_radius_yards=args.water_radius_yards,
        output_dir=course_dir,
        simplify=args.simplify,
        geofence_step=args.geofence_step,
        geofence_smooth=args.geofence_smooth,
        geofence_max_points=args.geofence_max_points,
    )

    print("Running extractor:")
    print(" ".join(cmd))

    if args.dry_run:
        print("[dry-run] Skipping extractor execution")
        return 0

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:  # noqa: BLE001
        print(f"Extractor failed with exit code {e.returncode}")
        return e.returncode or 1
    except Exception as e:  # noqa: BLE001
        print(f"Failed to execute extractor: {e}")
        return 1

    print("\n✅ Refresh complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


