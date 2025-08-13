"""
Delivery Runner Metrics Analysis Script

This script analyzes existing delivery runner simulation output directories
and calculates comprehensive metrics for delivery runner only simulations
with Clubhouse delivery (1-2 runners) context.
"""

from __future__ import annotations

import argparse
import json
import csv
from pathlib import Path
from typing import Any, Dict, List, Optional

from golfsim.logging import get_logger, init_logging
from golfsim.analysis.delivery_runner_metrics import (
    calculate_delivery_runner_metrics,
    summarize_delivery_runner_metrics,
    format_delivery_runner_metrics_report,
    format_delivery_runner_summary_report,
    DeliveryRunnerMetrics,
)

# Ensure project root is on sys.path for `utils` imports when running via python path/to/script.py
import sys
from pathlib import Path as _P
sys.path.append(str(_P(__file__).parent.parent.parent.parent))

from utils import setup_encoding, add_log_level_argument
from utils.simulation_reporting import create_argparse_epilog


logger = get_logger(__name__)


def load_delivery_stats_data(file_path: Path) -> List[Dict[str, Any]]:
    """Load delivery statistics data from various file formats."""
    if not file_path.exists():
        logger.warning("File not found: %s", file_path)
        return []
    
    try:
        if file_path.suffix.lower() == '.json':
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Handle nested structures
                if isinstance(data, dict):
                    return data.get('delivery_stats', [])
                elif isinstance(data, list):
                    return data
                else:
                    return []
        elif file_path.suffix.lower() == '.csv':
            delivery_stats = []
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Convert string values to appropriate types
                    converted_row = {}
                    for key, value in row.items():
                        if key in ['order_id', 'golfer_group_id', 'hole_num', 'capacity_15min_window']:
                            try:
                                converted_row[key] = int(value) if value else 0
                            except ValueError:
                                converted_row[key] = 0
                        elif key in ['order_time_s', 'queue_delay_s', 'prep_time_s', 'delivery_time_s', 
                                   'return_time_s', 'total_drive_time_s', 'delivery_distance_m', 
                                   'total_completion_time_s', 'delivered_at_time_s']:
                            try:
                                converted_row[key] = float(value) if value else 0.0
                            except ValueError:
                                converted_row[key] = 0.0
                        else:
                            converted_row[key] = value
                    delivery_stats.append(converted_row)
            return delivery_stats
        else:
            logger.warning("Unsupported file format: %s", file_path.suffix)
            return []
    except Exception as e:
        logger.error("Error loading delivery stats from %s: %s", file_path, e)
        return []


def load_activity_log_data(file_path: Path) -> List[Dict[str, Any]]:
    """Load activity log data from various file formats."""
    if not file_path.exists():
        logger.warning("File not found: %s", file_path)
        return []
    
    try:
        if file_path.suffix.lower() == '.json':
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Handle nested structures
                if isinstance(data, dict):
                    return data.get('activity_log', [])
                elif isinstance(data, list):
                    return data
                else:
                    return []
        elif file_path.suffix.lower() == '.csv':
            activity_log = []
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Convert string values to appropriate types
                    converted_row = {}
                    for key, value in row.items():
                        if key in ['timestamp_s']:
                            try:
                                converted_row[key] = int(value) if value else 0
                            except ValueError:
                                converted_row[key] = 0
                        else:
                            converted_row[key] = value
                    activity_log.append(converted_row)
            return activity_log
        else:
            logger.warning("Unsupported file format: %s", file_path.suffix)
            return []
    except Exception as e:
        logger.error("Error loading activity log from %s: %s", file_path, e)
        return []


def load_orders_data(file_path: Path) -> List[Dict[str, Any]]:
    """Load orders data from various file formats."""
    if not file_path.exists():
        logger.warning("File not found: %s", file_path)
        return []
    
    try:
        if file_path.suffix.lower() == '.json':
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Handle nested structures
                if isinstance(data, dict):
                    return data.get('orders', [])
                elif isinstance(data, list):
                    return data
                else:
                    return []
        elif file_path.suffix.lower() == '.csv':
            orders = []
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Convert string values to appropriate types
                    converted_row = {}
                    for key, value in row.items():
                        if key in ['golfer_group_id', 'hole_num', 'total_orders', 'successful_orders', 'failed_orders']:
                            try:
                                converted_row[key] = int(value) if value else 0
                            except ValueError:
                                converted_row[key] = 0
                        elif key in ['order_time_s', 'total_completion_time_s']:
                            try:
                                converted_row[key] = float(value) if value else 0.0
                            except ValueError:
                                converted_row[key] = 0.0
                        else:
                            converted_row[key] = value
                    orders.append(converted_row)
            return orders
        else:
            logger.warning("Unsupported file format: %s", file_path.suffix)
            return []
    except Exception as e:
        logger.error("Error loading orders from %s: %s", file_path, e)
        return []


