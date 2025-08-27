#!/usr/bin/env python3
"""
GPS Coordinate Processor and Map App Runner

This script scans for simulation directories and loads coordinate files 
for map visualization with hierarchical selection.
"""

from __future__ import annotations

import os
import glob
import shutil
import subprocess
import sys
import json
import re
from pathlib import Path
from typing import List, Tuple, Dict, Optional
from datetime import datetime
import socket
try:
    # Make stdout UTF-8 capable on Windows PowerShell to avoid emoji crash
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

# --- Start of new path configuration ---
# Make paths robust to script's location and execution directory
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = (SCRIPT_DIR / "..").resolve()

# Configuration - Copy to my-map-animation/public only
PUBLIC_DIRS = [str(SCRIPT_DIR / "public")]
# Setup app public directory (for required lightweight assets only)
SETUP_PUBLIC_DIR = PROJECT_ROOT / "my-map-setup" / "public"
COORDINATES_DIR = "coordinates"
LOCAL_CSV_FILE = str(SCRIPT_DIR / "public" / "coordinates.csv")

# Determine outputs directory dynamically, with env override
# Falls back to ../outputs relative to this script
DEFAULT_OUTPUTS_DIR = str(PROJECT_ROOT / "outputs")
SIM_BASE_DIR = os.environ.get("SIM_BASE_DIR", DEFAULT_OUTPUTS_DIR)
# --- End of new path configuration ---

def _humanize(name: str) -> str:
    name = name.replace('-', ' ').replace('_', ' ').strip()
    parts = [p for p in name.split(' ') if p]
    return ' '.join(w.capitalize() for w in parts) if parts else name


def _parse_simulation_folder_name(folder_name: str) -> Dict[str, str]:
    """
    Parse simulation folder names to extract meaningful information.
    
    Expected format: YYYYMMDD_HHMMSS_Xbevcarts_Yrunners_Zgolfers_[scenario]
    
    Returns:
        Dict with parsed components
    """
    result = {
        'date': '',
        'time': '',
        'bev_carts': '0',
        'runners': '0', 
        'golfers': '0',
        'scenario': '',
        'original': folder_name
    }
    
    # Handle timestamp prefix (YYYYMMDD_HHMMSS_)
    if '_' in folder_name:
        parts = folder_name.split('_')
        
        # Check if first part looks like a date (8 digits)
        if len(parts) > 0 and len(parts[0]) == 8 and parts[0].isdigit():
            result['date'] = parts[0]
            
            # Check if second part looks like time (6 digits)
            if len(parts) > 1 and len(parts[1]) == 6 and parts[1].isdigit():
                result['time'] = parts[1]
                
                # Parse the configuration part
                config_parts = parts[2:]
                config_str = '_'.join(config_parts)
                
                # Extract bev carts (handle both "bevcarts" and "bev_carts")
                bev_match = re.search(r'(\d+)bev_?carts?', config_str, re.IGNORECASE)
                if bev_match:
                    result['bev_carts'] = bev_match.group(1)
                
                # Extract runners (handle both "1runners" and "1_runners")
                runner_match = re.search(r'(\d+)_?runners?', config_str, re.IGNORECASE)
                if runner_match:
                    result['runners'] = runner_match.group(1)
                
                # Extract golfers
                golfer_match = re.search(r'(\d+)golfers?', config_str, re.IGNORECASE)
                if golfer_match:
                    result['golfers'] = golfer_match.group(1)
                
                # Look for scenario after the last numeric component
                # Skip parts that match numeric patterns (like "sim_01", "run_01")
                scenario_parts = []
                for part in config_parts:
                    # Skip if it's a numeric component or sim/run folder
                    if not (re.match(r'^\d+[a-zA-Z]+$', part) or 
                           re.match(r'^(sim|run)_\d+$', part, re.IGNORECASE)):
                        scenario_parts.append(part)
                
                if scenario_parts:
                    result['scenario'] = '_'.join(scenario_parts)
    
    return result


def _format_simulation_name(parsed: Dict[str, str]) -> str:
    """
    Format parsed simulation data into a readable name.
    """
    components = []
    
    # Add configuration summary
    config_parts = []
    if parsed['bev_carts'] != '0':
        config_parts.append(f"{parsed['bev_carts']} Cart{'s' if parsed['bev_carts'] != '1' else ''}")
    if parsed['runners'] != '0':
        config_parts.append(f"{parsed['runners']} Runner{'s' if parsed['runners'] != '1' else ''}")
    if parsed['golfers'] != '0':
        config_parts.append(f"{parsed['golfers']} Golfer{'s' if parsed['golfers'] != '1' else ''}")
    
    if config_parts:
        components.append(' + '.join(config_parts))
    
    # Add scenario if available
    if parsed['scenario']:
        scenario_name = _humanize(parsed['scenario'])
        components.append(scenario_name)
    
    # Add variant if available
    if 'variant_key' in parsed and parsed['variant_key'] != 'none':
        components.append(f"({_humanize(parsed['variant_key'])})")

    # Add date/time if available
    if parsed['date'] and parsed['time']:
        try:
            date_obj = datetime.strptime(f"{parsed['date']}_{parsed['time']}", "%Y%m%d_%H%M%S")
            components.append(date_obj.strftime("%b %d, %H:%M"))
        except ValueError:
            pass
    
    return ' | '.join(components) if components else parsed['original']


