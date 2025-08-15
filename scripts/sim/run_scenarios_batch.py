#!/usr/bin/env python3
"""
Scenario batch runner

Runs, for each tee-time scenario in the course config:
- 5 simulations of bev-with-golfers (1 beverage cart)
- 5 simulations of delivery-runner with 1 runner
- 5 simulations of delivery-runner with 2 runners
- 5 simulations of delivery-runner with 3 runners

Leverages unified mode entrypoints in `scripts/sim/run_unified_simulation.py` to ensure
consistent outputs and metrics with the rest of the tooling.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Dict, List
import csv
import pandas as pd

from golfsim.config.loaders import load_tee_times_config, load_simulation_config
from golfsim.logging import get_logger, init_logging
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))
from utils import setup_encoding, add_log_level_argument, write_json
from scripts.sim import run_unified_simulation as unified


logger = get_logger(__name__)


def _aggregate_run_stats_to_csv(output_dir: Path, scenario_name: str, run_prefix: str) -> None:
    """Aggregate stats from all runs in a scenario group and save to CSV."""
    try:
        run_dirs = [d for d in output_dir.iterdir() if d.is_dir() and d.name.startswith("run_")]
        if not run_dirs:
            logger.warning("No run directories found in %s", output_dir)
            return
            
        all_stats = []
        
        for run_dir in sorted(run_dirs):
            # Initialize base stats
            stats = {
                'run_id': run_dir.name,
                'scenario': scenario_name,
                'run_prefix': run_prefix,
                'total_orders': 0,
                'successful_deliveries': 0,
                'failed_deliveries': 0,
                'avg_delivery_time_min': 0,
                'total_distance_km': 0,
                'total_revenue_usd': 0,
                'service_efficiency_pct': 0,
                'avg_sla_compliance_pct': 0,
            }
            
            # Try to load base results from results.json
            results_file = run_dir / "results.json"
            if results_file.exists():
                try:
                    with open(results_file, 'r') as f:
                        data = json.load(f)
                    
                    # Extract basic order counts from results.json structure
                    orders = data.get('orders', [])
                    if orders:
                        stats['total_orders'] = len(orders)
                        stats['successful_deliveries'] = len([o for o in orders if o.get('status') == 'processed'])
                        stats['failed_deliveries'] = len([o for o in orders if o.get('status') == 'failed'])
                        
                        # Calculate average delivery time
                        completion_times = [o.get('total_completion_time_s', 0) for o in orders if o.get('total_completion_time_s')]
                        if completion_times:
                            stats['avg_delivery_time_min'] = sum(completion_times) / len(completion_times) / 60.0
                        
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning("Error reading results from %s: %s", results_file, e)
            
            # Load delivery runner metrics from separate JSON file
            dr_metrics_file = run_dir / f"delivery_runner_metrics_{run_dir.name}.json"
            if dr_metrics_file.exists():
                try:
                    with open(dr_metrics_file, 'r') as f:
                        dr_metrics = json.load(f)
                    
                    stats.update({
                        # Executive-priority delivery metrics
                        'dr_revenue_per_round': dr_metrics.get('revenue_per_round', 0),
                        'dr_orders_per_runner_hour': dr_metrics.get('orders_per_runner_hour', 0),
                        'dr_on_time_rate': dr_metrics.get('on_time_rate', 0),
                        'dr_delivery_cycle_time_p90': dr_metrics.get('delivery_cycle_time_p90', 0),
                        'dr_delivery_cycle_time_avg': dr_metrics.get('delivery_cycle_time_avg', 0),
                        'dr_failed_rate': dr_metrics.get('failed_rate', 0),
                        'dr_second_runner_break_even_orders': dr_metrics.get('second_runner_break_even_orders', 0),
                        'dr_queue_wait_avg': dr_metrics.get('queue_wait_avg', 0),
                        'dr_runner_utilization_driving_pct': dr_metrics.get('runner_utilization_driving_pct', 0),
                        'dr_runner_utilization_waiting_pct': dr_metrics.get('runner_utilization_waiting_pct', 0),
                        'dr_distance_per_delivery_avg': dr_metrics.get('distance_per_delivery_avg', 0),
                        # Additional delivery metrics
                        'dr_total_revenue': dr_metrics.get('total_revenue', 0),
                        'dr_successful_orders': dr_metrics.get('successful_orders', 0),
                        'dr_failed_orders': dr_metrics.get('failed_orders', 0),
                        'dr_total_rounds': dr_metrics.get('total_rounds', 0),
                        'dr_active_runner_hours': dr_metrics.get('active_runner_hours', 0),
                    })
                    
                    # Add zone service times if available
                    zone_times = dr_metrics.get('zone_service_times', {})
                    for zone_key, time_val in zone_times.items():
                        stats[f'dr_zone_{zone_key}'] = time_val
                        
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning("Error reading delivery runner metrics from %s: %s", dr_metrics_file, e)
            
            # Load beverage cart metrics from separate JSON file
            bc_metrics_file = run_dir / f"bev_cart_metrics_{run_dir.name}.json"
            if bc_metrics_file.exists():
                try:
                    with open(bc_metrics_file, 'r') as f:
                        bc_metrics = json.load(f)
                    
                    stats.update({
                        # Executive-priority beverage cart metrics
                        'bc_revenue_per_round': bc_metrics.get('revenue_per_round', 0),
                        'bc_total_revenue': bc_metrics.get('total_revenue', 0),
                        'bc_orders_per_cart_hour': bc_metrics.get('orders_per_cart_hour', 0),
                        'bc_order_penetration_rate': bc_metrics.get('order_penetration_rate', 0),
                        'bc_average_order_value': bc_metrics.get('average_order_value', 0),
                        'bc_total_tips': bc_metrics.get('total_tips', 0),
                        'bc_total_delivery_orders_conversion_count': bc_metrics.get('total_delivery_orders_conversion_count', 0),
                        'bc_total_delivery_orders_conversion_revenue': bc_metrics.get('total_delivery_orders_conversion_revenue', 0),
                        'bc_holes_covered_per_hour': bc_metrics.get('holes_covered_per_hour', 0),
                        'bc_minutes_per_hole_per_cart': bc_metrics.get('minutes_per_hole_per_cart', 0),
                        # Additional beverage cart metrics
                        'bc_unique_customers': bc_metrics.get('unique_customers', 0),
                        'bc_tip_rate': bc_metrics.get('tip_rate', 0),
                        'bc_tips_per_order': bc_metrics.get('tips_per_order', 0),
                        'bc_total_holes_covered': bc_metrics.get('total_holes_covered', 0),
                        'bc_golfer_repeat_rate': bc_metrics.get('golfer_repeat_rate', 0),
                        'bc_average_orders_per_customer': bc_metrics.get('average_orders_per_customer', 0),
                        'bc_customers_with_multiple_orders': bc_metrics.get('customers_with_multiple_orders', 0),
                        'bc_golfer_visibility_interval_minutes': bc_metrics.get('golfer_visibility_interval_minutes', 0),
                        'bc_total_visibility_events': bc_metrics.get('total_visibility_events', 0),
                        'bc_service_hours': bc_metrics.get('service_hours', 0),
                        'bc_rounds_in_service_window': bc_metrics.get('rounds_in_service_window', 0),
                        'bc_total_orders': bc_metrics.get('total_orders', 0),
                    })
                        
                except (json.JSONDecodeError, KeyError) as e:
                    logger.warning("Error reading beverage cart metrics from %s: %s", bc_metrics_file, e)
            
            all_stats.append(stats)
        
        if all_stats:
            # Create aggregated stats CSV
            csv_file = output_dir / "aggregated_stats.csv"
            
            # Get all possible column names
            all_columns = set()
            for stat in all_stats:
                all_columns.update(stat.keys())
            all_columns = sorted(all_columns)
            
            with open(csv_file, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=all_columns)
                writer.writeheader()
                writer.writerows(all_stats)
            
            logger.info("Aggregated stats saved to: %s", csv_file)
            
            # Create summary stats
            summary = {
                'total_runs': len(all_stats),
                'avg_total_orders': sum(s.get('total_orders', 0) for s in all_stats) / len(all_stats),
                'avg_successful_deliveries': sum(s.get('successful_deliveries', 0) for s in all_stats) / len(all_stats),
                'avg_delivery_time_min': sum(s.get('avg_delivery_time_min', 0) for s in all_stats) / len(all_stats),
                'avg_revenue_usd': sum(s.get('total_revenue_usd', 0) for s in all_stats) / len(all_stats),
            }
            
            summary_file = output_dir / "aggregated_summary.json"
            with open(summary_file, 'w') as f:
                json.dump(summary, f, indent=2)
            
            logger.info("Summary stats saved to: %s", summary_file)
        
    except Exception as e:
        logger.error("Failed to aggregate stats for %s: %s", output_dir, e)


# Local helper mirroring unified scenario parsing to avoid private imports
def _build_groups_from_scenario(course_dir: str, scenario_key: str, default_group_size: int = 4) -> List[Dict[str, Any]]:
    if not scenario_key or scenario_key.lower() in {"none", "manual"}:
        return []
    try:
        cfg = load_tee_times_config(course_dir)
    except FileNotFoundError:
        logger.warning("tee_times_config.json not found; skipping scenario '%s'", scenario_key)
        return []

    scenarios = cfg.scenarios or {}
    if scenario_key not in scenarios:
        logger.warning("Scenario '%s' not found in tee_times_config.json", scenario_key)
        return []

    scenario = scenarios[scenario_key]
    hourly: Dict[str, int] = scenario.get("hourly_golfers", {})
    if not hourly:
        logger.warning("Scenario '%s' missing 'hourly_golfers' — skipping", scenario_key)
        return []

    def _parse_hhmm_to_seconds_since_7am(hhmm: str) -> int:
        try:
            hh, mm = hhmm.split(":")
            return (int(hh) - 7) * 3600 + int(mm) * 60
        except Exception:
            return 0

    groups: List[Dict[str, Any]] = []
    group_id = 1
    for hour_label, golfers in sorted(hourly.items(), key=lambda kv: _parse_hhmm_to_seconds_since_7am(kv[0])):
        golfers_int = int(golfers or 0)
        if golfers_int <= 0:
            continue
        groups_this_hour = (golfers_int + default_group_size - 1) // default_group_size
        if groups_this_hour <= 0:
            continue
        base_s = _parse_hhmm_to_seconds_since_7am(hour_label)
        interval_seconds = int(3600 / groups_this_hour)
        remaining_golfers = golfers_int
        for i in range(groups_this_hour):
            size = min(default_group_size, remaining_golfers)
            if size <= 0:
                break
            tee_time_s = base_s + i * interval_seconds
            groups.append({
                "group_id": group_id,
                "tee_time_s": int(tee_time_s),
                "num_golfers": int(size),
            })
            group_id += 1
            remaining_golfers -= size
    return groups


def main() -> int:
    setup_encoding()

    parser = argparse.ArgumentParser(
        description="Run scenario batch: bev-with-golfers and delivery-runner (1-3 runners)",
    )
    parser.add_argument(
        "--course-dir",
        default="courses/pinetree_country_club",
        help="Course directory containing config files",
    )
    parser.add_argument(
        "--scenario",
        default=None,
        help="Scenario key from tee_times_config.json; run all if omitted",
    )
    parser.add_argument(
        "--runs-per-scenario",
        type=int,
        default=3,
        help="Number of runs per scenario",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs",
        help="Base output directory",
    )
    parser.add_argument(
        "--delivery-total-orders",
        type=str,
        default="10,20,30,40",
        help="Comma-separated list of delivery total orders to test (e.g., 10,20,30,40)",
    )
    parser.add_argument(
        "--block-variants",
        type=str,
        default="none,1-3,1-6",
        help="Comma-separated blocking variants: 'none', '1-3', '1-6'",
    )
    # Optional overrides (fall back to simulation_config.json)
    parser.add_argument("--prep-time", type=int, default=None, help="Delivery prep time minutes (override)")
    parser.add_argument("--runner-speed", type=float, default=None, help="Runner speed m/s (override)")
    parser.add_argument("--order-prob-9", type=float, default=None, help="Delivery order probability per 9 holes (override)")
    parser.add_argument("--bev-pass-prob", type=float, default=None, help="Bev cart pass order probability (override)")
    parser.add_argument("--bev-avg-order", type=float, default=None, help="Bev cart average order USD (override)")
    add_log_level_argument(parser)

    args = parser.parse_args()

    init_logging(args.log_level)
    course_dir = Path(args.course_dir)
    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    # Load configs for defaults
    sim_cfg = load_simulation_config(course_dir)
    try:
        tee_cfg = load_tee_times_config(course_dir)
        available = list((tee_cfg.scenarios or {}).keys())
    except FileNotFoundError:
        available = []
    if args.scenario:
        scenarios = [args.scenario]
    else:
        scenarios = available
    if not scenarios:
        logger.error("No scenarios found in tee_times_config.json")
        return 1

    # Resolve defaults with overrides
    prep_time_min = int(args.prep_time) if args.prep_time is not None else int(sim_cfg.delivery_prep_time_sec // 60)
    runner_speed_mps = float(args.runner_speed) if args.runner_speed is not None else float(sim_cfg.delivery_runner_speed_mps)
    # Unified runner now derives delivery probability from delivery_total_orders; default to 0.0 here if not overridden
    delivery_prob_9 = float(args.order_prob_9) if args.order_prob_9 is not None else 0.0
    # Use new bev-cart probability field name with fallback to 0.35
    bev_pass_prob = float(args.bev_pass_prob) if args.bev_pass_prob is not None else float(getattr(sim_cfg, "bev_cart_order_probability_per_9_holes", 0.35))
    bev_avg_order = float(args.bev_avg_order) if args.bev_avg_order is not None else float(sim_cfg.bev_cart_avg_order_usd)

    # Service hours for delivery metrics scaling (fallback to 10h if not set)
    service_hours = 10.0
    if getattr(sim_cfg, "service_hours", None) is not None:
        try:
            service_hours = float(sim_cfg.service_hours.end_hour - sim_cfg.service_hours.start_hour)
        except Exception:
            service_hours = 10.0

    # Parse delivery totals
    try:
        delivery_totals = [int(x.strip()) for x in str(args.delivery_total_orders).split(",") if str(x).strip()]
    except Exception:
        delivery_totals = [10, 20, 30, 40]

    # Parse block variants
    block_variants: List[Dict[str, int]] = []
    for tok in [t.strip().lower() for t in str(args.block_variants).split(",") if t.strip()]:
        if tok in ("none", "0", "no", "false"):
            block_variants.append({"label": "none", "upto": 0})
        elif tok in ("1-3", "1_to_3", "1..3"):
            block_variants.append({"label": "block_to_hole3", "upto": 3})
        elif tok in ("1-6", "1_to_6", "1..6"):
            block_variants.append({"label": "block_to_hole6", "upto": 6})
    if not block_variants:
        block_variants = [
            {"label": "none", "upto": 0},
            {"label": "block_to_hole3", "upto": 3},
            {"label": "block_to_hole6", "upto": 6},
        ]

    # Helpers to modify/restore config
    def _backup_and_modify_config_for_delivery_totals(course_dir: Path, delivery_total_orders: int) -> Path:
        config_path = Path(course_dir) / "config" / "simulation_config.json"
        backup_path = config_path.with_suffix('.json.backup')
        if not backup_path.exists():
            shutil.copy2(config_path, backup_path)
            logger.info("Backed up simulation_config.json to %s", backup_path)
        data = json.loads(config_path.read_text(encoding="utf-8"))
        data["delivery_total_orders"] = int(delivery_total_orders)
        config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        logger.info("Set delivery_total_orders=%d in %s", int(delivery_total_orders), config_path)
        return backup_path

    def _restore_config_from_backup(course_dir: Path, backup_path: Path) -> None:
        try:
            if backup_path and backup_path.exists():
                config_path = Path(course_dir) / "config" / "simulation_config.json"
                shutil.copy2(backup_path, config_path)
                logger.info("Restored original simulation_config.json from %s", backup_path)
        except Exception as e:
            logger.warning("Failed to restore config backup: %s", e)

    for scenario_name in scenarios:
        logger.info("Running scenario: %s", scenario_name)
        # Verify scenario exists
        groups_preview = _build_groups_from_scenario(str(course_dir), scenario_name)
        if not groups_preview:
            logger.warning("No groups generated for scenario '%s'; skipping", scenario_name)
            continue

        scenario_dir = output_root / f"scenario_{scenario_name}"
        scenario_dir.mkdir(parents=True, exist_ok=True)

        # 1) Bev-with-golfers (1 cart)
        bev_out = scenario_dir / "bev_with_golfers"
        bev_args = argparse.Namespace(
            mode="bev-with-golfers",
            course_dir=str(course_dir),
            num_runs=int(args.runs_per_scenario),
            output_dir=str(bev_out),
            log_level=args.log_level,
            groups_count=0,
            groups_interval_min=15.0,
            first_tee="09:00",
            tee_scenario=scenario_name,
            num_carts=1,
            order_prob=float(bev_pass_prob),
            avg_order_usd=float(bev_avg_order),
            random_seed=None,
            no_visualization=True,
        )
        bev_out.mkdir(parents=True, exist_ok=True)
        unified._run_mode_bev_with_golfers(bev_args)
        
        # Aggregate stats for beverage cart runs
        _aggregate_run_stats_to_csv(bev_out, scenario_name, "bev_with_golfers")

        # 2) Delivery-runner with 1, 2, 3 runners, multiple delivery totals, and blocking variants
        for total_orders in delivery_totals:
            backup_path = None
            try:
                backup_path = _backup_and_modify_config_for_delivery_totals(course_dir, int(total_orders))
                for rn in (1, 2, 3):
                    for bv in block_variants:
                        label = bv["label"]
                        upto = int(bv["upto"])
                        dr_out = scenario_dir / f"delivery_runner_{rn}r_total{int(total_orders)}_{label}"
                        dr_out.mkdir(parents=True, exist_ok=True)

                        if upto <= 0:
                            # No blocking: call unified runner directly
                            dr_args = argparse.Namespace(
                                mode="delivery-runner",
                                course_dir=str(course_dir),
                                num_runs=int(args.runs_per_scenario),
                                output_dir=str(dr_out),
                                log_level=args.log_level,
                                groups_count=0,
                                groups_interval_min=15.0,
                                first_tee="09:00",
                                tee_scenario=scenario_name,
                                order_prob_9=float(delivery_prob_9),
                                prep_time=int(prep_time_min),
                                runner_speed=float(runner_speed_mps),
                                revenue_per_order=float(sim_cfg.delivery_avg_order_usd),
                                sla_minutes=30,
                                service_hours=float(service_hours),
                                num_runners=int(rn),
                                random_seed=None,
                                no_visualization=True,
                                no_bev_cart=True,  # Disable beverage cart for delivery-runner-only simulations
                            )
                            unified._run_mode_delivery_runner(dr_args)
                        else:
                            # Blocking variant: use the with_blocking script via subprocess
                            script_path = Path(__file__).parent / "run_unified_simulation_with_blocking.py"
                            cmd = [
                                sys.executable, str(script_path),
                                "--mode", "delivery-runner",
                                "--course-dir", str(course_dir),
                                "--tee-scenario", str(scenario_name),
                                "--num-runs", str(int(args.runs_per_scenario)),
                                "--num-runners", str(int(rn)),
                                "--block-up-to-hole", str(upto),
                                "--output-dir", str(dr_out),
                                "--log-level", str(args.log_level),
                                "--no-visualization",
                                "--no-bev-cart",  # Disable beverage cart for delivery-runner-only simulations
                            ]
                            try:
                                logger.info("Running (blocking %s): %s", label, " ".join(cmd))
                                subprocess.run(cmd, check=True, text=True)
                            except subprocess.CalledProcessError as e:
                                logger.warning("Blocking run failed (runners=%d, total=%d, %s): %s", rn, total_orders, label, e)
                        
                        # Aggregate stats for this group of runs
                        run_prefix = f"delivery_runner_{rn}r_total{int(total_orders)}_{label}"
                        _aggregate_run_stats_to_csv(dr_out, scenario_name, run_prefix)
            finally:
                if backup_path:
                    _restore_config_from_backup(course_dir, backup_path)

    logger.info("All scenarios complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
