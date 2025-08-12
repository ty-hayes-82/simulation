"""
Phase 6 simulation runner with metrics: Delivery staff + one golfer group.

This script runs delivery runner simulations and calculates comprehensive metrics
for Clubhouse delivery (1-2 runners) scenarios, including all the prioritized metrics
requested for delivery runner only simulations.
"""

from __future__ import annotations

import argparse
import json
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

from golfsim.logging import get_logger, init_logging
from golfsim.simulation.engine import run_golf_delivery_simulation
from golfsim.simulation.services import run_multi_golfer_simulation
from golfsim.config.loaders import load_simulation_config
from golfsim.io.results import save_results_bundle
from golfsim.analysis.delivery_runner_metrics import (
    calculate_delivery_runner_metrics,
    summarize_delivery_runner_metrics,
    format_delivery_runner_metrics_report,
    format_delivery_runner_summary_report,
    DeliveryRunnerMetrics,
)
from golfsim.viz.matplotlib_viz import (
    load_course_geospatial_data,
    render_delivery_plot,
)

# Ensure project root is on sys.path for `utils` imports when running via python path/to/script.py
import sys
from pathlib import Path as _P
sys.path.append(str(_P(__file__).parent.parent.parent.parent))

from utils import setup_encoding, add_log_level_argument, add_course_dir_argument
from utils.simulation_reporting import (
    log_simulation_results,
    write_simulation_stats,
    write_multi_run_summary,
    handle_simulation_error,
    create_argparse_epilog,
)


logger = get_logger(__name__)


def format_time_from_seconds(seconds: float) -> str:
    """Convert seconds to HH:MM:SS format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def create_delivery_metrics_log(metrics: DeliveryRunnerMetrics, run_idx: int, save_path: Path) -> None:
    """
    Create a detailed delivery metrics log with all calculated metrics.
    
    Args:
        metrics: DeliveryRunnerMetrics object
        run_idx: Run index for identification
        save_path: Path where to save the metrics log
    """
    report = format_delivery_runner_metrics_report(metrics)
    
    # Save the report
    metrics_file = save_path / f"delivery_metrics_run_{run_idx:02d}.md"
    with open(metrics_file, 'w', encoding='utf-8') as f:
        f.write(report)
    
    logger.info("Saved delivery metrics report: %s", metrics_file)


def _write_metrics_json(metrics: DeliveryRunnerMetrics, run_idx: int, output_dir: Path) -> None:
    """Write metrics data to JSON file for programmatic access."""
    metrics_file = output_dir / f"delivery_metrics_run_{run_idx:02d}.json"
    
    # Convert dataclass to dict for JSON serialization
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
    
    with open(metrics_file, 'w', encoding='utf-8') as f:
        json.dump(metrics_dict, f, indent=2, ensure_ascii=False)
    
    logger.info("Saved metrics JSON: %s", metrics_file)


def _write_stats_md(results: Dict, metrics: DeliveryRunnerMetrics, run_idx: int, output_dir: Path) -> None:
    """Write enhanced stats markdown with key metrics."""
    stats_file = output_dir / f"stats_run_{run_idx:02d}.md"
    
    # Extract key timing data
    order_time_s = results.get('order_time_s', 0)
    order_created_s = results.get('order_created_s', order_time_s)
    prep_completed_s = results.get('prep_completed_s', 0)
    delivered_s = results.get('delivered_s', 0)
    runner_returned_s = results.get('runner_returned_s', 0)
    
    # Calculate derived times
    prep_duration = prep_completed_s - order_created_s
    delivery_duration = delivered_s - prep_completed_s
    return_duration = runner_returned_s - delivered_s
    total_service_time = results.get('total_service_time_s', 0)
    
    # Get delivery details
    order_hole = results.get('order_hole', 'Unknown')
    delivery_distance = results.get('delivery_distance_m', 0)
    prediction_method = results.get('prediction_method', 'Unknown')
    
    content = f"""# Delivery Simulation Results - Run {run_idx:02d}

## Order Details
- **Hole**: {order_hole}
- **Prediction Method**: {prediction_method}
- **Total Service Time**: {format_time_from_seconds(total_service_time)}
- **Delivery Distance**: {delivery_distance:.0f} meters

