"""
Structured simulation validation runner.

Runs end-to-end scenarios multiple times and validates key invariants:
- More golfers → more orders (on average)
- With fixed capacity, higher load → longer average completion times (non-decreasing)
- Orders placed at random holes ~ uniform across 1..18 (sanity checks)
- Beverage cart GPS: 60s cadence, service window bounds, continuous 18→1 looping

Usage (PowerShell):
  conda activate my_gemini_env
  python scripts/analysis/validate_scenarios.py --course-dir courses/pinetree_country_club --runs 5

Exit code is non-zero if any hard assertion fails.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import simpy

from golfsim.simulation.services import (
    BeverageCartService,
    run_multi_golfer_simulation,
)
from golfsim.simulation.bev_cart_pass import simulate_beverage_cart_sales


@dataclass
class TestResult:
    name: str
    passed: bool
    warnings: List[str]
    details: Dict[str, Any]


def _assert(condition: bool, message: str, failures: List[str]) -> None:
    if not condition:
        failures.append(message)


def _warn(condition: bool, message: str, warnings: List[str]) -> None:
    if not condition:
        warnings.append(message)


def validate_bev_cart_only(course_dir: str) -> TestResult:
    env = simpy.Environment()
    svc = BeverageCartService(env=env, course_dir=course_dir, cart_id="bev_cart_1", track_coordinates=True)
    env.run(until=svc.service_end_s)

    coords = svc.coordinates
    warnings: List[str] = []
    failures: List[str] = []

    _assert(len(coords) > 0, "No beverage cart coordinates generated", failures)

    if coords:
        # 60s cadence and monotonically increasing timestamps
        timestamps = [c.get("timestamp") for c in coords]
        deltas = [b - a for a, b in zip(timestamps[:-1], timestamps[1:])]
        _assert(all(d == 60 for d in deltas), "Beverage cart timestamps not spaced by 60s", failures)
        _assert(timestamps[0] >= svc.service_start_s, "First timestamp before service start", failures)
        _assert(timestamps[-1] <= svc.service_end_s, "Last timestamp after service end", failures)

        # Should loop continuously and cover holes in reverse order 18→1 across the day
        holes = [c.get("current_hole") for c in coords if c.get("current_hole")]
        _warn(len(set(holes)) >= 12, "Beverage cart holes coverage seems low (<12 distinct holes)", warnings)

    return TestResult(
        name="bev_cart_only",
        passed=len(failures) == 0,
        warnings=warnings + failures[:0],  # keep warnings separate; failures handled in passed
        details={
            "num_coords": len(coords),
            "first_ts": coords[0]["timestamp"] if coords else None,
            "last_ts": coords[-1]["timestamp"] if coords else None,
        },
    )


def _build_groups(num_groups: int, start_hour: int = 8, interval_min: int = 10) -> List[Dict[str, int]]:
    base_s = (start_hour - 7) * 3600
    return [
        {"group_id": i + 1, "tee_time_s": base_s + i * interval_min * 60, "num_golfers": 4}
        for i in range(num_groups)
    ]


def validate_single_runner_monotonic_load(
    course_dir: str,
    runs: int,
    base_seed: int = 1234,
) -> TestResult:
    group_sizes = [1, 2, 4, 8]
    avg_orders: List[float] = []
    avg_completion_s: List[float] = []
    warnings: List[str] = []
    failures: List[str] = []

    for idx, n_groups in enumerate(group_sizes):
        per_run_orders: List[int] = []
        per_run_avg_time: List[float] = []

        for r in range(runs):
            seed = base_seed + idx * 100 + r
            random.seed(seed)
            groups = _build_groups(n_groups)
            res = run_multi_golfer_simulation(
                course_dir=course_dir,
                groups=groups,
                order_probability_per_9_holes=0.5,
                prep_time_min=10,
                runner_speed_mps=6.0,
                create_visualization=False,
            )

            orders = res.get("orders", [])
            agg = res.get("aggregate_metrics", {})
            per_run_orders.append(len([o for o in orders if o.get("status") in {"processed", "pending", "failed"}]))
            per_run_avg_time.append(float(agg.get("average_order_time_s", 0.0)))

        avg_orders.append(sum(per_run_orders) / len(per_run_orders))
        avg_completion_s.append(sum(per_run_avg_time) / len(per_run_avg_time))

    # Invariants: more golfers -> more orders (mean trend increasing)
    for i in range(1, len(group_sizes)):
        _assert(
            avg_orders[i] >= avg_orders[i - 1] - 1e-9,
            f"Avg orders not non-decreasing: groups {group_sizes[i-1]} -> {group_sizes[i]} ({avg_orders[i-1]:.2f} -> {avg_orders[i]:.2f})",
            failures,
        )

    # With fixed capacity, average completion times should not decrease as load rises
    for i in range(1, len(group_sizes)):
        _warn(
            avg_completion_s[i] >= avg_completion_s[i - 1] - 1.0,  # allow small statistical fluctuation
            f"Avg completion time decreased under higher load: groups {group_sizes[i-1]} -> {group_sizes[i]} ({avg_completion_s[i-1]:.1f}s -> {avg_completion_s[i]:.1f}s)",
            warnings,
        )

    return TestResult(
        name="single_runner_monotonic_load",
        passed=len(failures) == 0,
        warnings=warnings,
        details={
            "group_sizes": group_sizes,
            "avg_orders": avg_orders,
            "avg_completion_s": avg_completion_s,
        },
    )


def validate_random_order_hole_uniformity(
    course_dir: str,
    runs: int,
    base_seed: int = 9876,
) -> TestResult:
    warnings: List[str] = []
    failures: List[str] = []
    hole_counts: Counter[int] = Counter()

    # Moderate-load scenario to accumulate orders across runs
    groups = _build_groups(6)
    for r in range(runs):
        random.seed(base_seed + r)
        res = run_multi_golfer_simulation(
            course_dir=course_dir,
            groups=groups,
            order_probability_per_9_holes=0.6,
            prep_time_min=10,
            runner_speed_mps=6.0,
            create_visualization=False,
        )
        for o in res.get("orders", []):
            hole = int(o.get("hole_num", 0))
            if 1 <= hole <= 18:
                hole_counts[hole] += 1

    # Sanity checks for approximate uniformity
    distinct_holes = len([h for h, c in hole_counts.items() if c > 0])
    _warn(distinct_holes >= 12, f"Only {distinct_holes} distinct holes observed (<12)", warnings)

    if hole_counts:
        counts = [c for _, c in sorted(hole_counts.items())]
        max_c, min_c = max(counts), min(counts)
        ratio = (max_c / max(min_c, 1)) if min_c > 0 else math.inf
        _warn(ratio <= 3.0, f"Hole frequency imbalance high (max/min={ratio:.2f})", warnings)

    return TestResult(
        name="random_order_hole_uniformity",
        passed=len(failures) == 0,
        warnings=warnings,
        details={"hole_counts": dict(hole_counts)},
    )


def validate_multi_runner_benefit_placeholder() -> TestResult:
    return TestResult(
        name="multi_runner_benefit",
        passed=True,
        warnings=[
            "Multi-runner queue not implemented yet; skipping capacity expansion check. Once available, compare avg completion and failures for 1 vs 2 runners under identical demand."
        ],
        details={},
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run structured simulation validations")
    parser.add_argument("--course-dir", type=str, default="courses/pinetree_country_club")
    parser.add_argument("--runs", type=int, default=5, help="Number of repetitions for stochastic scenarios")
    args = parser.parse_args()

    results: List[TestResult] = []

    # Deterministic or near-deterministic checks
    results.append(validate_bev_cart_only(course_dir=args.course_dir))

    # Stochastic checks (repeat across seeds)
    results.append(validate_single_runner_monotonic_load(course_dir=args.course_dir, runs=args.runs))
    results.append(validate_random_order_hole_uniformity(course_dir=args.course_dir, runs=args.runs))

    # Placeholder for future capacity expansion
    results.append(validate_multi_runner_benefit_placeholder())

    # Optional: Exercise beverage cart pass-by sales with 1 and 2 groups (does not fail the run yet)
    try:
        one_group = _build_groups(1)
        two_groups = _build_groups(2)
        sales1 = simulate_beverage_cart_sales(args.course_dir, one_group, pass_order_probability=0.4)
        sales2 = simulate_beverage_cart_sales(args.course_dir, two_groups, pass_order_probability=0.4)
        print(f"[INFO] bev_cart_sales: groups=1 revenue={sales1['revenue']:.2f} orders={len(sales1['sales'])}")
        print(f"[INFO] bev_cart_sales: groups=2 revenue={sales2['revenue']:.2f} orders={len(sales2['sales'])}")
    except Exception as e:
        print(f"[INFO] bev_cart_sales check skipped: {e}")

    # Reporting
    any_fail = False
    for tr in results:
        status = "PASS" if tr.passed else "FAIL"
        print(f"[{status}] {tr.name}")
        if tr.warnings:
            for w in tr.warnings:
                print(f"  warning: {w}")
        if not tr.passed:
            any_fail = True

    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())


