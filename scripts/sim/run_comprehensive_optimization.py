#!/usr/bin/env python3
"""
Comprehensive Optimization Runner

Tests combinations of:
- Total orders: 5-40 (both bev cart and delivery)
- Bev carts: 1-5
- Delivery blocking scenarios: Full course, block up to hole 3, block up to hole 6, block holes 10-12, block holes 1-5, block holes 1-5 AND 10-12
- Runner counts: 1-4
- Tee scenarios: busy_weekend, typical_weekday, etc.
- SLA optimization mode for 95% target

Generates all output files including coordinates for each configuration (unless disabled).

Windows PowerShell friendly: one short command per line, no piping/chaining.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
import subprocess
import sys

from golfsim.logging import init_logging, get_logger
from golfsim.config.loaders import load_simulation_config

logger = get_logger(__name__)

def _backup_and_modify_config(course_dir: str, bev_order_prob: float, delivery_total_orders: int) -> Path:
    """Backup original config and update JSON in-place with only the needed fields.

    Critical: Preserve existing fields like 'clubhouse' exactly as-is to avoid loader errors.
    """
    config_path = Path(course_dir) / "config" / "simulation_config.json"
    backup_path = config_path.with_suffix('.json.backup')

    # Backup original if not already done
    if not backup_path.exists():
        shutil.copy2(config_path, backup_path)
        logger.info("Backed up original config to: %s", backup_path)

    # Load original JSON directly to preserve structure
    try:
        with config_path.open('r', encoding='utf-8') as f:
            config_json = json.load(f)
    except Exception as e:
        logger.error("Failed to read simulation_config.json: %s", e)
        raise

    # Update only the fields we intend to change
    try:
        if bev_order_prob is not None:
            config_json['bev_cart_order_probability_per_9_holes'] = float(bev_order_prob)
        if delivery_total_orders is not None:
            config_json['delivery_total_orders'] = int(delivery_total_orders)
    except Exception as e:
        logger.error("Failed to apply config overrides: %s", e)
        raise

    # Write updated JSON back
    try:
        with config_path.open('w', encoding='utf-8') as f:
            json.dump(config_json, f, indent=2)
    except Exception as e:
        logger.error("Failed to write modified simulation_config.json: %s", e)
        raise

    logger.info(
        "Modified config: bev_cart_order_probability_per_9_holes=%.2f, delivery_total_orders=%d",
        bev_order_prob,
        delivery_total_orders,
    )
    return backup_path

def _restore_config(course_dir: str, backup_path: Path) -> None:
    """Restore original configuration."""
    config_path = Path(course_dir) / "config" / "simulation_config.json"
    if backup_path.exists():
        shutil.copy2(backup_path, config_path)
        logger.info("Restored original config")

def _run_unified_simulation(mode: str, use_blocking: bool = False, **kwargs) -> int:
    """Run the unified simulation script with given parameters."""
    cmd = [sys.executable, "scripts/sim/run_unified_simulation.py", "--mode", mode]
    
    # Add common parameters
    common_params = {
        "course_dir": "courses/pinetree_country_club",
        "tee_scenario": kwargs.get("tee_scenario", "busy_weekend"),
        "num_runs": kwargs.get("num_runs", 5),
        "log_level": kwargs.get("log_level", "WARNING"),  # Reduce log noise
        "skip_executive_summary": False,  # Generate executive summaries for metrics
    }
    
    # Add coordinate CSV disabling if requested
    if kwargs.get("skip_coordinates", False):
        cmd.extend(["--no-coordinates"])
    
    # Override with provided kwargs
    params = {**common_params, **kwargs}
    
    # Convert parameters to command line arguments
    for key, value in params.items():
        if key in ["skip_coordinates", "skip_executive_summary"]:
            continue  # Already handled above
        elif key == "block_holes_10_12":
            # Handle boolean flag correctly - only add if True
            if value:
                cmd.append("--block-holes-10-12")
        else:
            cmd.extend([f"--{key.replace('_', '-')}", str(value)])
    
    logger.info("Running: %s", " ".join(cmd))
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return result.returncode
    except subprocess.CalledProcessError as e:
        logger.error("Command failed with return code %d", e.returncode)
        if e.stdout:
            logger.error("STDOUT: %s", e.stdout[-1000:])  # Last 1000 chars
        if e.stderr:
            logger.error("STDERR: %s", e.stderr[-1000:])
        return e.returncode

def _create_run_summary(output_root: Path, total_orders_list: List[int], 
                       bev_carts_list: List[int], delivery_blocking_scenarios: List[Dict],
                       runner_counts: List[int], tee_scenarios: List[str]) -> None:
    """Create comprehensive summary of all runs."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    summary_lines = [
        "# Comprehensive Optimization Summary",
        "",
        f"**Generated:** {timestamp}",
        f"**Total Configurations:** {len(total_orders_list) * len(bev_carts_list) * len(delivery_blocking_scenarios) * len(runner_counts) * len(tee_scenarios)}",
        "",
        "## Test Parameters",
        "",
        f"- **Total Orders Range:** {min(total_orders_list)}-{max(total_orders_list)}",
        f"- **Beverage Carts Range:** {min(bev_carts_list)}-{max(bev_carts_list)}",
        f"- **Runner Counts:** {', '.join(map(str, runner_counts))}",
        f"- **Tee Scenarios:** {', '.join(tee_scenarios)}",
        f"- **Delivery Blocking Scenarios:** {len(delivery_blocking_scenarios)} variants",
        "",
        "## Delivery Blocking Scenarios",
        "",
    ]
    
    for scenario in delivery_blocking_scenarios:
        summary_lines.append(f"- **{scenario['name']}:** {scenario['description']}")
    
    summary_lines.extend([
        "",
        "## Directory Structure",
        "",
        "Each configuration creates outputs in format:",
        "`{timestamp}_{total_orders}orders_{num_carts}bevcarts_{blocking_scenario}_{num_runners}runners_{tee_scenario}/`",
        "",
        "Contains:",
        "- `bev_cart_*` directories: Beverage cart simulations (1-5 carts)",
        "- `delivery_*` directories: Delivery runner simulations with blocking",
        "- Coordinate CSV files for visualization (unless disabled)",
        "- Metrics and analysis files",
        "",
        "## Navigation",
        "",
        "- Look for `coordinates.csv` files for GPS tracking data",
        "- Check `summary.md` files in each subdirectory for metrics",
        "- Review `events.csv` files for detailed simulation timelines",
    ])
    
    summary_path = output_root / "comprehensive_optimization_summary.md"
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")
    logger.info("Comprehensive summary written to: %s", summary_path)

