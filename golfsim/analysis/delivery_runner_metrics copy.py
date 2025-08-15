"""
Delivery Runner Metrics Analysis Module

This module provides comprehensive metrics calculation for delivery runner simulations,
specifically designed for Clubhouse delivery (1-2 runners) scenarios.

The metrics include:
- RPR (Revenue per round)
- Order penetration rate
- AOV (Average order value)
- Orders per runner-hour
- On-time rate vs promised ETA
- Delivery cycle time (p50/p90)
- Dispatch delay
- Travel time
- Failed rate
- Runner utilization mix
- Distance per delivery by hole/zone
- Queue depth & wait at kitchen
- Capacity per 15-min window before SLA breach
- Second-runner break-even analysis
- Zone heatmap from clubhouse
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ..logging import get_logger

logger = get_logger(__name__)


@dataclass
class DeliveryRunnerMetrics:
    """Comprehensive metrics for delivery runner simulations."""
    
    # Core business metrics
    revenue_per_round: float
    order_penetration_rate: float
    average_order_value: float
    orders_per_runner_hour: float
    
    # Service quality metrics
    on_time_rate: float
    delivery_cycle_time_p50: float
    delivery_cycle_time_p90: float
    dispatch_delay_avg: float
    travel_time_avg: float
    failed_rate: float
    
    # Operational metrics
    runner_utilization_driving_pct: float
    runner_utilization_waiting_pct: float
    
    # Distance and capacity metrics
    distance_per_delivery_avg: float
    queue_depth_avg: float
    queue_wait_avg: float
    capacity_15min_window: int
    
    # Financial analysis
    second_runner_break_even_orders: float
    
    # Zone analysis
    zone_service_times: Dict[str, float]  # hole/zone -> avg service time
    
    # Raw data for analysis
    total_revenue: float
    total_orders: int
    successful_orders: int
    failed_orders: int
    total_rounds: int
    active_runner_hours: float
    simulation_id: str
    runner_id: str
    # Per-runner utilization breakdown (percentages)
    runner_utilization_by_runner: Dict[str, Dict[str, float]] | None = None


def calculate_delivery_runner_metrics(
    delivery_stats: List[Dict[str, Any]],
    activity_log: List[Dict[str, Any]],
    orders: List[Dict[str, Any]],
    failed_orders: List[Dict[str, Any]],
    revenue_per_order: float = 25.0,
    sla_minutes: int = 30,
    simulation_id: str = "unknown",
    runner_id: str = "runner_1",
    service_hours: float = 10.0,
) -> DeliveryRunnerMetrics:
    """
    Calculate comprehensive delivery runner metrics from simulation data.
    
    Args:
        delivery_stats: List of successful delivery statistics
        activity_log: Detailed activity log from simulation
        orders: List of all orders (successful and failed)
        failed_orders: List of failed orders
        revenue_per_order: Revenue per successful order
        sla_minutes: Service level agreement time in minutes
        simulation_id: Identifier for this simulation
        runner_id: Identifier for the runner
        service_hours: Active service hours for the runner
        
    Returns:
        DeliveryRunnerMetrics object with all calculated metrics
    """
    
    # Basic counts
    total_orders = len(orders)
    successful_orders = len(delivery_stats)
    failed_orders_count = len(failed_orders)
    total_rounds = _extract_total_rounds(orders, activity_log)
    
    # Revenue calculations
    total_revenue = successful_orders * revenue_per_order
    revenue_per_round = total_revenue / max(total_rounds, 1)
    average_order_value = total_revenue / max(successful_orders, 1)
    
    # Order penetration rate
    order_penetration_rate = total_orders / max(total_rounds, 1)
    
    # Orders per runner-hour
    orders_per_runner_hour = successful_orders / max(service_hours, 0.1)
    
    # Service quality metrics
    on_time_rate = _calculate_on_time_rate(delivery_stats, sla_minutes)
    delivery_cycle_times = [d.get('total_completion_time_s', 0) / 60 for d in delivery_stats]
    delivery_cycle_time_p50 = statistics.median(delivery_cycle_times) if delivery_cycle_times else 0
    delivery_cycle_time_p90 = statistics.quantiles(delivery_cycle_times, n=10)[8] if len(delivery_cycle_times) >= 10 else max(delivery_cycle_times) if delivery_cycle_times else 0
    
    # Timing metrics
    dispatch_delays = [d.get('queue_delay_s', 0) / 60 for d in delivery_stats]
    dispatch_delay_avg = statistics.mean(dispatch_delays) if dispatch_delays else 0
    
    travel_times = [d.get('delivery_time_s', 0) / 60 for d in delivery_stats]
    travel_time_avg = statistics.mean(travel_times) if travel_times else 0
    
    # Failure rate
    failed_rate = failed_orders_count / max(total_orders, 1)
    
    # Runner utilization analysis
    utilization_mix = _calculate_runner_utilization(activity_log, service_hours)
    utilization_by_runner = _calculate_runner_utilization_by_runner(activity_log, service_hours)
    
    # Distance metrics
    distances = [d.get('delivery_distance_m', 0) for d in delivery_stats]
    distance_per_delivery_avg = statistics.mean(distances) if distances else 0
    
    # Queue analysis
    queue_metrics = _calculate_queue_metrics(activity_log)
    
    # Capacity analysis
    capacity_15min_window = _calculate_capacity_15min_window(orders, sla_minutes)
    
    # Second runner break-even analysis
    second_runner_break_even_orders = _calculate_second_runner_break_even(
        total_revenue, successful_orders, service_hours
    )
    
    # Zone heatmap analysis
    zone_service_times = _calculate_zone_service_times(delivery_stats)
    
    return DeliveryRunnerMetrics(
        revenue_per_round=revenue_per_round,
        order_penetration_rate=order_penetration_rate,
        average_order_value=average_order_value,
        orders_per_runner_hour=orders_per_runner_hour,
        on_time_rate=on_time_rate,
        delivery_cycle_time_p50=delivery_cycle_time_p50,
        delivery_cycle_time_p90=delivery_cycle_time_p90,
        dispatch_delay_avg=dispatch_delay_avg,
        travel_time_avg=travel_time_avg,
        failed_rate=failed_rate,
        runner_utilization_driving_pct=utilization_mix['driving'],
        runner_utilization_waiting_pct=utilization_mix['waiting'],
        distance_per_delivery_avg=distance_per_delivery_avg,
        queue_depth_avg=queue_metrics['avg_depth'],
        queue_wait_avg=queue_metrics['avg_wait'],
        capacity_15min_window=capacity_15min_window,
        second_runner_break_even_orders=second_runner_break_even_orders,
        zone_service_times=zone_service_times,
        total_revenue=total_revenue,
        total_orders=total_orders,
        successful_orders=successful_orders,
        failed_orders=failed_orders_count,
        total_rounds=total_rounds,
        active_runner_hours=service_hours,
        simulation_id=simulation_id,
        runner_id=runner_id,
        runner_utilization_by_runner=utilization_by_runner,
    )


def _extract_total_rounds(orders: List[Dict[str, Any]], activity_log: List[Dict[str, Any]]) -> int:
    """Extract total number of rounds from orders and activity log."""
    # Count unique golfer groups
    golfer_groups = set()
    for order in orders:
        golfer_groups.add(order.get('golfer_group_id', 0))
    
    # If no orders, try to extract from activity log
    if not golfer_groups:
        for activity in activity_log:
            if 'Group' in activity.get('description', ''):
                # Extract group number from description like "Group 1", "Group 2", etc.
                desc = activity['description']
                if 'Group' in desc:
                    try:
                        group_num = int(desc.split('Group')[1].split()[0])
                        golfer_groups.add(group_num)
                    except (ValueError, IndexError):
                        continue
    
    return len(golfer_groups) if golfer_groups else 1


def _calculate_on_time_rate(delivery_stats: List[Dict[str, Any]], sla_minutes: int) -> float:
    """Calculate percentage of orders delivered within SLA."""
    if not delivery_stats:
        return 0.0
    
    sla_seconds = sla_minutes * 60
    on_time_count = 0
    
    for stat in delivery_stats:
        completion_time = stat.get('total_completion_time_s', 0)
        if completion_time <= sla_seconds:
            on_time_count += 1
    
    return on_time_count / len(delivery_stats)


def _calculate_runner_utilization(activity_log: List[Dict[str, Any]], service_hours: float) -> Dict[str, float]:
    """Calculate runner utilization mix (driving, waiting)."""
    service_seconds = service_hours * 3600
    
    # Initialize time tracking
    driving_time = 0
    waiting_time = 0
    
    # Analyze activity log for time spent in different activities
    for i, activity in enumerate(activity_log):
        activity_type = activity.get('activity_type', '')
        timestamp = activity.get('timestamp_s', 0)
        
        # Calculate duration to next activity
        next_timestamp = service_seconds
        if i + 1 < len(activity_log):
            next_timestamp = activity_log[i + 1].get('timestamp_s', service_seconds)
        
        duration = next_timestamp - timestamp
        
        # Categorize activity - only driving and waiting
        if 'delivery_start' in activity_type or 'returning' in activity_type:
            driving_time += duration
        elif 'prep_start' in activity_type or 'prep_complete' in activity_type:
            waiting_time += duration
        # All other activities (delivery_complete, idle, queue_status) are ignored
    
    # Calculate percentages
    total_time = max(service_seconds, 1)
    
    return {
        'driving': (driving_time / total_time) * 100,
        'waiting': (waiting_time / total_time) * 100,
    }


def _calculate_runner_utilization_by_runner(activity_log: List[Dict[str, Any]], service_hours: float) -> Dict[str, Dict[str, float]]:
    """Calculate utilization percentages per runner_id (driving, waiting, handoff, deadhead)."""
    service_seconds = service_hours * 3600

    # Collect runner_ids
    runner_ids = []
    for a in activity_log:
        rid = a.get('runner_id')
        if isinstance(rid, str) and rid:
            if rid not in runner_ids:
                runner_ids.append(rid)

    def categorize(activity_type: str) -> str:
        if 'delivery_start' in activity_type or 'returning' in activity_type:
            return 'driving'
        if 'prep_start' in activity_type or 'prep_complete' in activity_type:
            return 'waiting'
        return 'other'

    # Initialize structures
    by_runner: Dict[str, Dict[str, float]] = {rid: {'driving': 0.0, 'waiting': 0.0} for rid in runner_ids}

    # Compute durations per runner by walking activity stream and attributing to that runner
    for idx, activity in enumerate(activity_log):
        rid = activity.get('runner_id')
        if not isinstance(rid, str) or not rid:
            continue
        activity_type = activity.get('activity_type', '')
        start_t = activity.get('timestamp_s', 0)
        end_t = service_seconds
        if idx + 1 < len(activity_log):
            end_t = activity_log[idx + 1].get('timestamp_s', service_seconds)
        duration = max(0.0, float(end_t - start_t))
        bucket = categorize(activity_type)
        if bucket in by_runner.get(rid, {}):
            by_runner[rid][bucket] += duration

    # Convert to percentages
    for rid, buckets in by_runner.items():
        total = max(1.0, float(service_seconds))
        for k in buckets:
            buckets[k] = (buckets[k] / total) * 100.0

    return by_runner


def _calculate_queue_metrics(activity_log: List[Dict[str, Any]]) -> Dict[str, float]:
    """Calculate queue depth and wait time metrics."""
    queue_depths = []
    wait_times = []
    
    for activity in activity_log:
        if 'queue_status' in activity.get('activity_type', ''):
            description = activity.get('description', '')
            # Extract queue depth from description like "3 orders waiting"
            if 'orders waiting' in description:
                try:
                    depth = int(description.split()[0])
                    queue_depths.append(depth)
                except (ValueError, IndexError):
                    continue
    
    # Calculate average queue depth
    avg_depth = statistics.mean(queue_depths) if queue_depths else 0
    
    # Estimate wait times based on queue position and processing time
    # This is a simplified calculation
    avg_wait = avg_depth * 15  # Assume 15 minutes per order in queue
    
    return {
        'avg_depth': avg_depth,
        'avg_wait': avg_wait,
    }


def _calculate_capacity_15min_window(orders: List[Dict[str, Any]], sla_minutes: int) -> int:
    """Calculate maximum orders that can be processed in a 15-minute window before SLA breach."""
    if not orders:
        return 0
    
    # Group orders by 15-minute windows
    window_orders = {}
    window_size = 15 * 60  # 15 minutes in seconds
    
    for order in orders:
        order_time = order.get('order_time_s', 0)
        window_start = (order_time // window_size) * window_size
        window_key = int(window_start)
        
        if window_key not in window_orders:
            window_orders[window_key] = 0
        window_orders[window_key] += 1
    
    # Find the window with maximum orders
    max_orders = max(window_orders.values()) if window_orders else 0
    
    return max_orders


def _calculate_second_runner_break_even(
    total_revenue: float, 
    successful_orders: int, 
    service_hours: float
) -> float:
    """Calculate break-even point for adding a second runner."""
    if successful_orders == 0:
        return 0.0
    
    # Assumptions for break-even calculation
    revenue_per_order = total_revenue / successful_orders
    runner_cost_per_hour = 25.0  # Estimated runner cost per hour
    variable_cost_per_order = 5.0  # Estimated variable cost per order
    
    # Calculate marginal contribution per order
    marginal_contribution = revenue_per_order - variable_cost_per_order
    
    # Calculate marginal labor cost for second runner
    marginal_labor_cost = runner_cost_per_hour * service_hours
    
    # Break-even orders needed
    if marginal_contribution <= 0:
        return float('inf')
    
    break_even_orders = marginal_labor_cost / marginal_contribution
    
    return break_even_orders


def _calculate_zone_service_times(delivery_stats: List[Dict[str, Any]]) -> Dict[str, float]:
    """Calculate average service time by hole/zone."""
    zone_times = {}
    
    for stat in delivery_stats:
        hole_num = stat.get('hole_num', 'unknown')
        completion_time = stat.get('total_completion_time_s', 0) / 60  # Convert to minutes
        
        zone_key = f"hole_{hole_num}"
        
        if zone_key not in zone_times:
            zone_times[zone_key] = []
        zone_times[zone_key].append(completion_time)
    
    # Calculate averages
    zone_averages = {}
    for zone, times in zone_times.items():
        zone_averages[zone] = statistics.mean(times)
    
    return zone_averages


def summarize_delivery_runner_metrics(metrics_list: List[DeliveryRunnerMetrics]) -> Dict[str, Any]:
    """
    Summarize metrics across multiple simulation runs.
    
    Args:
        metrics_list: List of DeliveryRunnerMetrics objects
        
    Returns:
        Dictionary with summary statistics
    """
    if not metrics_list:
        return {}
    
    # Extract all values for each metric
    summaries = {}
    
    # Core business metrics
    summaries['revenue_per_round'] = {
        'mean': statistics.mean([m.revenue_per_round for m in metrics_list]),
        'min': min([m.revenue_per_round for m in metrics_list]),
        'max': max([m.revenue_per_round for m in metrics_list]),
    }
    
    summaries['order_penetration_rate'] = {
        'mean': statistics.mean([m.order_penetration_rate for m in metrics_list]),
        'min': min([m.order_penetration_rate for m in metrics_list]),
        'max': max([m.order_penetration_rate for m in metrics_list]),
    }
    
    summaries['average_order_value'] = {
        'mean': statistics.mean([m.average_order_value for m in metrics_list]),
        'min': min([m.average_order_value for m in metrics_list]),
        'max': max([m.average_order_value for m in metrics_list]),
    }
    
    summaries['orders_per_runner_hour'] = {
        'mean': statistics.mean([m.orders_per_runner_hour for m in metrics_list]),
        'min': min([m.orders_per_runner_hour for m in metrics_list]),
        'max': max([m.orders_per_runner_hour for m in metrics_list]),
    }
    
    # Service quality metrics
    summaries['on_time_rate'] = {
        'mean': statistics.mean([m.on_time_rate for m in metrics_list]),
        'min': min([m.on_time_rate for m in metrics_list]),
        'max': max([m.on_time_rate for m in metrics_list]),
    }
    
    summaries['delivery_cycle_time_p50'] = {
        'mean': statistics.mean([m.delivery_cycle_time_p50 for m in metrics_list]),
        'min': min([m.delivery_cycle_time_p50 for m in metrics_list]),
        'max': max([m.delivery_cycle_time_p50 for m in metrics_list]),
    }
    
    summaries['delivery_cycle_time_p90'] = {
        'mean': statistics.mean([m.delivery_cycle_time_p90 for m in metrics_list]),
        'min': min([m.delivery_cycle_time_p90 for m in metrics_list]),
        'max': max([m.delivery_cycle_time_p90 for m in metrics_list]),
    }
    
    summaries['failed_rate'] = {
        'mean': statistics.mean([m.failed_rate for m in metrics_list]),
        'min': min([m.failed_rate for m in metrics_list]),
        'max': max([m.failed_rate for m in metrics_list]),
    }
    
    # Aggregate totals
    summaries['total_revenue'] = sum([m.total_revenue for m in metrics_list])
    summaries['total_orders'] = sum([m.total_orders for m in metrics_list])
    summaries['successful_orders'] = sum([m.successful_orders for m in metrics_list])
    summaries['failed_orders'] = sum([m.failed_orders for m in metrics_list])
    summaries['total_rounds'] = sum([m.total_rounds for m in metrics_list])
    
    return summaries


def format_delivery_runner_metrics_report(metrics: DeliveryRunnerMetrics) -> str:
    """Format delivery runner metrics as a markdown report."""
    
    # Metric definitions as inline HTML comments
    defs = {
        'RPR': 'Revenue per round = total revenue / total rounds during service window.',
        'OrdersPerRunnerHour': 'Successful orders divided by active runner hours.',
        'Penetration': 'Total orders placed per round (orders / rounds).',
        'OnTimeRate': 'Share of deliveries completed within SLA minutes.',
        'CycleP50': 'Median (50th percentile) of total completion time in minutes.',
        'CycleP90': '90th percentile of total completion time in minutes.',
        'DispatchDelay': 'Average time from order ready/received to prep start (queue delay).',
        'TravelTime': 'Average one-way travel time from clubhouse to hole.',
        'DistancePerDelivery': 'Average distance per successful delivery (meters).',
        'FailedRate': 'Failed orders divided by total orders.',
        'AOV': 'Average revenue per successful order.',
        'QueueDepth': 'Average number of orders waiting in queue when sampled.',
        'QueueWait': 'Estimated average minutes an order waits in queue.',
        'Capacity15Min': 'Maximum orders placed within any 15-minute window.',
        'BreakEven': 'Orders needed for added runner to break even under assumed costs.',
    }

    report = f"""# Delivery Runner Metrics Report

