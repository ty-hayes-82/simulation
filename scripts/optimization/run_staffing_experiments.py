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
import math
import shutil
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass
class BlockingVariant:
    key: str
    cli_flags: List[str]

BLOCKING_VARIANTS: List[BlockingVariant] = [
    BlockingVariant(key="none", cli_flags=[]),
    BlockingVariant(key="front", cli_flags=["--block-holes", "1", "2", "3"]),
    BlockingVariant(key="back", cli_flags=["--block-holes", "10", "11", "12"]),
    BlockingVariant(key="front_mid", cli_flags=["--block-holes", "1", "2", "3", "4", "5", "6"]),
    BlockingVariant(key="front_back", cli_flags=["--block-holes", "1", "2", "3", "10", "11", "12"]),
    BlockingVariant(key="front_mid_back", cli_flags=["--block-holes", "1", "2", "3", "4", "5", "6", "10", "11", "12"]),
]


@dataclass
class MetricsAggregate:
    on_time_rate_mean: float
    failed_rate_mean: float
    p90_mean: float
    orders_per_runner_hour_mean: float
    second_runner_break_even_orders_mean: float
    zone_service_times_avg: Dict[str, float]
    runs_count: int
    # New fields for confidence intervals and efficiency frontier
    on_time_rate_std: float = 0.0
    failed_rate_std: float = 0.0
    p90_std: float = 0.0
    orders_per_runner_hour_std: float = 0.0
    on_time_rate_ci_lower: float = 0.0
    on_time_rate_ci_upper: float = 0.0
    failed_rate_ci_lower: float = 0.0
    failed_rate_ci_upper: float = 0.0
    p90_ci_lower: float = 0.0
    p90_ci_upper: float = 0.0
    composite_score: float = 0.0
    is_frontier_point: bool = False
    is_knee_point: bool = False
    is_stable: bool = False


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run staffing and policy optimization sweeps")
    parser.add_argument("--base-course-dir", required=True, help="Path to original course directory (will be copied)")
    parser.add_argument("--tee-scenarios", nargs="+", default=["typical_weekday"], help="Tee scenarios to test (e.g., real_tee_sheet)")
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
    parser.add_argument("--prefer-real-tee-config", action="store_true", help="If present and tee_times_config_real.json exists, copy it over tee_times_config.json in the experiment course copy")
    # Targets
    parser.add_argument("--target-on-time", type=float, default=0.95, help="Minimum on-time rate to meet target")
    parser.add_argument("--max-failed-rate", type=float, default=0.05, help="Maximum failed rate")
    parser.add_argument("--max-p90", type=float, default=40.0, help="Maximum p90 delivery cycle time (minutes)")
    # Hole policy
    parser.add_argument("--top-holes", type=int, default=3, help="How many slowest holes to recommend restricting")
    # Parallelism and reliability
    parser.add_argument("--parallel-jobs", type=int, default=1, help="Number of parallel jobs to run (default: 1 = sequential)")
    parser.add_argument("--resume", action="store_true", help="Skip combinations that already have complete results")
    parser.add_argument("--force", action="store_true", help="Force rerun even if results exist (overrides --resume)")
    parser.add_argument("--base-seed", type=int, help="Base seed for reproducible runs (each run gets base_seed + run_number)")
    parser.add_argument("--max-retries", type=int, default=2, help="Maximum retries for failed runs")
    parser.add_argument("--run-blocking-variants", action="store_true", help="Run all four blocking variants for each combination")
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


def maybe_use_real_tee_config(course_copy_dir: Path, prefer_real: bool) -> None:
    """If requested and available, replace tee_times_config.json with tee_times_config_real.json in the course copy.

    This keeps original files untouched while ensuring runs use the real tee sheet.
    """
    if not prefer_real:
        return
    cfg_dir = course_copy_dir / "config"
    real_fp = cfg_dir / "tee_times_config_real.json"
    default_fp = cfg_dir / "tee_times_config.json"
    try:
        if real_fp.exists():
            default_fp.write_text(real_fp.read_text(encoding="utf-8"), encoding="utf-8")
    except Exception:
        # Non-fatal; proceed with existing file
        pass