def _create_sla_optimization_summary(output_root: Path, results: List[Dict], 
                                   target_sla: float, tee_scenario: str, num_runners: int) -> None:
    """Create SLA optimization summary focusing on 95% target achievement."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    summary_lines = [
        "# SLA Optimization Summary",
        "",
        f"**Generated:** {timestamp}",
        f"**Target SLA:** {target_sla*100:.1f}%",
        f"**Tee Scenario:** {tee_scenario}",
        f"**Runner Count:** {num_runners}",
        "",
        "## Results by Blocking Scenario",
        "",
        "| Scenario | SLA % | Failed % | Avg Wait | Avg Order | P90 Order | Revenue | Status |",
        "|----------|-------|---------|----------|-----------|-----------|---------|--------|",
    ]
    
    # Sort results by SLA percentage (descending)
    sorted_results = sorted(results, key=lambda x: x.get('sla_percentage', 0), reverse=True)
    
    for result in sorted_results:
        sla_pct = result.get('sla_percentage', 0) * 100
        failed_pct = result.get('failed_rate', 0) * 100
        queue_wait = result.get('queue_wait_avg', 0)
        cycle_time = result.get('delivery_cycle_time_avg', 0)
        p90_time = result.get('delivery_cycle_time_p90', 0)
        revenue = result.get('revenue_per_round', 0)
        status = "✓ Target Met" if sla_pct >= target_sla * 100 else "✗ Below Target"
        
        summary_lines.append(
            f"| {result['scenario_name']} | {sla_pct:.1f}% | {failed_pct:.1f}% | "
            f"{queue_wait:.1f} min | {cycle_time:.1f} min | {p90_time:.1f} min | "
            f"${revenue:.2f} | {status} |"
        )
        
        # Add description as a separate row with colspan
        summary_lines.append(
            f"| <small><i>{result['description']}</i></small> | | | | | | |"
        )
    
    # Find best scenarios
    target_met = [r for r in sorted_results if r.get('sla_percentage', 0) >= target_sla]
    best_scenario = sorted_results[0] if sorted_results else None
    
    summary_lines.extend([
        "",
        "## Summary",
        "",
        f"- **Total scenarios tested:** {len(results)}",
        f"- **Scenarios meeting {target_sla*100:.1f}% SLA:** {len(target_met)}",
        f"- **Best scenario:** {best_scenario['scenario_name'] if best_scenario else 'None'} "
        f"({best_scenario.get('sla_percentage', 0)*100:.1f}% SLA)" if best_scenario else "",
        "",
        "## Recommendations",
        "",
    ])
    
    if target_met:
        summary_lines.append(f"**Recommended blocking scenarios for {target_sla*100:.1f}% SLA:**")
        for scenario in target_met[:3]:  # Top 3
            summary_lines.append(f"- {scenario['scenario_name']}: {scenario['description']} "
                               f"({scenario.get('sla_percentage', 0)*100:.1f}% SLA)")
    else:
        summary_lines.append(f"**No scenarios achieved {target_sla*100:.1f}% SLA.**")
        summary_lines.append(f"Best achievable: {best_scenario.get('sla_percentage', 0)*100:.1f}% "
                           f"with {best_scenario['scenario_name']}" if best_scenario else "No data")
    
    summary_path = output_root / "sla_optimization_summary.md"
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")
    logger.info("SLA optimization summary written to: %s", summary_path)

def main() -> int:
    parser = argparse.ArgumentParser(description="Comprehensive optimization testing with SLA focus")
    parser.add_argument("--course-dir", default="courses/pinetree_country_club", help="Course directory")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory root")
    parser.add_argument("--log-level", type=str, default="INFO", help="Log level")
    parser.add_argument("--bev-order-prob-range", type=str, default="0.2,0.3,0.35,0.4,0.5", 
                       help="Comma-separated list of bev-cart order probability per 9-holes values to test")
    parser.add_argument("--bev-carts-range", type=str, default="1,2,3,4,5",
                       help="Comma-separated list of beverage cart counts to test")
    parser.add_argument("--skip-bev-carts", action="store_true", 
                       help="Skip beverage cart simulations (delivery only)")
    parser.add_argument("--skip-delivery", action="store_true",
                       help="Skip delivery simulations (bev carts only)")
    parser.add_argument("--runner-counts", type=str, default="1,2,3,4",
                       help="Comma-separated list of delivery runner counts to test")
    parser.add_argument("--tee-scenarios", type=str, default="busy_weekend",
                       help="Comma-separated list of tee scenarios to test")
    parser.add_argument("--sla-optimization", action="store_true",
                       help="Focus on SLA optimization mode (95% target)")
    parser.add_argument("--target-sla", type=float, default=0.95,
                       help="Target SLA percentage (0.0-1.0) for optimization mode")
    parser.add_argument("--skip-coordinates", action="store_true",
                       help="Skip coordinate CSV generation to speed up optimization")
    parser.add_argument("--num-runs", type=int, default=5,
                       help="Number of simulation runs per configuration")
    parser.add_argument("--optimize", action="store_true",
                       help="Run true optimization to find best blocking scenario automatically")
    parser.add_argument("--delivery-total-orders", type=int, default=None,
                       help="Override the total number of delivery orders in the simulation")
    
    args = parser.parse_args()
    init_logging(args.log_level)
    
    # Parse ranges
    bev_prob_list = [float(x.strip()) for x in args.bev_order_prob_range.split(",")]
    bev_carts_list = [int(x.strip()) for x in args.bev_carts_range.split(",")]
    runner_counts = [int(x.strip()) for x in args.runner_counts.split(",")]
    tee_scenarios = [x.strip() for x in args.tee_scenarios.split(",")]
    
    # Define delivery blocking scenarios (expanded from blocking optimization)
    delivery_blocking_scenarios = [
        {"name": "full_course", "description": "No blocking (full course)", "block_up_to_hole": 0, "block_holes_10_12": False},
        {"name": "block_to_hole3", "description": "Block holes 1-3", "block_up_to_hole": 3, "block_holes_10_12": False},
        {"name": "block_to_hole6", "description": "Block holes 1-6", "block_up_to_hole": 6, "block_holes_10_12": False},
        {"name": "block_holes_10_12", "description": "Block holes 10-12", "block_up_to_hole": 0, "block_holes_10_12": True},
        {"name": "block_holes_0_5", "description": "Block holes 1-5", "block_up_to_hole": 5, "block_holes_10_12": False},
        {"name": "block_holes_1_5_and_10_12", "description": "Block holes 1-5 AND 10-12", "block_up_to_hole": 5, "block_holes_10_12": True},
    ]
    
    # Create output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if args.sla_optimization:
        default_name = f"sla_optimization_{timestamp}"
    else:
        default_name = f"comprehensive_optimization_{timestamp}"
    output_root = Path(args.output_dir or (Path("outputs") / default_name))
    output_root.mkdir(parents=True, exist_ok=True)
    
    logger.info("Starting %s", "SLA optimization" if args.sla_optimization else "comprehensive optimization")
    logger.info("Output directory: %s", output_root)
    logger.info("Bev order probabilities to test: %s", bev_prob_list)
    logger.info("Bev carts to test: %s", bev_carts_list)
    logger.info("Runner counts to test: %s", runner_counts)
    logger.info("Tee scenarios to test: %s", tee_scenarios)
    logger.info("Delivery scenarios: %d", len(delivery_blocking_scenarios))
    if args.sla_optimization:
        logger.info("Target SLA: %.1f%%", args.target_sla * 100)
    if args.skip_coordinates:
        logger.info("Coordinate CSV generation disabled for speed")
    
    # Track results for SLA optimization
    sla_results = []
    
    # Backup original config
    backup_path = None
    
    try:
        for bev_prob in bev_prob_list:
            # Determine if we need to modify the config
            if args.delivery_total_orders is not None or not args.sla_optimization:
                # Backup and modify config with specified order count or default
                order_count = args.delivery_total_orders if args.delivery_total_orders is not None else 20
                backup_path = _backup_and_modify_config(args.course_dir, bev_prob, order_count)
                logger.info("Setting delivery_total_orders to %d", order_count)
            else:
                # Use existing config
                backup_path = None
            
            for num_carts in bev_carts_list:
                if args.skip_bev_carts:
                    continue
                    
                config_name = f"{int(bev_prob*100)}p_{num_carts}bevcarts"
                logger.info("Testing %s", config_name)
                
                # Create subdirectory for this configuration
                config_output = output_root / config_name
                config_output.mkdir(parents=True, exist_ok=True)
                
                # Run beverage cart simulations
                bev_cart_output = config_output / "bev_cart_only"
                try:
                    result = _run_unified_simulation(
                        mode="bev-carts",
                        num_carts=num_carts,
                        output_dir=str(bev_cart_output),
                        skip_coordinates=args.skip_coordinates,
                        num_runs=args.num_runs
                    )
                    if result != 0:
                        logger.warning("Beverage cart simulation failed for %s", config_name)
                except Exception as e:
                    logger.error("Failed to run bev-carts for %s: %s", config_name, e)
                
                # Run beverage cart with golfers
                bev_with_golfers_output = config_output / "bev_with_golfers"
                try:
                    result = _run_unified_simulation(
                        mode="bev-with-golfers",
                        output_dir=str(bev_with_golfers_output),
                        skip_coordinates=args.skip_coordinates,
                        num_runs=args.num_runs
                    )
                    if result != 0:
                        logger.warning("Bev-with-golfers simulation failed for %s", config_name)
                except Exception as e:
                    logger.error("Failed to run bev-with-golfers for %s: %s", config_name, e)
            
            # Run delivery simulations with different blocking scenarios and runner counts
            if not args.skip_delivery:
                for scenario in delivery_blocking_scenarios:
                    for num_runners in runner_counts:
                        for tee_scenario in tee_scenarios:
                            config_name = f"{int(bev_prob*100)}p_delivery_{scenario['name']}_{num_runners}runners_{tee_scenario}"
                            logger.info("Testing %s", config_name)
                            
                            # Create subdirectory for this configuration  
                            config_output = output_root / config_name
                            config_output.mkdir(parents=True, exist_ok=True)
                            
                            # Run with blocking parameters
                            try:
                                start_time = time.time()
                                result = _run_unified_simulation(
                                    mode="delivery-runner",
                                    num_runners=num_runners,
                                    tee_scenario=tee_scenario,
                                    block_up_to_hole=scenario['block_up_to_hole'],
                                    block_holes_10_12=scenario['block_holes_10_12'],
                                    output_dir=str(config_output),
                                    skip_coordinates=args.skip_coordinates,
                                    num_runs=args.num_runs
                                )
                                end_time = time.time()
                                
                                if result != 0:
                                    logger.warning("Delivery simulation failed for %s", config_name)
                                else:
                                    # For SLA optimization, collect metrics
                                    if args.sla_optimization:
                                        # Try to read metrics from the output
                                        try:
                                            metrics_file = config_output / "run_01" / "delivery_runner_metrics_run_01.json"
                                            if metrics_file.exists():
                                                with open(metrics_file, 'r') as f:
                                                    metrics = json.load(f)
                                                
                                                # Extract more metrics for comprehensive analysis
                                                sla_percentage = metrics.get('on_time_rate', 0)
                                                orders_delivered = metrics.get('successful_orders', 0)
                                                total_orders = metrics.get('total_orders', 0)
                                                failed_rate = metrics.get('failed_rate', 0)
                                                queue_wait_avg = metrics.get('queue_wait_avg', 0)
                                                delivery_cycle_time_avg = metrics.get('delivery_cycle_time_avg', 0)
                                                delivery_cycle_time_p90 = metrics.get('delivery_cycle_time_p90', 0)
                                                revenue_per_round = metrics.get('revenue_per_round', 0)
                                                runner_utilization = metrics.get('runner_utilization_driving_pct', 0)
                                                
                                                sla_results.append({
                                                    'scenario_name': scenario['name'],
                                                    'description': scenario['description'],
                                                    'num_runners': num_runners,
                                                    'tee_scenario': tee_scenario,
                                                    'sla_percentage': sla_percentage,
                                                    'orders_delivered': orders_delivered,
                                                    'total_orders': total_orders,
                                                    'failed_rate': failed_rate,
                                                    'queue_wait_avg': queue_wait_avg,
                                                    'delivery_cycle_time_avg': delivery_cycle_time_avg,
                                                    'delivery_cycle_time_p90': delivery_cycle_time_p90,
                                                    'revenue_per_round': revenue_per_round,
                                                    'runner_utilization': runner_utilization,
                                                    'duration_seconds': end_time - start_time,
                                                    'config_name': config_name
                                                })
                                        except Exception as e:
                                            logger.warning("Failed to read metrics for %s: %s", config_name, e)
                                
                                # Save scenario metadata
                                scenario_note = config_output / "blocking_scenario.json"
                                scenario_note.write_text(json.dumps(scenario, indent=2), encoding="utf-8")
                                    
                            except Exception as e:
                                logger.error("Failed to run delivery for %s: %s", config_name, e)
            
            # Restore config after each total_orders iteration (only if we backed it up)
            if backup_path and not args.sla_optimization:
                _restore_config(args.course_dir, backup_path)
    
    finally:
        # Ensure config is restored (only if we backed it up)
        if backup_path and not args.sla_optimization:
            _restore_config(args.course_dir, backup_path)
    
    # Create appropriate summary
    if args.sla_optimization and sla_results:
        # Create SLA-focused summary
        _create_sla_optimization_summary(output_root, sla_results, args.target_sla, 
                                       tee_scenarios[0] if len(tee_scenarios) == 1 else "multiple", 
                                       runner_counts[0] if len(runner_counts) == 1 else "multiple")
        
        # If optimize flag is set, find the best blocking scenario and save as a separate file
        if args.optimize and sla_results:
            # Group results by runner count and tee scenario
            by_config = {}
            for result in sla_results:
                key = (result['num_runners'], result['tee_scenario'])
                if key not in by_config:
                    by_config[key] = []
                by_config[key].append(result)
            
            # For each configuration, find the best scenario
            optimization_results = []
            for (runners, tee), results in by_config.items():
                # Sort by multiple metrics: SLA %, revenue, and failed rate (inverse)
                sorted_results = sorted(results, 
                                        key=lambda x: (x.get('sla_percentage', 0), 
                                                     x.get('revenue_per_round', 0), 
                                                     -x.get('failed_rate', 1)), 
                                        reverse=True)
                
                if sorted_results:
                    best = sorted_results[0]
                    optimization_results.append({
                        'runners': runners,
                        'tee_scenario': tee,
                        'best_scenario': best['scenario_name'],
                        'description': best['description'],
                        'sla_percentage': best['sla_percentage'],
                        'revenue_per_round': best.get('revenue_per_round', 0),
                        'failed_rate': best.get('failed_rate', 0)
                    })
            
            # Save optimization results
            opt_path = output_root / "optimization_results.json"
            with open(opt_path, 'w', encoding='utf-8') as f:
                json.dump(optimization_results, f, indent=2)
            logger.info("Saved optimization results to: %s", opt_path)
    else:
        # Create comprehensive summary
        _create_run_summary(output_root, bev_prob_list, bev_carts_list, delivery_blocking_scenarios, 
                          runner_counts, tee_scenarios)
    
    logger.info("Optimization complete!")
    logger.info("Results saved to: %s", output_root)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