## Top 10 Metrics
- **Revenue per Round (RPR)**: ${metrics.revenue_per_round:.2f} <!-- {defs['RPR']} -->
- **Orders per Runner-Hour**: {metrics.orders_per_runner_hour:.2f} <!-- {defs['OrdersPerRunnerHour']} -->
- **Order Penetration Rate**: {metrics.order_penetration_rate:.1%} <!-- {defs['Penetration']} -->
- **On-Time Rate**: {metrics.on_time_rate:.1%} <!-- {defs['OnTimeRate']} -->
- **Delivery Cycle Time (P50)**: {metrics.delivery_cycle_time_p50:.1f} minutes <!-- {defs['CycleP50']} -->
- **Delivery Cycle Time (P90)**: {metrics.delivery_cycle_time_p90:.1f} minutes <!-- {defs['CycleP90']} -->
- **Dispatch Delay (Avg)**: {metrics.dispatch_delay_avg:.1f} minutes <!-- {defs['DispatchDelay']} -->
- **Travel Time (Avg)**: {metrics.travel_time_avg:.1f} minutes <!-- {defs['TravelTime']} -->
- **Distance per Delivery (Avg)**: {metrics.distance_per_delivery_avg:.0f} meters <!-- {defs['DistancePerDelivery']} -->
- **Failed Rate**: {metrics.failed_rate:.1%} <!-- {defs['FailedRate']} -->