def update_sim_config(course_dir: Path, *, delivery_total_orders: int, opening_ramp_min: Optional[int]) -> None:
    config_path = course_dir / "config" / "simulation_config.json"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    data["delivery_total_orders"] = int(delivery_total_orders)
    if isinstance(opening_ramp_min, int):
        data["delivery_opening_ramp_minutes"] = int(opening_ramp_min)
    config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def is_combo_complete(output_dir: Path, runs_per: int) -> bool:
    """Check if a combination has complete results."""
    if not output_dir.exists():
        return False
    
    # Check if all expected metrics files exist
    for i in range(1, runs_per + 1):
        metrics_file = output_dir / f"run_{i:02d}" / f"delivery_runner_metrics_run_{i:02d}.json"
        if not metrics_file.exists():
            return False
    
    return True


def run_single_combo_with_retry(
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
    base_seed: Optional[int] = None,
    max_retries: int = 2,
    extra_cli_args: Optional[List[str]] = None,
) -> bool:
    """Run a single combination with retry logic."""
    for attempt in range(max_retries + 1):
        try:
            run_single_combo(
                python_bin=python_bin,
                course_dir=course_dir,
                tee_scenario=tee_scenario,
                num_runners=num_runners,
                runs_per=runs_per,
                runner_speed=runner_speed,
                prep_time=prep_time,
                output_dir=output_dir,
                log_level=log_level,
                base_seed=base_seed,
                extra_cli_args=extra_cli_args,
            )
            return True
        except subprocess.CalledProcessError as e:
            if attempt < max_retries:
                print(f"Attempt {attempt + 1} failed for {tee_scenario}/orders/runners_{num_runners}, retrying...")
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                print(f"Failed after {max_retries + 1} attempts: {tee_scenario}/orders/runners_{num_runners}")
                print(f"Error: {e}")
                return False
        except Exception as e:
            print(f"Unexpected error for {tee_scenario}/orders/runners_{num_runners}: {e}")
            return False
    
    return False


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
    base_seed: Optional[int] = None,
    extra_cli_args: Optional[List[str]] = None,
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
    
    # Add seed if provided
    if base_seed is not None:
        cmd.extend(["--base-seed", str(base_seed)])
    
    # Add any extra CLI flags for variants
    if extra_cli_args:
        cmd.extend(extra_cli_args)

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


def calculate_confidence_interval(values: List[float], confidence: float = 0.95) -> Tuple[float, float]:
    """Calculate confidence interval for a list of values."""
    if len(values) < 2:
        return (0.0, 0.0)
    
    n = len(values)
    mean_val = sum(values) / n
    variance = sum((x - mean_val) ** 2 for x in values) / (n - 1)
    std_dev = math.sqrt(variance)
    
    # Use t-distribution for small samples (approximation)
    # For simplicity, using 1.96 for 95% CI (normal approximation)
    t_value = 1.96 if n > 30 else 2.0  # Conservative for small samples
    margin = t_value * std_dev / math.sqrt(n)
    
    return (mean_val - margin, mean_val + margin)


def calculate_composite_score(agg: MetricsAggregate) -> float:
    """Calculate composite efficiency score for frontier analysis."""
    # Weighted score: maximize on_time_rate and orders_per_runner_hour, minimize failed_rate and p90
    # Normalize to 0-1 scale and weight appropriately
    on_time_score = agg.on_time_rate_mean  # Already 0-1
    failed_score = 1.0 - min(agg.failed_rate_mean, 1.0)  # Invert so higher is better
    p90_score = max(0.0, 1.0 - (agg.p90_mean / 60.0))  # Normalize assuming 60min is very poor
    efficiency_score = min(agg.orders_per_runner_hour_mean / 10.0, 1.0)  # Normalize assuming 10 orders/hour is excellent
    
    # Weighted combination (adjust weights as needed)
    return (0.3 * on_time_score + 0.3 * failed_score + 0.2 * p90_score + 0.2 * efficiency_score)