def load_failed_orders_data(file_path: Path) -> List[Dict[str, Any]]:
    """Load failed orders data from various file formats."""
    if not file_path.exists():
        logger.warning("File not found: %s", file_path)
        return []
    
    try:
        if file_path.suffix.lower() == '.json':
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Handle nested structures
                if isinstance(data, dict):
                    return data.get('failed_orders', [])
                elif isinstance(data, list):
                    return data
                else:
                    return []
        elif file_path.suffix.lower() == '.csv':
            failed_orders = []
            with open(file_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    failed_orders.append(row)
            return failed_orders
        else:
            logger.warning("Unsupported file format: %s", file_path.suffix)
            return []
    except Exception as e:
        logger.error("Error loading failed orders from %s: %s", file_path, e)
        return []


def analyze_single_simulation(simulation_dir: Path, **kwargs) -> Optional[DeliveryRunnerMetrics]:
    """Analyze a single simulation directory and calculate metrics."""
    
    logger.info("Analyzing simulation directory: %s", simulation_dir)
    
    # Look for data files in various locations and formats
    delivery_stats = []
    activity_log = []
    orders = []
    failed_orders = []
    
    # Search for delivery stats
    delivery_stats_candidates = [
        simulation_dir / "delivery_stats.json",
        simulation_dir / "delivery_stats.csv",
        simulation_dir / "results.json",
        simulation_dir / "stats.json",
    ]
    
    for candidate in delivery_stats_candidates:
        if candidate.exists():
            delivery_stats = load_delivery_stats_data(candidate)
            if delivery_stats:
                logger.info("Found delivery stats in: %s", candidate)
                break
    
    # Search for activity log
    activity_log_candidates = [
        simulation_dir / "activity_log.json",
        simulation_dir / "activity_log.csv",
        simulation_dir / "results.json",
        simulation_dir / "log.json",
    ]
    
    for candidate in activity_log_candidates:
        if candidate.exists():
            activity_log = load_activity_log_data(candidate)
            if activity_log:
                logger.info("Found activity log in: %s", candidate)
                break
    
    # Search for orders
    orders_candidates = [
        simulation_dir / "orders.json",
        simulation_dir / "orders.csv",
        simulation_dir / "results.json",
        simulation_dir / "data.json",
    ]
    
    for candidate in orders_candidates:
        if candidate.exists():
            orders = load_orders_data(candidate)
            if orders:
                logger.info("Found orders in: %s", candidate)
                break
    
    # Search for failed orders
    failed_orders_candidates = [
        simulation_dir / "failed_orders.json",
        simulation_dir / "failed_orders.csv",
        simulation_dir / "results.json",
        simulation_dir / "errors.json",
    ]
    
    for candidate in failed_orders_candidates:
        if candidate.exists():
            failed_orders = load_failed_orders_data(candidate)
            if failed_orders:
                logger.info("Found failed orders in: %s", candidate)
                break
    
    # If no data found, try to extract from results.json
    if not any([delivery_stats, activity_log, orders, failed_orders]):
        results_file = simulation_dir / "results.json"
        if results_file.exists():
            try:
                with open(results_file, 'r', encoding='utf-8') as f:
                    results = json.load(f)
                
                delivery_stats = results.get('delivery_stats', [])
                activity_log = results.get('activity_log', [])
                orders = results.get('orders', [])
                failed_orders = results.get('failed_orders', [])
                
                logger.info("Extracted data from results.json")
            except Exception as e:
                logger.error("Error loading results.json: %s", e)
    
    # Calculate metrics if we have sufficient data
    if delivery_stats or orders:
        try:
            metrics = calculate_delivery_runner_metrics(
                delivery_stats=delivery_stats,
                activity_log=activity_log,
                orders=orders,
                failed_orders=failed_orders,
                simulation_id=simulation_dir.name,
                **kwargs
            )
            logger.info("Successfully calculated metrics for: %s", simulation_dir.name)
            return metrics
        except Exception as e:
            logger.error("Error calculating metrics for %s: %s", simulation_dir.name, e)
            return None
    else:
        logger.warning("No sufficient data found in: %s", simulation_dir)
        return None


def analyze_multiple_simulations(
    root_dir: Path,
    output_dir: Path,
    **kwargs
) -> List[DeliveryRunnerMetrics]:
    """Analyze multiple simulation directories and calculate metrics."""
    
    logger.info("Analyzing multiple simulations in: %s", root_dir)
    
    metrics_list = []
    
    # Find simulation directories
    simulation_dirs = []
    
    # Look for run_XX directories
    for item in root_dir.iterdir():
        if item.is_dir() and item.name.startswith('run_'):
            simulation_dirs.append(item)
    
    # If no run_XX directories, look for other simulation directories
    if not simulation_dirs:
        for item in root_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.'):
                # Check if it contains simulation data
                if any([
                    (item / "results.json").exists(),
                    (item / "delivery_stats.json").exists(),
                    (item / "activity_log.json").exists(),
                    (item / "orders.json").exists(),
                ]):
                    simulation_dirs.append(item)
    
    if not simulation_dirs:
        logger.warning("No simulation directories found in: %s", root_dir)
        return []
    
    logger.info("Found %d simulation directories", len(simulation_dirs))
    
    # Analyze each simulation
    for simulation_dir in sorted(simulation_dirs):
        metrics = analyze_single_simulation(simulation_dir, **kwargs)
        if metrics:
            metrics_list.append(metrics)
    
    # Generate summary if we have metrics
    if metrics_list:
        summaries = summarize_delivery_runner_metrics(metrics_list)
        
        # Save summary report
        summary_report = format_delivery_runner_summary_report(summaries, len(metrics_list))
        summary_file = output_dir / "delivery_runner_metrics_summary.md"
        
        with open(summary_file, 'w', encoding='utf-8') as f:
            f.write(summary_report)
        
        logger.info("Saved summary report: %s", summary_file)
        
        # Save individual metrics reports
        for i, metrics in enumerate(metrics_list):
            report = format_delivery_runner_metrics_report(metrics)
            report_file = output_dir / f"delivery_metrics_{i+1:02d}_{metrics.simulation_id}.md"
            
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(report)
            
            # Also save as JSON
            metrics_dict = {
                'revenue_per_round': metrics.revenue_per_round,
                'order_penetration_rate': metrics.order_penetration_rate,
                'average_order_value': metrics.average_order_value,
                'orders_per_runner_hour': metrics.orders_per_runner_hour,
                'on_time_rate': metrics.on_time_rate,
                'delivery_cycle_time_p50': metrics.delivery_cycle_time_p50,
                'delivery_cycle_time_p90': metrics.delivery_cycle_time_p90,
                'dispatch_delay_avg': metrics.dispatch_delay_avg,
                'travel_time_avg': metrics.travel_time_avg,
                'failed_rate': metrics.failed_rate,
                'runner_utilization_driving_pct': metrics.runner_utilization_driving_pct,
                'runner_utilization_waiting_pct': metrics.runner_utilization_waiting_pct,
                'runner_utilization_handoff_pct': metrics.runner_utilization_handoff_pct,
                'runner_utilization_deadhead_pct': metrics.runner_utilization_deadhead_pct,
                'distance_per_delivery_avg': metrics.distance_per_delivery_avg,
                'queue_depth_avg': metrics.queue_depth_avg,
                'queue_wait_avg': metrics.queue_wait_avg,
                'capacity_15min_window': metrics.capacity_15min_window,
                'second_runner_break_even_orders': metrics.second_runner_break_even_orders,
                'zone_service_times': metrics.zone_service_times,
                'total_revenue': metrics.total_revenue,
                'total_orders': metrics.total_orders,
                'successful_orders': metrics.successful_orders,
                'failed_orders': metrics.failed_orders,
                'total_rounds': metrics.total_rounds,
                'active_runner_hours': metrics.active_runner_hours,
                'simulation_id': metrics.simulation_id,
                'runner_id': metrics.runner_id,
            }
            
            json_file = output_dir / f"delivery_metrics_{i+1:02d}_{metrics.simulation_id}.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(metrics_dict, f, indent=2, ensure_ascii=False)
    
    logger.info("Completed analysis of %d simulations", len(metrics_list))
    return metrics_list


def main():
    """Main function to analyze delivery runner simulation results."""
    parser = argparse.ArgumentParser(
        description="Analyze delivery runner simulation results and calculate comprehensive metrics",
        epilog=create_argparse_epilog([]),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    add_log_level_argument(parser)
    
    parser.add_argument("input_dir", help="Input directory containing simulation results")
    parser.add_argument("--output-dir", type=str, default="outputs/delivery_runner_analysis", help="Output directory for analysis results")
    parser.add_argument("--revenue-per-order", type=float, default=25.0, help="Revenue per successful order (default: 25.0)")
    parser.add_argument("--sla-minutes", type=int, default=30, help="Service level agreement time in minutes (default: 30)")
    parser.add_argument("--service-hours", type=float, default=10.0, help="Active service hours for runner (default: 10.0)")
    
    args = parser.parse_args()
    
    # Setup
    setup_encoding()
    init_logging(args.log_level)
    
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if not input_dir.exists():
        logger.error("Input directory does not exist: %s", input_dir)
        return
    
    logger.info("Starting delivery runner metrics analysis")
    logger.info("Input directory: %s", input_dir)
    logger.info("Output directory: %s", output_dir)
    
    # Analyze simulations
    metrics_list = analyze_multiple_simulations(
        root_dir=input_dir,
        output_dir=output_dir,
        revenue_per_order=args.revenue_per_order,
        sla_minutes=args.sla_minutes,
        service_hours=args.service_hours,
    )
    
    if metrics_list:
        logger.info("Successfully analyzed %d simulations", len(metrics_list))
        logger.info("Results saved to: %s", output_dir)
    else:
        logger.warning("No valid simulation data found for analysis")


if __name__ == "__main__":
    main()
