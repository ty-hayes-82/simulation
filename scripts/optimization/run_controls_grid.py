#!/usr/bin/env python3
"""
Batch grid to generate simulations for interactive controls (runners × orders).

Writes outputs under outputs/<timestamp>_delivery_runner_<N>_runners_<scenario>... with per-run
coordinates.csv, delivery_heatmap.png, simulation_metrics.json. Designed to be discovered by
my-map-animation/run_map_app.py to build the manifest.
"""

from __future__ import annotations

import argparse
import itertools
import json
from collections import defaultdict
import subprocess
import sys
import shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional
import csv


def cleanup_old_simulation_outputs(output_root: Path) -> None:
    """Remove all existing simulation output directories to ensure clean results."""
    try:
        if not output_root.exists():
            print("No existing outputs directory to clean")
            return
            
        # Find all simulation output directories (timestamped folders)
        old_dirs = [d for d in output_root.iterdir() if d.is_dir() and d.name.startswith("202")]
        
        if not old_dirs:
            print("No old simulation outputs to clean")
            return
            
        print(f"🧹 Cleaning up {len(old_dirs)} old simulation output directories")
        for old_dir in old_dirs:
            try:
                shutil.rmtree(old_dir)
                print(f"   Removed: {old_dir.name}")
            except Exception as e:
                print(f"   ⚠️ Failed to remove {old_dir.name}: {e}")
                
        print("✅ Cleaned up old simulation outputs")
        
    except Exception as e:
        print(f"⚠️ Failed to cleanup old outputs: {e}")


def update_map_animation_files():
    """Finds all simulation outputs and updates the map animation files."""
    print("🚀 Updating map animation files...")

    # Add my-map-animation to path to import run_map_app
    project_root = Path(__file__).resolve().parent.parent.parent
    map_app_dir = project_root / "my-map-animation"
    if str(map_app_dir) not in sys.path:
        sys.path.insert(0, str(map_app_dir))

    try:
        from run_map_app import find_all_simulations, copy_all_coordinate_files

        all_simulations = find_all_simulations()

        if copy_all_coordinate_files(all_simulations, preferred_default_id=None):
            print("✅ Successfully updated map animation files.")
        else:
            print("⚠️ Failed to update map animation files.")

    except ImportError:
        print(
            "⚠️ Could not import from 'run_map_app.py'. "
            "Skipping map animation files update. Run it manually."
        )
    except Exception as e:
        print(f"❌ An error occurred while updating map animation files: {e}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate runner×orders grid for the UI controls")
    p.add_argument("--course-dir", default="courses/pinetree_country_club")
    p.add_argument("--tee-scenario", default="real_tee_sheet")
    p.add_argument("--runners", nargs="+", type=int, default=[1, 2, 3])
    p.add_argument("--orders", nargs="+", type=int, default=[20, 28, 36, 44])
    p.add_argument("--runs-per", type=int, default=1)
    p.add_argument("--groups-count", type=int, default=0, help="Use tee scenario instead of fixed group count")
    p.add_argument("--first-tee", type=str, default=None, help="Override first tee (HH:MM), passed to run_new.py")
    p.add_argument("--runner-speed", type=float, default=None)
    p.add_argument("--prep-time", type=int, default=None)
    p.add_argument("--output-root", default="outputs")
    p.add_argument("--python-bin", default=sys.executable)
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--minimal-outputs", action="store_true", default=False, help="Only write coordinates.csv, simulation_metrics.json, results.json for each run")
    p.add_argument("--keep-old-outputs", action="store_true", default=False, help="Keep existing simulation outputs (default: clean them up)")
    return p.parse_args()


def run_one(*, py: str, course_dir: Path, scenario: str, runners: int, orders: int, runs: int, groups_count: int, first_tee: Optional[str], speed: float | None, prep: int | None, out_dir: Path, log_level: str, minimal_outputs: bool, keep_old_outputs: bool) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    project_root = Path(__file__).resolve().parent.parent.parent
    run_new_py = str(project_root / "scripts" / "sim" / "run_new.py")
    cmd: List[str] = [
        py, run_new_py,
        "--course-dir", str(course_dir),
        "--tee-scenario", scenario,
        "--num-runners", str(runners),
        "--delivery-total-orders", str(orders),
        "--num-runs", str(runs),
        "--groups-count", str(groups_count),
        "--output-dir", str(out_dir),
        "--log-level", log_level,
    ]
    # Pass through first tee time if provided on the grid CLI
    if first_tee:
        cmd += ["--first-tee", str(first_tee)]
    if speed is not None:
        cmd += ["--runner-speed", str(speed)]
    if prep is not None:
        cmd += ["--prep-time", str(prep)]
    if minimal_outputs:
        cmd += ["--minimal-outputs"]
    if keep_old_outputs:
        cmd += ["--keep-old-outputs"]
    subprocess.run(cmd, check=True)


