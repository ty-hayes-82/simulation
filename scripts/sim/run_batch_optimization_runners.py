#!/usr/bin/env python3
"""
Batch optimization runner for finding ideal delivery runner counts.

Systematically tests different runner configurations to find the minimum number
of runners needed to achieve target on-time rates (95% and 99%).

Focuses on optimization metrics:
- On-time delivery rate
- Queue depth and wait times
- Utilization rates
- Break-even analysis

Windows PowerShell friendly: one short command per line, no piping/chaining.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import simpy

from golfsim.logging import init_logging, get_logger
from golfsim.config.loaders import load_tee_times_config, load_simulation_config
from golfsim.simulation.phase_simulations import generate_golfer_track
from golfsim.simulation.services import (
    DeliveryOrder,
    MultiRunnerDeliveryService,
)
from golfsim.analysis.delivery_runner_metrics import calculate_delivery_runner_metrics


logger = get_logger(__name__)


# -------------------- Helpers --------------------

def _parse_float_list(spec: str) -> List[float]:
    return [float(x.strip()) for x in str(spec).split(",") if str(x).strip()]


def _parse_int_list_or_range(spec: str) -> List[int]:
    s = str(spec).strip()
    if "-" in s and "," not in s:
        a, b = s.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def _timestamped_dirname(prefix: str) -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{ts}"


def _ensure_csv(path: Path, fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()


def _append_csv(path: Path, fieldnames: Sequence[str], row: Dict[str, Any]) -> None:
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writerow(row)


def _load_scenario_keys(course_dir: str, selected: Optional[str]) -> List[str]:
    cfg = load_tee_times_config(course_dir)
    scenarios = sorted((cfg.scenarios or {}).keys())
    if not selected or selected.lower() == "all":
        return scenarios
    chosen = [s.strip() for s in selected.split(",") if s.strip()]
    return [s for s in scenarios if s in chosen]


def _groups_from_scenario(course_dir: str, scenario_key: str, default_group_size: int = 4) -> List[Dict[str, Any]]:
    config = load_tee_times_config(course_dir)
    scenarios = config.scenarios or {}
    scenario = scenarios.get(scenario_key) or {}
    hourly: Dict[str, int] = scenario.get("hourly_golfers", {}) or {}
    if not hourly:
        logger.warning("tee-scenario '%s' missing 'hourly_golfers'", scenario_key)
        return []

    def _hhmm_to_seconds_since_7am(hhmm: str) -> int:
        try:
            hh, mm = hhmm.split(":")
            return (int(hh) - 7) * 3600 + int(mm) * 60
        except Exception:
            return 0

    groups: List[Dict[str, Any]] = []
    group_id = 1
    for hour_label, golfers in sorted(hourly.items(), key=lambda kv: _hhmm_to_seconds_since_7am(kv[0])):
        golfers_int = int(golfers or 0)
        if golfers_int <= 0:
            continue
        groups_this_hour = (golfers_int + default_group_size - 1) // default_group_size
        base_s = _hhmm_to_seconds_since_7am(hour_label)
        interval_seconds = int(3600 / max(groups_this_hour, 1))
        remaining = golfers_int
        for i in range(groups_this_hour):
            size = min(default_group_size, remaining)
            if size <= 0:
                break
            tee_time_s = base_s + i * interval_seconds
            groups.append({
                "group_id": group_id,
                "tee_time_s": int(tee_time_s),
                "num_golfers": int(size),
            })
            group_id += 1
            remaining -= size
    return groups


def _simulate_delivery_orders_with_constraints(
    groups: List[Dict[str, Any]],
    delivery_prob_per_9: float,
    prevent_front_upto_hole: int = 0,
    front9_prob_if_prevent: Optional[float] = None,
    minutes_per_hole: int = 12,
) -> List[DeliveryOrder]:
    orders: List[DeliveryOrder] = []
    prevent_upto = int(prevent_front_upto_hole or 0)
    use_prevent = prevent_upto >= 1
    front_prob = float(front9_prob_if_prevent) if (use_prevent and front9_prob_if_prevent is not None) else float(delivery_prob_per_9)
    front_min_hole = max(prevent_upto + 1, 1)
    front_max_hole = 9
    for group in groups:
        group_id = group["group_id"]
        tee_time_s = int(group["tee_time_s"])

        # Front nine
        if use_prevent:
            if random.random() < front_prob and front_min_hole <= front_max_hole:
                hole_front = random.randint(front_min_hole, front_max_hole)
                order_time_front_s = tee_time_s + (hole_front - 1) * minutes_per_hole * 60
                orders.append(DeliveryOrder(
                    order_id=None,
                    golfer_group_id=group_id,
                    golfer_id=f"G{group_id}",
                    order_time_s=order_time_front_s,
                    hole_num=hole_front,
                ))
        else:
            if random.random() < float(delivery_prob_per_9):
                hole_front = random.randint(1, 9)
                order_time_front_s = tee_time_s + (hole_front - 1) * minutes_per_hole * 60
                orders.append(DeliveryOrder(
                    order_id=None,
                    golfer_group_id=group_id,
                    golfer_id=f"G{group_id}",
                    order_time_s=order_time_front_s,
                    hole_num=hole_front,
                ))

        # Back nine
        if random.random() < float(delivery_prob_per_9):
            hole_back = random.randint(10, 18)
            order_time_back_s = tee_time_s + (hole_back - 1) * minutes_per_hole * 60
            orders.append(DeliveryOrder(
                order_id=None,
                golfer_group_id=group_id,
                golfer_id=f"G{group_id}",
                order_time_s=order_time_back_s,
                hole_num=hole_back,
            ))

    orders.sort(key=lambda x: x.order_time_s)
    for i, order in enumerate(orders, 1):
        order.order_id = f"{i:03d}"
    return orders


# -------------------- Optimization Context --------------------

@dataclass
class OptimizationTarget:
    name: str
    metric: str
    threshold: float
    comparison: str  # ">=", "<=", "==", etc.


@dataclass
class OptimizationResult:
    scenario: str
    prevention_variant: str
    delivery_prob: float
    target_name: str
    optimal_runners: Optional[int]
    achieved_metric: Optional[float]
    runs_tested: int
    total_simulations: int


@dataclass
class OptimizationContext:
    batch_id: str
    course_dir: str
    output_root: Path
    results_csv: Path
    detailed_csv: Path
    summary_path: Path
    targets: List[OptimizationTarget]


def _init_optimization_output(root_dir: Optional[str], targets: List[OptimizationTarget]) -> OptimizationContext:
    batch_id = _timestamped_dirname("optimization")
    output_root = Path(root_dir or (Path("outputs") / batch_id))
    output_root.mkdir(parents=True, exist_ok=True)
    
    results_csv = output_root / "optimization_results.csv"
    detailed_csv = output_root / "optimization_detailed.csv"
    summary_path = output_root / "optimization_summary.md"

    # Results CSV: one row per scenario/variant/target combination with optimal runners
    _ensure_csv(results_csv, [
        "batch_id", "scenario", "prevention_variant", "delivery_prob", "target_name",
        "target_metric", "target_threshold", "optimal_runners", "achieved_metric",
        "runs_tested", "total_simulations", "optimization_status"
    ])

    # Detailed CSV: all simulation runs with full metrics
    _ensure_csv(detailed_csv, [
        "batch_id", "scenario", "prevention_variant", "delivery_prob", "target_name",
        "num_runners", "run_index", "seed", "groups", "orders_placed",
        "on_time_rate", "delivery_cycle_time_p50", "delivery_cycle_time_p90",
        "failed_rate", "queue_depth_avg", "queue_wait_avg", "orders_per_runner_hour",
        "util_driving_pct", "util_waiting_pct", "util_handoff_pct", "util_deadhead_pct",
        "distance_per_delivery_avg", "total_orders", "successful_orders", "failed_orders",
        "total_revenue", "capacity_15min_window", "second_runner_break_even_orders"
    ])

    return OptimizationContext(
        batch_id=batch_id,
        course_dir="",
        output_root=output_root,
        results_csv=results_csv,
        detailed_csv=detailed_csv,
        summary_path=summary_path,
        targets=targets
    )


def _write_optimization_result(ctx: OptimizationContext, result: OptimizationResult) -> None:
    target = next((t for t in ctx.targets if t.name == result.target_name), None)
    if not target:
        return
    
    row = {
        "batch_id": ctx.batch_id,
        "scenario": result.scenario,
        "prevention_variant": result.prevention_variant,
        "delivery_prob": result.delivery_prob,
        "target_name": result.target_name,
        "target_metric": target.metric,
        "target_threshold": target.threshold,
        "optimal_runners": result.optimal_runners,
        "achieved_metric": result.achieved_metric,
        "runs_tested": result.runs_tested,
        "total_simulations": result.total_simulations,
        "optimization_status": "achieved" if result.optimal_runners is not None else "not_achieved"
    }
    
    _append_csv(ctx.results_csv, [
        "batch_id", "scenario", "prevention_variant", "delivery_prob", "target_name",
        "target_metric", "target_threshold", "optimal_runners", "achieved_metric",
        "runs_tested", "total_simulations", "optimization_status"
    ], row)


def _write_detailed_result(ctx: OptimizationContext, scenario: str, prevention_variant: str,
                          delivery_prob: float, target_name: str, num_runners: int,
                          run_index: int, seed: int, metrics: Any, groups: List[Dict[str, Any]],
                          orders_count: int) -> None:
    row = {
        "batch_id": ctx.batch_id,
        "scenario": scenario,
        "prevention_variant": prevention_variant,
        "delivery_prob": delivery_prob,
        "target_name": target_name,
        "num_runners": num_runners,
        "run_index": run_index,
        "seed": seed,
        "groups": len(groups),
        "orders_placed": orders_count,
        "on_time_rate": metrics.on_time_rate,
        "delivery_cycle_time_p50": metrics.delivery_cycle_time_p50,
        "delivery_cycle_time_p90": metrics.delivery_cycle_time_p90,
        "failed_rate": metrics.failed_rate,
        "queue_depth_avg": metrics.queue_depth_avg,
        "queue_wait_avg": metrics.queue_wait_avg,
        "orders_per_runner_hour": metrics.orders_per_runner_hour,
        "util_driving_pct": metrics.runner_utilization_driving_pct,
        "util_waiting_pct": metrics.runner_utilization_waiting_pct,
        "util_handoff_pct": metrics.runner_utilization_handoff_pct,
        "util_deadhead_pct": metrics.runner_utilization_deadhead_pct,
        "distance_per_delivery_avg": metrics.distance_per_delivery_avg,
        "total_orders": metrics.total_orders,
        "successful_orders": metrics.successful_orders,
        "failed_orders": metrics.failed_orders,
        "total_revenue": metrics.total_revenue,
        "capacity_15min_window": metrics.capacity_15min_window,
        "second_runner_break_even_orders": metrics.second_runner_break_even_orders,
    }
    
    _append_csv(ctx.detailed_csv, [
        "batch_id", "scenario", "prevention_variant", "delivery_prob", "target_name",
        "num_runners", "run_index", "seed", "groups", "orders_placed",
        "on_time_rate", "delivery_cycle_time_p50", "delivery_cycle_time_p90",
        "failed_rate", "queue_depth_avg", "queue_wait_avg", "orders_per_runner_hour",
        "util_driving_pct", "util_waiting_pct", "util_handoff_pct", "util_deadhead_pct",
        "distance_per_delivery_avg", "total_orders", "successful_orders", "failed_orders",
        "total_revenue", "capacity_15min_window", "second_runner_break_even_orders"
    ], row)


# -------------------- Optimization Logic --------------------

def _evaluate_target_achievement(metrics: Any, target: OptimizationTarget) -> bool:
    """Check if the target has been achieved based on the metric and threshold."""
    metric_value = getattr(metrics, target.metric, None)
    if metric_value is None:
        return False
    
    if target.comparison == ">=":
        return float(metric_value) >= target.threshold
    elif target.comparison == "<=":
        return float(metric_value) <= target.threshold
    elif target.comparison == "==":
        return abs(float(metric_value) - target.threshold) < 0.001
    else:
        return False


def _run_runner_simulation(course_dir: str, scenario: str, num_runners: int,
                          delivery_prob_per_9: float, prevention_variant: Dict[str, Any],
                          runner_speed_mps: float, prep_time_min: int, seed: int) -> Tuple[Any, List[Dict[str, Any]], int]:
    """Run a single runner simulation and return metrics, groups, and order count."""
    # Build groups
    groups = _groups_from_scenario(course_dir, scenario)

    # Orders with constraints
    random.seed(seed)
    orders = _simulate_delivery_orders_with_constraints(
        groups=groups,
        delivery_prob_per_9=float(delivery_prob_per_9),
        prevent_front_upto_hole=int(prevention_variant["upto"]),
        front9_prob_if_prevent=prevention_variant["front_prob"],
        minutes_per_hole=12,
    )

    # MultiRunner service
    env = simpy.Environment()
    service = MultiRunnerDeliveryService(
        env=env,
        course_dir=course_dir,
        num_runners=int(num_runners),
        runner_speed_mps=float(runner_speed_mps),
        prep_time_min=int(prep_time_min),
    )

    def order_arrivals():
        last_time = env.now
        for order in orders:
            target_time = max(order.order_time_s, service.service_open_s)
            if target_time > last_time:
                yield env.timeout(target_time - last_time)
            service.place_order(order)
            last_time = target_time

    env.process(order_arrivals())
    run_until = max(service.service_close_s + 1, max((o.order_time_s for o in orders), default=0) + 4 * 3600)
    env.run(until=run_until)

    # Compute metrics
    delivery_stats = service.delivery_stats or []
    failed_orders = service.failed_orders or []
    
    orders_dicts = [
        {
            "order_id": getattr(o, "order_id", None),
            "golfer_group_id": getattr(o, "golfer_group_id", None),
            "golfer_id": getattr(o, "golfer_id", None),
            "order_time_s": getattr(o, "order_time_s", None),
            "hole_num": getattr(o, "hole_num", None),
            "status": getattr(o, "status", None),
        }
        for o in orders
    ]
    failed_orders_dicts = [
        {
            "order_id": getattr(o, "order_id", None),
            "reason": getattr(o, "failure_reason", None),
        }
        for o in failed_orders
    ]

    sim_id = f"optimization_{scenario}_{num_runners}runners_{seed}"
    metrics = calculate_delivery_runner_metrics(
        delivery_stats=delivery_stats,
        activity_log=service.activity_log or [],
        orders=orders_dicts,
        failed_orders=failed_orders_dicts,
        revenue_per_order=25.0,
        sla_minutes=30,
        simulation_id=sim_id,
        runner_id=f"{int(num_runners)}_runners",
        service_hours=float((service.service_close_s - service.service_open_s) / 3600.0) if hasattr(service, 'service_close_s') else 10.0,
    )

    return metrics, groups, len(orders)


def _optimize_for_target(ctx: OptimizationContext, course_dir: str, scenario: str,
                        delivery_prob: float, prevention_variant: Dict[str, Any],
                        target: OptimizationTarget, max_runners: int, runs_per_config: int,
                        runner_speed_mps: float, prep_time_min: int, seed_base: int) -> OptimizationResult:
    """Find the optimal number of runners for a specific target."""
    
    total_simulations = 0
    
    # Test runner counts from 1 to max_runners
    for num_runners in range(1, max_runners + 1):
        achieved_count = 0
        metric_values = []
        
        # Run multiple simulations for this runner count to get stable results
        for run_idx in range(runs_per_config):
            seed = seed_base + total_simulations
            total_simulations += 1
            
            try:
                metrics, groups, orders_count = _run_runner_simulation(
                    course_dir=course_dir,
                    scenario=scenario,
                    num_runners=num_runners,
                    delivery_prob_per_9=delivery_prob,
                    prevention_variant=prevention_variant,
                    runner_speed_mps=runner_speed_mps,
                    prep_time_min=prep_time_min,
                    seed=seed
                )
                
                # Record detailed results
                _write_detailed_result(
                    ctx=ctx,
                    scenario=scenario,
                    prevention_variant=prevention_variant["label"],
                    delivery_prob=delivery_prob,
                    target_name=target.name,
                    num_runners=num_runners,
                    run_index=run_idx + 1,
                    seed=seed,
                    metrics=metrics,
                    groups=groups,
                    orders_count=orders_count
                )
                
                # Check if target is achieved
                if _evaluate_target_achievement(metrics, target):
                    achieved_count += 1
                
                # Collect metric values for averaging
                metric_value = getattr(metrics, target.metric, 0.0)
                metric_values.append(float(metric_value))
                
                print(f"[optimize] {scenario} {prevention_variant['label']} {target.name} {num_runners}r run{run_idx+1}: {target.metric}={metric_value:.3f}")
                
            except Exception as e:
                logger.warning("Simulation failed: %s", e)
                continue
        
        # Check if we consistently achieve the target (e.g., 80% of runs)
        success_rate = achieved_count / max(len(metric_values), 1)
        avg_metric = sum(metric_values) / max(len(metric_values), 1) if metric_values else 0.0
        
        print(f"[optimize] {scenario} {prevention_variant['label']} {target.name} {num_runners} runners: success_rate={success_rate:.2f} avg_{target.metric}={avg_metric:.3f}")
        
        # If we achieve the target in most runs, this is our optimal runner count
        if success_rate >= 0.8:  # 80% success rate threshold
            return OptimizationResult(
                scenario=scenario,
                prevention_variant=prevention_variant["label"],
                delivery_prob=delivery_prob,
                target_name=target.name,
                optimal_runners=num_runners,
                achieved_metric=avg_metric,
                runs_tested=num_runners,
                total_simulations=total_simulations
            )
    
    # If we never achieved the target, return result with no optimal runners
    return OptimizationResult(
        scenario=scenario,
        prevention_variant=prevention_variant["label"],
        delivery_prob=delivery_prob,
        target_name=target.name,
        optimal_runners=None,
        achieved_metric=None,
        runs_tested=max_runners,
        total_simulations=total_simulations
    )


def _generate_optimization_summary(ctx: OptimizationContext) -> None:
    """Generate a markdown summary of optimization results."""
    try:
        # Read results
        with ctx.results_csv.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            results = list(reader)
        
        summary_lines = [
            f"# Delivery Runner Optimization Summary",
            f"",
            f"**Batch ID:** {ctx.batch_id}",
            f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"",
            f"## Optimization Targets",
            f"",
        ]
        
        for target in ctx.targets:
            summary_lines.append(f"- **{target.name}:** {target.metric} {target.comparison} {target.threshold}")
        
        summary_lines.extend([
            f"",
            f"## Results by Scenario",
            f"",
        ])
        
        # Group results by scenario
        scenarios = {}
        for result in results:
            scenario = result["scenario"]
            if scenario not in scenarios:
                scenarios[scenario] = []
            scenarios[scenario].append(result)
        
        for scenario, scenario_results in scenarios.items():
            summary_lines.extend([
                f"### {scenario}",
                f"",
                f"| Prevention | Delivery Prob | Target | Optimal Runners | Achieved Metric | Status |",
                f"|------------|---------------|--------|-----------------|-----------------|--------|",
            ])
            
            for result in scenario_results:
                prevention = result["prevention_variant"]
                delivery_prob = result["delivery_prob"]
                target = result["target_name"]
                optimal_runners = result["optimal_runners"] or "Not Found"
                achieved_metric = f"{float(result['achieved_metric']):.3f}" if result["achieved_metric"] else "N/A"
                status = result["optimization_status"]
                
                summary_lines.append(f"| {prevention} | {delivery_prob} | {target} | {optimal_runners} | {achieved_metric} | {status} |")
            
            summary_lines.append("")
        
        # Write summary
        ctx.summary_path.write_text("\n".join(summary_lines), encoding="utf-8")
        print(f"Optimization summary written to: {ctx.summary_path}")
        
    except Exception as e:
        logger.warning("Failed to generate optimization summary: %s", e)


# -------------------- CLI --------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Optimize delivery runner counts for target on-time rates")
    parser.add_argument("--course-dir", default="courses/pinetree_country_club", help="Course directory")
    parser.add_argument("--output-dir", type=str, default=None, help="Where to store optimization results")
    parser.add_argument("--log-level", type=str, default="INFO", help="Log level")
    
    # Scenarios and variants to test
    parser.add_argument("--tee-scenarios", type=str, default="all", help="Comma-separated scenario keys or 'all'")
    parser.add_argument("--delivery-order-probs", type=str, default="0.2,0.3", help="Delivery order probability per nine to test")
    parser.add_argument("--front-preventions", type=str, default="none,1-3,1-6", help="Prevention variants: 'none', '1-3', '1-5', '1-6'")
    parser.add_argument("--front9-prob-if-prevent", type=float, default=0.1, help="Front-9 order prob if preventing front holes")
    
    # Optimization parameters
    parser.add_argument("--max-runners", type=int, default=10, help="Maximum number of runners to test")
    parser.add_argument("--runs-per-config", type=int, default=5, help="Number of runs per runner configuration")
    parser.add_argument("--target-95", action="store_true", help="Optimize for 95% on-time rate")
    parser.add_argument("--target-99", action="store_true", help="Optimize for 99% on-time rate")
    parser.add_argument("--custom-targets", type=str, default="", help="Custom targets in format 'name:metric:threshold:comparison,...'")
    
    # Runner parameters
    parser.add_argument("--runner-speed-mps", type=float, default=2.68, help="Runner speed in m/s")
    parser.add_argument("--prep-time-min", type=int, default=10, help="Food preparation time in minutes")
    parser.add_argument("--seed-base", type=int, default=12345, help="Base seed for reproducibility")
    
    args = parser.parse_args()
    init_logging(args.log_level)
    
    # Build optimization targets
    targets = []
    if args.target_95:
        targets.append(OptimizationTarget(name="95_percent_ontime", metric="on_time_rate", threshold=0.95, comparison=">="))
    if args.target_99:
        targets.append(OptimizationTarget(name="99_percent_ontime", metric="on_time_rate", threshold=0.99, comparison=">="))
    
    # Parse custom targets
    if args.custom_targets:
        for target_spec in args.custom_targets.split(","):
            parts = target_spec.strip().split(":")
            if len(parts) == 4:
                name, metric, threshold, comparison = parts
                targets.append(OptimizationTarget(
                    name=name.strip(),
                    metric=metric.strip(),
                    threshold=float(threshold),
                    comparison=comparison.strip()
                ))
    
    if not targets:
        targets = [
            OptimizationTarget(name="95_percent_ontime", metric="on_time_rate", threshold=0.95, comparison=">="),
            OptimizationTarget(name="99_percent_ontime", metric="on_time_rate", threshold=0.99, comparison=">=")
        ]
    
    # Initialize optimization context
    ctx = _init_optimization_output(args.output_dir, targets)
    ctx.course_dir = args.course_dir
    
    # Load scenarios and variants
    scenario_keys = _load_scenario_keys(args.course_dir, args.tee_scenarios)
    delivery_probs = _parse_float_list(args.delivery_order_probs)
    
    # Build prevention variants
    front_preventions_raw = [t.strip().lower() for t in str(args.front_preventions).split(",") if t.strip()]
    variants: List[Dict[str, Any]] = []
    seen_upto: set = set()
    for tok in front_preventions_raw:
        if tok in ("none", "0", "no", "false"):
            if 0 not in seen_upto:
                variants.append({"label": "none", "upto": 0, "front_prob": None})
                seen_upto.add(0)
        elif tok in ("1-3", "1_to_3", "1..3"):
            if 3 not in seen_upto:
                variants.append({"label": "front1_3", "upto": 3, "front_prob": 0.15})
                seen_upto.add(3)
        elif tok in ("1-6", "1_to_6", "1..6"):
            if 6 not in seen_upto:
                variants.append({"label": "front1_6", "upto": 6, "front_prob": 0.10})
                seen_upto.add(6)
        elif tok in ("1-5", "1_to_5", "1..5"):
            if 5 not in seen_upto:
                variants.append({"label": "front1_5", "upto": 5, "front_prob": float(args.front9_prob_if_prevent)})
                seen_upto.add(5)
    
    if not variants:
        variants = [{"label": "none", "upto": 0, "front_prob": None}]
    
    logger.info("Starting optimization. Output: %s", ctx.output_root)
    logger.info("Targets: %s", [f"{t.name} ({t.metric} {t.comparison} {t.threshold})" for t in targets])
    
    # Run optimizations
    total_optimizations = len(scenario_keys) * len(delivery_probs) * len(variants) * len(targets)
    current_optimization = 0
    
    for scenario in scenario_keys:
        for delivery_prob in delivery_probs:
            for variant in variants:
                for target in targets:
                    current_optimization += 1
                    print(f"\n[{current_optimization}/{total_optimizations}] Optimizing {scenario} {variant['label']} {delivery_prob} for {target.name}")
                    
                    result = _optimize_for_target(
                        ctx=ctx,
                        course_dir=args.course_dir,
                        scenario=scenario,
                        delivery_prob=delivery_prob,
                        prevention_variant=variant,
                        target=target,
                        max_runners=args.max_runners,
                        runs_per_config=args.runs_per_config,
                        runner_speed_mps=args.runner_speed_mps,
                        prep_time_min=args.prep_time_min,
                        seed_base=args.seed_base + current_optimization * 1000
                    )
                    
                    _write_optimization_result(ctx, result)
                    
                    if result.optimal_runners:
                        print(f"✓ Found optimal: {result.optimal_runners} runners for {result.achieved_metric:.3f} {target.metric}")
                    else:
                        print(f"✗ No solution found within {args.max_runners} runners")
    
    # Generate summary
    _generate_optimization_summary(ctx)
    
    logger.info("Optimization complete. Results: %s", ctx.results_csv)
    logger.info("Summary: %s", ctx.summary_path)
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