## Key Metrics
- **Revenue per Round (RPR)**: ${metrics.revenue_per_round:.2f}
- **Order Penetration Rate**: {metrics.order_penetration_rate:.1%}
- **Average Order Value (AOV)**: ${metrics.average_order_value:.2f}
- **Orders per Runner-Hour**: {metrics.orders_per_runner_hour:.2f}
- **On-Time Rate**: {metrics.on_time_rate:.1%}
- **Failed Rate**: {metrics.failed_rate:.1%}

## Timeline
- **Order Placed**: {format_time_from_seconds(order_time_s)}
- **Order Created**: {format_time_from_seconds(order_created_s)}
- **Prep Started**: {format_time_from_seconds(order_created_s)}
- **Prep Completed**: {format_time_from_seconds(prep_completed_s)} ({prep_duration/60:.1f} min)
- **Delivery Started**: {format_time_from_seconds(prep_completed_s)}
- **Delivered**: {format_time_from_seconds(delivered_s)} ({delivery_duration/60:.1f} min)
- **Runner Returned**: {format_time_from_seconds(runner_returned_s)} ({return_duration/60:.1f} min)

## Service Quality
- **Delivery Cycle Time (P50)**: {metrics.delivery_cycle_time_p50:.1f} minutes
- **Delivery Cycle Time (P90)**: {metrics.delivery_cycle_time_p90:.1f} minutes
- **Dispatch Delay (Avg)**: {metrics.dispatch_delay_avg:.1f} minutes
- **Travel Time (Avg)**: {metrics.travel_time_avg:.1f} minutes

## Operational Metrics
- **Runner Utilization - Driving**: {metrics.runner_utilization_driving_pct:.1f}%
- **Runner Utilization - Waiting**: {metrics.runner_utilization_waiting_pct:.1f}%
- **Runner Utilization - Handoff**: {metrics.runner_utilization_handoff_pct:.1f}%
- **Runner Utilization - Deadhead**: {metrics.runner_utilization_deadhead_pct:.1f}%
- **Distance per Delivery (Avg)**: {metrics.distance_per_delivery_avg:.0f} meters
- **Queue Depth (Avg)**: {metrics.queue_depth_avg:.1f} orders
- **Capacity per 15-min Window**: {metrics.capacity_15min_window} orders

## Financial Analysis
- **Second Runner Break-Even**: {metrics.second_runner_break_even_orders:.1f} orders