def aggregate_metrics(items: List[Dict[str, Any]]) -> MetricsAggregate:
    def mean(vals: Iterable[float]) -> float:
        vals = list(vals)
        return sum(vals) / len(vals) if vals else 0.0
    
    def std_dev(vals: List[float]) -> float:
        if len(vals) < 2:
            return 0.0
        mean_val = sum(vals) / len(vals)
        variance = sum((x - mean_val) ** 2 for x in vals) / (len(vals) - 1)
        return math.sqrt(variance)

    # Extract values for statistics
    on_time_vals = [x.get("on_time_rate", 0.0) for x in items]
    failed_vals = [x.get("failed_rate", 0.0) for x in items]
    p90_vals = [x.get("delivery_cycle_time_p90", 0.0) for x in items]
    oph_vals = [x.get("orders_per_runner_hour", 0.0) for x in items]
    breakeven_vals = [x.get("second_runner_break_even_orders", 0.0) for x in items]

    # Calculate means
    on_time = mean(on_time_vals)
    failed = mean(failed_vals)
    p90 = mean(p90_vals)
    oph = mean(oph_vals)
    breakeven = mean(breakeven_vals)

    # Calculate standard deviations
    on_time_std = std_dev(on_time_vals)
    failed_std = std_dev(failed_vals)
    p90_std = std_dev(p90_vals)
    oph_std = std_dev(oph_vals)

    # Calculate confidence intervals
    on_time_ci = calculate_confidence_interval(on_time_vals)
    failed_ci = calculate_confidence_interval(failed_vals)
    p90_ci = calculate_confidence_interval(p90_vals)

    # Average zone service times across runs
    zone_sum: Dict[str, Tuple[float, int]] = {}
    for x in items:
        zst = x.get("zone_service_times", {}) or {}
        for zone, value in zst.items():
            total, cnt = zone_sum.get(zone, (0.0, 0))
            zone_sum[zone] = (total + float(value), cnt + 1)
    zone_avg = {z: (s / c if c else 0.0) for z, (s, c) in zone_sum.items()}

    # Create aggregate with all new fields
    agg = MetricsAggregate(
        on_time_rate_mean=on_time,
        failed_rate_mean=failed,
        p90_mean=p90,
        orders_per_runner_hour_mean=oph,
        second_runner_break_even_orders_mean=breakeven,
        zone_service_times_avg=zone_avg,
        runs_count=len(items),
        on_time_rate_std=on_time_std,
        failed_rate_std=failed_std,
        p90_std=p90_std,
        orders_per_runner_hour_std=oph_std,
        on_time_rate_ci_lower=on_time_ci[0],
        on_time_rate_ci_upper=on_time_ci[1],
        failed_rate_ci_lower=failed_ci[0],
        failed_rate_ci_upper=failed_ci[1],
        p90_ci_lower=p90_ci[0],
        p90_ci_upper=p90_ci[1],
    )
    
    # Calculate composite score
    agg.composite_score = calculate_composite_score(agg)
    
    return agg


def meets_targets(agg: MetricsAggregate, *, target_on_time: float, max_failed: float, max_p90: float) -> bool:
    if agg.runs_count == 0:
        return False
    return (
        agg.on_time_rate_mean >= target_on_time and
        agg.failed_rate_mean <= max_failed and
        agg.p90_mean <= max_p90
    )