def main() -> None:
    a = parse_args()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    project_root = Path(__file__).resolve().parent.parent.parent
    root = (project_root / a.output_root) if not Path(a.output_root).is_absolute() else Path(a.output_root)
    
    # Clean up old simulation outputs unless explicitly told to keep them
    if not a.keep_old_outputs:
        cleanup_old_simulation_outputs(root)
    
    # Resolve course dir relative to project root if a relative path was provided
    course_dir_abs = Path(a.course_dir)
    if not course_dir_abs.is_absolute():
        course_dir_abs = (project_root / a.course_dir)
    course_dir_abs = course_dir_abs.resolve()
    combos = list(itertools.product(sorted(set(a.runners)), sorted(set(a.orders))))

    # Track unique top-level runner directories; we'll scan them after the loop
    runner_roots_set = set()
    all_metrics_files: List[Path] = []

    for r, o in combos:
        runner_root = root / f"{stamp}_delivery_runner_{r}_runners_{a.tee_scenario}"
        out = runner_root / f"orders_{o:03d}"
        run_one(
            py=a.python_bin,
            course_dir=course_dir_abs,
            scenario=a.tee_scenario,
            runners=r,
            orders=o,
            runs=a.runs_per,
            groups_count=a.groups_count,
            first_tee=a.first_tee,
            speed=a.runner_speed,
            prep=a.prep_time,
            out_dir=out,
            log_level=a.log_level,
            minimal_outputs=a.minimal_outputs,
            keep_old_outputs=a.keep_old_outputs,
        )
        print(f"✅ Generated runners={r}, orders={o} → {out}")

        # Track this runner root; we'll scan once after all combos to avoid duplicates
        runner_roots_set.add(runner_root)

    # After all runs complete, collect metrics once to avoid duplicates
    runner_roots: defaultdict[Path, List[Path]] = defaultdict(list)
    for runner_root in sorted(runner_roots_set):
        for metrics_path in runner_root.rglob("run_*/simulation_metrics.json"):
            if metrics_path.is_file():
                runner_roots[runner_root].append(metrics_path)
                all_metrics_files.append(metrics_path)

    # Helper to compute averaged metrics across many simulation_metrics.json files
    def compute_average_metrics(files: List[Path]) -> dict:
        if not files:
            return {}

        # Accumulators
        sum_total_orders = 0.0
        sum_success = 0.0
        sum_failed = 0.0
        sum_avg_order_time = 0.0
        sum_on_time_pct = 0.0
        count = 0
        any_runners = False
        any_bev = False

        for f in files:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            dm = (data or {}).get("deliveryMetrics") or {}
            if dm:
                sum_total_orders += float(dm.get("totalOrders", 0) or 0)
                sum_success += float(dm.get("successfulDeliveries", 0) or 0)
                sum_failed += float(dm.get("failedDeliveries", 0) or 0)
                sum_avg_order_time += float(dm.get("avgOrderTime", 0.0) or 0.0)
                sum_on_time_pct += float(dm.get("onTimePercentage", 0.0) or 0.0)
                count += 1
            any_runners = any_runners or bool((data or {}).get("hasRunners"))
            any_bev = any_bev or bool((data or {}).get("hasBevCart"))

        if count == 0:
            return {}

        avg_metrics = {
            "deliveryMetrics": {
                "totalOrders": sum_total_orders / count,
                "successfulDeliveries": sum_success / count,
                "failedDeliveries": sum_failed / count,
                "avgOrderTime": sum_avg_order_time / count,
                "onTimePercentage": sum_on_time_pct / count,
            },
            "bevCartMetrics": None,
            "hasRunners": any_runners,
            "hasBevCart": any_bev,
            "_notes": "Averages computed across per-run simulation_metrics.json files",
            "_samples": count,
        }
        return avg_metrics

    # Write per-runner averaged metrics
    for runner_root, files in runner_roots.items():
        avg = compute_average_metrics(files)
        if avg:
            out_path = runner_root / "@simulation_metrics.json"
            try:
                out_path.write_text(json.dumps(avg, indent=2), encoding="utf-8")
                print(f"📊 Wrote averaged metrics → {out_path}")
            except Exception as e:
                print(f"⚠️  Failed to write averaged metrics for {runner_root}: {e}")

    # Write overall averaged metrics across all runners in this batch
    overall_avg = compute_average_metrics(all_metrics_files)
    if overall_avg:
        overall_root = root / f"{stamp}_delivery_runner_ALL_runners_{a.tee_scenario}"
        overall_root.mkdir(parents=True, exist_ok=True)
        overall_path = overall_root / "@simulation_metrics.json"
        try:
            overall_path.write_text(json.dumps(overall_avg, indent=2), encoding="utf-8")
            print(f"📈 Wrote overall averaged metrics → {overall_path}")
        except Exception as e:
            print(f"⚠️  Failed to write overall averaged metrics: {e}")

    # Also write a flat CSV of per-run delivery metrics across all generated runs
    try:
        def _gather_delivery_metrics_files() -> List[Path]:
            files: List[Path] = []
            for rr in sorted(runner_roots_set):
                files.extend(sorted(rr.rglob("orders_*/run_*/delivery_runner_metrics_run_*.json")))
            return files

        def _parse_runner_orders_run(fp: Path) -> tuple[int | None, int | None, int | None, str | None]:
            # runners from top-level folder name: <stamp>_delivery_runner_<R>_runners_<scenario>
            try:
                runner_root = fp.parents[3]
                name = runner_root.name
                pre = "delivery_runner_"
                mid = "_runners_"
                r_start = name.index(pre) + len(pre)
                r_end = name.index(mid, r_start)
                runners_val = int(name[r_start:r_end])
                scenario_val = name[r_end + len(mid):]
            except Exception:
                runners_val = None
                scenario_val = None
            # orders from orders_XXX
            try:
                orders_dir = fp.parents[2].name
                orders_val = int(orders_dir.split("_")[-1])
            except Exception:
                orders_val = None
            # run from run_YY
            try:
                run_dir = fp.parents[1].name
                run_val = int(run_dir.split("_")[-1])
            except Exception:
                run_val = None
            return runners_val, orders_val, run_val, scenario_val

        metrics_files = _gather_delivery_metrics_files()
        if metrics_files:
            csv_root = root / f"{stamp}_delivery_runner_ALL_runners_{a.tee_scenario}"
            csv_root.mkdir(parents=True, exist_ok=True)
            csv_path = csv_root / "all_simulation_metrics.csv"

            fieldnames = [
                "file",
                "stamp",
                "scenario",
                "runners",
                "orders",
                "run",
                "revenue_per_round",
                "orders_per_runner_hour",
                "on_time_rate",
                "delivery_cycle_time_p90",
                "delivery_cycle_time_avg",
                "failed_rate",
                "second_runner_break_even_orders",
                "queue_wait_avg",
                "runner_utilization_driving_pct",
                "runner_utilization_prep_pct",
                "runner_utilization_idle_pct",
                "distance_per_delivery_avg",
                "total_revenue",
                "total_orders",
                "successful_orders",
                "failed_orders",
                "total_rounds",
                "active_runner_hours",
            ]

            with csv_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for fp in metrics_files:
                    try:
                        data = json.loads(fp.read_text(encoding="utf-8"))
                    except Exception:
                        data = {}
                    runners_val, orders_val, run_val, scenario_val = _parse_runner_orders_run(fp)
                    row = {
                        "file": str(fp.relative_to(root)),
                        "stamp": stamp,
                        "scenario": scenario_val or a.tee_scenario,
                        "runners": runners_val,
                        "orders": orders_val,
                        "run": run_val,
                    }
                    for k in fieldnames:
                        if k in row:
                            continue
                        row[k] = data.get(k)
                    writer.writerow(row)
            print(f"🧾 Wrote per-run metrics CSV → {csv_path} ({len(metrics_files)} rows)")
        else:
            print("ℹ️  No delivery_runner_metrics_run_*.json files found; skipping CSV export.")
    except Exception as e:
        print(f"⚠️  Failed to write per-run metrics CSV: {e}")

    update_map_animation_files()


if __name__ == "__main__":
    main()


