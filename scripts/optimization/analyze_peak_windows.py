#!/usr/bin/env python3
"""
Analyze delivery performance by time windows to identify peak periods and recommend
dynamic staffing or hole restrictions during problematic hours.

This script reads simulation results and analyzes performance metrics by hour-of-day
to identify when service quality degrades and recommend targeted interventions.

Usage:
  python scripts/optimization/analyze_peak_windows.py \
    --experiment-dir outputs/experiments/baseline/real_tee_sheet/orders_028/runners_1 \
    --output-dir outputs/experiments/peak_analysis \
    --window-size 60
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import defaultdict
from datetime import datetime, time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class TimeWindowMetrics:
    window_start_hour: int
    window_start_min: int
    window_end_hour: int
    window_end_min: int
    total_orders: int
    successful_orders: int
    failed_orders: int
    on_time_orders: int
    avg_delivery_time: float
    p90_delivery_time: float
    avg_queue_wait: float
    zone_service_times: Dict[str, List[float]]
    
    @property
    def on_time_rate(self) -> float:
        return self.on_time_orders / max(self.total_orders, 1)
    
    @property
    def failed_rate(self) -> float:
        return self.failed_orders / max(self.total_orders, 1)
    
    @property
    def success_rate(self) -> float:
        return self.successful_orders / max(self.total_orders, 1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze delivery performance by time windows")
    parser.add_argument("--experiment-dir", required=True, help="Directory containing simulation runs")
    parser.add_argument("--output-dir", required=True, help="Output directory for analysis results")
    parser.add_argument("--window-size", type=int, default=60, help="Time window size in minutes")
    parser.add_argument("--sla-minutes", type=int, default=30, help="SLA threshold in minutes")
    parser.add_argument("--service-start-hour", type=int, default=7, help="Service start hour (24h format)")
    parser.add_argument("--service-end-hour", type=int, default=17, help="Service end hour (24h format)")
    return parser.parse_args()


def seconds_to_hour_min(seconds: int, base_hour: int = 7) -> Tuple[int, int]:
    """Convert seconds since base hour to (hour, minute)."""
    total_minutes = seconds // 60
    hour = base_hour + (total_minutes // 60)
    minute = total_minutes % 60
    return hour, minute


def get_time_window(timestamp_s: int, window_size_min: int, base_hour: int = 7) -> Tuple[int, int]:
    """Get the time window (start_hour, start_min) for a given timestamp."""
    total_minutes = timestamp_s // 60
    window_start_min = (total_minutes // window_size_min) * window_size_min
    start_hour = base_hour + (window_start_min // 60)
    start_min = window_start_min % 60
    return start_hour, start_min


def load_run_data(run_dir: Path, sla_minutes: int) -> List[Dict[str, Any]]:
    """Load order timing and delivery data from a single run."""
    orders_data = []
    
    # Load order timing logs
    timing_file = run_dir / "order_timing_logs.csv"
    if not timing_file.exists():
        return orders_data
    
    try:
        with timing_file.open('r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            timing_data = {row['order_id']: row for row in reader}
    except Exception:
        return orders_data
    
    # Load delivery metrics for zone information
    metrics_files = list(run_dir.glob("delivery_runner_metrics_*.json"))
    zone_service_times = {}
    if metrics_files:
        try:
            with metrics_files[0].open('r', encoding='utf-8') as f:
                metrics = json.load(f)
                zone_service_times = metrics.get("zone_service_times", {})
        except Exception:
            pass
    
    # Load order logs for hole information
    order_logs_file = run_dir / "order_logs.csv"
    hole_mapping = {}
    if order_logs_file.exists():
        try:
            with order_logs_file.open('r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    hole_mapping[row.get('order_id', '')] = row.get('hole_num', 'unknown')
        except Exception:
            pass
    
    # Process timing data
    for order_id, timing in timing_data.items():
        try:
            order_time_s = float(timing.get('order_time_s', 0))
            delivery_time_s = float(timing.get('delivery_timestamp_s', 0))
            return_time_s = float(timing.get('return_timestamp_s', 0))
            
            # Calculate delivery duration
            delivery_duration_s = delivery_time_s - order_time_s if delivery_time_s > 0 else 0
            delivery_duration_min = delivery_duration_s / 60.0
            
            # Determine if order was successful and on-time
            is_successful = delivery_time_s > 0
            is_on_time = is_successful and delivery_duration_min <= sla_minutes
            
            # Get hole information
            hole_num = hole_mapping.get(order_id, 'unknown')
            zone_key = f"hole_{hole_num}" if hole_num != 'unknown' else 'unknown'
            zone_service_time = zone_service_times.get(zone_key, delivery_duration_min)
            
            orders_data.append({
                'order_id': order_id,
                'order_time_s': int(order_time_s),
                'delivery_time_s': int(delivery_time_s) if delivery_time_s > 0 else None,
                'delivery_duration_min': delivery_duration_min,
                'is_successful': is_successful,
                'is_on_time': is_on_time,
                'hole_num': hole_num,
                'zone_service_time': zone_service_time,
            })
        except (ValueError, TypeError):
            continue
    
    return orders_data


def analyze_time_windows(
    all_orders: List[Dict[str, Any]], 
    window_size_min: int,
    service_start_hour: int,
    service_end_hour: int
) -> List[TimeWindowMetrics]:
    """Analyze orders by time windows."""
    
    # Group orders by time window
    window_orders = defaultdict(list)
    
    for order in all_orders:
        order_time_s = order['order_time_s']
        window_start_hour, window_start_min = get_time_window(order_time_s, window_size_min)
        
        # Skip orders outside service hours
        if window_start_hour < service_start_hour or window_start_hour >= service_end_hour:
            continue
            
        window_key = (window_start_hour, window_start_min)
        window_orders[window_key].append(order)
    
    # Calculate metrics for each window
    window_metrics = []
    
    for (start_hour, start_min), orders in window_orders.items():
        if not orders:
            continue
        
        # Calculate end time
        end_hour = start_hour
        end_min = start_min + window_size_min
        if end_min >= 60:
            end_hour += end_min // 60
            end_min = end_min % 60
        
        # Calculate basic counts
        total_orders = len(orders)
        successful_orders = sum(1 for o in orders if o['is_successful'])
        failed_orders = total_orders - successful_orders
        on_time_orders = sum(1 for o in orders if o['is_on_time'])
        
        # Calculate timing metrics
        successful_deliveries = [o for o in orders if o['is_successful']]
        if successful_deliveries:
            delivery_times = [o['delivery_duration_min'] for o in successful_deliveries]
            avg_delivery_time = statistics.mean(delivery_times)
            p90_delivery_time = statistics.quantiles(delivery_times, n=10)[8] if len(delivery_times) >= 10 else max(delivery_times)
        else:
            avg_delivery_time = 0.0
            p90_delivery_time = 0.0
        
        # Group zone service times
        zone_times = defaultdict(list)
        for order in orders:
            if order['is_successful'] and order['hole_num'] != 'unknown':
                zone_key = f"hole_{order['hole_num']}"
                zone_times[zone_key].append(order['zone_service_time'])
        
        window_metrics.append(TimeWindowMetrics(
            window_start_hour=start_hour,
            window_start_min=start_min,
            window_end_hour=end_hour,
            window_end_min=end_min,
            total_orders=total_orders,
            successful_orders=successful_orders,
            failed_orders=failed_orders,
            on_time_orders=on_time_orders,
            avg_delivery_time=avg_delivery_time,
            p90_delivery_time=p90_delivery_time,
            avg_queue_wait=0.0,  # Would need activity log to calculate
            zone_service_times=dict(zone_times),
        ))
    
    return sorted(window_metrics, key=lambda w: (w.window_start_hour, w.window_start_min))


def identify_peak_windows(
    windows: List[TimeWindowMetrics],
    on_time_threshold: float = 0.95,
    failed_threshold: float = 0.05
) -> List[TimeWindowMetrics]:
    """Identify problematic time windows that don't meet SLA targets."""
    
    problematic_windows = []
    
    for window in windows:
        if window.total_orders == 0:
            continue
            
        # Check if window fails SLA targets
        fails_on_time = window.on_time_rate < on_time_threshold
        fails_failed_rate = window.failed_rate > failed_threshold
        
        if fails_on_time or fails_failed_rate:
            problematic_windows.append(window)
    
    return problematic_windows


