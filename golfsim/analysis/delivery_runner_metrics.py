"""
Delivery Runner Metrics Analysis Module

This module provides GM-priority metrics calculation for delivery runner simulations,
specifically designed for executive decision-making on Clubhouse delivery (1-2 runners).

The executive-priority metrics include:
1. Revenue per Round (RPR) - Headline financial impact
2. Orders per Runner-Hour - Labor productivity
3. On-Time Rate - SLA reliability
4. Delivery Cycle Time (P90) - Worst-case customer wait
5. Failed Rate - Defect rate protection
6. Second-Runner Break-Even - Clear scaling/ROI trigger
7. Queue Wait Avg - Kitchen bottleneck signal
8. Runner Utilization Mix - Proof of efficient paid hours
9. Distance per Delivery Avg - Routing efficiency
10. Zone Service Times - Course heatmap for action planning
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any, Dict, List

from ..logging import get_logger

logger = get_logger(__name__)


@dataclass
class DeliveryRunnerMetrics:
    """Executive-priority metrics for delivery runner simulations (GM-ready)."""
    
    # Executive-priority metrics
    revenue_per_round: float
    orders_per_runner_hour: float
    on_time_rate: float
    delivery_cycle_time_p90: float
    delivery_cycle_time_avg: float
    failed_rate: float
    second_runner_break_even_orders: float
    queue_wait_avg: float
    runner_utilization_driving_pct: float
    runner_utilization_prep_pct: float
    runner_utilization_idle_pct: float
    distance_per_delivery_avg: float
    zone_service_times: Dict[str, float]
    
    # Simulation details and aggregates
    total_revenue: float
    total_orders: int
    successful_orders: int
    failed_orders: int
    total_rounds: int
    active_runner_hours: float
    simulation_id: str
    runner_id: str


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
    Calculate executive-priority delivery runner metrics from simulation data.
    """
    # Basic counts
    total_orders = len(orders)
    successful_orders = len(delivery_stats)
    failed_orders_count = len(failed_orders)
    total_ordering_groups = _extract_total_ordering_groups(orders, activity_log)
    
    # Calculate actual active hours
    actual_active_hours = _calculate_actual_active_hours(activity_log, service_hours)
    
    # Revenue
    total_revenue = successful_orders * revenue_per_order
    revenue_per_round = total_revenue / max(total_ordering_groups, 1)
    
    # Throughput
    orders_per_runner_hour = successful_orders / max(actual_active_hours, 0.1)
    
    # Service quality
    on_time_rate = _calculate_on_time_rate(delivery_stats, sla_minutes)
    delivery_cycle_times_min = [d.get("total_completion_time_s", 0) / 60 for d in delivery_stats]
    delivery_cycle_time_avg = statistics.mean(delivery_cycle_times_min) if delivery_cycle_times_min else 0.0
    delivery_cycle_time_p90 = (
        statistics.quantiles(delivery_cycle_times_min, n=10)[8]
        if len(delivery_cycle_times_min) >= 10
        else max(delivery_cycle_times_min) if delivery_cycle_times_min else 0.0
    )
    
    # Failure rate
    failed_rate = failed_orders_count / max(total_orders, 1)
    
    # Utilization
    utilization_mix = _calculate_runner_utilization(activity_log, actual_active_hours)
    
    # Distance
    distances_m = [d.get("delivery_distance_m", 0) for d in delivery_stats]
    distance_per_delivery_avg = statistics.mean(distances_m) if distances_m else 0.0
    
    # Queue (keep function but only use wait)
    queue_metrics = _calculate_queue_metrics(delivery_stats, activity_log)
    queue_wait_avg = float(queue_metrics.get("avg_wait", 0.0))
    
    # Break-even
    second_runner_break_even_orders = _calculate_second_runner_break_even(
        total_revenue, successful_orders, actual_active_hours
    )
    
    # Zones
    zone_service_times = _calculate_zone_service_times(delivery_stats)
    
    return DeliveryRunnerMetrics(
        revenue_per_round=revenue_per_round,
        orders_per_runner_hour=orders_per_runner_hour,
        on_time_rate=on_time_rate,
        delivery_cycle_time_p90=delivery_cycle_time_p90,
        delivery_cycle_time_avg=delivery_cycle_time_avg,
        failed_rate=failed_rate,
        second_runner_break_even_orders=second_runner_break_even_orders,
        queue_wait_avg=queue_wait_avg,
        runner_utilization_driving_pct=utilization_mix["driving"],
        runner_utilization_prep_pct=utilization_mix["prep"],
        runner_utilization_idle_pct=utilization_mix["idle"],
        distance_per_delivery_avg=distance_per_delivery_avg,
        zone_service_times=zone_service_times,
        total_revenue=total_revenue,
        total_orders=total_orders,
        successful_orders=successful_orders,
        failed_orders=failed_orders_count,
        total_rounds=total_ordering_groups,
        active_runner_hours=actual_active_hours,
        simulation_id=simulation_id,
        runner_id=runner_id,
    )