def is_stable(agg: MetricsAggregate, *, target_on_time: float, max_failed: float, max_p90: float) -> bool:
    """Check if the configuration is stable based on confidence intervals."""
    if agg.runs_count < 3:  # Need at least 3 runs for meaningful CI
        return False
    
    # Check if upper bounds of CI still meet targets
    return (
        agg.on_time_rate_ci_lower >= target_on_time * 0.95 and  # Allow 5% tolerance
        agg.failed_rate_ci_upper <= max_failed * 1.05 and
        agg.p90_ci_upper <= max_p90 * 1.05
    )


def identify_frontier_points(combos: List[Tuple[int, MetricsAggregate]]) -> List[Tuple[int, MetricsAggregate]]:
    """Identify points on the efficiency frontier using Pareto dominance."""
    if not combos:
        return []
    
    frontier_points = []
    
    for i, (runners_i, agg_i) in enumerate(combos):
        is_dominated = False
        
        for j, (runners_j, agg_j) in enumerate(combos):
            if i == j:
                continue
                
            # Check if j dominates i (j is better or equal in all dimensions and strictly better in at least one)
            if (agg_j.on_time_rate_mean >= agg_i.on_time_rate_mean and
                agg_j.failed_rate_mean <= agg_i.failed_rate_mean and
                agg_j.p90_mean <= agg_i.p90_mean and
                agg_j.orders_per_runner_hour_mean >= agg_i.orders_per_runner_hour_mean and
                runners_j <= runners_i and  # Prefer fewer runners
                (agg_j.on_time_rate_mean > agg_i.on_time_rate_mean or
                 agg_j.failed_rate_mean < agg_i.failed_rate_mean or
                 agg_j.p90_mean < agg_i.p90_mean or
                 agg_j.orders_per_runner_hour_mean > agg_i.orders_per_runner_hour_mean or
                 runners_j < runners_i)):
                is_dominated = True
                break
        
        if not is_dominated:
            agg_i.is_frontier_point = True
            frontier_points.append((runners_i, agg_i))
    
    return sorted(frontier_points, key=lambda x: x[0])


def identify_knee_point(frontier_points: List[Tuple[int, MetricsAggregate]]) -> Optional[int]:
    """Identify the knee point in the efficiency frontier using curvature analysis."""
    if len(frontier_points) < 3:
        return None
    
    # Sort by number of runners
    sorted_points = sorted(frontier_points, key=lambda x: x[0])
    
    max_curvature = 0.0
    knee_runners = None
    
    # Calculate curvature for each point (except first and last)
    for i in range(1, len(sorted_points) - 1):
        prev_runners, prev_agg = sorted_points[i-1]
        curr_runners, curr_agg = sorted_points[i]
        next_runners, next_agg = sorted_points[i+1]
        
        # Use composite score as the y-axis for curvature calculation
        x1, y1 = prev_runners, prev_agg.composite_score
        x2, y2 = curr_runners, curr_agg.composite_score
        x3, y3 = next_runners, next_agg.composite_score
        
        # Calculate curvature using the formula for discrete points
        if x3 - x1 != 0:
            # Approximate curvature using second derivative
            d1 = (y2 - y1) / (x2 - x1) if x2 != x1 else 0
            d2 = (y3 - y2) / (x3 - x2) if x3 != x2 else 0
            curvature = abs(d2 - d1) / (x3 - x1)
            
            if curvature > max_curvature:
                max_curvature = curvature
                knee_runners = curr_runners
    
    return knee_runners


@dataclass
class ComboJob:
    """Represents a single combination job to be executed."""
    scenario: str
    orders: int
    num_runners: int
    course_dir: Path
    output_dir: Path
    python_bin: str
    runs_per: int
    runner_speed: float
    prep_time: int
    log_level: str
    base_seed: Optional[int]
    max_retries: int
    variant_key: str
    extra_cli_args: Optional[List[str]]


