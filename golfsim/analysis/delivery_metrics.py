from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from scripts.optimization.optimize_staffing_policy import RunMetrics


def format_minutes(value: Optional[float]) -> str:
    """Formats a float value into a string with 'm' suffix."""
    if value is None:
        return "0m"
    return f"{round(value)}m"


def format_percentage(value: Optional[float]) -> str:
    """Formats a float value into a percentage string."""
    if value is None:
        return "0%"
    return f"{round(value * 100)}%"


def format_currency(value: Optional[float]) -> str:
    """Formats a float value into a currency string."""
    if value is None:
        return "$0"
    return f"${round(value)}"


def calculate_delivery_metrics(
    agg_results: Dict[str, Any], run_metrics: List[RunMetrics], num_runners: int
) -> Dict[str, Any]:
    """
    Calculates and formats a summary of delivery metrics.

    Args:
        agg_results: Aggregated results from `aggregate_runs`.
        run_metrics: A list of `RunMetrics` objects from individual runs.
        num_runners: The number of runners for this group of simulations.

    Returns:
        A dictionary containing the formatted delivery metrics summary.
    """
    total_orders = agg_results.get("total_orders", 0)
    
    # Calculate late orders. successful_orders are on-time, so late is total - successful
    total_successful = agg_results.get("total_successful_orders", 0)
    late_orders = total_orders - total_successful

    # Sum of failed orders from all runs
    failed_orders = sum(m.failed_orders for m in run_metrics if m.failed_orders is not None)

    # Average runner utilization
    runner_utilization = (
        sum(m.runner_utilization_pct for m in run_metrics if m.runner_utilization_pct is not None)
        / len(run_metrics)
        if run_metrics
        else 0
    )

    # Sum of total revenue
    total_revenue = sum(m.total_revenue for m in run_metrics if m.total_revenue is not None)

    # Calculate runner drive minutes and shift minutes
    total_active_runner_hours = sum(m.active_runner_hours for m in run_metrics if m.active_runner_hours is not None)
    avg_active_runner_hours_per_run = total_active_runner_hours / len(run_metrics) if run_metrics else 0
    
    # Total shift minutes assumes a 10-hour day per runner as a baseline
    runner_shift_minutes = num_runners * 10 * 60
    
    # Drive minutes is derived from utilization % of active time
    runner_drive_minutes = (
        sum(
            (m.runner_utilization_driving_pct / 100.0) * m.active_runner_hours
            for m in run_metrics
            if m.runner_utilization_driving_pct is not None and m.active_runner_hours is not None
        )
        * 60
    ) / len(run_metrics) if run_metrics else 0


    return {
        "Order Count": total_orders,
        "Avg Order Time": format_minutes(agg_results.get("avg_delivery_time_mean")),
        "Avg Queue Wait": format_minutes(
            sum(m.queue_wait_avg for m in run_metrics if m.queue_wait_avg is not None) / len(run_metrics)
            if run_metrics
            else 0
        ),
        "Late Orders": late_orders,
        "Failed Orders": failed_orders,
        "Runner Utilization %": format_percentage(runner_utilization),
        "On-Time %": format_percentage(agg_results.get("on_time_wilson_lo")),
        "Total Revenue": format_currency(total_revenue),
        "Runner Drive Minutes": format_minutes(runner_drive_minutes),
        "Runner Shift Minutes": format_minutes(runner_shift_minutes),
    }


def write_delivery_metrics_summary(
    group_dir: Path, metrics: Dict[str, Any]
) -> None:
    """Writes the delivery metrics summary to a file."""
    output_path = group_dir / "delivery_metrics.json"
    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2)
    except IOError as e:
        print(f"Error writing delivery metrics summary to {output_path}: {e}")