## Simulation Details
- **Simulation ID**: {metrics.simulation_id}
- **Runner ID**: {metrics.runner_id}
- **Total Orders**: {metrics.total_orders}
- **Successful Orders**: {metrics.successful_orders}
- **Failed Orders**: {metrics.failed_orders}
- **Total Rounds**: {metrics.total_rounds}
- **Active Runner Hours**: {metrics.active_runner_hours:.1f}

## Core Business Metrics

### Revenue & Orders
- **Revenue per Round (RPR)**: ${metrics.revenue_per_round:.2f} <!-- {defs['RPR']} -->
- **Order Penetration Rate**: {metrics.order_penetration_rate:.1%} <!-- {defs['Penetration']} -->
- **Average Order Value (AOV)**: ${metrics.average_order_value:.2f} <!-- {defs['AOV']} -->
- **Orders per Runner-Hour**: {metrics.orders_per_runner_hour:.2f} <!-- {defs['OrdersPerRunnerHour']} -->

### Service Quality
- **On-Time Rate**: {metrics.on_time_rate:.1%} <!-- {defs['OnTimeRate']} -->
- **Delivery Cycle Time (P50)**: {metrics.delivery_cycle_time_p50:.1f} minutes <!-- {defs['CycleP50']} -->
- **Delivery Cycle Time (P90)**: {metrics.delivery_cycle_time_p90:.1f} minutes <!-- {defs['CycleP90']} -->
- **Dispatch Delay (Avg)**: {metrics.dispatch_delay_avg:.1f} minutes <!-- {defs['DispatchDelay']} -->
- **Travel Time (Avg)**: {metrics.travel_time_avg:.1f} minutes <!-- {defs['TravelTime']} -->
- **Failed Rate**: {metrics.failed_rate:.1%} <!-- {defs['FailedRate']} -->