def write_window_analysis_csv(output_path: Path, windows: List[TimeWindowMetrics]) -> None:
    """Write detailed window analysis to CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with output_path.open('w', newline='', encoding='utf-8') as f:
        fieldnames = [
            'window_start', 'window_end', 'total_orders', 'successful_orders', 'failed_orders',
            'on_time_orders', 'on_time_rate', 'failed_rate', 'success_rate',
            'avg_delivery_time_min', 'p90_delivery_time_min', 'slowest_zones'
        ]
        
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        for window in windows:
            # Find slowest zones
            zone_avg_times = {}
            for zone, times in window.zone_service_times.items():
                if times:
                    zone_avg_times[zone] = statistics.mean(times)
            
            slowest_zones = sorted(zone_avg_times.items(), key=lambda x: x[1], reverse=True)[:3]
            slowest_zones_str = '; '.join([f"{zone}: {time:.1f}min" for zone, time in slowest_zones])
            
            writer.writerow({
                'window_start': f"{window.window_start_hour:02d}:{window.window_start_min:02d}",
                'window_end': f"{window.window_end_hour:02d}:{window.window_end_min:02d}",
                'total_orders': window.total_orders,
                'successful_orders': window.successful_orders,
                'failed_orders': window.failed_orders,
                'on_time_orders': window.on_time_orders,
                'on_time_rate': round(window.on_time_rate, 4),
                'failed_rate': round(window.failed_rate, 4),
                'success_rate': round(window.success_rate, 4),
                'avg_delivery_time_min': round(window.avg_delivery_time, 2),
                'p90_delivery_time_min': round(window.p90_delivery_time, 2),
                'slowest_zones': slowest_zones_str,
            })


def write_peak_recommendations_md(
    output_path: Path, 
    windows: List[TimeWindowMetrics],
    peak_windows: List[TimeWindowMetrics],
    window_size_min: int
) -> None:
    """Write peak window recommendations markdown."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    lines = []
    lines.append("# Peak Window Analysis & Recommendations\n\n")
    
    # Executive summary
    lines.append("## Executive Summary\n\n")
    lines.append(f"Analysis of delivery performance across {window_size_min}-minute time windows.\n\n")
    
    if peak_windows:
        lines.append(f"**{len(peak_windows)} problematic time windows identified** that fail to meet SLA targets.\n\n")
        
        # Calculate overall stats for peak windows
        total_peak_orders = sum(w.total_orders for w in peak_windows)
        avg_peak_on_time = statistics.mean([w.on_time_rate for w in peak_windows])
        avg_peak_failed = statistics.mean([w.failed_rate for w in peak_windows])
        
        lines.append(f"**Peak Window Performance:**\n")
        lines.append(f"- Total orders in peak windows: {total_peak_orders}\n")
        lines.append(f"- Average on-time rate: {avg_peak_on_time:.1%}\n")
        lines.append(f"- Average failed rate: {avg_peak_failed:.1%}\n\n")
    else:
        lines.append("✅ **No problematic time windows identified.** All periods meet SLA targets.\n\n")
    
    # Detailed peak windows
    if peak_windows:
        lines.append("## 🚨 Problematic Time Windows\n\n")
        lines.append("| Time Window | Orders | On-Time Rate | Failed Rate | Avg Delivery (min) | P90 Delivery (min) | Recommendation |\n")
        lines.append("|-------------|--------|--------------|-------------|---------------------|---------------------|----------------|\n")
        
        for window in peak_windows:
            start_time = f"{window.window_start_hour:02d}:{window.window_start_min:02d}"
            end_time = f"{window.window_end_hour:02d}:{window.window_end_min:02d}"
            time_range = f"{start_time}-{end_time}"
            
            # Generate recommendation
            recommendation = "Add runner"
            if window.failed_rate > 0.1:
                recommendation = "Add runner + restrict slowest holes"
            elif window.on_time_rate < 0.8:
                recommendation = "Add runner"
            elif window.on_time_rate < 0.9:
                recommendation = "Restrict slowest holes"
            
            lines.append(f"| {time_range} | {window.total_orders} | {window.on_time_rate:.1%} | {window.failed_rate:.1%} | {window.avg_delivery_time:.1f} | {window.p90_delivery_time:.1f} | {recommendation} |\n")
        
        lines.append("\n")
        
        # Hole restriction recommendations for peak windows
        lines.append("### Recommended Hole Restrictions During Peak Windows\n\n")
        
        # Aggregate zone performance across all peak windows
        all_zone_times = defaultdict(list)
        for window in peak_windows:
            for zone, times in window.zone_service_times.items():
                all_zone_times[zone].extend(times)
        
        # Calculate average service times per zone
        zone_avg_times = {}
        for zone, times in all_zone_times.items():
            if times:
                zone_avg_times[zone] = statistics.mean(times)
        
        if zone_avg_times:
            slowest_zones = sorted(zone_avg_times.items(), key=lambda x: x[1], reverse=True)[:5]
            
            lines.append("**Slowest holes during peak periods:**\n\n")
            for i, (zone, avg_time) in enumerate(slowest_zones, 1):
                hole_num = zone.replace('hole_', '') if zone.startswith('hole_') else zone
                lines.append(f"{i}. Hole {hole_num}: {avg_time:.1f} minutes average service time\n")
            
            lines.append(f"\n**Recommendation:** Consider restricting the top 3 slowest holes during peak windows to maintain service quality.\n\n")
    
    # Overall performance by hour
    lines.append("## Performance by Time Window\n\n")
    lines.append("| Time Window | Orders | On-Time Rate | Failed Rate | Avg Delivery (min) | Status |\n")
    lines.append("|-------------|--------|--------------|-------------|---------------------|--------|\n")
    
    for window in windows:
        start_time = f"{window.window_start_hour:02d}:{window.window_start_min:02d}"
        end_time = f"{window.window_end_hour:02d}:{window.window_end_min:02d}"
        time_range = f"{start_time}-{end_time}"
        
        # Status indicator
        status = "✅ Good"
        if window in peak_windows:
            if window.failed_rate > 0.1:
                status = "🔴 Critical"
            elif window.on_time_rate < 0.8:
                status = "🟠 Poor"
            else:
                status = "🟡 Warning"
        
        lines.append(f"| {time_range} | {window.total_orders} | {window.on_time_rate:.1%} | {window.failed_rate:.1%} | {window.avg_delivery_time:.1f} | {status} |\n")
    
    lines.append("\n")
    lines.append("**SLA Targets:** On-time ≥ 95%, Failed ≤ 5%\n")
    
    with output_path.open('w', encoding='utf-8') as f:
        f.writelines(lines)


