#!/usr/bin/env python3
"""
Optimize staffing and blocking policy across order levels.

For each orders level and each blocked-holes variant, this script:
- Runs the delivery simulation across a range of runner counts
- Aggregates per-run metrics and computes Wilson CI for on-time rate
- Chooses the minimal runner count per variant that meets targets
- Recommends the best variant with the lowest runners (ties broken by CI and p90)

Example (Windows PowerShell line breaks with ^):

  python scripts/optimization/optimize_staffing_policy.py ^
    --course-dir courses/pinetree_country_club ^
    --tee-scenario real_tee_sheet ^
    --orders-levels 20 30 40 ^
    --runner-range 1-3 ^
    --runs-per 8 ^
    --target-on-time 0.90 --max-failed-rate 0.05 --max-p90 40

Outputs a human-readable summary and prints a JSON recommendation to stdout.
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from dataclasses import dataclass
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


@dataclass
class BlockingVariant:
    key: str
    cli_flags: List[str]
    description: str


BLOCKING_VARIANTS: List[BlockingVariant] = [
    BlockingVariant(key="none", cli_flags=[], description="no blocked holes"),
    BlockingVariant(key="front", cli_flags=["--block-holes", "1", "2", "3"], description="block holes 1–3"),
    BlockingVariant(key="mid", cli_flags=["--block-holes", "4", "5", "6"], description="block holes 4–6"),
    BlockingVariant(key="back", cli_flags=["--block-holes", "10", "11", "12"], description="block holes 10–12"),
    BlockingVariant(key="front_mid", cli_flags=["--block-holes", "1", "2", "3", "4", "5", "6"], description="block holes 1–6"),
    BlockingVariant(key="front_back", cli_flags=["--block-holes", "1", "2", "3", "10", "11", "12"], description="block holes 1–3 & 10–12"),
    BlockingVariant(key="mid_back", cli_flags=["--block-holes", "4", "5", "6", "10", "11", "12"], description="block holes 4–6 & 10–12"),
    BlockingVariant(key="front_mid_back", cli_flags=["--block-holes", "1", "2", "3", "4", "5", "6", "10", "11", "12"], description="block holes 1–6 & 10–12"),
]


def parse_range(spec: str) -> List[int]:
    spec = spec.strip()
    if "-" in spec:
        a, b = spec.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(spec)]


def mean(values: Iterable[float]) -> float:
    vals = list(values)
    return (sum(vals) / len(vals)) if vals else 0.0


def wilson_ci(successes: int, total: int, confidence: float = 0.95) -> Tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
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
    # Prefer detailed metrics JSON
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
                p90=float("nan"),
                orders_per_runner_hour=float(dm.get("ordersPerRunnerHour", 0.0) or 0.0),
                successful_orders=successful,
                total_orders=total,
            )
        except Exception:
            return None
    return None


def aggregate_runs(run_dirs: List[Path]) -> Dict[str, Any]:
    items: List[RunMetrics] = []
    for rd in run_dirs:
        m = load_one_run_metrics(rd)
        if m is not None:
            items.append(m)
    if not items:
        return {"runs": 0}

    on_time_vals = [m.on_time_rate for m in items if not math.isnan(m.on_time_rate)]
    failed_vals = [m.failed_rate for m in items if not math.isnan(m.failed_rate)]
    p90_vals = [m.p90 for m in items if not math.isnan(m.p90)]
    oph_vals = [m.orders_per_runner_hour for m in items if not math.isnan(m.orders_per_runner_hour)]

    total_successes = sum(m.successful_orders for m in items)
    total_orders = sum(m.total_orders for m in items)
    ot_lo, ot_hi = wilson_ci(total_successes, total_orders, confidence=0.95)

    return {
        "runs": len(items),
        "on_time_mean": mean(on_time_vals),
        "failed_mean": mean(failed_vals),
        "p90_mean": mean(p90_vals) if p90_vals else float("nan"),
        "oph_mean": mean(oph_vals),
        "on_time_wilson_lo": ot_lo,
        "on_time_wilson_hi": ot_hi,
        "total_successful_orders": total_successes,
        "total_orders": total_orders,
    }


def run_combo(*, py: str, course_dir: Path, scenario: str, runners: int, orders: int, runs: int, out: Path, log_level: str, variant: BlockingVariant, runner_speed: Optional[float], prep_time: Optional[int]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    cmd: List[str] = [
        py, "scripts/sim/run_new.py",
        "--course-dir", str(course_dir),
        "--tee-scenario", scenario,
        "--num-runners", str(runners),
        "--delivery-total-orders", str(orders),
        "--num-runs", str(runs),
        "--output-dir", str(out),
        "--log-level", log_level,
        "--no-export-geojson",
        "--keep-old-outputs",
        "--skip-publish",
        "--minimal-outputs",
        "--coordinates-only-for-first-run",
    ]
    if variant.cli_flags:
        cmd += variant.cli_flags
    if runner_speed is not None:
        cmd += ["--runner-speed", str(runner_speed)]
    if prep_time is not None:
        cmd += ["--prep-time", str(prep_time)]
    subprocess.run(cmd, check=True)


def choose_best_variant(results_by_variant: Dict[str, Dict[int, Dict[str, Any]]], *, target_on_time: float, max_failed: float, max_p90: float) -> Optional[Tuple[str, int, Dict[str, Any]]]:
    # For each variant, find minimal runners meeting targets
    candidates: List[Tuple[str, int, Dict[str, Any]]] = []
    for variant_key, per_runner in results_by_variant.items():
        for n in sorted(per_runner.keys()):
            agg = per_runner[n]
            if not agg or not agg.get("runs"):
                continue
            meets = (
                agg.get("on_time_wilson_lo", 0.0) >= target_on_time
                and agg.get("failed_mean", 1.0) <= max_failed
                and (math.isnan(agg.get("p90_mean", float("nan"))) or agg.get("p90_mean", 1e9) <= max_p90)
            )
            if meets:
                candidates.append((variant_key, n, agg))
                break

    if not candidates:
        return None

    # Primary: smallest n; Secondary: highest on_time_wilson_lo; Tertiary: lowest p90_mean
    candidates.sort(key=lambda t: (t[1], -float(t[2].get("on_time_wilson_lo", 0.0)), float(t[2].get("p90_mean", 1e9))))
    return candidates[0]


def main() -> None:
    p = argparse.ArgumentParser(description="Optimize runners and blocking policy across orders levels")
    p.add_argument("--course-dir", default="courses/pinetree_country_club")
    p.add_argument("--tee-scenario", default="real_tee_sheet")
    p.add_argument("--orders-levels", nargs="+", type=int, required=True)
    p.add_argument("--runner-range", type=str, default="1-3")
    p.add_argument("--runs-per", type=int, default=12)
    # Auto confirmation pass for borderline results
    p.add_argument("--confirm-runs-per", type=int, default=16, help="rerun borderline combos with this many runs for higher confidence")
    p.add_argument("--borderline-margin", type=float, default=0.02, help="treat on_time_wilson_lo within this of target as borderline")
    p.add_argument("--no-auto-confirm", action="store_true", help="disable automatic high-confidence rerun for borderline results")
    p.add_argument("--python-bin", default=sys.executable)
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--runner-speed", type=float, default=None)
    p.add_argument("--prep-time", type=int, default=None)
    p.add_argument("--variants", nargs="+", default=[v.key for v in BLOCKING_VARIANTS], help="Subset of variant keys to test")
    p.add_argument("--output-root", default="outputs/policy_opt")
    # Targets
    p.add_argument("--target-on-time", type=float, default=0.90)
    p.add_argument("--max-failed-rate", type=float, default=0.05)
    p.add_argument("--max-p90", type=float, default=40.0)
    p.add_argument("--concurrency", type=int, default=max(1, min(4, (os.cpu_count() or 2))), help="max concurrent simulations")
    args = p.parse_args()

    project_root = Path(__file__).resolve().parents[2]
    course_dir = Path(args.course_dir)
    if not course_dir.is_absolute():
        course_dir = (project_root / args.course_dir).resolve()
    if not course_dir.exists():
        print(json.dumps({"error": f"Course dir not found: {course_dir}"}))
        sys.exit(1)

    variant_map: Dict[str, BlockingVariant] = {v.key: v for v in BLOCKING_VARIANTS}
    selected_variants: List[BlockingVariant] = [variant_map[k] for k in args.variants if k in variant_map]
    runner_values = parse_range(args.runner_range)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    root = Path(args.output_root)
    if not root.is_absolute():
        root = (project_root / args.output_root)
    root = (root / f"{stamp}_{args.tee_scenario}")

    summary: Dict[int, Dict[str, Any]] = {}

    for orders in args.orders_levels:
        results_by_variant: Dict[str, Dict[int, Dict[str, Any]]] = {}
        # Run all variant/runner combos in parallel for this orders level
        future_to_combo: Dict[Any, Tuple[BlockingVariant, int, Path]] = {}
        with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
            for variant in selected_variants:
                for n in runner_values:
                    out_dir = root / f"orders_{orders:03d}" / variant.key / f"runners_{n}"
                    fut = executor.submit(
                        run_combo,
                        py=args.python_bin,
                        course_dir=course_dir,
                        scenario=args.tee_scenario,
                        runners=n,
                        orders=orders,
                        runs=args.runs_per,
                        out=out_dir,
                        log_level=args.log_level,
                        variant=variant,
                        runner_speed=args.runner_speed,
                        prep_time=args.prep_time,
                    )
                    future_to_combo[fut] = (variant, n, out_dir)
            for fut in as_completed(future_to_combo):
                _ = fut.result()

        # Aggregate after all complete
        for variant in selected_variants:
            for n in runner_values:
                out_dir = root / f"orders_{orders:03d}" / variant.key / f"runners_{n}"
                run_dirs = sorted([p for p in out_dir.glob("run_*") if p.is_dir()])
                agg = aggregate_runs(run_dirs)
                results_by_variant.setdefault(variant.key, {})[n] = agg

        # Optional high-confidence rerun for borderline combinations
        if not args.no_auto_confirm:
            borderline: List[Tuple[BlockingVariant, int]] = []
            for variant in selected_variants:
                per_runner = results_by_variant.get(variant.key, {})
                for n, agg in per_runner.items():
                    if not agg or not agg.get("runs"):
                        continue
                    ot_lo = float(agg.get("on_time_wilson_lo", 0.0) or 0.0)
                    if abs(ot_lo - args.target_on_time) <= args.borderline_margin:
                        borderline.append((variant, n))

            # Run confirm reruns in parallel
            with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
                future_to_confirm: Dict[Any, Tuple[BlockingVariant, int, Path]] = {}
                for variant, n in borderline:
                    out_dir = root / f"orders_{orders:03d}" / variant.key / f"runners_{n}"
                    confirm_dir = out_dir / "confirm"
                    fut = executor.submit(
                        run_combo,
                        py=args.python_bin,
                        course_dir=course_dir,
                        scenario=args.tee_scenario,
                        runners=n,
                        orders=orders,
                        runs=args.confirm_runs_per,
                        out=confirm_dir,
                        log_level=args.log_level,
                        variant=variant,
                        runner_speed=args.runner_speed,
                        prep_time=args.prep_time,
                    )
                    future_to_confirm[fut] = (variant, n, confirm_dir)
                for fut in as_completed(future_to_confirm):
                    _ = fut.result()

            # Re-aggregate across original and confirm runs
            for variant, n in borderline:
                out_dir = root / f"orders_{orders:03d}" / variant.key / f"runners_{n}"
                confirm_dir = out_dir / "confirm"
                orig_dirs = sorted([p for p in out_dir.glob("run_*") if p.is_dir()])
                confirm_dirs = sorted([p for p in confirm_dir.glob("run_*") if p.is_dir()])
                agg = aggregate_runs(orig_dirs + confirm_dirs)
                results_by_variant.setdefault(variant.key, {})[n] = agg

        chosen = choose_best_variant(
            results_by_variant,
            target_on_time=args.target_on_time,
            max_failed=args.max_failed_rate,
            max_p90=args.max_p90,
        )

        human: str
        if chosen is None:
            human = f"Orders {orders}: No variant met targets up to {max(runner_values)} runners."
        else:
            v_key, v_runners, v_agg = chosen
            # Also compute baseline (no blocks) minimal
            baseline = None
            if "none" in results_by_variant:
                for n in sorted(results_by_variant["none"].keys()):
                    agg = results_by_variant["none"][n]
                    if agg and agg.get("runs") and (
                        agg.get("on_time_wilson_lo", 0.0) >= args.target_on_time
                        and agg.get("failed_mean", 1.0) <= args.max_failed_rate
                        and (math.isnan(agg.get("p90_mean", float("nan"))) or agg.get("p90_mean", 1e9) <= args.max_p90)
                    ):
                        baseline = n
                        break
            desc = variant_map[v_key].description
            if baseline is not None and v_runners < baseline:
                human = f"Orders {orders}: You can use {v_runners} runner(s) if you {desc}; otherwise you need {baseline} runner(s)."
            else:
                human = f"Orders {orders}: Recommended {v_runners} runner(s) with policy: {desc}."

        print(human)

        summary[orders] = {
            "chosen": {
                "variant": chosen[0] if chosen else None,
                "runners": chosen[1] if chosen else None,
                "metrics": chosen[2] if chosen else None,
            },
            "per_variant": results_by_variant,
        }

    # Print machine-readable JSON at the end
    print(json.dumps({
        "course": str(course_dir),
        "tee_scenario": args.tee_scenario,
        "runs_per": args.runs_per,
        "targets": {"on_time": args.target_on_time, "max_failed": args.max_failed_rate, "max_p90": args.max_p90},
        "orders_levels": args.orders_levels,
        "summary": summary,
        "output_root": str(root),
    }, indent=2))


if __name__ == "__main__":
    main()


