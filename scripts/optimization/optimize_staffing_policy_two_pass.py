#!/usr/bin/env python3
"""
Two-pass staffing and blocking policy optimizer.

Pass 1 (first_pass):
- Run 10 simulations with minimal outputs for ALL variant/runner combinations.

Pass 2 (second_pass):
- For the recommended option(s) per orders level, run another 10 simulations
  without the minimal-output flags to generate richer artifacts.

Notes:
- This substitutes the staged 4/8/8 logic with a simpler 10 + 10 confirmation.
- Outputs are organized under `<output_root>/<stamp>_<scenario>/{first_pass|second_pass}/orders_XXX/...`.

Example (single course):
  python scripts/optimization/optimize_staffing_policy_two_pass.py --course-dir courses/pinetree_country_club --tee-scenario real_tee_sheet --orders-levels 20 30 40 50 --runner-range 1-3 --concurrency 3

Example (all courses):
  python scripts/optimization/optimize_staffing_policy_two_pass.py --run-all-courses --tee-scenario real_tee_sheet --orders-levels 10 20 30 40 50 --runner-range 1-3 --concurrency 10
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Reuse helpers from the primary optimizer to avoid duplication
from scripts.optimization.optimize_staffing_policy import (
    BLOCKING_VARIANTS,
    BlockingVariant,
    aggregate_runs,
    build_feature_collection,
    choose_best_variant,
    parse_range,
    utility_score,
    _make_group_context,
    _row_from_context_and_agg,
    _write_group_aggregate_file,
    _write_group_aggregate_heatmap,
    _write_group_delivery_geojson,
    _write_final_csv,
)


def choose_top_variants(
    results_by_variant: Dict[str, Dict[int, Dict[str, Any]]], *, target_on_time: float, max_failed: float, max_p90: float
) -> List[Tuple[str, int, Dict[str, Any]]]:
    """Find all candidates that meet targets and return the top 3 based on utility score."""
    candidates: List[Tuple[str, int, Dict[str, Any]]] = []
    for variant_key, per_runner in results_by_variant.items():
        for n in sorted(per_runner.keys()):
            agg = per_runner[n]
            if not agg or not agg.get("runs"):
                continue

            p90_mean = agg.get("p90_mean", float("nan"))
            p90_meets = math.isnan(p90_mean) or p90_mean <= max_p90

            meets = (
                agg.get("on_time_wilson_lo", 0.0) >= target_on_time
                and agg.get("failed_mean", 1.0) <= max_failed
                and p90_meets
            )
            if meets:
                candidates.append((variant_key, n, agg))

    if not candidates:
        return []

    candidates.sort(key=lambda t: utility_score(t[0], t[1], t[2]))
    return candidates[:3]


def run_combo(
    *,
    py: str,
    course_dir: Path,
    scenario: str,
    runners: int,
    orders: int,
    runs: int,
    out: Path,
    log_level: str,
    variant: BlockingVariant,
    runner_speed: Optional[float],
    prep_time: Optional[int],
    minimal_output: bool,
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    cmd: List[str] = [
        py,
        "scripts/sim/run_new.py",
        "--course-dir",
        str(course_dir),
        "--tee-scenario",
        scenario,
        "--num-runners",
        str(runners),
        "--delivery-total-orders",
        str(orders),
        "--num-runs",
        str(runs),
        "--output-dir",
        str(out),
        "--log-level",
        log_level,
    ]

    # Minimal outputs only for first pass
    if minimal_output:
        cmd += ["--minimal-outputs"]
    # Always ensure only run_01 coordinates are generated and avoid auto-publish
    # so that aggregation and map copying are handled centrally after optimization
    cmd += ["--coordinates-only-for-first-run", "--skip-publish"]

    if variant.cli_flags:
        cmd += variant.cli_flags
    if runner_speed is not None:
        cmd += ["--runner-speed", str(runner_speed)]
    if prep_time is not None:
        cmd += ["--prep-time", str(prep_time)]
    subprocess.run(cmd, check=True)


def _collect_run_dirs(
    root: Path, orders: int, variant_key: str, runners: int, include_first: bool = True, include_second: bool = True
) -> List[Path]:
    """Collect run_* directories from first_pass and/or second_pass for a specific combo."""
    run_dirs: List[Path] = []
    details = f"orders_{orders:03d}/runners_{runners}/{variant_key}"
    if include_first:
        fp = root / "first_pass" / details
        if fp.exists():
            run_dirs += sorted([p for p in fp.glob("run_*") if p.is_dir()])
    if include_second:
        sp = root / "second_pass" / details
        if sp.exists():
            run_dirs += sorted([p for p in sp.glob("run_*") if p.is_dir()])
    return run_dirs


def meets_targets(agg: Dict[str, Any], args: argparse.Namespace) -> bool:
    """Check if an aggregated result meets performance targets."""
    if not agg or not agg.get("runs"):
        return False

    p90_mean = agg.get("p90_mean", float("nan"))
    p90_meets = math.isnan(p90_mean) or p90_mean <= args.max_p90

    return (
        agg.get("on_time_wilson_lo", 0.0) >= args.target_on_time
        and agg.get("failed_mean", 1.0) <= args.max_failed_rate
        and p90_meets
    )


def _publish_map_assets(*, optimization_root: Path, project_root: Path) -> None:
    """Finds and copies simulation artifacts to the map app's public directories."""

    # --- BEGIN MAP ASSETS PUBLISHING LOGIC ---
    # This code is moved and adapted from my-map-animation/run_map_app.py

    # Path Configuration
    map_animation_dir = project_root / "my-map-animation"
    public_dirs = [str(map_animation_dir / "public")]
    setup_public_dir = project_root / "my-map-setup" / "public"
    coordinates_dir_name = "coordinates"
    local_csv_file = str(map_animation_dir / "public" / "coordinates.csv")
    sim_base_dir = str(optimization_root)

    def _humanize(name: str) -> str:
        name = name.replace("-", " ").replace("_", " ").strip()
        parts = [p for p in name.split(" ") if p]
        return " ".join(w.capitalize() for w in parts) if parts else name

    def _parse_simulation_folder_name(folder_name: str) -> Dict[str, str]:
        result = {
            "date": "",
            "time": "",
            "bev_carts": "0",
            "runners": "0",
            "golfers": "0",
            "scenario": "",
            "original": folder_name,
        }
        if "_" in folder_name:
            parts = folder_name.split("_")
            if len(parts) > 0 and len(parts[0]) == 8 and parts[0].isdigit():
                result["date"] = parts[0]
                if len(parts) > 1 and len(parts[1]) == 6 and parts[1].isdigit():
                    result["time"] = parts[1]
                    config_parts = parts[2:]
                    config_str = "_".join(config_parts)
                    bev_match = re.search(r"(\d+)bev_?carts?", config_str, re.IGNORECASE)
                    if bev_match:
                        result["bev_carts"] = bev_match.group(1)
                    runner_match = re.search(r"(\d+)_?runners?", config_str, re.IGNORECASE)
                    if runner_match:
                        result["runners"] = runner_match.group(1)
                    golfer_match = re.search(r"(\d+)golfers?", config_str, re.IGNORECASE)
                    if golfer_match:
                        result["golfers"] = golfer_match.group(1)
                    scenario_parts = []
                    for part in config_parts:
                        if not (
                            re.match(r"^\d+[a-zA-Z]+$", part) or re.match(r"^(sim|run)_\d+$", part, re.IGNORECASE)
                        ):
                            scenario_parts.append(part)
                    if scenario_parts:
                        result["scenario"] = "_".join(scenario_parts)
        return result

    def _format_simple_simulation_name(parsed: Dict[str, str]) -> str:
        components = []
        config_parts = []
        if parsed["bev_carts"] != "0":
            config_parts.append(f"{parsed['bev_carts']} Cart{'s' if parsed['bev_carts'] != '1' else ''}")
        if parsed["runners"] != "0":
            config_parts.append(f"{parsed['runners']} Runner{'s' if parsed['runners'] != '1' else ''}")
        if parsed["golfers"] != "0":
            config_parts.append(f"{parsed['golfers']} Golfer{'s' if parsed['golfers'] != '1' else ''}")
        if config_parts:
            components.append(" + ".join(config_parts))
        if parsed["scenario"]:
            scenario_name = _humanize(parsed["scenario"])
            components.append(scenario_name)
        if "variant_key" in parsed and parsed["variant_key"] != "none":
            components.append(f"({_humanize(parsed['variant_key'])})")
        return " | ".join(components) if components else parsed["original"]

    def _create_group_name(parsed: Dict[str, str]) -> str:
        if parsed["scenario"]:
            return _humanize(parsed["scenario"])
        if parsed["bev_carts"] != "0" and parsed["runners"] != "0":
            return "Mixed Operations"
        elif parsed["bev_carts"] != "0":
            return "Beverage Cart Only"
        elif parsed["runners"] != "0":
            return "Delivery Runners Only"
        else:
            return "Other Simulations"

    def _get_course_id_from_run_dir(run_dir: Path) -> Optional[str]:
        try:
            results_path = run_dir / "results.json"
            if not results_path.exists():
                return None
            with results_path.open("r", encoding="utf-8") as f:
                results = json.load(f)
            course_dir_str = results.get("metadata", {}).get("course_dir")
            if isinstance(course_dir_str, str) and course_dir_str:
                return os.path.basename(course_dir_str.replace("\\", "/").rstrip("/"))
        except Exception:
            pass
        return None

    def _sanitize_and_copy_coordinates_csv(source_path: str, target_path: str) -> None:
        import csv as _csv

        with open(source_path, "r", newline="", encoding="utf-8") as fsrc:
            reader = _csv.DictReader(fsrc)
            fieldnames = reader.fieldnames or []
            rows = list(reader)
        first_move_ts_by_id: Dict[str, Optional[int]] = {}
        for r in rows:
            rid = str(r.get("id", "") or "")
            rtype = (r.get("type") or "").strip().lower()
            if rtype != "runner" and not rid.startswith("runner"):
                continue
            hole = (r.get("hole") or "").strip().lower()
            try:
                ts = int(float(r.get("timestamp") or 0))
            except Exception:
                continue
            if hole != "clubhouse":
                prev = first_move_ts_by_id.get(rid)
                if prev is None or ts < prev:
                    first_move_ts_by_id[rid] = ts
        filtered: List[Dict[str, str]] = []
        for r in rows:
            rid = str(r.get("id", "") or "")
            rtype = (r.get("type") or "").strip().lower()
            hole = (r.get("hole") or "").strip().lower()
            try:
                ts = int(float(r.get("timestamp") or 0))
            except Exception:
                filtered.append(r)
                continue
            first_move_ts = first_move_ts_by_id.get(rid)
            if (
                (rtype == "runner" or rid.startswith("runner"))
                and hole == "clubhouse"
                and first_move_ts is not None
                and ts < int(first_move_ts)
            ):
                continue
            filtered.append(r)
        chosen: Dict[Tuple[str, int], Dict[str, str]] = {}
        for r in filtered:
            rid = str(r.get("id", "") or "")
            try:
                ts = int(float(r.get("timestamp") or 0))
            except Exception:
                filtered.append(r)
                continue
            key = (rid, ts)
            hole = (r.get("hole") or "").strip().lower()
            if key not in chosen:
                chosen[key] = r
            else:
                prev_hole = (chosen[key].get("hole") or "").strip().lower()
                if prev_hole == "clubhouse" and hole != "clubhouse":
                    chosen[key] = r
        deduped = list(chosen.values())
        try:
            deduped.sort(key=lambda d: (str(d.get("id", "")), int(float(d.get("timestamp") or 0))))
        except Exception:
            pass
        with open(target_path, "w", newline="", encoding="utf-8") as fdst:
            writer = _csv.DictWriter(fdst, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in deduped:
                writer.writerow(r)

    def find_all_simulations() -> Dict[str, List[Tuple[str, str, str]]]:
        simulations: Dict[str, List[Tuple[str, str, str]]] = {}
        if os.path.exists(local_csv_file):
            any_outputs = (
                any(True for _ in Path(sim_base_dir).rglob("coordinates.csv"))
                if os.path.exists(sim_base_dir)
                else False
            )
            if not any_outputs:
                simulations.setdefault("Local", []).append(("coordinates", "GPS Coordinates", local_csv_file))
        if not os.path.exists(sim_base_dir):
            return simulations
        valid_filenames = {"coordinates.csv", "bev_cart_coordinates.csv"}
        for root, dirs, files in os.walk(sim_base_dir):
            csv_files = [f for f in files if f in valid_filenames]
            if not csv_files:
                continue
            for file_name in csv_files:
                full_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(full_path, sim_base_dir)
                parts = rel_path.split(os.sep)
                if len(parts) >= 3:
                    sim_folder_name = parts[-3]
                    run_folder = parts[-2]
                    parsed = _parse_simulation_folder_name(sim_folder_name)
                    group_name = _create_group_name(parsed)
                    base_sim_name = _format_simple_simulation_name(parsed)
                    run_id = run_folder.upper() if run_folder.startswith(("sim_", "run_")) else ""
                    if file_name == "coordinates.csv":
                        friendly_type = "GPS Coordinates"
                    elif file_name == "bev_cart_coordinates.csv":
                        friendly_type = "Beverage Cart GPS"
                    else:
                        friendly_type = os.path.splitext(file_name)[0].replace("_", " ").title()
                    display_components = [base_sim_name]
                    if run_id:
                        display_components.append(run_id)
                    display_components.append(friendly_type)
                    display_name = " | ".join(display_components)
                elif len(parts) >= 2:
                    sim_folder_name = parts[-2]
                    parsed = _parse_simulation_folder_name(sim_folder_name)
                    group_name = _create_group_name(parsed)
                    base_sim_name = _format_simple_simulation_name(parsed)
                    if file_name == "coordinates.csv":
                        friendly_type = "GPS Coordinates"
                    elif file_name == "bev_cart_coordinates.csv":
                        friendly_type = "Beverage Cart GPS"
                    else:
                        friendly_type = os.path.splitext(file_name)[0].replace("_", " ").title()
                    display_name = f"{base_sim_name} | {friendly_type}"
                else:
                    group_name = "Simulations"
                    display_name = f"Coordinates ({os.path.splitext(file_name)[0]})"
                sim_id = rel_path.replace(os.sep, "_").replace(".csv", "")
                simulations.setdefault(group_name, []).append((sim_id, display_name, full_path))
        sorted_simulations: Dict[str, List[Tuple[str, str, str]]] = {}
        for group in sorted(simulations.keys()):
            sorted_simulations[group] = sorted(simulations[group], key=lambda x: x[0])
        return sorted_simulations

    def _derive_combo_key_from_path(csv_path: str) -> Optional[str]:
        try:
            p = Path(csv_path)
            run_dir = p.parent
            variant_dir = run_dir.parent if run_dir.name.startswith("run_") else p.parent
            runners_dir = variant_dir.parent
            orders_dir = runners_dir.parent
            scenario_dir = orders_dir.parent
            if runners_dir.name.startswith("runners_") and orders_dir.name.startswith("orders_"):
                try:
                    n_runners = int(runners_dir.name.split("_")[1])
                except Exception:
                    n_runners = None
                try:
                    orders_val = int(orders_dir.name.split("_")[1])
                except Exception:
                    orders_val = None
                scenario = scenario_dir.name
                variant_key = variant_dir.name
                if n_runners is not None and orders_val is not None:
                    return f"{scenario}|orders_{orders_val:03d}|runners_{n_runners}|{variant_key}"
            for ancestor in p.parents:
                name = ancestor.name
                if ("runners" in name) and ("delivery_runner" in name or "runners_" in name):
                    scenario = None
                    orders_val = None
                    m_orders = re.search(r"orders[_-]?([0-9]{2,3})", name, re.IGNORECASE)
                    if m_orders:
                        try:
                            orders_val = int(m_orders.group(1))
                        except Exception:
                            orders_val = None
                    m_runners = re.search(r"runners[_-]?([0-9]+)", name, re.IGNORECASE)
                    n_runners = int(m_runners.group(1)) if m_runners else None
                    if n_runners and orders_val:
                        scenario = ancestor.parent.name
                        return f"{scenario}|orders_{orders_val:03d}|runners_{n_runners}"
            return None
        except Exception:
            return None

    def _select_representative_runs(all_items: List[Tuple[str, str, str]]) -> Dict[str, str]:
        selection_mode = os.environ.get("RUN_MAP_SELECT_RUNS", "").strip().lower()
        prefer_first_run = selection_mode in {"run_01", "first", "first_run"}
        groups: Dict[str, List[Tuple[str, str, str]]] = {}
        for sim_id, display_name, csv_path in all_items:
            key = _derive_combo_key_from_path(csv_path)
            if key:
                groups.setdefault(key, []).append((sim_id, display_name, csv_path))
        selected: Dict[str, str] = {}

        def load_metrics_for_run(run_dir: Path) -> Dict[str, float]:
            metrics: Dict[str, float] = {}
            try:
                candidates = [
                    *[
                        f
                        for f in os.listdir(run_dir)
                        if f.startswith("delivery_runner_metrics_run_") and f.endswith(".json")
                    ],
                ]
                chosen = None
                if candidates:
                    run_name = run_dir.name.lower()
                    chosen = None
                    for c in candidates:
                        if run_name in c.lower():
                            chosen = c
                            break
                    if not chosen:
                        chosen = sorted(candidates)[0]
                elif (run_dir / "simulation_metrics.json").exists():
                    chosen = "simulation_metrics.json"
                if not chosen:
                    return metrics
                with open(run_dir / chosen, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                return metrics
            try:
                on_time = data.get("on_time_rate")
                failed = data.get("failed_rate")
                p90 = data.get("delivery_cycle_time_p90")
                oph = data.get("orders_per_runner_hour")
                if on_time is None or p90 is None or oph is None:
                    dm = data.get("deliveryMetrics") or {}
                    on_time = dm.get("onTimeRate") if dm is not None else None
                    if isinstance(on_time, (int, float)) and on_time > 1.5:
                        on_time = float(on_time) / 100.0
                    p90 = dm.get("deliveryCycleTimeP90") if dm is not None else None
                    oph = dm.get("ordersPerRunnerHour") if dm is not None else None
                    failed = dm.get("failedRate") if isinstance(dm, dict) else data.get("failed_rate")
                    if isinstance(failed, (int, float)) and failed > 1.5:
                        failed = float(failed) / 100.0
                for k, v in {
                    "on_time": on_time,
                    "failed": failed,
                    "p90": p90,
                    "oph": oph,
                }.items():
                    if isinstance(v, (int, float)) and float("inf") != v and float("-inf") != v:
                        metrics[k] = float(v)
            except Exception:
                pass
            return metrics

        for key, items in groups.items():
            per_run: List[Tuple[str, Path]] = []
            for _, __, csv_path in items:
                run_dir = Path(csv_path).parent
                per_run.append((csv_path, run_dir))
            if len(per_run) <= 1:
                selected[per_run[0][0]] = per_run[0][0]
                continue
            if prefer_first_run:
                try:
                    for csv_path, run_dir in per_run:
                        if run_dir.name.lower() == "run_01":
                            selected[csv_path] = csv_path
                            break
                    else:
                        per_run_sorted = sorted(per_run, key=lambda t: t[1].name)
                        selected[per_run_sorted[0][0]] = per_run_sorted[0][0]
                    continue
                except Exception:
                    pass
            run_metrics: List[Tuple[str, Dict[str, float]]] = []
            for csv_path, run_dir in per_run:
                m = load_metrics_for_run(run_dir)
                run_metrics.append((csv_path, m))
            keys = ["on_time", "failed", "p90", "oph"]
            means: Dict[str, float] = {}
            stds: Dict[str, float] = {}
            for k in keys:
                vals = [m.get(k) for _, m in run_metrics if isinstance(m.get(k), (int, float))]
                if vals:
                    mu = sum(vals) / len(vals)
                    means[k] = mu
                    if len(vals) >= 2:
                        var = sum((x - mu) ** 2 for x in vals) / (len(vals) - 1)
                        stds[k] = (var**0.5) if var > 0 else 1.0
                    else:
                        stds[k] = 1.0
                else:
                    means[k] = 0.0
                    stds[k] = 1.0
            best_csv = per_run[0][0]
            best_dist = float("inf")
            for csv_path, m in run_metrics:
                dist = 0.0
                for k in keys:
                    v = m.get(k)
                    if isinstance(v, (int, float)):
                        z = (v - means[k]) / (stds.get(k) or 1.0)
                        dist += z * z
                if dist < best_dist:
                    best_dist = dist
                    best_csv = csv_path
            selected[best_csv] = best_csv
        return selected

    def get_file_info(file_path: str) -> str:
        try:
            with open(file_path, "r") as f:
                lines = f.readlines()
                if len(lines) > 1:
                    data_rows = len(lines) - 1
                    return f"{data_rows:,} coordinate points"
                else:
                    return "Empty file"
        except Exception as e:
            return f"Error reading file: {e}"

    def _generate_per_run_hole_geojson(run_dir: Path) -> Optional[Path]:
        try:
            results_path = run_dir / "results.json"
            if not results_path.exists():
                return None
            with results_path.open("r", encoding="utf-8") as f:
                results = json.load(f)
            course_dir = None
            try:
                course_dir = results.get("metadata", {}).get("course_dir")
            except Exception:
                course_dir = None
            if not course_dir:
                course_dir = str(project_root / "courses" / "pinetree_country_club")
            from golfsim.viz.heatmap_viz import (
                load_geofenced_holes,
                extract_order_data,
                calculate_delivery_time_stats,
            )

            hole_polygons = load_geofenced_holes(course_dir)
            order_data = extract_order_data(results)
            hole_stats = calculate_delivery_time_stats(order_data)
            import json as _json
            import geopandas as gpd

            features = []
            for hole_num, geom in hole_polygons.items():
                props = {"hole": int(hole_num)}
                stats = hole_stats.get(hole_num)
                if stats:
                    props.update(
                        {
                            "has_data": True,
                            "avg_time": float(stats.get("avg_time", 0.0)),
                            "min_time": float(stats.get("min_time", 0.0)),
                            "max_time": float(stats.get("max_time", 0.0)),
                            "count": int(stats.get("count", 0)),
                        }
                    )
                else:
                    props.update({"has_data": False})
                gdf = gpd.GeoDataFrame({"geometry": [geom]}, crs="EPSG:4326")
                feature_geom = _json.loads(gdf.to_json())["features"][0]["geometry"]
                features.append({"type": "Feature", "properties": props, "geometry": feature_geom})
            fc = {"type": "FeatureCollection", "features": features}
            out_path = run_dir / "hole_delivery_times.geojson"
            with out_path.open("w", encoding="utf-8") as f:
                _json.dump(fc, f)
            return out_path
        except Exception as e:
            return None

    def copy_hole_delivery_geojson(coordinates_dirs: List[str]) -> None:
        source_file = map_animation_dir / "public" / "hole_delivery_times.geojson"
        if os.path.exists(source_file):
            for public_dir in public_dirs:
                target_file = os.path.join(public_dir, "hole_delivery_times.geojson")
                try:
                    temp_target = target_file + ".tmp"
                    shutil.copy2(source_file, temp_target)
                    os.replace(temp_target, target_file)
                except Exception:
                    pass

    def copy_all_coordinate_files(
        all_simulations: Dict[str, List[Tuple[str, str, str]]], preferred_default_id: Optional[str] = None
    ) -> Tuple[bool, List[str]]:
        courses_being_updated = set()
        for _, file_options in all_simulations.items():
            for _, _, source_path in file_options:
                run_dir = Path(source_path).parent
                course_id = _get_course_id_from_run_dir(run_dir)
                if course_id:
                    courses_being_updated.add(course_id)
        if courses_being_updated:
            print(f"ℹ️  This run contains simulations for course(s): {', '.join(courses_being_updated)}")
        try:
            coordinates_dirs = []
            for public_dir in public_dirs:
                try:
                    stale_files = [
                        os.path.join(public_dir, "coordinates.csv"),
                        os.path.join(public_dir, "hole_delivery_times.geojson"),
                        os.path.join(public_dir, "hole_delivery_times_debug.geojson"),
                        os.path.join(public_dir, "simulation_metrics.json"),
                    ]
                    for f in stale_files:
                        if os.path.exists(f):
                            try:
                                os.remove(f)
                            except Exception:
                                pass
                except Exception:
                    pass
                coordinates_dir = os.path.join(public_dir, coordinates_dir_name)
                coordinates_dirs.append(coordinates_dir)
                os.makedirs(coordinates_dir, exist_ok=True)
            simulations_to_keep = []
            manifest_processed = False
            if courses_being_updated:
                for coordinates_dir in coordinates_dirs:
                    manifest_path = os.path.join(coordinates_dir, "manifest.json")
                    if not os.path.exists(manifest_path):
                        continue
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        try:
                            old_manifest = json.load(f)
                        except json.JSONDecodeError:
                            old_manifest = {}
                    current_dir_sims_to_keep = []
                    for sim_entry in old_manifest.get("simulations", []):
                        if sim_entry.get("courseId") in courses_being_updated:
                            for key in ["filename", "heatmapFilename", "metricsFilename", "holeDeliveryGeojson"]:
                                if filename := sim_entry.get(key):
                                    file_to_delete = os.path.join(coordinates_dir, filename)
                                    if os.path.exists(file_to_delete):
                                        try:
                                            os.remove(file_to_delete)
                                        except OSError:
                                            pass
                        else:
                            current_dir_sims_to_keep.append(sim_entry)
                    if not manifest_processed:
                        simulations_to_keep = current_dir_sims_to_keep
                        manifest_processed = True
            manifest = {"simulations": simulations_to_keep, "defaultSimulation": None, "courses": []}
            discovered_courses: Dict[str, str] = {}
            copied_count = 0
            total_size = 0
            id_to_mtime: Dict[str, float] = {}

            def _extract_orders_from_metrics(metrics_path: str) -> int | None:
                try:
                    with open(metrics_path, "r", encoding="utf-8") as f:
                        import json as _json

                        data = _json.load(f)
                    dm = data.get("deliveryMetrics") or {}
                    if isinstance(dm, dict):
                        orders = dm.get("totalOrders") or dm.get("orderCount")
                        if isinstance(orders, (int, float)):
                            return int(orders)
                    for key in ("totalOrders", "orderCount"):
                        if key in data and isinstance(data[key], (int, float)):
                            return int(data[key])
                except Exception:
                    return None
                return None

            def _extract_variant_info_from_metrics(
                metrics_path: str,
            ) -> Tuple[Optional[str], Optional[List[int]]]:
                try:
                    with open(metrics_path, "r", encoding="utf-8") as f:
                        import json as _json

                        data = _json.load(f)
                    variant_key = data.get("variantKey")
                    blocked_holes = data.get("blockedHoles")
                    return variant_key, blocked_holes
                except Exception:
                    return None, None

            flat_items: List[Tuple[str, str, str]] = []
            for gname, items in all_simulations.items():
                for sim_id, disp, src in items:
                    flat_items.append((sim_id, disp, src))
            selected_csvs = _select_representative_runs(flat_items)
            selected_mode_active = len(selected_csvs) > 0
            for group_name, file_options in all_simulations.items():
                for scenario_id, display_name, source_path in file_options:
                    if selected_mode_active:
                        key = _derive_combo_key_from_path(source_path)
                        if key and source_path not in selected_csvs:
                            continue
                    try:
                        p = Path(source_path)
                        parents = list(p.parents)
                        has_orders = any(parent.name.lower().startswith("orders_") for parent in parents)
                        has_delivery_runners = False
                        for parent in parents:
                            name = parent.name.lower()
                            if name.startswith("runners_"):
                                try:
                                    runner_count = int(name.split("_")[1])
                                    if runner_count > 0:
                                        has_delivery_runners = True
                                        break
                                except (ValueError, IndexError):
                                    continue
                        if not has_delivery_runners:
                            for parent in parents:
                                name = parent.name.lower()
                                if "delivery_runner_" in name and "_runners_" in name:
                                    match = re.search(r"_(\d+)_runners_", name)
                                    if match:
                                        try:
                                            runner_count = int(match.group(1))
                                            if runner_count > 0:
                                                has_delivery_runners = True
                                                break
                                        except ValueError:
                                            continue
                        if not (has_orders and has_delivery_runners):
                            continue
                    except Exception:
                        continue
                    if not os.path.exists(source_path):
                        continue
                    target_filename = f"{scenario_id}.csv"
                    all_copies_successful = True
                    sanitized_mode = os.path.basename(source_path) == "coordinates.csv"
                    for coordinates_dir in coordinates_dirs:
                        target_path = os.path.join(coordinates_dir, target_filename)
                        try:
                            if os.path.basename(source_path) == "coordinates.csv":
                                _sanitize_and_copy_coordinates_csv(source_path, target_path)
                            else:
                                shutil.copy2(source_path, target_path)
                        except Exception:
                            all_copies_successful = False
                            break
                        if os.path.exists(target_path):
                            source_size = os.path.getsize(source_path)
                            target_size = os.path.getsize(target_path)
                            if sanitized_mode:
                                if target_size <= 0:
                                    all_copies_successful = False
                                    break
                            else:
                                if source_size != target_size:
                                    all_copies_successful = False
                                    break
                        else:
                            all_copies_successful = False
                            break
                    if all_copies_successful:
                        copied_count += 1
                        total_size += source_size
                        csv_dir = os.path.dirname(source_path)
                        found_heatmap_filename: str | None = None
                        found_metrics_filename: str | None = None
                        found_hole_geojson_filename: str | None = None
                        orders_value: int | None = None
                        variant_key: str | None = "none"
                        blocked_holes: list[int] | None = []
                        for fname in os.listdir(csv_dir):
                            if fname in {"delivery_heatmap.png", "heatmap.png"}:
                                heatmap_source = os.path.join(csv_dir, fname)
                                for coordinates_dir in coordinates_dirs:
                                    heatmap_filename = f"{scenario_id}_{fname}"
                                    heatmap_target = os.path.join(coordinates_dir, heatmap_filename)
                                    try:
                                        shutil.copy2(heatmap_source, heatmap_target)
                                        found_heatmap_filename = heatmap_filename
                                    except Exception:
                                        pass
                                break
                        metrics_candidates = []
                        for fname in os.listdir(csv_dir):
                            if fname == "simulation_metrics.json":
                                metrics_candidates = [fname]
                                break
                            if fname.startswith("delivery_runner_metrics_run_") and fname.endswith(".json"):
                                metrics_candidates.append(fname)
                        if metrics_candidates:
                            metrics_source = os.path.join(csv_dir, metrics_candidates[0])
                            for coordinates_dir in coordinates_dirs:
                                metrics_filename = f"{scenario_id}_metrics.json"
                                metrics_target = os.path.join(coordinates_dir, metrics_filename)
                                try:
                                    shutil.copy2(metrics_source, metrics_target)
                                    found_metrics_filename = metrics_filename
                                except Exception:
                                    pass
                            try:
                                orders_value = _extract_orders_from_metrics(metrics_source)
                                variant_key, blocked_holes = _extract_variant_info_from_metrics(metrics_source)
                            except Exception:
                                orders_value = None
                                variant_key = None
                                blocked_holes = None
                        course_id: Optional[str] = None
                        course_name: Optional[str] = None
                        try:
                            results_path = os.path.join(csv_dir, "results.json")
                            if os.path.exists(results_path):
                                with open(results_path, "r", encoding="utf-8") as f:
                                    _results = json.load(f)
                                course_dir_str = None
                                try:
                                    course_dir_str = _results.get("metadata", {}).get("course_dir")
                                except Exception:
                                    course_dir_str = None
                                if isinstance(course_dir_str, str) and course_dir_str:
                                    course_id = os.path.basename(course_dir_str.replace("\\", "/").rstrip("/"))
                                    course_name = _humanize(course_id)
                        except Exception:
                            course_id = None
                            course_name = None
                        if course_id and course_name:
                            discovered_courses[course_id] = course_name
                        try:
                            existing_geo = None
                            for fname in os.listdir(csv_dir):
                                if fname.startswith("hole_delivery_times") and fname.endswith(".geojson"):
                                    existing_geo = os.path.join(csv_dir, fname)
                                    break
                            if not existing_geo:
                                maybe = _generate_per_run_hole_geojson(Path(csv_dir))
                                if maybe and os.path.exists(maybe):
                                    existing_geo = str(maybe)
                            if existing_geo:
                                for coordinates_dir in coordinates_dirs:
                                    hole_geojson_filename = f"hole_delivery_times_{scenario_id}.geojson"
                                    hole_geojson_target = os.path.join(coordinates_dir, hole_geojson_filename)
                                    try:
                                        shutil.copy2(existing_geo, hole_geojson_target)
                                        found_hole_geojson_filename = hole_geojson_filename
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                        file_info = get_file_info(source_path)
                        try:
                            mtime = os.path.getmtime(source_path)
                            id_to_mtime[scenario_id] = mtime
                            last_modified_iso = datetime.fromtimestamp(mtime).isoformat()
                        except Exception:
                            last_modified_iso = None
                        path_parts = Path(source_path).parts
                        sim_folder_name = None
                        for i, part in enumerate(path_parts):
                            if "delivery_runner" in part and "runners" in part:
                                sim_folder_name = part
                                break
                        parsed = _parse_simulation_folder_name(sim_folder_name) if sim_folder_name else {}
                        extracted_runners: Optional[int] = None
                        extracted_orders: Optional[int] = None
                        for part in path_parts:
                            m_r = re.match(r"runners[_-]?([0-9]+)", part, re.IGNORECASE)
                            if m_r:
                                try:
                                    extracted_runners = int(m_r.group(1))
                                except Exception:
                                    pass
                            m_o = re.match(r"orders[_-]?([0-g]{2,3})", part, re.IGNORECASE)
                            if m_o:
                                try:
                                    extracted_orders = int(m_o.group(1))
                                except Exception:
                                    pass
                        meta = {
                            "runners": (int(parsed.get("runners", "0") or 0) if isinstance(parsed, dict) else None)
                            or extracted_runners,
                            "bevCarts": int(parsed.get("bev_carts", "0") or 0) if isinstance(parsed, dict) else None,
                            "golfers": int(parsed.get("golfers", "0") or 0) if isinstance(parsed, dict) else None,
                            "scenario": parsed.get("scenario") if isinstance(parsed, dict) else None,
                            "orders": (int(orders_value) if isinstance(orders_value, (int, float)) else None)
                            or extracted_orders,
                            "lastModified": last_modified_iso,
                            "blockedHoles": blocked_holes,
                        }
                        entry = {
                            "id": scenario_id,
                            "name": f"{group_name}: {display_name}",
                            "filename": target_filename,
                            "description": file_info,
                            "variantKey": variant_key or "none",
                            "meta": {k: v for k, v in meta.items() if v is not None},
                        }
                        if course_id:
                            entry["courseId"] = course_id
                        if course_name:
                            entry["courseName"] = course_name
                        if found_heatmap_filename:
                            entry["heatmapFilename"] = found_heatmap_filename
                        if found_metrics_filename:
                            entry["metricsFilename"] = found_metrics_filename
                        if found_hole_geojson_filename:
                            entry["holeDeliveryGeojson"] = found_hole_geojson_filename
                        manifest["simulations"].append(entry)
                    else:
                        return False, []
            if manifest["simulations"]:
                env_default_id = os.environ.get("DEFAULT_SIMULATION_ID", "").strip()
                chosen_id = (preferred_default_id or env_default_id or "").strip()
                selected_default = None
                if chosen_id:
                    for sim in manifest["simulations"]:
                        if sim["id"] == chosen_id:
                            selected_default = sim
                            break
                if not selected_default:
                    if id_to_mtime:
                        try:
                            newest_id = max(id_to_mtime.items(), key=lambda kv: kv[1])[0]
                            selected_default = next(
                                (sim for sim in manifest["simulations"] if sim["id"] == newest_id), None
                            )
                        except Exception:
                            selected_default = None
                if not selected_default:
                    selected_default = next(
                        (sim for sim in manifest["simulations"] if not sim["name"].startswith("Local:")),
                        manifest["simulations"][0],
                    )
                manifest["defaultSimulation"] = selected_default["id"]
            if discovered_courses:
                items = list(discovered_courses.items())
                items.sort(key=lambda kv: (0 if kv[0] == "pinetree_country_club" else 1, kv[1].lower()))
                manifest["courses"] = [{"id": cid, "name": cname} for cid, cname in items]
            for coordinates_dir in coordinates_dirs:
                manifest_path = os.path.join(coordinates_dir, "manifest.json")
                with open(manifest_path, "w") as f:
                    json.dump(manifest, f, indent=2)
            metrics_source = map_animation_dir / "public" / "simulation_metrics.json"
            if os.path.exists(metrics_source):
                for coordinates_dir in coordinates_dirs:
                    metrics_target = os.path.join(coordinates_dir, "simulation_metrics.json")
                    try:
                        shutil.copy2(metrics_source, metrics_target)
                    except Exception:
                        pass
            copy_hole_delivery_geojson(coordinates_dirs)
            return True, list(discovered_courses.keys())
        except Exception:
            return False, []

    def ensure_setup_required_assets(course_ids: list[str]) -> None:
        try:
            courses_base_dir = project_root / "courses"
            target_dirs = [setup_public_dir, map_animation_dir / "public"]
            for course_id in course_ids:
                course_src_dir = courses_base_dir / course_id
                for base in target_dirs:
                    course_target_dir = base / course_id
                    course_target_dir.mkdir(exist_ok=True)
                assets_to_copy = {
                    "holes_connected.geojson": f"geojson{os.sep}holes_connected.geojson",
                    "cart_paths.geojson": f"geojson{os.sep}cart_paths.geojson",
                    "course_polygon.geojson": f"geojson{os.sep}course_polygon.geojson",
                    "holes.geojson": f"geojson{os.sep}holes.geojson",
                    "greens.geojson": f"geojson{os.sep}greens.geojson",
                    "tees.geojson": f"geojson{os.sep}tees.geojson",
                    "holes_geofenced.geojson": f"geojson{os.sep}generated{os.sep}holes_geofenced.geojson",
                }
                for target_name, source_subpath in assets_to_copy.items():
                    source_path = course_src_dir / source_subpath
                    if not source_path.exists():
                        if target_name == "holes_connected.geojson":
                            fallback_dir = map_animation_dir / "public" / course_id
                            if fallback_dir.exists():
                                source_path = fallback_dir / target_name
                        if not source_path.exists():
                            continue
                    for base in target_dirs:
                        course_target_dir = base / course_id
                        target_path = course_target_dir / target_name
                        try:
                            if (
                                not target_path.exists()
                                or source_path.stat().st_mtime > target_path.stat().st_mtime
                            ):
                                shutil.copy2(str(source_path), str(target_path))
                        except Exception:
                            pass
        except Exception:
            pass

    # Main publishing logic starts here
    try:
        all_simulations = find_all_simulations()
        if not all_simulations:
            print("No new simulation results found to publish.")
            return

        ok, courses = copy_all_coordinate_files(all_simulations, preferred_default_id=None)
        if not ok:
            print("⚠️  Failed to copy coordinate files for map display.")
            return

        ensure_setup_required_assets(courses)
        print("✅ Map assets updated successfully.")

    except Exception as e:
        print(f"⚠️  Skipped map asset update due to error: {e}")


def main() -> None:
    p = argparse.ArgumentParser(description="Two-pass optimization: 10 minimal for all; 10 full for winners")
    p.add_argument("--course-dir", default="courses/pinetree_country_club")
    p.add_argument(
        "--run-all-courses", action="store_true", help="Run optimization for all courses in the 'courses' directory."
    )
    p.add_argument("--tee-scenario", default="real_tee_sheet")
    p.add_argument("--orders-levels", nargs="+", type=int, default=None, help="Orders totals to simulate (required unless --summarize-only)")
    p.add_argument("--runner-range", type=str, default="1-3")
    p.add_argument("--first-pass-runs", type=int, default=10, help="runs per combo in first pass (minimal outputs)")
    p.add_argument("--second-pass-runs", type=int, default=10, help="runs for winner confirmation in second pass (full outputs)")
    p.add_argument("--python-bin", default=sys.executable)
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--runner-speed", type=float, default=None)
    p.add_argument("--prep-time", type=int, default=None)
    p.add_argument("--variants", nargs="+", default=[v.key for v in BLOCKING_VARIANTS], help="Subset of variant keys to test")
    p.add_argument("--output-root", default=None, help="Base for outputs, defaults to output/<course_name>")
    p.add_argument("--summarize-only", action="store_true", help="Skip running sims; summarize an existing output root")
    p.add_argument("--existing-root", type=str, default=None, help="Path to existing optimization output root to summarize")
    # Targets for recommendation
    p.add_argument("--target-on-time", type=float, default=0.90)
    p.add_argument("--max-failed-rate", type=float, default=0.05)
    p.add_argument("--max-p90", type=float, default=40.0)
    p.add_argument("--concurrency", type=int, default=max(1, min(4, (os.cpu_count() or 2))), help="max concurrent simulations")
    p.add_argument("--auto-report", action="store_true", help="Automatically generate GM-friendly reports after simulations complete")
    args = p.parse_args()

    project_root = Path(__file__).resolve().parents[2]

    if args.run_all_courses:
        courses_root = project_root / "courses"
        # A course is valid if it's a directory and has a tee times config.
        # This helps filter out temporary directories or copies.
        course_dirs = [
            d for d in courses_root.iterdir() if d.is_dir() and (d / "config" / "tee_times_config.json").exists()
        ]

        # Reconstruct the command line, removing --run-all-courses and any existing --course-dir
        cmd_args = [sys.argv[0]]  # script name
        i = 1
        while i < len(sys.argv):
            arg = sys.argv[i]
            if arg == "--run-all-courses":
                i += 1
                continue
            if arg == "--course-dir":
                i += 2  # skip value
                continue
            if arg.startswith("--course-dir="):
                i += 1
                continue
            cmd_args.append(arg)
            i += 1

        base_cmd = [sys.executable] + cmd_args

        print(f"Found {len(course_dirs)} valid courses to process.")
        for course_d in course_dirs:
            print(f"\n{'=' * 20}\nRunning for course: {course_d.name}\n{'=' * 20}\n")
            cmd = base_cmd + ["--course-dir", str(course_d.resolve())]
            subprocess.run(cmd, check=False)
        return
    
    course_dir = Path(args.course_dir)
    if not course_dir.is_absolute():
        course_dir = (project_root / args.course_dir).resolve()
    if not course_dir.exists():
        print(json.dumps({"error": f"Course dir not found: {course_dir}"}))
        sys.exit(1)

    variant_map: Dict[str, BlockingVariant] = {v.key: v for v in BLOCKING_VARIANTS}
    selected_variants: List[BlockingVariant] = [variant_map[k] for k in args.variants if k in variant_map]
    runner_values = parse_range(args.runner_range)

    # Determine output root
    if args.summarize_only:
        if not args.existing_root:
            print(json.dumps({"error": "--summarize-only requires --existing-root <path>"}))
            sys.exit(2)
        root = Path(args.existing_root)
        if not root.is_absolute():
            root = (project_root / args.existing_root)
        if not root.exists():
            print(json.dumps({"error": f"Existing root not found: {root}"}))
            sys.exit(2)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if args.output_root:
            out_base = Path(args.output_root)
            if not out_base.is_absolute():
                out_base = project_root / out_base
        else:
            # Extract course name from course_dir path
            course_name = course_dir.name
            out_base = project_root / "output" / course_name
        root = out_base / f"{stamp}_{args.tee_scenario}"

    # Identify orders levels
    if args.summarize_only:
        orders_found: List[int] = []
        seen: set = set()
        for pass_dir in [root / "first_pass", root / "second_pass"]:
            if not pass_dir.exists():
                continue
            for d in sorted(pass_dir.glob("orders_*")):
                if not d.is_dir():
                    continue
                try:
                    val = int(str(d.name).split("_")[-1])
                    if val not in seen:
                        orders_found.append(val)
                        seen.add(val)
                except Exception:
                    continue
        # Fallback for legacy layouts that may have orders_* at the root
        if not orders_found:
            for d in sorted(root.glob("orders_*")):
                if not d.is_dir():
                    continue
                try:
                    val = int(str(d.name).split("_")[-1])
                    if val not in seen:
                        orders_found.append(val)
                        seen.add(val)
                except Exception:
                    continue
        orders_iter = sorted(orders_found)
    else:
        if not args.orders_levels:
            print(json.dumps({"error": "--orders-levels is required unless --summarize-only is set"}))
            sys.exit(2)
        orders_iter = args.orders_levels

    summary: Dict[int, Dict[str, Any]] = {}
    csv_rows: List[Dict[str, Any]] = []

    for orders in orders_iter:
        results_by_variant: Dict[str, Dict[int, Dict[str, Any]]] = {}

        # First pass: run all combos (minimal outputs)
        if not args.summarize_only:
            future_to_combo: Dict[Any, Tuple[BlockingVariant, int, Path]] = {}
            with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
                for variant in selected_variants:
                    for n in runner_values:
                        details = f"orders_{orders:03d}/runners_{n}/{variant.key}"
                        out_dir = root / "first_pass" / details
                        group_dir = root / "first_pass" / details
                        fut = executor.submit(
                            run_combo,
                            py=args.python_bin,
                            course_dir=course_dir,
                            scenario=args.tee_scenario,
                            runners=n,
                            orders=orders,
                            runs=args.first_pass_runs,
                            out=out_dir,
                            log_level=args.log_level,
                            variant=variant,
                            runner_speed=args.runner_speed,
                            prep_time=args.prep_time,
                            minimal_output=True,
                        )
                        future_to_combo[fut] = (variant, n, group_dir)
                for fut in as_completed(future_to_combo):
                    _ = fut.result()

        # Aggregate after first pass (only first_pass runs for selection)
        for variant in selected_variants:
            for n in runner_values:
                details = f"orders_{orders:03d}/runners_{n}/{variant.key}"
                group_dir = root / "first_pass" / details
                run_dirs = _collect_run_dirs(
                    root, orders=orders, variant_key=variant.key, runners=n, include_first=True, include_second=False
                )
                agg = aggregate_runs(run_dirs)
                results_by_variant.setdefault(variant.key, {})[n] = agg
                context = _make_group_context(
                    course_dir=course_dir,
                    tee_scenario=args.tee_scenario,
                    orders=orders,
                    variant_key=variant.key,
                    runners=n,
                )
                _write_group_aggregate_file(group_dir, context, agg)
                # Write averaged heatmap across available runs (best-effort)
                _write_group_aggregate_heatmap(
                    group_dir,
                    course_dir=course_dir,
                    tee_scenario=args.tee_scenario,
                    variant_key=variant.key,
                    runners=n,
                    run_dirs=run_dirs,
                )
                _write_group_delivery_geojson(
                    group_dir,
                    course_dir=course_dir,
                    tee_scenario=args.tee_scenario,
                    variant_key=variant.key,
                    runners=n,
                )
                _row = _row_from_context_and_agg(context, agg, group_dir)
                _write = _row  # clarity
                # Upsert into CSV rows
                from scripts.optimization.optimize_staffing_policy import _upsert_row  # local import to avoid polluting top

                _upsert_row(csv_rows, _write)

        # Select top 3 + baseline for each runner count for the second pass
        winners_for_2nd_pass: List[Tuple[str, int]] = []
        for n in runner_values:
            candidates_for_n: List[Tuple[str, int, Dict[str, Any]]] = []
            for variant in selected_variants:
                if variant.key == "none":
                    continue
                agg = results_by_variant.get(variant.key, {}).get(n)
                if meets_targets(agg, args):
                    candidates_for_n.append((variant.key, n, agg))

            candidates_for_n.sort(key=lambda t: utility_score(t[0], t[1], t[2]))
            top_3_blocking_for_n = candidates_for_n[:3]
            for v_key, v_runners, _ in top_3_blocking_for_n:
                winners_for_2nd_pass.append((v_key, v_runners))

            none_agg = results_by_variant.get("none", {}).get(n)
            if meets_targets(none_agg, args):
                winners_for_2nd_pass.append(("none", n))

        winners = sorted(list(set(winners_for_2nd_pass)))

        if not winners:
            print(f"Orders {orders}: No variant met targets up to {max(runner_values)} runners after first pass.")
        else:
            print(f"Orders {orders}: Found {len(winners)} candidates for second pass...")
            for v_key, v_runners in winners:
                desc = next((v.description for v in BLOCKING_VARIANTS if v.key == v_key), v_key)
                print(f"  - Candidate: {v_runners} runner(s) with policy: {desc}")

            # Second pass: run confirmation for all winners (full outputs)
            if not args.summarize_only:
                with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
                    futures = []
                    for v_key, v_runners in winners:
                        details = f"orders_{orders:03d}/runners_{v_runners}/{v_key}"
                        out_dir = root / "second_pass" / details
                        fut = executor.submit(
                            run_combo,
                            py=args.python_bin,
                            course_dir=course_dir,
                            scenario=args.tee_scenario,
                            runners=v_runners,
                            orders=orders,
                            runs=args.second_pass_runs,
                            out=out_dir,
                            log_level=args.log_level,
                            variant=next(v for v in BLOCKING_VARIANTS if v.key == v_key),
                            runner_speed=args.runner_speed,
                            prep_time=args.prep_time,
                            minimal_output=False,
                        )
                        futures.append(fut)
                    for fut in as_completed(futures):
                        _ = fut.result()

            # Re-aggregate winners including both passes
            for v_key, v_runners in winners:
                details = f"orders_{orders:03d}/runners_{v_runners}/{v_key}"
                group_dir = root / "second_pass" / details
                win_run_dirs = _collect_run_dirs(
                    root, orders=orders, variant_key=v_key, runners=v_runners, include_first=True, include_second=True
                )
                win_agg = aggregate_runs(win_run_dirs)
                results_by_variant.setdefault(v_key, {})[v_runners] = win_agg
                win_context = _make_group_context(
                    course_dir=course_dir,
                    tee_scenario=args.tee_scenario,
                    orders=orders,
                    variant_key=v_key,
                    runners=v_runners,
                )
                _write_group_aggregate_file(group_dir, win_context, win_agg)
                _write_group_aggregate_heatmap(
                    group_dir,
                    course_dir=course_dir,
                    tee_scenario=args.tee_scenario,
                    variant_key=v_key,
                    runners=v_runners,
                    run_dirs=win_run_dirs,
                )
                _write_group_delivery_geojson(
                    group_dir,
                    course_dir=course_dir,
                    tee_scenario=args.tee_scenario,
                    variant_key=v_key,
                    runners=v_runners,
                )
                from scripts.optimization.optimize_staffing_policy import _upsert_row

                _upsert_row(csv_rows, _row_from_context_and_agg(win_context, win_agg, group_dir))

        # Final choice after second pass
        chosen = choose_best_variant(
            results_by_variant,
            target_on_time=args.target_on_time,
            max_failed=args.max_failed_rate,
            max_p90=args.max_p90,
        )

        # Baseline reporting for transparency (no-blocks)
        baseline_none_runners = None
        if "none" in results_by_variant:
            for n in sorted(results_by_variant["none"].keys()):
                agg = results_by_variant["none"][n]
                if not agg or not agg.get("runs"):
                    continue
                p90_mean = agg.get("p90_mean", float("nan"))
                p90_meets = math.isnan(p90_mean) or p90_mean <= args.max_p90
                if (
                    agg.get("on_time_wilson_lo", 0.0) >= args.target_on_time
                    and agg.get("failed_mean", 1.0) <= args.max_failed_rate
                    and p90_meets
                ):
                    baseline_none_runners = n
                    break
        if baseline_none_runners is not None:
            print(f"Orders {orders} (no blocked holes): Recommended {baseline_none_runners} runner(s).")
        else:
            print(f"Orders {orders} (no blocked holes): No runner count up to {max(runner_values)} met targets.")

        # Persist summary entry
        summary[orders] = {
            "chosen": {
                "variant": chosen[0] if chosen else None,
                "runners": chosen[1] if chosen else None,
                "metrics": chosen[2] if chosen else None,
            },
            "per_variant": results_by_variant,
            "baseline_none": {
                "runners": baseline_none_runners,
                "metrics": results_by_variant.get("none", {}).get(baseline_none_runners) if baseline_none_runners is not None else None,
            },
        }

    # Print machine-readable JSON at the end (with serialization fix)
    def make_serializable(obj):
        """Convert non-serializable objects to serializable format"""
        if hasattr(obj, '__dict__'):
            return {k: make_serializable(v) for k, v in obj.__dict__.items() if not k.startswith('_')}
        elif isinstance(obj, dict):
            return {k: make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [make_serializable(item) for item in obj]
        elif isinstance(obj, (str, int, float, bool)) or obj is None:
            return obj
        else:
            return str(obj)  # fallback to string representation
    
    serializable_summary = make_serializable(summary)
    
    print(
        json.dumps(
            {
                "course": str(course_dir),
                "tee_scenario": args.tee_scenario,
                "targets": {
                    "on_time": args.target_on_time,
                    "max_failed": args.max_failed_rate,
                    "max_p90": args.max_p90,
                },
                "orders_levels": list(orders_iter),
                "summary": serializable_summary,
                "output_root": str(root),
            },
            indent=2,
        )
    )

    # Write final CSV combining group aggregates
    try:
        csv_path = _write_final_csv(root, csv_rows)
        if csv_path is not None:
            print(f"Aggregated metrics CSV written to {csv_path}")
    except Exception:
        pass

    # Generate reports if requested
    if args.auto_report and not args.summarize_only:
        try:
            print(f"\n📊 Generating GM-friendly reports for {root}")
            report_cmd = [
                sys.executable,
                "scripts/report/auto_report.py",
                "--scenario-dir", str(root)
            ]
            result = subprocess.run(report_cmd, check=False, cwd=project_root)
            if result.returncode == 0:
                print("✅ Reports generated successfully.")
                # Open the scenario index
                index_path = root / "index.html"
                if index_path.exists():
                    print(f"🎯 Scenario index available at: {index_path}")
                    try:
                        subprocess.run(["start", str(index_path)], shell=True, check=False)
                    except Exception:
                        pass
            else:
                print("⚠️  Report generation completed with warnings.")
        except Exception as e:
            print(f"⚠️  Report generation failed: {e}")

    # Post-run: sync assets for this specific course only
    try:
        print(f"Syncing assets for course: {course_dir.name}")
        sync_cmd = [
            sys.executable, 
            "sync_simulation_assets.py"
        ]
        subprocess.run(sync_cmd, check=False, cwd=project_root)
        print("✅ Assets synced successfully.")
    except Exception as e:
        print(f"⚠️  Asset sync failed: {e}")


if __name__ == "__main__":
    main()