def _format_simple_simulation_name(parsed: Dict[str, str]) -> str:
    """
    Format parsed simulation data into a simple name without date/time.
    """
    components = []
    
    # Add configuration summary
    config_parts = []
    if parsed['bev_carts'] != '0':
        config_parts.append(f"{parsed['bev_carts']} Cart{'s' if parsed['bev_carts'] != '1' else ''}")
    if parsed['runners'] != '0':
        config_parts.append(f"{parsed['runners']} Runner{'s' if parsed['runners'] != '1' else ''}")
    if parsed['golfers'] != '0':
        config_parts.append(f"{parsed['golfers']} Golfer{'s' if parsed['golfers'] != '1' else ''}")
    
    if config_parts:
        components.append(' + '.join(config_parts))
    
    # Add scenario if available
    if parsed['scenario']:
        scenario_name = _humanize(parsed['scenario'])
        components.append(scenario_name)
    
    # Add variant if available
    if 'variant_key' in parsed and parsed['variant_key'] != 'none':
        components.append(f"({_humanize(parsed['variant_key'])})")

    return ' | '.join(components) if components else parsed['original']


def _create_group_name(parsed: Dict[str, str]) -> str:
    """
    Create a meaningful group name based on parsed simulation data.
    """
    # Group by scenario if available
    if parsed['scenario']:
        return _humanize(parsed['scenario'])
    
    # Group by configuration type
    if parsed['bev_carts'] != '0' and parsed['runners'] != '0':
        return "Mixed Operations"
    elif parsed['bev_carts'] != '0':
        return "Beverage Cart Only"
    elif parsed['runners'] != '0':
        return "Delivery Runners Only"
    else:
        return "Other Simulations"