## Zone Service Times
"""
    
    # Add zone service times
    for zone, service_time in metrics.zone_service_times.items():
        content += f"- **{zone}**: {service_time:.1f} minutes\n"
    
    with open(stats_file, 'w', encoding='utf-8') as f:
        f.write(content)
    
    logger.info("Saved enhanced stats: %s", stats_file)


def run_once(
    course_dir: str,
    run_idx: int,
    output_dir: Path,
    order_hole: Optional[int] = None,
    prep_time_min: int = 10,
    runner_speed_mps: float = 6.0,
    revenue_per_order: float = 25.0,
    sla_minutes: int = 30,
    service_hours: float = 10.0,
) -> Dict:
    """Run a single delivery simulation with metrics calculation."""
    
    logger.info("Starting delivery simulation run %d", run_idx)
    
    try:
        # Run the delivery simulation
        results = run_golf_delivery_simulation(
            course_dir=course_dir,
            order_hole=order_hole,
            prep_time_min=prep_time_min,
            runner_speed_mps=runner_speed_mps,
            track_coordinates=True,
        )
        
        # Extract data for metrics calculation
        delivery_stats = results.get('delivery_stats', [])
        activity_log = results.get('activity_log', [])
        orders = results.get('orders', [])
        failed_orders = results.get('failed_orders', [])
        
        # If no delivery_stats (single order simulation), create mock data
        if not delivery_stats and results.get('total_service_time_s'):
            # Create mock delivery stats from single order results
            mock_delivery_stats = [{
                'order_id': results.get('order_id', '001'),
                'golfer_group_id': 1,
                'hole_num': results.get('order_hole', 1),
                'order_time_s': results.get('order_time_s', 0),
                'queue_delay_s': 0,
                'prep_time_s': results.get('prep_time_s', prep_time_min * 60),
                'delivery_time_s': results.get('delivery_travel_time_s', 0) / 2,  # One way
                'return_time_s': results.get('delivery_travel_time_s', 0) / 2,  # Return
                'total_drive_time_s': results.get('delivery_travel_time_s', 0),
                'delivery_distance_m': results.get('delivery_distance_m', 0) / 2,  # One way
                'total_completion_time_s': results.get('total_service_time_s', 0),
                'delivered_at_time_s': results.get('delivered_s', 0),
            }]
            delivery_stats = mock_delivery_stats
            
            # Create mock orders list
            mock_orders = [{
                'order_id': results.get('order_id', '001'),
                'golfer_group_id': 1,
                'golfer_id': 'G1',
                'hole_num': results.get('order_hole', 1),
                'order_time_s': results.get('order_time_s', 0),
                'status': 'processed',
                'total_completion_time_s': results.get('total_service_time_s', 0),
            }]
            orders = mock_orders
        
        # Calculate delivery runner metrics
        metrics = calculate_delivery_runner_metrics(
            delivery_stats=delivery_stats,
            activity_log=activity_log,
            orders=orders,
            failed_orders=failed_orders,
            revenue_per_order=revenue_per_order,
            sla_minutes=sla_minutes,
            simulation_id=f"delivery_run_{run_idx:02d}",
            runner_id="runner_1",
            service_hours=service_hours,
        )
        
        # Save results
        results['delivery_metrics'] = metrics
        results['run_idx'] = run_idx
        
        # Create output files
        run_output_dir = output_dir / f"run_{run_idx:02d}"
        run_output_dir.mkdir(parents=True, exist_ok=True)
        
        # Save raw results
        results_file = run_output_dir / "results.json"
        with open(results_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False, default=str)
        
        # Save metrics
        _write_metrics_json(metrics, run_idx, run_output_dir)
        create_delivery_metrics_log(metrics, run_idx, run_output_dir)
        _write_stats_md(results, metrics, run_idx, run_output_dir)
        
        # Create visualization if coordinates are available
        if results.get('golfer_coordinates') and results.get('runner_coordinates'):
            try:
                from golfsim.viz.matplotlib_viz import render_delivery_plot
                from golfsim.viz.matplotlib_viz import load_course_geospatial_data
                import networkx as nx
                
                # Load course data for visualization
                sim_cfg = load_simulation_config(course_dir)
                clubhouse_coords = sim_cfg.clubhouse
                course_data = load_course_geospatial_data(course_dir)
                
                # Try to load cart graph
                cart_graph = None
                cart_graph_path = Path(course_dir) / "pkl" / "cart_graph.pkl"
                if cart_graph_path.exists():
                    import pickle
                    with open(cart_graph_path, "rb") as f:
                        cart_graph = pickle.load(f)
                
                # Create visualization
                viz_path = run_output_dir / "delivery_map.png"
                render_delivery_plot(
                    results=results,
                    course_data=course_data,
                    clubhouse_coords=clubhouse_coords,
                    cart_graph=cart_graph,
                    save_path=viz_path,
                    style="detailed"
                )
                
                logger.info("Created delivery visualization: %s", viz_path)
                results["visualization_path"] = str(viz_path)
                
            except Exception as e:
                logger.warning("Failed to create visualization: %s", e)
                results["visualization_error"] = str(e)
        
        logger.info("Completed delivery simulation run %d", run_idx)
        return results
        
    except Exception as e:
        logger.error("Error in delivery simulation run %d: %s", run_idx, e)
        return {
            'success': False,
            'error': str(e),
            'run_idx': run_idx,
        }


def write_summary_md(all_runs: List[Dict], output_dir: Path, title: str) -> None:
    """Write comprehensive summary with delivery runner metrics."""
    
    # Extract successful runs with metrics
    successful_runs = [run for run in all_runs if run.get('success', False) and 'delivery_metrics' in run]
    
    if not successful_runs:
        logger.warning("No successful runs with metrics found for summary")
        return
    
    # Extract metrics from successful runs
    metrics_list = [run['delivery_metrics'] for run in successful_runs]
    
    # Calculate summary statistics
    summaries = summarize_delivery_runner_metrics(metrics_list)
    
    # Generate summary report
    summary_report = format_delivery_runner_summary_report(summaries, len(successful_runs))
    
    # Add run details
    summary_report += f"""