def _calculate_actual_active_hours(activity_log: List[Dict[str, Any]], max_service_hours: float) -> float:
    """Calculate actual active hours from service_opened to last activity."""
    if not activity_log:
        return max_service_hours
    
    # Find service_opened timestamp
    service_start = None
    service_end = None
    
    for activity in activity_log:
        activity_type = activity.get('activity_type', '')
        timestamp = activity.get('timestamp_s', 0)
        
        if activity_type == 'service_opened':
            service_start = timestamp
        
        # Track the last activity timestamp
        if timestamp > (service_end or 0):
            service_end = timestamp
    
    if service_start is None or service_end is None:
        return max_service_hours
    
    # Calculate actual hours, but cap at max_service_hours
    actual_hours = (service_end - service_start) / 3600.0
    return min(actual_hours, max_service_hours)


def _extract_total_ordering_groups(orders: List[Dict[str, Any]], activity_log: List[Dict[str, Any]]) -> int:
    """Extract total number of groups that placed orders."""
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
    """Calculate runner utilization considering only driving as active time.

    Prep is handled by the kitchen and should not count toward runner utilization.
    """
    service_seconds = service_hours * 3600

    # Track only driving time (outbound + return). Ignore prep.
    driving_time = 0

    for i, activity in enumerate(activity_log):
        activity_type = activity.get('activity_type', '')
        timestamp = activity.get('timestamp_s', 0)

        # Duration to next activity marker within the log window
        next_timestamp = service_seconds
        if i + 1 < len(activity_log):
            next_timestamp = activity_log[i + 1].get('timestamp_s', service_seconds)

        duration = next_timestamp - timestamp

        # Driving includes delivery_start.. and returning.. segments
        if 'delivery_start' in activity_type or 'returning' in activity_type:
            driving_time += max(0, duration)

    total_time = max(service_seconds, 1)
    driving_pct = (driving_time / total_time) * 100.0
    idle_pct = 100.0 - driving_pct

    return {
        'driving': driving_pct,
        'prep': 0.0,
        'idle': idle_pct,
    }


