#!/usr/bin/env python3
"""
Recommend number of delivery runners for given orders and blocked holes.

Runs scripts/sim/run_new.py for a range of runner counts, aggregates per-run
delivery metrics, computes confidence bounds, and prints the smallest runner
count that meets targets with high confidence.

Usage examples (Windows PowerShell caret for line breaks):

  python scripts/optimization/optimize_runners.py ^
    --course-dir courses/pinetree_country_club ^
    --tee-scenario real_tee_sheet ^
    --orders 36 ^
    --runner-range 1-3 ^
    --runs-per 8 ^
    --block-holes 1 2 3 ^
    --target-on-time 0.90 --max-failed-rate 0.05 --max-p90 40

This wrapper prints a single line JSON recommendation and exits with code 0
if a recommendation is found, or 2 if no runner count meets targets.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def parse_range(spec: str) -> List[int]:
    spec = spec.strip()
    if "-" in spec:
        a, b = spec.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(spec)]


def mean(values: Iterable[float]) -> float:
    vals = list(values)
    return (sum(vals) / len(vals)) if vals else 0.0


def std_dev(values: Iterable[float]) -> float:
    vals = list(values)
    n = len(vals)
    if n < 2:
        return 0.0
    m = sum(vals) / n
    return math.sqrt(sum((x - m) ** 2 for x in vals) / (n - 1))


def wilson_ci(successes: int, total: int, confidence: float = 0.95) -> Tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Returns (lower, upper) for p, handling edge cases gracefully.
    """
    if total <= 0:
        return (0.0, 0.0)
    # z for two-sided CI; 1.96≈95%
    z = 1.96 if abs(confidence - 0.95) < 1e-6 else 1.96
    phat = successes / total
    denom = 1 + z * z / total
    center = phat + z * z / (2 * total)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total)
    lower = (center - margin) / denom
    upper = (center + margin) / denom
    return (max(0.0, lower), min(1.0, upper))


@dataclass
class RunMetrics:
    on_time_rate: float
    failed_rate: float
    p90: float
    orders_per_runner_hour: float
    successful_orders: int
    total_orders: int


def load_one_run_metrics(run_dir: Path) -> Optional[RunMetrics]:
    """Prefer delivery_runner_metrics_run_XX.json; fallback to simulation_metrics.json."""
    # Try delivery_runner_metrics_run_XX.json
    for path in run_dir.glob("delivery_runner_metrics_run_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        return RunMetrics(
            on_time_rate=float(data.get("on_time_rate", 0.0) or 0.0),
            failed_rate=float(data.get("failed_rate", 0.0) or 0.0),
            p90=float(data.get("delivery_cycle_time_p90", 0.0) or 0.0),
            orders_per_runner_hour=float(data.get("orders_per_runner_hour", 0.0) or 0.0),
            successful_orders=int(data.get("successful_orders", data.get("successfulDeliveries", 0)) or 0),
            total_orders=int(data.get("total_orders", data.get("totalOrders", 0)) or 0),
        )

    # Fallback simulation_metrics.json
    sm = run_dir / "simulation_metrics.json"
    if sm.exists():
        try:
            data = json.loads(sm.read_text(encoding="utf-8"))
            dm = data.get("deliveryMetrics") or {}
            on_time_pct = float(dm.get("onTimePercentage", 0.0) or 0.0) / 100.0
            successful = int(dm.get("successfulDeliveries", 0) or 0)
            total = int(dm.get("totalOrders", 0) or 0)
            failed = int(dm.get("failedDeliveries", 0) or (total - successful))
            failed_rate = (failed / total) if total > 0 else 0.0
            return RunMetrics(
                on_time_rate=on_time_pct,
                failed_rate=failed_rate,
                p90=float("nan"),  # not present in simulation_metrics.json
                orders_per_runner_hour=float(dm.get("ordersPerRunnerHour", 0.0) or 0.0),
                successful_orders=successful,
                total_orders=total,
            )
        except Exception:
            return None

    return None


def aggregate_runs(run_dirs: List[Path]) -> Tuple[List[RunMetrics], Dict[str, Any]]:
    items: List[RunMetrics] = []
    for rd in run_dirs:
        m = load_one_run_metrics(rd)
        if m is not None:
            items.append(m)

    # Means
    on_time_vals = [m.on_time_rate for m in items if not math.isnan(m.on_time_rate)]
    failed_vals = [m.failed_rate for m in items if not math.isnan(m.failed_rate)]
    p90_vals = [m.p90 for m in items if not math.isnan(m.p90)]
    oph_vals = [m.orders_per_runner_hour for m in items if not math.isnan(m.orders_per_runner_hour)]

    # Wilson CI from pooled successes
    total_successes = sum(m.successful_orders for m in items)
    total_orders = sum(m.total_orders for m in items)
    ot_ci_lo, ot_ci_hi = wilson_ci(total_successes, total_orders, confidence=0.95)

    agg = {
        "runs": len(items),
        "on_time_mean": mean(on_time_vals),
        "failed_mean": mean(failed_vals),
        "p90_mean": mean(p90_vals) if p90_vals else float("nan"),
        "oph_mean": mean(oph_vals),
        "on_time_wilson_lo": ot_ci_lo,
        "on_time_wilson_hi": ot_ci_hi,
        "total_successful_orders": total_successes,
        "total_orders": total_orders,
    }
    return items, agg


