#!/usr/bin/env python3
"""
Replay a single simulation from a batch to regenerate the normal outputs
produced by scripts/sim/run_unified_simulation.py.

Usage examples (PowerShell-friendly, one per line):
  python scripts/sim/replay_from_batch.py \
    --batch-dir outputs/batch_20250814_133642 \
    --simulation-id batch_20250814_133642_busy_weekday_run01_cart1

Optional overrides:
  --output-dir outputs/replay  (root where this tool creates a replay folder)
  --course-dir courses/pinetree_country_club
  --log-level INFO
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional


def _load_metrics_row(batch_dir: Path, simulation_id: str) -> Optional[Dict[str, str]]:
    metrics_path = batch_dir / "batch_metrics.csv"
    if not metrics_path.exists():
        return None
    with metrics_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if str(row.get("simulation_id", "")).strip() == simulation_id:
                return row
    return None


def _build_replay_output_root(output_dir: Optional[str], simulation_id: str) -> Path:
    base = Path(output_dir) if output_dir else Path("outputs")
    out = base / f"replay_{simulation_id}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def _run_cmd(cmd: list[str]) -> int:
    # Run as a single command invocation, no pipes/chains
    try:
        proc = subprocess.run(cmd, check=True)
        return proc.returncode
    except subprocess.CalledProcessError as e:
        return e.returncode


def replay_simulation(batch_dir: str, simulation_id: str, output_dir: Optional[str], course_dir: str, log_level: str) -> int:
    batch_path = Path(batch_dir)
    row = _load_metrics_row(batch_path, simulation_id)
    if row is None:
        print(f"metrics row not found for simulation_id: {simulation_id}")
        return 1

    mode = (row.get("mode") or "").strip().lower()
    scenario = (row.get("scenario") or "").strip()
    run_key = (row.get("run_key") or f"{scenario}_run{int(row.get('run_index', '1')):02d}").strip()
    num_carts = int(row.get("num_carts", "0") or 0)
    num_runners = int(row.get("num_runners", "0") or 0)

    replay_root = _build_replay_output_root(output_dir, simulation_id)

    run_script = str(Path("scripts") / "sim" / "run_unified_simulation.py")

    if mode == "bevcart":
        # If single cart, prefer bev-with-golfers to get sales + standard outputs.
        # If multiple carts, fall back to bev-carts GPS-only (run once per cart recomposition is not supported here).
        bev_prob = row.get("bev_order_prob")
        avg_price = row.get("bev_price_usd")
        seed = row.get("seed")
        if num_carts <= 1:
            cmd = [
                sys.executable,
                run_script,
                "--mode", "bev-with-golfers",
                "--course-dir", course_dir,
                "--num-runs", "1",
                "--output-dir", str(replay_root),
                "--log-level", log_level,
                "--tee-scenario", scenario or "typical_weekday",
                "--order-prob", f"{float(bev_prob) if bev_prob else 0.4}",
                "--avg-order-usd", f"{float(avg_price) if avg_price else 12.0}",
                "--random-seed", f"{int(seed)}" if seed else "0",
            ]
        else:
            cmd = [
                sys.executable,
                run_script,
                "--mode", "bev-carts",
                "--course-dir", course_dir,
                "--num-runs", "1",
                "--num-carts", str(num_carts),
                "--output-dir", str(replay_root),
                "--log-level", log_level,
            ]
        print("Replaying bev-cart simulation via:", " ".join(cmd))
        return _run_cmd(cmd)

    if mode == "runner":
        order_prob9 = row.get("delivery_order_prob")
        runner_speed_mps = row.get("runner_speed_mps") or "2.68"
        prep_time_min = row.get("prep_time_min") or "10"
        seed = row.get("seed")
        cmd = [
            sys.executable,
            run_script,
            "--mode", "delivery-runner",
            "--course-dir", course_dir,
            "--num-runs", "1",
            "--output-dir", str(replay_root),
            "--log-level", log_level,
            "--tee-scenario", scenario or "typical_weekday",
            "--num-runners", str(num_runners if num_runners > 0 else 1),
            "--order-prob-9", f"{float(order_prob9) if order_prob9 else 0.2}",
            "--runner-speed", f"{float(runner_speed_mps)}",
            "--prep-time", f"{int(prep_time_min)}",
            "--first-tee", "09:00",
            "--random-seed", f"{int(seed)}" if seed else "0",
        ]
        print("Replaying runner simulation via:", " ".join(cmd))
        return _run_cmd(cmd)

    print(f"Unknown or unsupported mode in metrics row: {mode}")
    return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a single simulation from batch outputs using run_unified_simulation")
    parser.add_argument("--batch-dir", required=True, help="Path to the batch output directory (contains batch_metrics.csv)")
    parser.add_argument("--simulation-id", required=True, help="Simulation ID to replay (matches batch_metrics.csv and events_by_run filename)")
    parser.add_argument("--output-dir", default=None, help="Where to store the recreated outputs")
    parser.add_argument("--course-dir", default="courses/pinetree_country_club", help="Course directory")
    parser.add_argument("--log-level", default="INFO", help="Log level for the underlying runner")

    args = parser.parse_args()
    return replay_simulation(args.batch_dir, args.simulation_id, args.output_dir, args.course_dir, args.log_level)


if __name__ == "__main__":
    raise SystemExit(main())