def main() -> None:
    args = parse_args()
    
    experiment_dir = Path(args.experiment_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load data from all runs
    all_orders = []
    run_count = 0
    
    for run_dir in experiment_dir.iterdir():
        if run_dir.is_dir() and run_dir.name.startswith('run_'):
            run_orders = load_run_data(run_dir, args.sla_minutes)
            all_orders.extend(run_orders)
            run_count += 1
    
    if not all_orders:
        print("No order data found!")
        return
    
    print(f"Loaded {len(all_orders)} orders from {run_count} runs")
    
    # Analyze time windows
    windows = analyze_time_windows(
        all_orders, 
        args.window_size, 
        args.service_start_hour, 
        args.service_end_hour
    )
    
    # Identify peak windows
    peak_windows = identify_peak_windows(windows)
    
    print(f"Analyzed {len(windows)} time windows")
    print(f"Identified {len(peak_windows)} problematic windows")
    
    # Write outputs
    csv_path = output_dir / "time_window_analysis.csv"
    write_window_analysis_csv(csv_path, windows)
    print(f"Window analysis CSV written to: {csv_path}")
    
    md_path = output_dir / "peak_window_recommendations.md"
    write_peak_recommendations_md(md_path, windows, peak_windows, args.window_size)
    print(f"Peak window recommendations written to: {md_path}")


if __name__ == "__main__":
    main()