def run_combo(
    *,
    python_bin: str,
    course_dir: Path,
    tee_scenario: str,
    num_runners: int,
    orders: int,
    runs_per: int,
    output_dir: Path,
    log_level: str,
    block_holes: Optional[List[int]] = None,
    runner_speed: Optional[float] = None,
    prep_time: Optional[int] = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    cmd: List[str] = [
        python_bin,
        "scripts/sim/run_new.py",
        "--course-dir", str(course_dir),
        "--tee-scenario", tee_scenario,
        "--num-runners", str(num_runners),
        "--delivery-total-orders", str(orders),
        "--num-runs", str(runs_per),
        "--output-dir", str(output_dir),
        "--log-level", log_level,
        "--keep-old-outputs",
        "--skip-publish",
        "--minimal-outputs",
        "--coordinates-only-for-first-run",
    ]
    if block_holes:
        cmd += ["--block-holes"] + [str(h) for h in block_holes]
    if runner_speed is not None:
        cmd += ["--runner-speed", str(runner_speed)]
    if prep_time is not None:
        cmd += ["--prep-time", str(prep_time)]
    subprocess.run(cmd, check=True)


def main() -> None:
    p = argparse.ArgumentParser(description="Recommend number of runners for given orders and hole blocks")
    p.add_argument("--course-dir", default="courses/pinetree_country_club")
    p.add_argument("--tee-scenario", default="real_tee_sheet")
    p.add_argument("--orders", type=int, required=True)
    p.add_argument("--runner-range", type=str, default="1-3")
    p.add_argument("--runs-per", type=int, default=6)
    p.add_argument("--block-holes", nargs="+", type=int, default=None)
    p.add_argument("--python-bin", default=sys.executable)
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--runner-speed", type=float, default=None)
    p.add_argument("--prep-time", type=int, default=None)
    # Targets
    p.add_argument("--target-on-time", type=float, default=0.90, help="minimum on-time rate")
    p.add_argument("--max-failed-rate", type=float, default=0.05)
    p.add_argument("--max-p90", type=float, default=40.0)
    p.add_argument("--confidence", type=float, default=0.95)
    p.add_argument("--output-root", default="outputs/runner_opt")
    args = p.parse_args()

    project_root = Path(__file__).resolve().parents[2]
    course_dir = Path(args.course_dir)
    if not course_dir.is_absolute():
        course_dir = (project_root / args.course_dir).resolve()
    if not course_dir.exists():
        print(json.dumps({"error": f"Course dir not found: {course_dir}"}))
        sys.exit(1)

    runner_values = parse_range(args.runner_range)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    root = Path(args.output_root)
    if not root.is_absolute():
        root = (project_root / args.output_root)
    root = (root / f"{stamp}_opt_{args.tee_scenario}_orders_{args.orders:03d}")

    recommendations: List[Dict[str, Any]] = []

    for n in runner_values:
        combo_dir = root / f"runners_{n}"
        run_combo(
            python_bin=args.python_bin,
            course_dir=course_dir,
            tee_scenario=args.tee_scenario,
            num_runners=n,
            orders=args.orders,
            runs_per=args.runs_per,
            output_dir=combo_dir,
            log_level=args.log_level,
            block_holes=args.block_holes,
            runner_speed=args.runner_speed,
            prep_time=args.prep_time,
        )

        # Aggregate per-run results
        run_dirs = sorted([p for p in combo_dir.glob("run_*") if p.is_dir()])
        _, agg = aggregate_runs(run_dirs)
        meets = (
            agg["on_time_wilson_lo"] >= args.target_on_time
            and agg["failed_mean"] <= args.max_failed_rate
            and (math.isnan(agg["p90_mean"]) or agg["p90_mean"] <= args.max_p90)
        )
        recommendations.append({
            "num_runners": n,
            "meets": bool(meets),
            **agg,
        })

    # Choose minimal n that meets targets
    chosen: Optional[Dict[str, Any]] = None
    for rec in sorted(recommendations, key=lambda r: r["num_runners"]):
        if rec["meets"]:
            chosen = rec
            break

    result = {
        "course": str(course_dir),
        "tee_scenario": args.tee_scenario,
        "orders": args.orders,
        "blocked_holes": args.block_holes or [],
        "runs_per": args.runs_per,
        "target_on_time": args.target_on_time,
        "max_failed_rate": args.max_failed_rate,
        "max_p90": args.max_p90,
        "recommendations": recommendations,
        "recommended_num_runners": chosen["num_runners"] if chosen else None,
    }

    print(json.dumps(result, indent=2))
    sys.exit(0 if chosen else 2)


if __name__ == "__main__":
    main()


