#!/usr/bin/env python3
"""
Run staffing and policy optimization sweeps WITHOUT modifying existing repository files.

Strategy:
- Create an experiment workspace under outputs/experiments/<exp-name>/
- Copy the course directory into this workspace (so config edits are applied to the copy only)
- For each scenario/order/runner/sensitivity combo, run scripts/sim/run_new.py with an explicit --output-dir
- Parse delivery_runner_metrics_run_*.json metrics per run and aggregate
- Produce staffing curve summary CSV and hole restriction recommendations (markdown)

Usage (example):
  python scripts/optimization/run_staffing_experiments.py \
    --base-course-dir courses/pinetree_country_club \
    --tee-scenarios typical_weekday busy_weekend \
    --order-levels 10 14 18 28 36 44 \
    --runner-range 1-4 \
    --runs-per 5 \
    --runner-speed 6.0 \
    --prep-time 10 \
    --opening-ramp-min 0 \
    --target-on-time 0.95 \
    --max-failed-rate 0.05 \
    --max-p90 40 \
    --top-holes 3 \
    --exp-name baseline
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass
class MetricsAggregate:
    on_time_rate_mean: float
    failed_rate_mean: float
    p90_mean: float
    orders_per_runner_hour_mean: float
    second_runner_break_even_orders_mean: float
    zone_service_times_avg: Dict[str, float]
    runs_count: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run staffing and policy optimization sweeps")
    parser.add_argument("--base-course-dir", required=True, help="Path to original course directory (will be copied)")
    parser.add_argument("--tee-scenarios", nargs="+", default=["typical_weekday"], help="Tee scenarios to test")
    parser.add_argument("--order-levels", nargs="+", type=int, required=True, help="Total delivery orders per day to test")
    parser.add_argument("--runner-range", type=str, default="1-3", help="Range like '1-3'")
    parser.add_argument("--runs-per", type=int, default=5, help="Number of runs per combination")
    parser.add_argument("--runner-speed", type=float, default=6.0, help="Runner speed (m/s) override")
    parser.add_argument("--prep-time", type=int, default=10, help="Prep time (min) override")
    parser.add_argument("--opening-ramp-min", type=int, default=None, help="delivery_opening_ramp_minutes to set in copied config (optional)")
    parser.add_argument("--log-level", type=str, default="INFO", help="Log level for simulations")
    parser.add_argument("--exp-name", type=str, default=None, help="Experiment name (default: timestamp)")
    parser.add_argument("--output-root", type=str, default="outputs/experiments", help="Root folder for experiment outputs")
    parser.add_argument("--python-bin", type=str, default=sys.executable, help="Python executable to run simulations")
    # Targets
    parser.add_argument("--target-on-time", type=float, default=0.95, help="Minimum on-time rate to meet target")
    parser.add_argument("--max-failed-rate", type=float, default=0.05, help="Maximum failed rate")
    parser.add_argument("--max-p90", type=float, default=40.0, help="Maximum p90 delivery cycle time (minutes)")
    # Hole policy
    parser.add_argument("--top-holes", type=int, default=3, help="How many slowest holes to recommend restricting")
    return parser.parse_args()


def parse_range(spec: str) -> List[int]:
    spec = spec.strip()
    if "-" in spec:
        a, b = spec.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(spec)]


def copy_course_dir(base_dir: Path, dest_dir: Path) -> None:
    if dest_dir.exists():
        # Keep existing copy (allows successive runs). Ensure config exists.
        return
    shutil.copytree(base_dir, dest_dir)


def update_sim_config(course_dir: Path, *, delivery_total_orders: int, opening_ramp_min: Optional[int]) -> None:
    config_path = course_dir / "config" / "simulation_config.json"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    data["delivery_total_orders"] = int(delivery_total_orders)
    if isinstance(opening_ramp_min, int):
        data["delivery_opening_ramp_minutes"] = int(opening_ramp_min)
    config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_single_combo(
    *,
    python_bin: str,
    course_dir: Path,
    tee_scenario: str,
    num_runners: int,
    runs_per: int,
    runner_speed: float,
    prep_time: int,
    output_dir: Path,
    log_level: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        python_bin,
        "scripts/sim/run_new.py",
        "--course-dir", str(course_dir),
        "--tee-scenario", tee_scenario,
        "--num-runners", str(num_runners),
        "--num-runs", str(runs_per),
        "--runner-speed", str(runner_speed),
        "--prep-time", str(prep_time),
        "--output-dir", str(output_dir),
        "--log-level", log_level,
    ]
    subprocess.run(cmd, check=True)


def load_metrics_from_output(output_dir: Path, runs_per: int) -> List[Dict[str, Any]]:
    results: List[Dict[str, Any]] = []
    for i in range(1, runs_per + 1):
        path = output_dir / f"run_{i:02d}" / f"delivery_runner_metrics_run_{i:02d}.json"
        if path.exists():
            try:
                results.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
    return results


def aggregate_metrics(items: List[Dict[str, Any]]) -> MetricsAggregate:
    def mean(vals: Iterable[float]) -> float:
        vals = list(vals)
        return sum(vals) / len(vals) if vals else 0.0

    on_time = mean(x.get("on_time_rate", 0.0) for x in items)
    failed = mean(x.get("failed_rate", 0.0) for x in items)
    p90 = mean(x.get("delivery_cycle_time_p90", 0.0) for x in items)
    oph = mean(x.get("orders_per_runner_hour", 0.0) for x in items)
    breakeven = mean(x.get("second_runner_break_even_orders", 0.0) for x in items)

    # Average zone service times across runs
    zone_sum: Dict[str, Tuple[float, int]] = {}
    for x in items:
        zst = x.get("zone_service_times", {}) or {}
        for zone, value in zst.items():
            total, cnt = zone_sum.get(zone, (0.0, 0))
            zone_sum[zone] = (total + float(value), cnt + 1)
    zone_avg = {z: (s / c if c else 0.0) for z, (s, c) in zone_sum.items()}

    return MetricsAggregate(
        on_time_rate_mean=on_time,
        failed_rate_mean=failed,
        p90_mean=p90,
        orders_per_runner_hour_mean=oph,
        second_runner_break_even_orders_mean=breakeven,
        zone_service_times_avg=zone_avg,
        runs_count=len(items),
    )


def meets_targets(agg: MetricsAggregate, *, target_on_time: float, max_failed: float, max_p90: float) -> bool:
    if agg.runs_count == 0:
        return False
    return (
        agg.on_time_rate_mean >= target_on_time and
        agg.failed_rate_mean <= max_failed and
        agg.p90_mean <= max_p90
    )


def write_staffing_csv(
    csv_path: Path,
    rows: List[Dict[str, Any]],
) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        csv_path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_hole_policy_md(md_path: Path, *, scenario: str, order_level: int, one_runner_agg: Optional[MetricsAggregate], top_k: int) -> None:
    md_path.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    lines.append(f"## Hole restriction recommendation — scenario {scenario}, orders {order_level}, 1 runner\n\n")
    if not one_runner_agg or not one_runner_agg.zone_service_times_avg:
        lines.append("No data available to recommend restrictions.\n")
        md_path.write_text("".join(lines), encoding="utf-8")
        return
    # Sort holes by average service time descending
    pairs = sorted(one_runner_agg.zone_service_times_avg.items(), key=lambda kv: kv[1], reverse=True)
    lines.append("Ranked slowest holes (avg service time in minutes):\n\n")
    for idx, (zone, avg_minutes) in enumerate(pairs[:top_k], start=1):
        lines.append(f"{idx}. {zone}: {avg_minutes:.1f} min\n")
    lines.append("\nPolicy: Restrict these holes for 1 runner days, or allow only outside peak windows.\n")
    md_path.write_text("".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()

    base_course_dir = Path(args.base_course_dir).resolve()
    if not base_course_dir.exists():
        raise SystemExit(f"Base course dir not found: {base_course_dir}")

    exp_name = args.exp_name or datetime.now().strftime("%Y%m%d_%H%M%S")
    exp_root = Path(args.output_root) / exp_name
    exp_root.mkdir(parents=True, exist_ok=True)

    # Prepare a course copy per tee scenario to allow scenario-specific config edits
    course_copies: Dict[str, Path] = {}
    for scenario in args.tee_scenarios:
        copy_path = exp_root / f"course_copy_{scenario}"
        copy_course_dir(base_course_dir, copy_path)
        course_copies[scenario] = copy_path

    runner_values = parse_range(args.runner_range)

    staffing_rows: List[Dict[str, Any]] = []
    minimal_choices: Dict[Tuple[str, int], int] = {}

    # For hole policy recommendations (1 runner only)
    one_runner_aggs: Dict[Tuple[str, int], MetricsAggregate] = {}

    for scenario in args.tee_scenarios:
        for orders in args.order_levels:
            # Update config in the copied course dir
            update_sim_config(course_copies[scenario], delivery_total_orders=orders, opening_ramp_min=args.opening_ramp_min)

            combos: List[Tuple[int, MetricsAggregate]] = []

            for n_runners in runner_values:
                out_dir = exp_root / scenario / f"orders_{orders:03d}" / f"runners_{n_runners}"
                run_single_combo(
                    python_bin=args.python_bin,
                    course_dir=course_copies[scenario],
                    tee_scenario=scenario,
                    num_runners=n_runners,
                    runs_per=args.runs_per,
                    runner_speed=args.runner_speed,
                    prep_time=args.prep_time,
                    output_dir=out_dir,
                    log_level=args.log_level,
                )

                metrics_items = load_metrics_from_output(out_dir, args.runs_per)
                agg = aggregate_metrics(metrics_items)
                combos.append((n_runners, agg))

                row = {
                    "tee_scenario": scenario,
                    "orders": orders,
                    "num_runners": n_runners,
                    "runs": agg.runs_count,
                    "on_time_rate_mean": round(agg.on_time_rate_mean, 4),
                    "failed_rate_mean": round(agg.failed_rate_mean, 4),
                    "p90_mean": round(agg.p90_mean, 2),
                    "orders_per_runner_hour_mean": round(agg.orders_per_runner_hour_mean, 3),
                    "second_runner_break_even_orders_mean": round(agg.second_runner_break_even_orders_mean, 2),
                    "meets_targets": meets_targets(agg, target_on_time=args.target_on_time, max_failed=args.max_failed_rate, max_p90=args.max_p90),
                }
                staffing_rows.append(row)

                if n_runners == 1:
                    one_runner_aggs[(scenario, orders)] = agg

            # Determine minimal staffing for this orders level
            minimal: Optional[int] = None
            for n_runners, agg in sorted(combos, key=lambda t: t[0]):
                if meets_targets(agg, target_on_time=args.target_on_time, max_failed=args.max_failed_rate, max_p90=args.max_p90):
                    minimal = n_runners
                    break
            if minimal is not None:
                minimal_choices[(scenario, orders)] = minimal

            # Write hole policy recommendation for 1 runner
            policy_md = exp_root / scenario / f"orders_{orders:03d}" / "hole_policy_1_runner.md"
            write_hole_policy_md(policy_md, scenario=scenario, order_level=orders, one_runner_agg=one_runner_aggs.get((scenario, orders)), top_k=args.top_holes)

    # Write staffing curve CSV
    staffing_csv = exp_root / "staffing_summary.csv"
    write_staffing_csv(staffing_csv, staffing_rows)

    # Write summary markdown
    summary_md = exp_root / "experiment_summary.md"
    lines: List[str] = []
    lines.append(f"## Experiment: {exp_name}\n\n")
    lines.append(f"Output root: {exp_root}\n\n")
    lines.append("### Minimal staffing by scenario and order level\n\n")
    if not minimal_choices:
        lines.append("No combinations met targets. Consider relaxing thresholds or increasing runners.\n")
    else:
        # Group by scenario
        by_scenario: Dict[str, List[Tuple[int, int]]] = {}
        for (scenario, orders), minimal in minimal_choices.items():
            by_scenario.setdefault(scenario, []).append((orders, minimal))
        for scenario, pairs in by_scenario.items():
            lines.append(f"- **{scenario}**:\n")
            for orders, minimal in sorted(pairs, key=lambda t: t[0]):
                lines.append(f"  - Orders {orders}: minimal runners = {minimal}\n")
    lines.append("\nTargets: on_time_rate ≥ {:.0%}, failed_rate ≤ {:.0%}, p90 ≤ {:.0f} min\n".format(args.target_on_time, args.max_failed_rate, args.max_p90))
    summary_md.write_text("".join(lines), encoding="utf-8")

    print(f"Done. Experiment directory: {exp_root}")


if __name__ == "__main__":
    main()


