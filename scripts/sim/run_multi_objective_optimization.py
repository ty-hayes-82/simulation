#!/usr/bin/env python3
"""
Multi-Objective Optimization Runner

Runs a matrix of delivery simulations varying:
- Order counts: multiples of 5 up to a max (default 50)
- Runner counts: 1..N (default 5)
- Blocking scenarios: none, 0-5, 10-12, 0-5 and 10-12
- With or without beverage cart (optionally runs bev-with-golfers alongside)

Organizes outputs using nested folders:
  outputs/{timestamp}/{optimization_type}/{order_count}orders/{runner_count}runners/{blocking_scenario}/{with_or_without_bev_cart}

Where:
- optimization_type: SLA | runners | revenue (labels only; all runs are produced for each type)
- blocking_scenario: none | 0_5 | 10_12 | 0_5_and_10_12
- with_or_without_bev_cart: with_bev_cart | without_bev_cart

Windows PowerShell friendly: one short command per line, no piping/chaining.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from golfsim.logging import init_logging, get_logger

logger = get_logger(__name__)


def _run_unified_simulation(mode: str, **kwargs) -> int:
    """Run the unified simulation script with given parameters.

    This constructs a Windows-friendly command without piping/chaining.
    """
    cmd: List[str] = [
        sys.executable,
        "scripts/sim/run_unified_simulation.py",
        "--mode",
        mode,
    ]

    # Add coordinate CSV disabling if requested
    if kwargs.get("skip_coordinates", False):
        cmd.append("--no-coordinates")

    # Convert key-value kwargs to CLI flags (kebab-case)
    for key, value in kwargs.items():
        if key in ["skip_coordinates", "skip_executive_summary"]:
            continue
        if key == "block_holes_10_12":
            if value:
                cmd.append("--block-holes-10-12")
            continue
        if key == "with_bev_cart":
            if value:
                cmd.append("--with-bev-cart")
            continue
        cmd.extend([f"--{key.replace('_', '-')}", str(value)])

    logger.info("Running: %s", " ".join(cmd))
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return result.returncode
    except subprocess.CalledProcessError as e:
        logger.error("Command failed with return code %d", e.returncode)
        if e.stdout:
            logger.error("STDOUT: %s", e.stdout[-1000:])
        if e.stderr:
            logger.error("STDERR: %s", e.stderr[-1000:])
        return e.returncode


def _backup_config(course_dir: str) -> Path:
    """Ensure a backup of simulation_config.json exists and return its path."""
    config_path = Path(course_dir) / "config" / "simulation_config.json"
    backup_path = config_path.with_suffix('.json.backup')
    if not backup_path.exists():
        shutil.copy2(config_path, backup_path)
        logger.info("Backed up original config to: %s", backup_path)
    return backup_path


def _modify_config_delivery_orders(course_dir: str, delivery_total_orders: Optional[int]) -> None:
    """Override only the delivery_total_orders field, preserving the rest."""
    config_path = Path(course_dir) / "config" / "simulation_config.json"
    backup_path = config_path.with_suffix('.json.backup')

    base_path = backup_path if backup_path.exists() else config_path
    with base_path.open('r', encoding='utf-8') as f:
        config_json = json.load(f)

    if delivery_total_orders is not None:
        config_json['delivery_total_orders'] = int(delivery_total_orders)

    with config_path.open('w', encoding='utf-8') as f:
        json.dump(config_json, f, indent=2)
    logger.info("Set delivery_total_orders=%s", delivery_total_orders)


def _restore_config(course_dir: str) -> None:
    """Restore simulation_config.json from its .backup copy if present."""
    config_path = Path(course_dir) / "config" / "simulation_config.json"
    backup_path = config_path.with_suffix('.json.backup')
    if backup_path.exists():
        shutil.copy2(backup_path, config_path)
        logger.info("Restored original config")


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-objective optimization batch runner")
    parser.add_argument("--course-dir", default="courses/pinetree_country_club", help="Course directory")
    parser.add_argument("--output-root", type=str, default=None, help="Output root; defaults to outputs/{timestamp}")
    parser.add_argument("--log-level", type=str, default="INFO", help="Log level")
    parser.add_argument("--tee-scenario", type=str, default="busy_weekend", help="Tee scenario to use")
    parser.add_argument("--num-runs", type=int, default=10, help="Number of simulation runs per configuration")
    parser.add_argument("--skip-coordinates", action="store_true", help="Disable coordinate CSVs for speed")
    parser.add_argument(
        "--optimization-types",
        type=str,
        default="SLA,runners,revenue",
        help="Comma-separated list of types to label runs (SLA,runners,revenue)",
    )
    parser.add_argument("--max-order", type=int, default=50, help="Max order count (multiple of 5)")
    parser.add_argument("--order-step", type=int, default=5, help="Order step size")
    parser.add_argument("--max-runners", type=int, default=5, help="Max number of runners to test")
    parser.add_argument("--num-bev-carts", type=int, default=1, help="Number of beverage carts when running bev-with-golfers")
    parser.add_argument(
        "--bev-options",
        type=str,
        default="with,without",
        help="Comma-separated list: with,without to control bev-cart runs",
    )
    parser.add_argument("--target-sla", type=float, default=0.95, help="Target SLA for recommendations (0..1)")

    args = parser.parse_args()
    init_logging(args.log_level)

    # Prepare iteration ranges
    optimization_types: List[str] = [x.strip() for x in args.optimization_types.split(",") if x.strip()]
    bev_options: List[str] = [x.strip() for x in args.bev_options.split(",") if x.strip()]
    order_counts: List[int] = [n for n in range(args.order_step, args.max_order + 1, args.order_step)]
    runner_counts: List[int] = list(range(1, int(args.max_runners) + 1))

    # Blocking scenarios mapping
    blocking_scenarios: List[Dict] = [
        {"label": "none", "block_up_to_hole": 0, "block_holes_10_12": False},
        {"label": "0_5", "block_up_to_hole": 5, "block_holes_10_12": False},
        {"label": "10_12", "block_up_to_hole": 0, "block_holes_10_12": True},
        {"label": "0_5_and_10_12", "block_up_to_hole": 5, "block_holes_10_12": True},
    ]

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    root = Path(args.output_root or (Path("outputs") / timestamp))
    root.mkdir(parents=True, exist_ok=True)

    logger.info("Output root: %s", root)
    logger.info("Optimization types: %s", optimization_types)
    logger.info("Orders: %s", order_counts)
    logger.info("Runners: %s", runner_counts)
    logger.info("Bev options: %s", bev_options)

    # Ensure we have a backup before modifying config
    _backup_config(args.course_dir)

    def _read_json(path: Path) -> Optional[Dict]:
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return None

    def _aggregate_delivery_metrics(delivery_dir: Path) -> Dict[str, any]:
        """Aggregate delivery metrics across run_* directories into simple means and extremes."""
        per_run: List[Dict[str, float]] = []
        for run_dir in sorted(delivery_dir.glob("run_*")):
            # Expected file name: delivery_runner_metrics_run_XX.json
            run_num = run_dir.name.split("_")[-1]
            metrics_path = run_dir / f"delivery_runner_metrics_run_{run_num}.json"
            data = _read_json(metrics_path)
            if not data:
                continue
            per_run.append({
                "on_time_rate": float(data.get("on_time_rate", 0.0)),
                "failed_rate": float(data.get("failed_rate", 0.0)),
                "queue_wait_avg": float(data.get("queue_wait_avg", 0.0)),
                "delivery_cycle_time_avg": float(data.get("delivery_cycle_time_avg", 0.0)),
                "delivery_cycle_time_p90": float(data.get("delivery_cycle_time_p90", 0.0)),
                "revenue_per_round": float(data.get("revenue_per_round", 0.0)),
                "runner_utilization_driving_pct": float(data.get("runner_utilization_driving_pct", 0.0)),
                "total_orders": int(data.get("total_orders", 0)),
                "successful_orders": int(data.get("successful_orders", 0)),
            })

        def _mean(key: str) -> float:
            vals = [r[key] for r in per_run if key in r]
            return float(sum(vals) / len(vals)) if vals else 0.0

        def _min(key: str) -> float:
            vals = [r[key] for r in per_run if key in r]
            return float(min(vals)) if vals else 0.0

        def _max(key: str) -> float:
            vals = [r[key] for r in per_run if key in r]
            return float(max(vals)) if vals else 0.0

        keys = [
            "on_time_rate",
            "failed_rate",
            "queue_wait_avg",
            "delivery_cycle_time_avg",
            "delivery_cycle_time_p90",
            "revenue_per_round",
            "runner_utilization_driving_pct",
            "total_orders",
            "successful_orders",
        ]

        metrics = {k: {"mean": _mean(k), "min": _min(k), "max": _max(k)} for k in keys}
        return {"runs": len(per_run), "per_run": per_run, "metrics": metrics}

    def _choose_best_config(configs: List[Dict[str, any]], target_sla: float) -> Optional[Dict[str, any]]:
        """Select best config by SLA then revenue, then lower failed rate.

        Each config should contain keys: sla_mean, revenue_mean, failed_mean, and the metadata fields.
        """
        if not configs:
            return None
        # Prefer those that meet target SLA; if none, pick the highest SLA
        eligible = [c for c in configs if c.get("sla_mean", 0.0) >= float(target_sla)] or configs
        # Sort by SLA desc, revenue desc, failed asc
        eligible.sort(key=lambda c: (float(c.get("sla_mean", 0.0)), float(c.get("revenue_mean", 0.0)), -float(c.get("failed_mean", 1.0))), reverse=True)
        return eligible[0]

    try:
        all_index_rows: List[Dict[str, any]] = []
        for opt_type in optimization_types:
            for orders in order_counts:
                # Apply order count override once per order bucket
                _modify_config_delivery_orders(args.course_dir, orders)

                for runners in runner_counts:
                    for scenario in blocking_scenarios:
                        for bev_flag in bev_options:
                            bev_label = "with_bev_cart" if bev_flag == "with" else "without_bev_cart"

                            out_dir = root / opt_type / f"{orders}orders" / f"{runners}runners" / scenario["label"] / bev_label
                            out_dir.mkdir(parents=True, exist_ok=True)

                            # Always run delivery-runner for metrics relevant to all objectives
                            try:
                                _ = _run_unified_simulation(
                                    mode="delivery-runner",
                                    course_dir=args.course_dir,
                                    tee_scenario=args.tee_scenario,
                                    num_runs=args.num_runs,
                                    num_runners=runners,
                                    block_up_to_hole=scenario["block_up_to_hole"],
                                    block_holes_10_12=scenario["block_holes_10_12"],
                                    with_bev_cart=(bev_flag == "with"),
                                    output_dir=str(out_dir / "delivery"),
                                    skip_coordinates=args.skip_coordinates,
                                )
                            except Exception as e:
                                logger.error("Delivery-runner failed for %s/%s: %s", scenario["label"], bev_label, e)

                            # Optionally also run bev-with-golfers to include bev-cart content
                            if bev_flag == "with":
                                try:
                                    _ = _run_unified_simulation(
                                        mode="bev-with-golfers",
                                        course_dir=args.course_dir,
                                        tee_scenario=args.tee_scenario,
                                        num_runs=args.num_runs,
                                        num_carts=args.num_bev_carts,
                                        output_dir=str(out_dir / "bev"),
                                        skip_coordinates=args.skip_coordinates,
                                    )
                                except Exception as e:
                                    logger.error("Bev-with-golfers failed for %s/%s: %s", scenario["label"], bev_label, e)

                            # After runs complete for this configuration, build an aggregate.json one level up
                            try:
                                delivery_dir = out_dir / "delivery"
                                agg = _aggregate_delivery_metrics(delivery_dir)
                                aggregate_payload = {
                                    "optimization_type": opt_type,
                                    "order_count": int(orders),
                                    "runner_count": int(runners),
                                    "blocking": scenario["label"],
                                    "bev_cart": bev_label,
                                    "delivery": agg,
                                }
                                (out_dir / "aggregate.json").write_text(json.dumps(aggregate_payload, indent=2), encoding="utf-8")
                                logger.info("Wrote aggregate.json for %s", out_dir)
                                # Collect for global recommendations index
                                row = {
                                    "path": str(out_dir),
                                    "optimization_type": opt_type,
                                    "orders": int(orders),
                                    "runners": int(runners),
                                    "blocking": scenario["label"],
                                    "bev": bev_label,
                                }
                                # Derive summary means for ranking
                                dm = agg.get("metrics", {})
                                row["sla_mean"] = float(dm.get("on_time_rate", {}).get("mean", 0.0))
                                row["failed_mean"] = float(dm.get("failed_rate", {}).get("mean", 0.0))
                                row["revenue_mean"] = float(dm.get("revenue_per_round", {}).get("mean", 0.0))
                                row["queue_wait_mean"] = float(dm.get("queue_wait_avg", {}).get("mean", 0.0))
                                row["p90_mean"] = float(dm.get("delivery_cycle_time_p90", {}).get("mean", 0.0))
                                all_index_rows.append(row)
                            except Exception as e:
                                logger.warning("Failed to write aggregate.json for %s: %s", out_dir, e)

                # Small pause between order buckets to avoid file contention on Windows
                time.sleep(0.1)
    finally:
        _restore_config(args.course_dir)

    # Build global recommendations grouped by order count
    try:
        by_orders: Dict[int, List[Dict[str, any]]] = {}
        for r in all_index_rows:
            by_orders.setdefault(int(r["orders"]), []).append(r)

        recommendations: Dict[str, any] = {"target_sla": float(args.target_sla), "by_orders": {}}
        for orders, rows in sorted(by_orders.items()):
            best = _choose_best_config(rows, target_sla=float(args.target_sla))
            if best:
                recommendations["by_orders"][str(orders)] = {
                    "recommended_path": best["path"],
                    "orders": orders,
                    "runners": int(best["runners"]),
                    "blocking": best["blocking"],
                    "bev": best["bev"],
                    "sla_mean": float(best.get("sla_mean", 0.0)),
                    "revenue_mean": float(best.get("revenue_mean", 0.0)),
                    "failed_mean": float(best.get("failed_mean", 0.0)),
                }

        # Save machine-readable optimization results
        (root / "optimization_results.json").write_text(json.dumps({
            "index": all_index_rows,
            "recommendations": recommendations,
        }, indent=2), encoding="utf-8")

        # Save a concise Markdown summary for the GM
        lines: List[str] = [
            "# Recommendations",
            f"Target SLA: {float(args.target_sla)*100:.1f}%",
            "",
            "## Best Configurations by Order Count",
        ]
        for orders in sorted(recommendations["by_orders"].keys(), key=lambda x: int(x)):
            r = recommendations["by_orders"][orders]
            lines += [
                f"- Orders {orders}: {r['runners']} runners, blocking={r['blocking']}, bev={r['bev']} — SLA {r['sla_mean']*100:.1f}%, Revenue ${r['revenue_mean']:.2f}",
                f"  Path: {r['recommended_path']}",
            ]
        (root / "recommendations.md").write_text("\n".join(lines), encoding="utf-8")
        logger.info("Saved recommendations to %s", root / "recommendations.md")
    except Exception as e:
        logger.warning("Failed to write global recommendations: %s", e)

    logger.info("Multi-objective optimization run complete. Results under: %s", root)
    return 0


if __name__ == "__main__":
    sys.exit(main())