def _sanitize_and_copy_coordinates_csv(source_path: str, target_path: str) -> None:
    """Copy coordinates.csv while removing leading runner clubhouse idle points and de-duping id+timestamp.

    Rules:
    - For each runner stream (type == 'runner' or id startswith 'runner'), drop rows where hole == 'clubhouse'
      that occur strictly before the first non-clubhouse row for that runner.
    - If multiple rows share the same (id, timestamp), prefer the non-clubhouse row; otherwise keep the first.
    - Preserve original column order from the source file.
    """
    import csv as _csv

    with open(source_path, 'r', newline='', encoding='utf-8') as fsrc:
        reader = _csv.DictReader(fsrc)
        fieldnames = reader.fieldnames or []
        rows = list(reader)

    # Determine first movement timestamp per runner id
    first_move_ts_by_id: Dict[str, Optional[int]] = {}
    for r in rows:
        rid = str(r.get('id', '') or '')
        rtype = (r.get('type') or '').strip().lower()
        if rtype != 'runner' and not rid.startswith('runner'):
            continue
        hole = (r.get('hole') or '').strip().lower()
        try:
            ts = int(float(r.get('timestamp') or 0))
        except Exception:
            continue
        if hole != 'clubhouse':
            prev = first_move_ts_by_id.get(rid)
            if prev is None or ts < prev:
                first_move_ts_by_id[rid] = ts

    # Filter out leading clubhouse rows
    filtered: List[Dict[str, str]] = []
    for r in rows:
        rid = str(r.get('id', '') or '')
        rtype = (r.get('type') or '').strip().lower()
        hole = (r.get('hole') or '').strip().lower()
        try:
            ts = int(float(r.get('timestamp') or 0))
        except Exception:
            filtered.append(r)
            continue
        first_move_ts = first_move_ts_by_id.get(rid)
        if (rtype == 'runner' or rid.startswith('runner')) and hole == 'clubhouse' and first_move_ts is not None and ts < int(first_move_ts):
            # Skip leading clubhouse idle point
            continue
        filtered.append(r)

    # De-duplicate by (id, timestamp), preferring non-clubhouse
    chosen: Dict[Tuple[str, int], Dict[str, str]] = {}
    for r in filtered:
        rid = str(r.get('id', '') or '')
        try:
            ts = int(float(r.get('timestamp') or 0))
        except Exception:
            # If timestamp is bad, just keep it as-is by using a unique fake key
            filtered.append(r)
            continue
        key = (rid, ts)
        hole = (r.get('hole') or '').strip().lower()
        if key not in chosen:
            chosen[key] = r
        else:
            # Prefer non-clubhouse
            prev_hole = (chosen[key].get('hole') or '').strip().lower()
            if prev_hole == 'clubhouse' and hole != 'clubhouse':
                chosen[key] = r

    deduped = list(chosen.values())
    # Sort stable by id then timestamp
    try:
        deduped.sort(key=lambda d: (str(d.get('id', '')), int(float(d.get('timestamp') or 0))))
    except Exception:
        pass

    # Write out
    with open(target_path, 'w', newline='', encoding='utf-8') as fdst:
        writer = _csv.DictWriter(fdst, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for r in deduped:
            writer.writerow(r)

def find_all_simulations() -> Dict[str, List[Tuple[str, str, str]]]:
    """
    Recursively scan for all coordinate CSV files under the outputs directory.

    Returns:
        Dict with simulation_group as key and list of (sim_id, display_name, full_path) as value
    """
    simulations: Dict[str, List[Tuple[str, str, str]]] = {}

    # Add local file if it exists AND there are no outputs at all
    # This avoids polluting dropdowns with a stale local file when real outputs exist
    if os.path.exists(LOCAL_CSV_FILE):
        any_outputs = any(True for _ in Path(SIM_BASE_DIR).rglob('coordinates.csv')) if os.path.exists(SIM_BASE_DIR) else False
        if not any_outputs:
            simulations.setdefault("Local", []).append(("coordinates", "GPS Coordinates", LOCAL_CSV_FILE))
            print(f"Found local simulation file: {LOCAL_CSV_FILE}")

    base_dir = SIM_BASE_DIR
    if not os.path.exists(base_dir):
        print(f"Outputs directory not found: {base_dir}")
        return simulations

    # Walk the outputs directory and collect any coordinates CSVs and heatmaps
    valid_filenames = {"coordinates.csv", "bev_cart_coordinates.csv"}
    valid_heatmap_filenames = {"delivery_heatmap.png", "heatmap.png"}

    for root, dirs, files in os.walk(base_dir):
        csv_files = [f for f in files if f in valid_filenames]
        if not csv_files:
            continue

        for file_name in csv_files:
            full_path = os.path.join(root, file_name)
            rel_path = os.path.relpath(full_path, base_dir)
            parts = rel_path.split(os.sep)

            # Parse the simulation folder name to extract meaningful information
            if len(parts) >= 3:
                # The simulation folder is the parent of the run/sim folder
                # Structure: outputs/simulation_folder/run_01/coordinates.csv
                sim_folder_name = parts[-3]
                run_folder = parts[-2]
                parsed = _parse_simulation_folder_name(sim_folder_name)
                
                # Create meaningful group name
                group_name = _create_group_name(parsed)
                
                # Create meaningful simulation name (without date/time to avoid duplication)
                base_sim_name = _format_simple_simulation_name(parsed)
                
                # Add run/sim identifier if available
                if run_folder.startswith(('sim_', 'run_')):
                    run_id = run_folder.upper()
                else:
                    run_id = ""
                
                # Friendly type from filename
                if file_name == 'coordinates.csv':
                    friendly_type = 'GPS Coordinates'
                elif file_name == 'bev_cart_coordinates.csv':
                    friendly_type = 'Beverage Cart GPS'
                else:
                    friendly_type = os.path.splitext(file_name)[0].replace('_', ' ').title()
                
                # Combine components for display name
                display_components = [base_sim_name]
                if run_id:
                    display_components.append(run_id)
                display_components.append(friendly_type)
                display_name = ' | '.join(display_components)
                
            elif len(parts) >= 2:
                # Fallback: direct simulation folder structure
                sim_folder_name = parts[-2]
                parsed = _parse_simulation_folder_name(sim_folder_name)
                
                # Create meaningful group name
                group_name = _create_group_name(parsed)
                
                # Create meaningful simulation name (without date/time to avoid duplication)
                base_sim_name = _format_simple_simulation_name(parsed)
                
                # Friendly type from filename
                if file_name == 'coordinates.csv':
                    friendly_type = 'GPS Coordinates'
                elif file_name == 'bev_cart_coordinates.csv':
                    friendly_type = 'Beverage Cart GPS'
                else:
                    friendly_type = os.path.splitext(file_name)[0].replace('_', ' ').title()
                
                display_name = f"{base_sim_name} | {friendly_type}"
                
            else:
                # Fallback for simple file structure
                group_name = 'Simulations'
                display_name = f"Coordinates ({os.path.splitext(file_name)[0]})"
            
            # Unique ID derived from relative path (without extension)
            sim_id = rel_path.replace(os.sep, '_').replace('.csv', '')

            simulations.setdefault(group_name, []).append((sim_id, display_name, full_path))

    # Sort groups and simulations for consistent UI ordering
    sorted_simulations: Dict[str, List[Tuple[str, str, str]]] = {}
    for group in sorted(simulations.keys()):
        sorted_simulations[group] = sorted(simulations[group], key=lambda x: x[0])

    # Logging summary
    for group_name, sims in sorted_simulations.items():
        print(f"Found {len(sims)} simulations in {group_name}")

    return sorted_simulations



def _derive_combo_key_from_path(csv_path: str) -> Optional[str]:
    """Derive a (scenario, orders, runners, variant) grouping key from a run CSV path.

    Supports experiment folders (e.g., outputs/experiments/<exp>/typical_weekday/orders_028/runners_2/variant_key/run_01/coordinates.csv).
    """
    try:
        p = Path(csv_path)
        # Expect .../run_xx/coordinates.csv → start from run folder
        run_dir = p.parent
        variant_dir = run_dir.parent if run_dir.name.startswith("run_") else p.parent # Handle cases where there is no run_xx folder
        runners_dir = variant_dir.parent
        orders_dir = runners_dir.parent
        scenario_dir = orders_dir.parent

        # Pattern A: experiments layout
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

        # Pattern B: timestamped folder with encoded tokens
        # Walk upward to find a segment that contains both 'runners' and (optionally) 'orders'
        for ancestor in p.parents:
            name = ancestor.name
            if ("runners" in name) and ("delivery_runner" in name or "runners_" in name):
                # Extract scenario best-effort
                scenario = None
                # Try to detect 'orders_XXX'
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
                    # Use next directory up as scenario hint when possible
                    scenario = ancestor.parent.name
                    return f"{scenario}|orders_{orders_val:03d}|runners_{n_runners}"
        return None
    except Exception:
        return None


def _select_representative_runs(all_items: List[Tuple[str, str, str]]) -> Dict[str, str]:
    """From a flat list of (sim_id, display_name, csv_path), select one representative csv per combo key.

    Strategy: For each combo key, read per-run metrics in the same run folder, compute the mean across runs
    for core delivery metrics, then pick the run whose metrics vector is closest (z-score distance) to the mean.
    Returns a mapping from csv_path → 'selected' (value is the same path for quick lookup).
    """
    # Group candidates by combo key derived from path
    groups: Dict[str, List[Tuple[str, str, str]]] = {}
    for sim_id, display_name, csv_path in all_items:
        key = _derive_combo_key_from_path(csv_path)
        if key:
            groups.setdefault(key, []).append((sim_id, display_name, csv_path))

    selected: Dict[str, str] = {}

    def load_metrics_for_run(run_dir: Path) -> Dict[str, float]:
        # Prefer delivery_runner_metrics_run_XX.json if present, else simulation_metrics.json
        metrics: Dict[str, float] = {}
        try:
            # Try to find a run-specific metrics file
            candidates = [
                *[f for f in os.listdir(run_dir) if f.startswith("delivery_runner_metrics_run_") and f.endswith(".json")],
            ]
            chosen = None
            if candidates:
                # Prefer the one matching the run folder name when possible
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

        # Normalize possible schemas
        try:
            # delivery_runner_metrics_run schema
            on_time = data.get("on_time_rate")
            failed = data.get("failed_rate")
            p90 = data.get("delivery_cycle_time_p90")
            oph = data.get("orders_per_runner_hour")
            if on_time is None or p90 is None or oph is None:
                # simulation_metrics.json schema under deliveryMetrics
                dm = data.get("deliveryMetrics") or {}
                on_time = dm.get("onTimeRate") if dm is not None else None
                # Some schemas use percentage 0-100
                if isinstance(on_time, (int, float)) and on_time > 1.5:
                    on_time = float(on_time) / 100.0
                p90 = dm.get("deliveryCycleTimeP90") if dm is not None else None
                oph = dm.get("ordersPerRunnerHour") if dm is not None else None
                # failed rate best-effort
                failed = dm.get("failedRate") if isinstance(dm, dict) else data.get("failed_rate")
                if isinstance(failed, (int, float)) and failed > 1.5:
                    failed = float(failed) / 100.0
            # Build numeric-only dict
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
        # Detect unique run folders under the combo
        per_run: List[Tuple[str, Path]] = []  # (csv_path, run_dir)
        for _, __, csv_path in items:
            run_dir = Path(csv_path).parent
            per_run.append((csv_path, run_dir))

        if len(per_run) <= 1:
            # Single run, select it
            selected[per_run[0][0]] = per_run[0][0]
            continue

        # Load metrics for each run
        run_metrics: List[Tuple[str, Dict[str, float]]] = []
        for csv_path, run_dir in per_run:
            m = load_metrics_for_run(run_dir)
            run_metrics.append((csv_path, m))

        # Compute mean across observed metrics
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
                    stds[k] = (var ** 0.5) if var > 0 else 1.0
                else:
                    stds[k] = 1.0
            else:
                means[k] = 0.0
                stds[k] = 1.0

        # Pick run with minimal z-score distance to mean
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


def copy_all_coordinate_files(all_simulations: Dict[str, List[Tuple[str, str, str]]], preferred_default_id: Optional[str] = None) -> Tuple[bool, List[str]]:
    """
    Copy all coordinate files to both public directories and create hierarchical manifests.
    
    Args:
        all_simulations: Dict with simulation groups and their files
        
    Returns:
        A tuple of (success_boolean, discovered_course_ids)
    """
    try:
        # Create coordinates directories in both locations
        coordinates_dirs = []
        for public_dir in PUBLIC_DIRS:
            # Proactively clean top-level public artifacts that may become stale
            try:
                stale_files = [
                    os.path.join(public_dir, 'coordinates.csv'),
                    os.path.join(public_dir, 'hole_delivery_times.geojson'),
                    os.path.join(public_dir, 'hole_delivery_times_debug.geojson'),
                    os.path.join(public_dir, 'simulation_metrics.json'),
                ]
                for f in stale_files:
                    if os.path.exists(f):
                        try:
                            os.remove(f)
                            print(f"🧹 Removed stale file: {f}")
                        except Exception:
                            pass
            except Exception:
                pass

            coordinates_dir = os.path.join(public_dir, COORDINATES_DIR)
            coordinates_dirs.append(coordinates_dir)

            # Fully clear out existing coordinate directory first (including manifest and any stale files)
            if os.path.exists(coordinates_dir):
                try:
                    print(f"Cleaning coordinates directory: {coordinates_dir}")
                    shutil.rmtree(coordinates_dir)
                except Exception as e:
                    print(f"Error clearing coordinates directory {coordinates_dir}: {e}")
                    return False, []

            os.makedirs(coordinates_dir, exist_ok=True)
        
        # Create flattened manifest for the React app (will be enriched per entry)
        manifest = {
            "simulations": [],
            "defaultSimulation": None,
            "courses": []
        }
        # Track discovered courses for dropdown
        discovered_courses: Dict[str, str] = {}
        
        copied_count = 0
        total_size = 0
        id_to_mtime: Dict[str, float] = {}
        
        def _extract_orders_from_metrics(metrics_path: str) -> int | None:
            try:
                with open(metrics_path, "r", encoding="utf-8") as f:
                    import json as _json
                    data = _json.load(f)
                # Prefer deliveryMetrics.totalOrders if present
                dm = data.get("deliveryMetrics") or {}
                if isinstance(dm, dict):
                    orders = dm.get("totalOrders") or dm.get("orderCount")
                    if isinstance(orders, (int, float)):
                        return int(orders)
                # Fallback tolerant keys at root
                for key in ("totalOrders", "orderCount"):
                    if key in data and isinstance(data[key], (int, float)):
                        return int(data[key])
            except Exception:
                return None
            return None

        def _extract_variant_info_from_metrics(metrics_path: str) -> Tuple[Optional[str], Optional[List[int]]]:
            try:
                with open(metrics_path, "r", encoding="utf-8") as f:
                    import json as _json
                    data = _json.load(f)
                variant_key = data.get("variantKey")
                blocked_holes = data.get("blockedHoles")
                return variant_key, blocked_holes
            except Exception:
                return None, None

        # Build a flat list of all candidates to allow representative selection
        flat_items: List[Tuple[str, str, str]] = []
        for gname, items in all_simulations.items():
            for sim_id, disp, src in items:
                flat_items.append((sim_id, disp, src))

        # Determine representative runs per (scenario, orders, runners)
        selected_csvs = _select_representative_runs(flat_items)
        selected_mode_active = len(selected_csvs) > 0

        for group_name, file_options in all_simulations.items():
            for scenario_id, display_name, source_path in file_options:
                # If representative selection is active and this csv is not selected for its combo, skip it
                if selected_mode_active:
                    key = _derive_combo_key_from_path(source_path)
                    if key and source_path not in selected_csvs:
                        # Skip non-representative runs for this combo
                        continue
                # Additional filter: only include delivery runner simulations (no hardcoded limits)
                try:
                    p = Path(source_path)
                    parents = list(p.parents)
                    # Orders condition: any parent folder named orders_XXX (completely dynamic)
                    has_orders = any(parent.name.lower().startswith("orders_") for parent in parents)
                    # Runners condition: any delivery runner simulation (completely dynamic)
                    has_delivery_runners = False
                    # Check for runners_X folder pattern (any number)
                    for parent in parents:
                        name = parent.name.lower()
                        if name.startswith("runners_"):
                            try:
                                runner_count = int(name.split("_")[1])
                                if runner_count > 0:  # Any positive number of runners
                                    has_delivery_runners = True
                                    break
                            except (ValueError, IndexError):
                                continue
                    # Check encoded top-level sim folder name like 2025..._delivery_runner_X_runners_...
                    if not has_delivery_runners:
                        for parent in parents:
                            name = parent.name.lower()
                            if "delivery_runner_" in name and "_runners_" in name:
                                # Extract runner count from pattern like _X_runners_
                                # use top-level 're' to avoid local shadowing causing 'referenced before assignment'
                                match = re.search(r'_(\d+)_runners_', name)
                                if match:
                                    try:
                                        runner_count = int(match.group(1))
                                        if runner_count > 0:  # Any positive number of runners
                                            has_delivery_runners = True
                                            break
                                    except ValueError:
                                        continue
                    if not (has_orders and has_delivery_runners):
                        continue
                except Exception:
                    # If we cannot parse, skip to be safe
                    continue
                # Skip entries whose source CSV no longer exists
                if not os.path.exists(source_path):
                    print(f"⚠️  Skipping missing source CSV: {source_path}")
                    continue
                # Create target filename
                target_filename = f"{scenario_id}.csv"
                
                # Copy the file to all coordinates directories
                all_copies_successful = True
                sanitized_mode = (os.path.basename(source_path) == 'coordinates.csv')
                for coordinates_dir in coordinates_dirs:
                    target_path = os.path.join(coordinates_dir, target_filename)
                    
                    # Copy the file (with optional sanitization for runner coordinates)
                    try:
                        if os.path.basename(source_path) == 'coordinates.csv':
                            _sanitize_and_copy_coordinates_csv(source_path, target_path)
                        else:
                            shutil.copy2(source_path, target_path)
                    except Exception as e:
                        print(f"❌ Error copying {display_name} to {coordinates_dir}: {e}")
                        all_copies_successful = False
                        break
                    
                    # Verify the copy
                    if os.path.exists(target_path):
                        source_size = os.path.getsize(source_path)
                        target_size = os.path.getsize(target_path)
                        # For sanitized coordinates.csv, sizes may differ; ensure non-empty only
                        if sanitized_mode:
                            if target_size <= 0:
                                print(f"❌ Sanitized copy appears empty for {display_name} in {coordinates_dir}")
                                all_copies_successful = False
                                break
                        else:
                            if source_size != target_size:
                                print(f"❌ Failed to verify copy for {display_name} to {coordinates_dir}")
                                all_copies_successful = False
                                break
                    else:
                        print(f"❌ Failed to copy {display_name} to {coordinates_dir}")
                        all_copies_successful = False
                        break
                
                if all_copies_successful:
                    copied_count += 1
                    total_size += source_size
                    # Discover accompanying artifacts in the source directory (heatmap, metrics, optional per-run hole geojson)
                    csv_dir = os.path.dirname(source_path)
                    found_heatmap_filename: str | None = None
                    found_metrics_filename: str | None = None
                    found_hole_geojson_filename: str | None = None
                    orders_value: int | None = None
                    variant_key: str | None = "none"
                    blocked_holes: list[int] | None = []

                    # Heatmap files
                    for fname in os.listdir(csv_dir):
                        if fname in {"delivery_heatmap.png", "heatmap.png"}:
                            heatmap_source = os.path.join(csv_dir, fname)
                            for coordinates_dir in coordinates_dirs:
                                heatmap_filename = f"{scenario_id}_{fname}"
                                heatmap_target = os.path.join(coordinates_dir, heatmap_filename)
                                try:
                                    shutil.copy2(heatmap_source, heatmap_target)
                                    found_heatmap_filename = heatmap_filename
                                except Exception as e:
                                    print(f"⚠️  Warning: Could not copy heatmap {fname}: {e}")
                            break

                    # Metrics files: prefer simulation_metrics.json, fallback to delivery_runner_metrics_run_XX.json
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
                            except Exception as e:
                                print(f"⚠️  Warning: Could not copy metrics {metrics_candidates[0]}: {e}")
                        # Try to parse orders from metrics
                        try:
                            orders_value = _extract_orders_from_metrics(metrics_source)
                            variant_key, blocked_holes = _extract_variant_info_from_metrics(metrics_source)
                        except Exception:
                            orders_value = None
                            variant_key = None
                            blocked_holes = None

                    # Derive course info (id/name) best-effort from results.json metadata
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

                    # Optional per-run hole delivery geojson: generate if missing, then copy
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
                                except Exception as e:
                                    print(f"⚠️  Warning: Could not copy hole geojson {os.path.basename(existing_geo)}: {e}")
                    except Exception as e:
                        print(f"⚠️  Warning: Hole geojson handling failed in {csv_dir}: {e}")

                    # Add to flattened simulations list (only once), enriched with meta
                    file_info = get_file_info(source_path)
                    try:
                        from datetime import datetime
                        mtime = os.path.getmtime(source_path)
                        id_to_mtime[scenario_id] = mtime
                        last_modified_iso = datetime.fromtimestamp(mtime).isoformat()
                    except Exception:
                        last_modified_iso = None

                    # Parse runner count and scenario for meta using multiple strategies
                    path_parts = Path(source_path).parts
                    sim_folder_name = None
                    for i, part in enumerate(path_parts):
                        if 'delivery_runner' in part and 'runners' in part:
                            sim_folder_name = part
                            break

                    parsed = _parse_simulation_folder_name(sim_folder_name) if sim_folder_name else {}
                    # Fallback: extract runners/orders from path segments like runners_N and orders_XXX
                    extracted_runners: Optional[int] = None
                    extracted_orders: Optional[int] = None
                    for part in path_parts:
                        m_r = re.match(r"runners[_-]?([0-9]+)", part, re.IGNORECASE)
                        if m_r:
                            try:
                                extracted_runners = int(m_r.group(1))
                            except Exception:
                                pass
                        m_o = re.match(r"orders[_-]?([0-9]{2,3})", part, re.IGNORECASE)
                        if m_o:
                            try:
                                extracted_orders = int(m_o.group(1))
                            except Exception:
                                pass
                    meta = {
                        "runners": (int(parsed.get("runners", "0") or 0) if isinstance(parsed, dict) else None) or extracted_runners,
                        "bevCarts": int(parsed.get("bev_carts", "0") or 0) if isinstance(parsed, dict) else None,
                        "golfers": int(parsed.get("golfers", "0") or 0) if isinstance(parsed, dict) else None,
                        "scenario": parsed.get("scenario") if isinstance(parsed, dict) else None,
                        "orders": (int(orders_value) if isinstance(orders_value, (int, float)) else None) or extracted_orders,
                        "lastModified": last_modified_iso,
                        "blockedHoles": blocked_holes,
                    }

                    entry = {
                        "id": scenario_id,
                        "name": f"{group_name}: {display_name}",
                        "filename": target_filename,
                        "description": file_info,
                        "variantKey": variant_key or "none",
                        "meta": {k: v for k, v in meta.items() if v is not None}
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
                    print(f"✅ {display_name} ({source_size//1024:,} KB) - copied to all locations")
                else:
                    return False, []
        
        # Set default simulation
        if manifest["simulations"]:
            # Allow caller to specify a preferred default simulation via param or env var
            env_default_id = os.environ.get("DEFAULT_SIMULATION_ID", "").strip()
            chosen_id = (preferred_default_id or env_default_id or "").strip()

            selected_default = None
            if chosen_id:
                for sim in manifest["simulations"]:
                    if sim["id"] == chosen_id:
                        selected_default = sim
                        break

            # Fallbacks
            if not selected_default:
                # 1) Most recently modified file if available
                if id_to_mtime:
                    try:
                        newest_id = max(id_to_mtime.items(), key=lambda kv: kv[1])[0]
                        selected_default = next((sim for sim in manifest["simulations"] if sim["id"] == newest_id), None)
                    except Exception:
                        selected_default = None
            if not selected_default:
                # 2) Prefer first non-Local simulation if available
                selected_default = next(
                    (sim for sim in manifest["simulations"] if not sim["name"].startswith("Local:")),
                    manifest["simulations"][0]
                )

            manifest["defaultSimulation"] = selected_default["id"]
            print(f"Set default simulation: {selected_default['name']}")
        
        # Populate courses list for dropdown; prefer Pinetree first when present
        if discovered_courses:
            # Ensure Pinetree appears first if discovered
            items = list(discovered_courses.items())
            items.sort(key=lambda kv: (0 if kv[0] == "pinetree_country_club" else 1, kv[1].lower()))
            manifest["courses"] = [{"id": cid, "name": cname} for cid, cname in items]

        # Write manifest files to all coordinates directories
        for coordinates_dir in coordinates_dirs:
            manifest_path = os.path.join(coordinates_dir, "manifest.json")
            with open(manifest_path, 'w') as f:
                json.dump(manifest, f, indent=2)
            print(f"📋 Created manifest: {manifest_path}")
        
        # Copy simulation_metrics.json if it exists in the my-map-animation public directory
        metrics_source = SCRIPT_DIR / "public" / "simulation_metrics.json"
        if os.path.exists(metrics_source):
            for coordinates_dir in coordinates_dirs:
                metrics_target = os.path.join(coordinates_dir, "simulation_metrics.json")
                try:
                    shutil.copy2(metrics_source, metrics_target)
                    print(f"📋 Copied simulation_metrics.json to {coordinates_dir}")
                except Exception as e:
                    print(f"⚠️  Warning: Could not copy simulation_metrics.json to {coordinates_dir}: {e}")
        
        # Heatmaps are copied per simulation above
        
        # Copy hole_delivery_times.geojson if it exists
        copy_hole_delivery_geojson(coordinates_dirs)
        
        print(f"\n✅ Successfully copied {copied_count} simulations ({total_size//1024:,} KB total)")
        
        # Return success state and the list of discovered course IDs
        return True, list(discovered_courses.keys())
        
    except Exception as e:
        print(f"❌ Error copying files: {e}")
        return False, []

def get_file_info(file_path: str) -> str:
    """Get information about the coordinate file."""
    try:
        with open(file_path, 'r') as f:
            lines = f.readlines()
            if len(lines) > 1:
                # Count data rows (excluding header)
                data_rows = len(lines) - 1
                return f"{data_rows:,} coordinate points"
            else:
                return "Empty file"
    except Exception as e:
        return f"Error reading file: {e}"

def _generate_per_run_hole_geojson(run_dir: Path) -> Optional[Path]:
    """Generate hole_delivery_times.geojson inside a run directory from its results.json.

    Returns the path if created, else None. Best-effort, failures are swallowed with a warning.
    """
    try:
        results_path = run_dir / "results.json"
        if not results_path.exists():
            return None
        with results_path.open("r", encoding="utf-8") as f:
            results = json.load(f)

        # Resolve course directory from results metadata when available
        course_dir = None
        try:
            course_dir = results.get("metadata", {}).get("course_dir")
        except Exception:
            course_dir = None
        if not course_dir:
            course_dir = str(PROJECT_ROOT / "courses" / "pinetree_country_club")

        # Lazily import heavy deps only when needed
        from golfsim.viz.heatmap_viz import (
            load_geofenced_holes,
            extract_order_data,
            calculate_delivery_time_stats,
        )
        import geopandas as _gpd  # noqa: F401 - used to convert shapely to geojson

        # Build feature collection (inline minimal builder to avoid cross-script import)
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
                props.update({
                    "has_data": True,
                    "avg_time": float(stats.get("avg_time", 0.0)),
                    "min_time": float(stats.get("min_time", 0.0)),
                    "max_time": float(stats.get("max_time", 0.0)),
                    "count": int(stats.get("count", 0)),
                })
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
        print(f"⚠️  Warning: Failed to generate per-run hole geojson in {run_dir}: {e}")
        return None

def copy_heatmaps_to_coordinates_dirs(all_simulations: Dict[str, List[Tuple[str, str, str]]], coordinates_dirs: List[str]) -> None:
    """Copy heatmap files from simulation outputs to coordinates directories."""
    valid_heatmap_filenames = {"delivery_heatmap.png", "heatmap.png"}
    
    for group_name, file_options in all_simulations.items():
        for scenario_id, display_name, csv_source_path in file_options:
            # Find heatmap files in the same directory as the CSV
            csv_dir = os.path.dirname(csv_source_path)
            
            for filename in os.listdir(csv_dir):
                if filename in valid_heatmap_filenames:
                    heatmap_source = os.path.join(csv_dir, filename)
                    
                    # Copy to all coordinates directories
                    for coordinates_dir in coordinates_dirs:
                        # Create a unique heatmap filename based on scenario_id
                        heatmap_filename = f"{scenario_id}_{filename}"
                        heatmap_target = os.path.join(coordinates_dir, heatmap_filename)
                        
                        try:
                            shutil.copy2(heatmap_source, heatmap_target)
                            print(f"🖼️  Copied {filename} to {coordinates_dir} as {heatmap_filename}")
                        except Exception as e:
                            print(f"⚠️  Warning: Could not copy {filename}: {e}")

def copy_hole_delivery_geojson(coordinates_dirs: List[str]) -> None:
    """Copy hole_delivery_times.geojson to parent public directories."""
    source_file = SCRIPT_DIR / "public" / "hole_delivery_times.geojson"
    
    if os.path.exists(source_file):
        for public_dir in PUBLIC_DIRS:
            target_file = os.path.join(public_dir, "hole_delivery_times.geojson")
            try:
                # Use a temporary file to handle potential file locks
                temp_target = target_file + ".tmp"
                shutil.copy2(source_file, temp_target)
                os.replace(temp_target, target_file)
                print(f"🗺️  Copied hole_delivery_times.geojson to {public_dir}")
            except Exception as e:
                print(f"⚠️  Warning: Could not copy hole_delivery_times.geojson to {public_dir}: {e}")

def ensure_setup_required_assets(course_ids: list[str]) -> None:
    """Ensure the Setup app has the minimal required geojson assets for each course."""
    try:
        # Source base directory for course assets
        courses_base_dir = PROJECT_ROOT / "courses"
        
        # Target base directory in the setup app
        target_base_dir = SETUP_PUBLIC_DIR
        target_base_dir.mkdir(exist_ok=True)
        
        for course_id in course_ids:
            course_src_dir = courses_base_dir / course_id
            course_target_dir = target_base_dir / course_id
            course_target_dir.mkdir(exist_ok=True)

            assets_to_copy = {
                "holes_connected.geojson": f"geojson{os.sep}holes_connected.geojson",
                "course_polygon.geojson": f"geojson{os.sep}course_polygon.geojson",
                "holes_geofenced.geojson": f"geojson{os.sep}generated{os.sep}holes_geofenced.geojson"
            }
            
            for target_name, source_subpath in assets_to_copy.items():
                source_path = course_src_dir / source_subpath
                target_path = course_target_dir / target_name
                
                if not source_path.exists():
                    # Fallback for holes_connected which may not be in the canonical courses folder
                    if target_name == "holes_connected.geojson":
                        fallback_dir = SCRIPT_DIR / "public" / course_id
                        if fallback_dir.exists():
                           source_path = fallback_dir / target_name
                    if not source_path.exists():
                        print(f"⚠️  Asset not found for course '{course_id}': {source_subpath}")
                        continue
                
                try:
                    # Copy if target doesn't exist or is older than source
                    if not target_path.exists() or source_path.stat().st_mtime > target_path.stat().st_mtime:
                        shutil.copy2(str(source_path), str(target_path))
                        print(f"🧩 Copied/updated asset for '{course_id}': {target_name}")
                except Exception as e:
                    print(f"⚠️  Warning: Could not copy {source_path} to {target_path}: {e}")

    except Exception as e:
        print(f"⚠️  Warning: ensure_setup_required_assets failed: {e}")

def _is_port_in_use(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False

def _find_available_port(preferred_port: int, avoid_ports: Optional[set[int]] = None, max_tries: int = 5) -> int:
    avoid = avoid_ports or set()
    port = preferred_port
    tries = 0
    while tries < max_tries and (port in avoid or _is_port_in_use(port)):
        port += 1
        tries += 1
    return port

def run_react_app(setup_only: bool = False) -> bool:
    """
    Start the React development server(s).
    
    Args:
        setup_only: If True, only start the setup app. If False, start both apps.
    
    Returns:
        True if app(s) started successfully, False otherwise
    """
    try:
        if setup_only:
            print("\n🚀 Starting React setup app...")
            print("📍 Setup app will open at http://localhost:3001")
            print("🔄 Use Ctrl+C to stop the server when done")
            print("-" * 60)
            
            # Start only the setup app
            setup_dir = SCRIPT_DIR.parent / "my-map-setup"
            env = os.environ.copy()
            # Pin Setup app to port 3001 to keep UX consistent
            env["PORT"] = "3001"
            result = subprocess.run(
                ["npm", "start"],
                cwd=str(setup_dir),
                shell=True,
                env=env,
            )
            return result.returncode == 0
        else:
            print("\n🚀 Starting both React apps...")
            # Resolve animation app port automatically if 3000 is busy
            animation_port = _find_available_port(3000, avoid_ports={3001})
            print(f"📍 Animation app will open at http://localhost:{animation_port}")
            print("📍 Setup app will open at http://localhost:3001")
            print("🔄 Use Ctrl+C to stop both servers when done")
            print("-" * 60)
            
            import threading
            import time
            
            # Function to run a single app
            def run_single_app(app_dir: str, app_name: str, env: Optional[Dict[str, str]] = None):
                try:
                    print(f"Starting {app_name}...")
                    subprocess.run(
                        ["npm", "start"],
                        cwd=app_dir,
                        shell=True,
                        env=env,
                    )
                except Exception as e:
                    print(f"❌ Error starting {app_name}: {e}")
            
            # Prepare envs
            animation_env = os.environ.copy()
            animation_env["PORT"] = str(animation_port)
            setup_env = os.environ.copy()
            setup_env["PORT"] = "3001"

            # Start animation app in a thread
            animation_thread = threading.Thread(
                target=run_single_app,
                args=[str(SCRIPT_DIR), "Animation App", animation_env],
                daemon=True
            )
            animation_thread.start()
            
            # Wait a moment before starting the second app
            time.sleep(2)
            
            # Start setup app in a thread
            setup_dir = SCRIPT_DIR.parent / "my-map-setup"
            setup_thread = threading.Thread(
                target=run_single_app,
                args=[str(setup_dir), "Setup App", setup_env],
                daemon=True
            )
            setup_thread.start()
            
            # Keep main thread alive
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n⏹️  Both apps stopped by user")
                return True
        
    except KeyboardInterrupt:
        print("\n⏹️  App stopped by user")
        return True
    except Exception as e:
        print(f"❌ Error starting React app: {e}")
        print("💡 Make sure you have Node.js and npm installed")
        print("💡 Try running 'npm install' first if this is a fresh setup")
        return False

def main():
    """Main function."""
    import argparse
    parser = argparse.ArgumentParser(description="Prepare map app coordinates and manifest")
    parser.add_argument("--default-id", dest="default_id", default=None, help="Preferred default simulation id (manifest id)")
    parser.add_argument("--setup-only", action="store_true", help="Only start the setup app (shortcuts)")
    parser.add_argument("--both-apps", action="store_true", help="Start both animation and setup apps")
    args = parser.parse_args()

    print("🔍 Scanning for simulation coordinate files...")
    
    try:
        # Find all simulations
        all_simulations = find_all_simulations()
        
        total_sims = sum(len(sims) for sims in all_simulations.values())
        print(f"\n📋 Found {total_sims} simulations across {len(all_simulations)} groups:")
        
        for group_name, sims in all_simulations.items():
            print(f"  📁 {group_name}: {len(sims)} simulations")
            for scenario_id, display_name, file_path in sims:
                file_info = get_file_info(file_path)
                print(f"    • {display_name} - {file_info}")
        
        print(f"\n📂 Copying simulations to React app...")
        
        # Copy coordinate files and get the list of discovered courses
        ok, courses = copy_all_coordinate_files(all_simulations, preferred_default_id=args.default_id)
        if not ok:
            print("❌ Failed to copy coordinate files")
            sys.exit(1)
        
        print("✅ Simulation is ready!")
        
        # Ensure Setup app has required lightweight assets for all discovered courses
        ensure_setup_required_assets(courses)
        
        # Launch apps based on arguments
        if args.setup_only:
            run_react_app(setup_only=True)
        elif args.both_apps:
            run_react_app(setup_only=False)
        else:
            print(f"💡 You can start the animation app manually with: npm start")
            print(f"💡 You can start the setup app with: --setup-only")
            print(f"💡 You can start both apps with: --both-apps")
            print(f"🎮 The golfer coordinates will be displayed on the map")
            
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
