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
- Outputs are organized under `<output_root>/<stamp>_<scenario>/orders_XXX/...` with
  subfolders `first_pass` and `second_pass` inside each runners group directory.

Example:
  python scripts/optimization/optimize_staffing_policy_two_pass.py \
    --course-dir courses/pinetree_country_club \
    --tee-scenario real_tee_sheet \
    --orders-levels 20 30 40 50 \
    --runner-range 1-3 \
    --concurrency 3
"""

from __future__ import annotations

import argparse
import json
import math
import os
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
    choose_best_variant,
    parse_range,
    _make_group_context,
    _row_from_context_and_agg,
    _write_group_aggregate_file,
    _write_group_aggregate_heatmap,
    _write_final_csv,
)


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

    if variant.cli_flags:
        cmd += variant.cli_flags
    if runner_speed is not None:
        cmd += ["--runner-speed", str(runner_speed)]
    if prep_time is not None:
        cmd += ["--prep-time", str(prep_time)]
    subprocess.run(cmd, check=True)


def _collect_run_dirs(group_dir: Path, include_first: bool = True, include_second: bool = True) -> List[Path]:
    """Collect run_* directories from first_pass and/or second_pass under a group dir."""
    run_dirs: List[Path] = []
    if include_first:
        fp = group_dir / "first_pass"
        if fp.exists():
            run_dirs += sorted([p for p in fp.glob("run_*") if p.is_dir()])
    if include_second:
        sp = group_dir / "second_pass"
        if sp.exists():
            run_dirs += sorted([p for p in sp.glob("run_*") if p.is_dir()])
    return run_dirs


def main() -> None:
    p = argparse.ArgumentParser(description="Two-pass optimization: 10 minimal for all; 10 full for winners")
    p.add_argument("--course-dir", default="courses/pinetree_country_club")
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
    p.add_argument("--output-root", default="outputs/policy_opt")
    p.add_argument("--summarize-only", action="store_true", help="Skip running sims; summarize an existing output root")
    p.add_argument("--existing-root", type=str, default=None, help="Path to existing optimization output root to summarize")
    # Targets for recommendation
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
        root = Path(args.output_root)
        if not root.is_absolute():
            root = (project_root / args.output_root)
        root = (root / f"{stamp}_{args.tee_scenario}")

    # Identify orders levels
    if args.summarize_only:
        orders_iter: List[int] = []
        for d in sorted(root.glob("orders_*")):
            if not d.is_dir():
                continue
            try:
                orders_iter.append(int(str(d.name).split("_")[-1]))
            except Exception:
                continue
        orders_iter = sorted(orders_iter)
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
                        group_dir = root / f"orders_{orders:03d}" / variant.key / f"runners_{n}"
                        out_dir = group_dir / "first_pass"
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
                group_dir = root / f"orders_{orders:03d}" / variant.key / f"runners_{n}"
                run_dirs = _collect_run_dirs(group_dir, include_first=True, include_second=False)
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
                _row = _row_from_context_and_agg(context, agg, group_dir)
                _write = _row  # clarity
                # Upsert into CSV rows
                from scripts.optimization.optimize_staffing_policy import _upsert_row  # local import to avoid polluting top

                _upsert_row(csv_rows, _write)

        # Select recommended winner for this orders level
        chosen = choose_best_variant(
            results_by_variant,
            target_on_time=args.target_on_time,
            max_failed=args.max_failed_rate,
            max_p90=args.max_p90,
        )

        if chosen is None:
            print(f"Orders {orders}: No variant met targets up to {max(runner_values)} runners after first pass.")
        else:
            v_key, v_runners, _ = chosen
            desc = next((v.description for v in BLOCKING_VARIANTS if v.key == v_key), v_key)
            print(f"Orders {orders}: Recommended {v_runners} runner(s) with policy: {desc} (first pass). Running second pass confirmation...")

            # Second pass: run confirmation for the winner (full outputs)
            if not args.summarize_only:
                group_dir = root / f"orders_{orders:03d}" / v_key / f"runners_{v_runners}"
                out_dir = group_dir / "second_pass"
                run_combo(
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

            # Re-aggregate winner including both passes
            group_dir = root / f"orders_{orders:03d}" / v_key / f"runners_{v_runners}"
            win_run_dirs = _collect_run_dirs(group_dir, include_first=True, include_second=True)
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
            from scripts.optimization.optimize_staffing_policy import _upsert_row  # local import

            _upsert_row(csv_rows, _row_from_context_and_agg(win_context, win_agg, group_dir))

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

    # Print machine-readable JSON at the end
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
                "orders_levels": orders_iter,
                "summary": summary,
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


if __name__ == "__main__":
    main()