def _calculate_queue_metrics(delivery_stats: List[Dict[str, Any]], activity_log: List[Dict[str, Any]]) -> Dict[str, float]:
    """Calculate queue depth and wait time metrics from actual queue delays."""
    # First try to get actual queue delays from delivery stats
    queue_delays_min = []
    for stat in delivery_stats:
        queue_delay_s = stat.get('queue_delay_s', 0)
        if queue_delay_s > 0:
            queue_delays_min.append(queue_delay_s / 60)  # Convert to minutes
    
    # If we have actual queue delays, use them
    if queue_delays_min:
        avg_wait = statistics.mean(queue_delays_min)
        avg_depth = len(queue_delays_min) / max(len(delivery_stats), 1)  # Approximation
    else:
        # Fallback to activity log analysis (legacy method)
        queue_depths = []
        
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
    window_size = 15 * 60  # 15 minutes in seconds
    sla_seconds = sla_minutes * 60
    
    windows = {}
    
    for order in orders:
        order_time_s = order.get('order_time_s', 0)
        # Only count orders within SLA window
        if order_time_s <= sla_seconds:
            window_index = int(order_time_s // window_size)
            if window_index not in windows:
                windows[window_index] = 0
            windows[window_index] += 1
    
    return max(windows.values()) if windows else 0


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
    Summarize executive-priority metrics across multiple runs.
    """
    if not metrics_list:
        return {}

    def _mm(arr: List[float]) -> Dict[str, float]:
        return {"mean": statistics.mean(arr), "min": min(arr), "max": max(arr)} if arr else {"mean": 0.0, "min": 0.0, "max": 0.0}

    summaries: Dict[str, Any] = {}

    # Executive metrics
    summaries["revenue_per_round"] = _mm([m.revenue_per_round for m in metrics_list])
    summaries["orders_per_runner_hour"] = _mm([m.orders_per_runner_hour for m in metrics_list])
    summaries["on_time_rate"] = _mm([m.on_time_rate for m in metrics_list])
    summaries["delivery_cycle_time_p90"] = _mm([m.delivery_cycle_time_p90 for m in metrics_list])
    summaries["delivery_cycle_time_avg"] = _mm([m.delivery_cycle_time_avg for m in metrics_list])
    summaries["failed_rate"] = _mm([m.failed_rate for m in metrics_list])
    summaries["queue_wait_avg"] = _mm([m.queue_wait_avg for m in metrics_list])
    summaries["distance_per_delivery_avg"] = _mm([m.distance_per_delivery_avg for m in metrics_list])

    # Totals
    summaries["total_revenue"] = sum(m.total_revenue for m in metrics_list)
    summaries["total_orders"] = sum(m.total_orders for m in metrics_list)
    summaries["successful_orders"] = sum(m.successful_orders for m in metrics_list)
    summaries["failed_orders"] = sum(m.failed_orders for m in metrics_list)
    summaries["total_rounds"] = sum(m.total_rounds for m in metrics_list)

    return summaries


def format_delivery_runner_metrics_report(metrics: DeliveryRunnerMetrics) -> str:
    """Format executive-priority delivery runner metrics as a GM-ready markdown report."""
    report = f"""# Delivery Runner Executive Metrics

## Executive Priority Ranking (Most Persuasive First)
1. **Revenue per Ordering Group**: ${metrics.revenue_per_round:.2f}
2. **Orders per Runner‑Hour**: {metrics.orders_per_runner_hour:.2f}
3. **On‑Time Rate**: {metrics.on_time_rate:.1%}
4. **Delivery Cycle Time (P90)**: {metrics.delivery_cycle_time_p90:.1f} minutes
5. **Failed Rate**: {metrics.failed_rate:.1%}
6. **Second‑Runner Break‑Even**: {metrics.second_runner_break_even_orders:.1f} orders (assumes $25/hr wage, $5 variable cost)
7. **Queue Wait (Avg)**: {metrics.queue_wait_avg:.1f} minutes
8. **Runner Utilization (Driving)**: {metrics.runner_utilization_driving_pct:.1f}% (Idle {metrics.runner_utilization_idle_pct:.1f}%)
9. **Avg Order Time**: {metrics.delivery_cycle_time_avg:.1f} minutes
10. **Distance per Delivery (Avg)**: {metrics.distance_per_delivery_avg:.0f} meters

## Zone Service Times
"""
    
    for zone, service_time in metrics.zone_service_times.items():
        report += f"- **{zone}**: {service_time:.1f} minutes\n"

    report += f"""

## Simulation Details
- Simulation ID: {metrics.simulation_id}
- Runner ID: {metrics.runner_id}
- Total Orders: {metrics.total_orders}
- Successful Orders: {metrics.successful_orders}
- Failed Orders: {metrics.failed_orders}
- Total Ordering Groups: {metrics.total_rounds}
- Active Runner Hours: {metrics.active_runner_hours:.1f}

> Tip: Lead with 1–3 to show revenue and efficiency, use 4–6 to prove reliability, and close with 7–8 as the scaling/ROI story.
"""
    return report


def format_delivery_runner_summary_report(summaries: Dict[str, Any], num_runs: int) -> str:
    """Format executive-priority metrics summary as a markdown report."""
    report = f"""# Delivery Runner Metrics Summary

## Summary Statistics (Across {num_runs} Runs)
- Revenue per Ordering Group — Mean: ${summaries.get('revenue_per_round', {}).get('mean', 0):.2f} (Range: ${summaries.get('revenue_per_round', {}).get('min', 0):.2f}–${summaries.get('revenue_per_round', {}).get('max', 0):.2f})
- Orders per Runner‑Hour — Mean: {summaries.get('orders_per_runner_hour', {}).get('mean', 0):.2f}
- On‑Time Rate — Mean: {summaries.get('on_time_rate', {}).get('mean', 0):.1%}
- Delivery Cycle Time (P90) — Mean: {summaries.get('delivery_cycle_time_p90', {}).get('mean', 0):.1f} min
- Avg Order Time — Mean: {summaries.get('delivery_cycle_time_avg', {}).get('mean', 0):.1f} min
- Failed Rate — Mean: {summaries.get('failed_rate', {}).get('mean', 0):.1%}
- Queue Wait (Avg) — Mean: {summaries.get('queue_wait_avg', {}).get('mean', 0):.1f} min

## Aggregate Totals
- Total Revenue: ${summaries.get('total_revenue', 0):.2f}
- Total Orders: {summaries.get('total_orders', 0)}
- Successful Orders: {summaries.get('successful_orders', 0)}
- Failed Orders: {summaries.get('failed_orders', 0)}
- Total Ordering Groups: {summaries.get('total_rounds', 0)}
"""
    return report


def format_delivery_runner_executive_summary_across_runs(metrics_list: List[DeliveryRunnerMetrics]) -> str:
    """Format an executive-style summary across multiple runs with mean and median values.

    Presents the same GM-priority list but aggregates across runs.
    """
    import statistics as _stats

    n = len(metrics_list)
    if n == 0:
        return "# Delivery Runner Executive Metrics — Summary\n\nNo runs.\n"

    def mean(arr: List[float]) -> float:
        return _stats.mean(arr) if arr else 0.0

    def median(arr: List[float]) -> float:
        return _stats.median(arr) if arr else 0.0

    vals = {
        "revenue_per_round": [m.revenue_per_round for m in metrics_list],
        "orders_per_runner_hour": [m.orders_per_runner_hour for m in metrics_list],
        "on_time_rate": [m.on_time_rate for m in metrics_list],
        "delivery_cycle_time_p90": [m.delivery_cycle_time_p90 for m in metrics_list],
        "delivery_cycle_time_avg": [m.delivery_cycle_time_avg for m in metrics_list],
        "failed_rate": [m.failed_rate for m in metrics_list],
        "second_runner_break_even_orders": [m.second_runner_break_even_orders for m in metrics_list],
        "queue_wait_avg": [m.queue_wait_avg for m in metrics_list],
        "runner_utilization_driving_pct": [m.runner_utilization_driving_pct for m in metrics_list],
        "runner_utilization_prep_pct": [m.runner_utilization_prep_pct for m in metrics_list],
        "runner_utilization_idle_pct": [m.runner_utilization_idle_pct for m in metrics_list],
        "distance_per_delivery_avg": [m.distance_per_delivery_avg for m in metrics_list],
    }

    total_revenue = sum(m.total_revenue for m in metrics_list)
    total_orders = sum(m.total_orders for m in metrics_list)
    successful_orders = sum(m.successful_orders for m in metrics_list)
    failed_orders = sum(m.failed_orders for m in metrics_list)
    total_rounds = sum(m.total_rounds for m in metrics_list)
    service_hours = metrics_list[0].active_runner_hours if metrics_list else 10.0

    report = f"""# Delivery Runner Executive Metrics — Summary

## Summary Across {n} Runs (Mean / Median)
1. **Revenue per Ordering Group**: ${mean(vals['revenue_per_round']):.2f} / ${median(vals['revenue_per_round']):.2f}
2. **Orders per Runner‑Hour**: {mean(vals['orders_per_runner_hour']):.2f} / {median(vals['orders_per_runner_hour']):.2f}
3. **On‑Time Rate**: {mean(vals['on_time_rate']):.1%} / {median(vals['on_time_rate']):.1%}
4. **Delivery Cycle Time (P90)**: {mean(vals['delivery_cycle_time_p90']):.1f} / {median(vals['delivery_cycle_time_p90']):.1f} minutes
5. **Failed Rate**: {mean(vals['failed_rate']):.1%} / {median(vals['failed_rate']):.1%}
6. **Second‑Runner Break‑Even**: {mean(vals['second_runner_break_even_orders']):.1f} / {median(vals['second_runner_break_even_orders']):.1f} orders (assumes $25/hr wage, $5 variable cost)
7. **Queue Wait (Avg)**: {mean(vals['queue_wait_avg']):.1f} / {median(vals['queue_wait_avg']):.1f} minutes
8. **Runner Utilization**: Driving {mean(vals['runner_utilization_driving_pct']):.1f}% / {median(vals['runner_utilization_driving_pct']):.1f}%, Prep {mean(vals['runner_utilization_prep_pct']):.1f}% / {median(vals['runner_utilization_prep_pct']):.1f}%, Idle {mean(vals['runner_utilization_idle_pct']):.1f}% / {median(vals['runner_utilization_idle_pct']):.1f}%
9. **Avg Order Time**: {mean(vals['delivery_cycle_time_avg']):.1f} / {median(vals['delivery_cycle_time_avg']):.1f} minutes
10. **Distance per Delivery (Avg)**: {mean(vals['distance_per_delivery_avg']):.0f} / {median(vals['distance_per_delivery_avg']):.0f} meters

## Aggregate Totals
- Total Revenue: ${total_revenue:.2f}
- Total Orders: {total_orders}
- Successful Orders: {successful_orders}
- Failed Orders: {failed_orders}
- Total Ordering Groups: {total_rounds}
"""

    return report