## Operational Metrics

### Runner Utilization Mix
- **Driving**: {metrics.runner_utilization_driving_pct:.1f}%
- **Waiting at Kitchen**: {metrics.runner_utilization_waiting_pct:.1f}%

### Runner Utilization by Runner
"""
    # Append per-runner utilization if available
    if metrics.runner_utilization_by_runner:
        for rid, buckets in metrics.runner_utilization_by_runner.items():
            report += f"- **{rid}**: Driving {buckets.get('driving', 0):.1f}%, Waiting {buckets.get('waiting', 0):.1f}%\n"
    else:
        report += "- n/a\n"

    report += f"""

### Distance & Capacity
- **Distance per Delivery (Avg)**: {metrics.distance_per_delivery_avg:.0f} meters <!-- {defs['DistancePerDelivery']} -->
- **Queue Depth (Avg)**: {metrics.queue_depth_avg:.1f} orders <!-- {defs['QueueDepth']} -->
- **Queue Wait (Avg)**: {metrics.queue_wait_avg:.1f} minutes <!-- {defs['QueueWait']} -->
- **Capacity per 15-min Window**: {metrics.capacity_15min_window} orders <!-- {defs['Capacity15Min']} -->

### Financial Analysis
- **Second Runner Break-Even**: {metrics.second_runner_break_even_orders:.1f} orders <!-- {defs['BreakEven']} -->

