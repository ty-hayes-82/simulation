"""
Dynamic delivery runner simulation runner.

Supports:
- Delivery runner only (no beverage cart), with 0..N golfer groups
- Parameterized order probability, prep time, runner speed

Outputs per run:
- results.json (raw + metrics)
- delivery_metrics_run_XX.json
- stats_run_XX.md
- delivery_orders_map.png (if coordinates available)
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Dict, List
import json

from golfsim.logging import init_logging, get_logger
from golfsim.simulation.services import run_multi_golfer_simulation
from golfsim.analysis.delivery_runner_metrics import (
    calculate_delivery_runner_metrics,
    format_delivery_runner_metrics_report,
)
from golfsim.analysis.metrics_integration import generate_and_save_metrics


logger = get_logger(__name__)


def _first_tee_to_seconds(hhmm: str) -> int:
    hh, mm = hhmm.split(":")
    return (int(hh) - 7) * 3600 + int(mm) * 60


def _build_groups_interval(count: int, first_tee_s: int, interval_min: float) -> List[Dict]:
    groups: List[Dict] = []
    for i in range(count):
        groups.append({
            "group_id": i + 1,
            "tee_time_s": int(first_tee_s + i * int(interval_min * 60)),
            "num_golfers": 4,
        })
    return groups


def main() -> None:
    parser = argparse.ArgumentParser(description="Dynamic delivery runner simulations (no beverage cart)")
    parser.add_argument("--course-dir", default="courses/pinetree_country_club", help="Course directory")
    parser.add_argument("--num-runs", type=int, default=5, help="Number of runs")
    parser.add_argument("--groups-count", type=int, default=1, help="Number of golfer groups (0..N)")
    parser.add_argument("--groups-interval-min", type=float, default=30.0, help="Interval between groups (minutes)")
    parser.add_argument("--first-tee", type=str, default="09:00", help="First tee time HH:MM")
    parser.add_argument("--order-prob-9", type=float, default=0.5, help="Order probability per 9 holes per group (0..1)")
    parser.add_argument("--prep-time", type=int, default=10, help="Food preparation time in minutes")
    parser.add_argument("--runner-speed", type=float, default=6.0, help="Runner speed in m/s (all scripts use m/s; config mph converted on load)")
    parser.add_argument("--revenue-per-order", type=float, default=25.0, help="Revenue per successful order")
    parser.add_argument("--sla-minutes", type=int, default=30, help="SLA in minutes")
    parser.add_argument("--service-hours", type=float, default=10.0, help="Active service hours for runner (for metrics scaling)")
    parser.add_argument("--output-dir", type=str, default="outputs/delivery_dynamic", help="Output directory")
    parser.add_argument("--log-level", type=str, default="INFO", help="Log level")

    args = parser.parse_args()

    init_logging(args.log_level)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Starting dynamic delivery runner sims: %d runs", args.num_runs)
    all_runs: List[Dict] = []

    first_tee_s = _first_tee_to_seconds(args.first_tee)

    for run_idx in range(1, int(args.num_runs) + 1):
        groups = _build_groups_interval(int(args.groups_count), first_tee_s, float(args.groups_interval_min)) if args.groups_count > 0 else []

        sim_result = run_multi_golfer_simulation(
            course_dir=args.course_dir,
            groups=groups,
            order_probability_per_9_holes=float(args.order_prob_9),
            prep_time_min=int(args.prep_time),
            runner_speed_mps=float(args.runner_speed),
            output_dir=str(output_dir / f"run_{run_idx:02d}"),
            create_visualization=True,
        )

        # Persist outputs
        run_path = output_dir / f"run_{run_idx:02d}"
        run_path.mkdir(parents=True, exist_ok=True)

        # Raw results
        (run_path / "results.json").write_text(json.dumps(sim_result, indent=2, default=str), encoding="utf-8")

        # Generate metrics using integrated approach
        try:
            _, delivery_metrics = generate_and_save_metrics(
                simulation_result=sim_result,
                output_dir=run_path,
                run_suffix=f"_run_{run_idx:02d}",
                simulation_id=f"delivery_dynamic_{run_idx:02d}",
                revenue_per_order=float(args.revenue_per_order),
                sla_minutes=int(args.sla_minutes),
                runner_id="runner_1",
                service_hours=float(args.service_hours),
            )
            metrics = delivery_metrics  # For compatibility with existing code
        except Exception as e:
            logger.warning("Failed to generate metrics for run %d: %s", run_idx, e)
            # Create a minimal metrics object for compatibility
            metrics = type('MinimalMetrics', (), {
                'revenue_per_round': 0.0,
                'order_penetration_rate': 0.0,
                'orders_per_runner_hour': 0.0,
            })()

        # Simple stats
        orders = sim_result.get("orders", [])
        failed_orders = sim_result.get("failed_orders", [])
        
        stats_md = [
            f"# Delivery Dynamic — Run {run_idx:02d}",
            "",
            f"Groups: {len(groups)}",
            f"Orders placed: {len([o for o in orders if o.get('status') == 'processed'])}",
            f"Orders failed: {len(failed_orders)}",
            f"Revenue per order: ${float(args.revenue_per_order):.2f}",
        ]
        (run_path / f"stats_run_{run_idx:02d}.md").write_text("\n".join(stats_md), encoding="utf-8")

        all_runs.append({
            "run_idx": run_idx,
            "groups": len(groups),
            "orders": len(orders),
            "failed": len(failed_orders),
            "rpr": getattr(metrics, 'revenue_per_round', 0.0),
        })

    # Phase-level summary
    lines: List[str] = ["# Delivery Dynamic Summary", "", f"Runs: {len(all_runs)}"]
    if all_runs:
        rprs = [float(r.get("rpr", 0.0)) for r in all_runs]
        lines.append(f"Revenue per round: min=${min(rprs):.2f} max=${max(rprs):.2f} mean=${sum(rprs)/len(rprs):.2f}")
    (output_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")

    logger.info("Done. Results in: %s", output_dir)


if __name__ == "__main__":
    main()