def run_combo_job(job: ComboJob) -> Tuple[str, int, int, str, bool, Optional[MetricsAggregate]]:
    """Run a single combination job (for parallel execution)."""
    success = run_single_combo_with_retry(
        python_bin=job.python_bin,
        course_dir=job.course_dir,
        tee_scenario=job.scenario,
        num_runners=job.num_runners,
        runs_per=job.runs_per,
        runner_speed=job.runner_speed,
        prep_time=job.prep_time,
        output_dir=job.output_dir,
        log_level=job.log_level,
        base_seed=job.base_seed,
        max_retries=job.max_retries,
        extra_cli_args=job.extra_cli_args,
    )
    
    if success:
        metrics_items = load_metrics_from_output(job.output_dir, job.runs_per)
        agg = aggregate_metrics(metrics_items)
        return (job.scenario, job.orders, job.num_runners, job.variant_key, True, agg)
    else:
        return (job.scenario, job.orders, job.num_runners, job.variant_key, False, None)


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
        maybe_use_real_tee_config(copy_path, args.prefer_real_tee_config)
        course_copies[scenario] = copy_path

    runner_values = parse_range(args.runner_range)

    staffing_rows: List[Dict[str, Any]] = []
    minimal_choices: Dict[Tuple[str, int], int] = {}

    # For hole policy recommendations (1 runner only)
    one_runner_aggs: Dict[Tuple[str, int], MetricsAggregate] = {}

    # Prepare all jobs
    all_jobs = []
    
    variants_to_run = BLOCKING_VARIANTS if args.run_blocking_variants else [BLOCKING_VARIANTS[0]]

    for scenario in args.tee_scenarios:
        for orders in args.order_levels:
            # Update config in the copied course dir
            update_sim_config(course_copies[scenario], delivery_total_orders=orders, opening_ramp_min=args.opening_ramp_min)

            for n_runners in runner_values:
                for variant in variants_to_run:
                    out_dir = exp_root / scenario / f"orders_{orders:03d}" / f"runners_{n_runners}" / variant.key
                    
                    # Check if we should skip this combination
                    if args.resume and not args.force and is_combo_complete(out_dir, args.runs_per):
                        print(f"Skipping {scenario}/orders_{orders:03d}/runners_{n_runners}/{variant.key} (already complete)")
                        continue
                    
                    # Calculate seed for this job
                    job_seed = None
                    if args.base_seed is not None:
                        # Create unique seed based on scenario, orders, runners, and variant
                        job_seed = args.base_seed + hash(f"{scenario}_{orders}_{n_runners}_{variant.key}") % 10000
                    
                    job = ComboJob(
                        scenario=scenario,
                        orders=orders,
                        num_runners=n_runners,
                        course_dir=course_copies[scenario],
                        output_dir=out_dir,
                        python_bin=args.python_bin,
                        runs_per=args.runs_per,
                        runner_speed=args.runner_speed,
                        prep_time=args.prep_time,
                        log_level=args.log_level,
                        base_seed=job_seed,
                        max_retries=args.max_retries,
                        variant_key=variant.key,
                        extra_cli_args=variant.cli_flags,
                    )
                    all_jobs.append(job)

    print(f"Prepared {len(all_jobs)} jobs to execute")
    
    # Execute jobs (parallel or sequential)
    job_results = {}
    failed_jobs = []
    
    if args.parallel_jobs > 1 and len(all_jobs) > 1:
        print(f"Running jobs in parallel with {args.parallel_jobs} workers")
        with ProcessPoolExecutor(max_workers=args.parallel_jobs) as executor:
            # Submit all jobs
            future_to_job = {executor.submit(run_combo_job, job): job for job in all_jobs}
            
            # Collect results as they complete
            for future in as_completed(future_to_job):
                job = future_to_job[future]
                try:
                    scenario, orders, num_runners, variant_key, success, agg = future.result()
                    if success and agg:
                        job_results[(scenario, orders, num_runners, variant_key)] = agg
                        print(f"✅ Completed {scenario}/orders_{orders:03d}/runners_{num_runners}/{variant_key}")
                    else:
                        failed_jobs.append((scenario, orders, num_runners, variant_key))
                        print(f"❌ Failed {scenario}/orders_{orders:03d}/runners_{num_runners}/{variant_key}")
                except Exception as e:
                    failed_jobs.append((job.scenario, job.orders, job.num_runners, job.variant_key))
                    print(f"❌ Exception in {job.scenario}/orders_{job.orders:03d}/runners_{job.num_runners}/{job.variant_key}: {e}")
    else:
        print("Running jobs sequentially")
        for job in all_jobs:
            try:
                scenario, orders, num_runners, variant_key, success, agg = run_combo_job(job)
                if success and agg:
                    job_results[(scenario, orders, num_runners, variant_key)] = agg
                    print(f"✅ Completed {scenario}/orders_{orders:03d}/runners_{num_runners}/{variant_key}")
                else:
                    failed_jobs.append((scenario, orders, num_runners, variant_key))
                    print(f"❌ Failed {scenario}/orders_{orders:03d}/runners_{num_runners}/{variant_key}")
            except Exception as e:
                failed_jobs.append((job.scenario, job.orders, job.num_runners, job.variant_key))
                print(f"❌ Exception in {job.scenario}/orders_{job.orders:03d}/runners_{job.num_runners}/{job.variant_key}: {e}")
    
    # Load results for completed jobs (including resumed ones)
    for scenario in args.tee_scenarios:
        for orders in args.order_levels:
            for variant in variants_to_run:
                combos: List[Tuple[int, MetricsAggregate]] = []
                
                for n_runners in runner_values:
                    out_dir = exp_root / scenario / f"orders_{orders:03d}" / f"runners_{n_runners}" / variant.key
                    
                    # Try to get from job results first, then load from disk
                    agg = job_results.get((scenario, orders, n_runners, variant.key))
                    if agg is None and is_combo_complete(out_dir, args.runs_per):
                        # Load from existing results
                        metrics_items = load_metrics_from_output(out_dir, args.runs_per)
                        agg = aggregate_metrics(metrics_items)
                    
                    if agg:
                        combos.append((n_runners, agg))
                        if n_runners == 1:
                            one_runner_aggs[(scenario, orders, variant.key)] = agg

                # Perform frontier analysis after all combinations are complete
                frontier_points = identify_frontier_points(combos)
                knee_runners = identify_knee_point(frontier_points)
                
                # Mark knee point
                if knee_runners:
                    for n_runners, agg in combos:
                        if n_runners == knee_runners:
                            agg.is_knee_point = True
                            break

                # Add rows to staffing data with enhanced metrics
                for n_runners, agg in combos:
                    # Check stability
                    agg.is_stable = is_stable(agg, target_on_time=args.target_on_time, max_failed=args.max_failed_rate, max_p90=args.max_p90)
                    
                    row = {
                        "tee_scenario": scenario,
                        "orders": orders,
                        "variant": variant.key,
                        "num_runners": n_runners,
                        "runs": agg.runs_count,
                        "on_time_rate_mean": round(agg.on_time_rate_mean, 4),
                        "failed_rate_mean": round(agg.failed_rate_mean, 4),
                        "p90_mean": round(agg.p90_mean, 2),
                        "orders_per_runner_hour_mean": round(agg.orders_per_runner_hour_mean, 3),
                        "second_runner_break_even_orders_mean": round(agg.second_runner_break_even_orders_mean, 2),
                        "meets_targets": meets_targets(agg, target_on_time=args.target_on_time, max_failed=args.max_failed_rate, max_p90=args.max_p90),
                        # New confidence interval fields
                        "on_time_rate_std": round(agg.on_time_rate_std, 4),
                        "failed_rate_std": round(agg.failed_rate_std, 4),
                        "p90_std": round(agg.p90_std, 2),
                        "on_time_rate_ci_lower": round(agg.on_time_rate_ci_lower, 4),
                        "on_time_rate_ci_upper": round(agg.on_time_rate_ci_upper, 4),
                        "failed_rate_ci_lower": round(agg.failed_rate_ci_lower, 4),
                        "failed_rate_ci_upper": round(agg.failed_rate_ci_upper, 4),
                        "p90_ci_lower": round(agg.p90_ci_lower, 2),
                        "p90_ci_upper": round(agg.p90_ci_upper, 2),
                        # Efficiency frontier fields
                        "composite_score": round(agg.composite_score, 4),
                        "is_frontier_point": agg.is_frontier_point,
                        "is_knee_point": agg.is_knee_point,
                        "is_stable": agg.is_stable,
                    }
                    staffing_rows.append(row)

                # Determine minimal staffing for this orders level
                minimal: Optional[int] = None
                for n_runners, agg in sorted(combos, key=lambda t: t[0]):
                    if meets_targets(agg, target_on_time=args.target_on_time, max_failed=args.max_failed_rate, max_p90=args.max_p90):
                        minimal = n_runners
                        break
                if minimal is not None:
                    minimal_choices[(scenario, orders, variant.key)] = minimal

                # Write hole policy recommendation for 1 runner
                policy_md = exp_root / scenario / f"orders_{orders:03d}" / variant.key / "hole_policy_1_runner.md"
                write_hole_policy_md(policy_md, scenario=scenario, order_level=orders, one_runner_agg=one_runner_aggs.get((scenario, orders, variant.key)), top_k=args.top_holes)

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
        by_scenario: Dict[str, List[Tuple[int, int, str]]] = {}
        for (scenario, orders, variant_key), minimal in minimal_choices.items():
            by_scenario.setdefault(scenario, []).append((orders, minimal, variant_key))
        for scenario, pairs in by_scenario.items():
            lines.append(f"- **{scenario}**:\n")
            # group by variant
            from itertools import groupby
            pairs.sort(key=lambda t: t[2]) # sort by variant key
            for variant_key, group in groupby(pairs, key=lambda t: t[2]):
                lines.append(f"  - **Variant: {variant_key}**\n")
                for orders, minimal, _ in sorted(list(group), key=lambda t: t[0]):
                    lines.append(f"    - Orders {orders}: minimal runners = {minimal}\n")

    lines.append("\nTargets: on_time_rate ≥ {:.0%}, failed_rate ≤ {:.0%}, p90 ≤ {:.0f} min\n".format(args.target_on_time, args.max_failed_rate, args.max_p90))
    
    # Add failed jobs summary if any
    if failed_jobs:
        lines.append(f"\n### Failed Jobs ({len(failed_jobs)} total)\n\n")
        lines.append("The following combinations failed to complete:\n\n")
        for scenario, orders, num_runners, variant_key in failed_jobs:
            lines.append(f"- {scenario}, orders {orders}, runners {num_runners}, variant {variant_key}\n")
        lines.append("\nConsider rerunning with `--max-retries` increased or check logs for errors.\n")
    
    summary_md.write_text("".join(lines), encoding="utf-8")

    # Print final summary
    total_combinations = len(args.tee_scenarios) * len(args.order_levels) * len(runner_values) * len(variants_to_run)
    completed_combinations = len(job_results)
    
    print(f"\nExperiment Summary:")
    print(f"  Directory: {exp_root}")
    print(f"  Total combinations: {total_combinations}")
    print(f"  Completed: {completed_combinations}")
    print(f"  Failed: {len(failed_jobs)}")
    if args.parallel_jobs > 1:
        print(f"  Parallel workers: {args.parallel_jobs}")
    if args.base_seed is not None:
        print(f"  Base seed: {args.base_seed}")
    print(f"  Resume mode: {'enabled' if args.resume else 'disabled'}")
    
    if failed_jobs:
        print(f"\n⚠️  {len(failed_jobs)} combinations failed. Check the summary.md for details.")
    else:
        print(f"\n✅ All combinations completed successfully!")


if __name__ == "__main__":
    main()