## Zone Service Times

"""
    
    # Add zone service times
    for zone, service_time in metrics.zone_service_times.items():
        report += f"- **{zone}**: {service_time:.1f} minutes\n"
    
    return report


def format_delivery_runner_summary_report(summaries: Dict[str, Any], num_runs: int) -> str:
    """Format delivery runner metrics summary as a markdown report."""
    
    report = f"""# Delivery Runner Metrics Summary

## Summary Statistics (Across {num_runs} Runs)

### Core Business Metrics

#### Revenue per Round (RPR)
- **Mean**: ${summaries.get('revenue_per_round', {}).get('mean', 0):.2f}
- **Range**: ${summaries.get('revenue_per_round', {}).get('min', 0):.2f} - ${summaries.get('revenue_per_round', {}).get('max', 0):.2f}

#### Order Penetration Rate
- **Mean**: {summaries.get('order_penetration_rate', {}).get('mean', 0):.1%}
- **Range**: {summaries.get('order_penetration_rate', {}).get('min', 0):.1%} - {summaries.get('order_penetration_rate', {}).get('max', 0):.1%}

#### Average Order Value (AOV)
- **Mean**: ${summaries.get('average_order_value', {}).get('mean', 0):.2f}
- **Range**: ${summaries.get('average_order_value', {}).get('min', 0):.2f} - ${summaries.get('average_order_value', {}).get('max', 0):.2f}