## Run Details
- **Total Runs**: {len(all_runs)}
- **Successful Runs**: {len(successful_runs)}
- **Failed Runs**: {len(all_runs) - len(successful_runs)}

## Individual Run Results
"""
    
    for i, run in enumerate(all_runs):
        if run.get('success', False) and 'delivery_metrics' in run:
            metrics = run['delivery_metrics']
            summary_report += f"""
### Run {i+1:02d}
- **RPR**: ${metrics.revenue_per_round:.2f}
- **Order Penetration Rate**: {metrics.order_penetration_rate:.1%}
- **AOV**: ${metrics.average_order_value:.2f}
- **Orders per Runner-Hour**: {metrics.orders_per_runner_hour:.2f}
- **On-Time Rate**: {metrics.on_time_rate:.1%}
- **Failed Rate**: {metrics.failed_rate:.1%}
"""
        else:
            summary_report += f"""
### Run {i+1:02d}
- **Status**: Failed
- **Error**: {run.get('error', 'Unknown error')}
"""
    
    # Save summary
    summary_file = output_dir / "comprehensive_delivery_metrics_summary.md"
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write(summary_report)
    
    logger.info("Saved comprehensive delivery metrics summary: %s", summary_file)


def main():
    """Main function to run delivery runner simulations with metrics."""
    parser = argparse.ArgumentParser(
        description="Run delivery runner simulations with comprehensive metrics",
        epilog=create_argparse_epilog([]),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    add_course_dir_argument(parser)
    add_log_level_argument(parser)
    
    parser.add_argument("--num-runs", type=int, default=10, help="Number of simulation runs (default: 10)")
    parser.add_argument("--order-hole", type=int, help="Specific hole to place order (1-18), or random if not specified")
    parser.add_argument("--prep-time", type=int, default=10, help="Food preparation time in minutes (default: 10)")
    parser.add_argument("--runner-speed", type=float, default=6.0, help="Runner speed in m/s (default: 6.0)")
    parser.add_argument("--revenue-per-order", type=float, default=25.0, help="Revenue per successful order (default: 25.0)")
    parser.add_argument("--sla-minutes", type=int, default=30, help="Service level agreement time in minutes (default: 30)")
    parser.add_argument("--service-hours", type=float, default=10.0, help="Active service hours for runner (default: 10.0)")
    parser.add_argument("--output-dir", type=str, default="outputs/delivery_runner_phase6_with_metrics", help="Output directory")
    
    args = parser.parse_args()
    
    # Setup
    setup_encoding()
    init_logging(args.log_level)
    
    course_dir = args.course_dir
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info("Starting delivery runner simulations with metrics")
    logger.info("Course: %s", course_dir)
    logger.info("Output directory: %s", output_dir)
    logger.info("Number of runs: %d", args.num_runs)
    
    # Run simulations
    all_runs = []
    
    for run_idx in range(1, args.num_runs + 1):
        results = run_once(
            course_dir=course_dir,
            run_idx=run_idx,
            output_dir=output_dir,
            order_hole=args.order_hole,
            prep_time_min=args.prep_time,
            runner_speed_mps=args.runner_speed,
            revenue_per_order=args.revenue_per_order,
            sla_minutes=args.sla_minutes,
            service_hours=args.service_hours,
        )
        all_runs.append(results)
    
    # Write comprehensive summary
    write_summary_md(all_runs, output_dir, "Phase 6 — Delivery Runner with Metrics")
    
    # Write traditional summary
    write_multi_run_summary(all_runs, output_dir, "Phase 6 — Delivery Runner with Metrics")
    
    logger.info("Completed all delivery runner simulations with metrics")
    logger.info("Results saved to: %s", output_dir)


if __name__ == "__main__":
    main()