#### Orders per Runner-Hour
- **Mean**: {summaries.get('orders_per_runner_hour', {}).get('mean', 0):.2f}
- **Range**: {summaries.get('orders_per_runner_hour', {}).get('min', 0):.2f} - {summaries.get('orders_per_runner_hour', {}).get('max', 0):.2f}

### Service Quality Metrics

#### On-Time Rate
- **Mean**: {summaries.get('on_time_rate', {}).get('mean', 0):.1%}
- **Range**: {summaries.get('on_time_rate', {}).get('min', 0):.1%} - {summaries.get('on_time_rate', {}).get('max', 0):.1%}

#### Delivery Cycle Time
- **P50 Mean**: {summaries.get('delivery_cycle_time_p50', {}).get('mean', 0):.1f} minutes
- **P90 Mean**: {summaries.get('delivery_cycle_time_p90', {}).get('mean', 0):.1f} minutes

#### Failed Rate
- **Mean**: {summaries.get('failed_rate', {}).get('mean', 0):.1%}
- **Range**: {summaries.get('failed_rate', {}).get('min', 0):.1%} - {summaries.get('failed_rate', {}).get('max', 0):.1%}

## Aggregate Totals
- **Total Revenue**: ${summaries.get('total_revenue', 0):.2f}
- **Total Orders**: {summaries.get('total_orders', 0)}
- **Successful Orders**: {summaries.get('successful_orders', 0)}
- **Failed Orders**: {summaries.get('failed_orders', 0)}
- **Total Rounds**: {summaries.get('total_rounds', 0)}
"""
    
    return report
