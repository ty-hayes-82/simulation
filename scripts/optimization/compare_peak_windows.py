#!/usr/bin/env python3
"""
Compare peak window performance across different staffing levels or policy configurations.

Usage:
  python scripts/optimization/compare_peak_windows.py \
    --baseline-dir outputs/20250823_071519_delivery_runner_1_runners_real_tee_sheet \
    --comparison-dirs outputs/experiments/triads/real_tee_sheet/orders_028/triad_10_12 \
    --output-dir outputs/experiments/peak_comparison \
    --labels "Baseline" "Holes 10-12 Blocked"
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import List

# Import the analysis functions from the peak window script
import sys
sys.path.append(str(Path(__file__).parent))
from analyze_peak_windows import load_run_data, analyze_time_windows, identify_peak_windows


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare peak window performance across configurations")
    parser.add_argument("--baseline-dir", required=True, help="Baseline experiment directory")
    parser.add_argument("--comparison-dirs", nargs="+", required=True, help="Comparison experiment directories")
    parser.add_argument("--labels", nargs="+", help="Labels for each configuration")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    parser.add_argument("--window-size", type=int, default=60, help="Time window size in minutes")
    parser.add_argument("--sla-minutes", type=int, default=30, help="SLA threshold in minutes")
    return parser.parse_args()


def analyze_experiment(exp_dir: Path, window_size_min: int, sla_minutes: int) -> dict:
    """Analyze a single experiment directory."""
    all_orders = []
    run_count = 0
    
    for run_dir in exp_dir.iterdir():
        if run_dir.is_dir() and run_dir.name.startswith('run_'):
            run_orders = load_run_data(run_dir, sla_minutes)
            all_orders.extend(run_orders)
            run_count += 1
    
    if not all_orders:
        return {"orders": [], "windows": [], "peak_windows": [], "run_count": 0}
    
    windows = analyze_time_windows(all_orders, window_size_min, 7, 17)
    peak_windows = identify_peak_windows(windows)
    
    return {
        "orders": all_orders,
        "windows": windows,
        "peak_windows": peak_windows,
        "run_count": run_count
    }


def write_comparison_report(output_path: Path, baseline_result: dict, comparison_results: List[dict], labels: List[str]) -> None:
    """Write comparative peak window analysis."""
    lines = []
    lines.append("# Peak Window Performance Comparison\n\n")
    
    # Summary table
    lines.append("## Configuration Summary\n\n")
    lines.append("| Configuration | Total Orders | Runs | Peak Windows | Avg Peak On-Time Rate |\n")
    lines.append("|---------------|--------------|------|--------------|----------------------|\n")
    
    all_results = [baseline_result] + comparison_results
    
    for i, (result, label) in enumerate(zip(all_results, labels)):
        total_orders = len(result["orders"])
        run_count = result["run_count"]
        peak_count = len(result["peak_windows"])
        
        if result["peak_windows"]:
            avg_peak_on_time = sum(w.on_time_rate for w in result["peak_windows"]) / len(result["peak_windows"])
        else:
            avg_peak_on_time = 1.0  # No peak windows means all good
        
        lines.append(f"| {label} | {total_orders} | {run_count} | {peak_count} | {avg_peak_on_time:.1%} |\n")
    
    lines.append("\n")
    
    # Detailed comparison by time window
    lines.append("## Performance by Time Window\n\n")
    
    # Get all unique time windows
    all_windows = set()
    for result in all_results:
        for window in result["windows"]:
            all_windows.add((window.window_start_hour, window.window_start_min))
    
    sorted_windows = sorted(all_windows)
    
    if sorted_windows:
        # Create header
        header = "| Time Window |"
        separator = "|-------------|"
        for label in labels:
            header += f" {label} On-Time |"
            separator += "---------------|"
        lines.append(header + "\n")
        lines.append(separator + "\n")
        
        # Add data rows
        for start_hour, start_min in sorted_windows:
            end_hour = start_hour
            end_min = start_min + 60
            if end_min >= 60:
                end_hour += 1
                end_min = 0
            
            time_str = f"{start_hour:02d}:{start_min:02d}-{end_hour:02d}:{end_min:02d}"
            row = f"| {time_str} |"
            
            for result in all_results:
                # Find matching window
                matching_window = None
                for window in result["windows"]:
                    if window.window_start_hour == start_hour and window.window_start_min == start_min:
                        matching_window = window
                        break
                
                if matching_window:
                    on_time_str = f"{matching_window.on_time_rate:.1%} ({matching_window.total_orders})"
                else:
                    on_time_str = "No data"
                
                row += f" {on_time_str} |"
            
            lines.append(row + "\n")
    
    lines.append("\n")
    
    # Recommendations
    lines.append("## Recommendations\n\n")
    
    baseline_peak_count = len(baseline_result["peak_windows"])
    
    if baseline_peak_count == 0:
        lines.append("✅ **Baseline configuration performs well** with no problematic time windows.\n\n")
        
        # Check if any comparison configurations are worse
        worse_configs = []
        for i, (result, label) in enumerate(zip(comparison_results, labels[1:])):
            if len(result["peak_windows"]) > 0:
                worse_configs.append((label, len(result["peak_windows"])))
        
        if worse_configs:
            lines.append("⚠️ **Alternative configurations show degraded performance:**\n")
            for config, peak_count in worse_configs:
                lines.append(f"- {config}: {peak_count} problematic windows\n")
            lines.append("\n**Recommendation:** Stick with baseline configuration.\n\n")
    else:
        lines.append(f"⚠️ **Baseline has {baseline_peak_count} problematic time windows.**\n\n")
        
        # Check if any comparison configurations are better
        better_configs = []
        for i, (result, label) in enumerate(zip(comparison_results, labels[1:])):
            comparison_peak_count = len(result["peak_windows"])
            if comparison_peak_count < baseline_peak_count:
                if result["peak_windows"]:
                    avg_on_time = sum(w.on_time_rate for w in result["peak_windows"]) / len(result["peak_windows"])
                else:
                    avg_on_time = 1.0
                better_configs.append((label, comparison_peak_count, avg_on_time))
        
        if better_configs:
            lines.append("✅ **Better performing configurations identified:**\n")
            for config, peak_count, avg_on_time in sorted(better_configs, key=lambda x: x[1]):
                lines.append(f"- {config}: {peak_count} problematic windows, {avg_on_time:.1%} avg on-time in peaks\n")
            lines.append(f"\n**Recommendation:** Consider switching to {better_configs[0][0]} configuration.\n\n")
        else:
            lines.append("**Recommendation:** Consider increasing staffing during peak hours or implementing dynamic hole restrictions.\n\n")
    
    with output_path.open('w', encoding='utf-8') as f:
        f.writelines(lines)


def main() -> None:
    args = parse_args()
    
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Set up labels
    if args.labels:
        labels = args.labels
    else:
        labels = ["Baseline"] + [f"Config {i+1}" for i in range(len(args.comparison_dirs))]
    
    # Ensure we have enough labels
    total_configs = 1 + len(args.comparison_dirs)
    while len(labels) < total_configs:
        labels.append(f"Config {len(labels)}")
    
    # Analyze baseline
    print(f"Analyzing baseline: {args.baseline_dir}")
    baseline_result = analyze_experiment(Path(args.baseline_dir), args.window_size, args.sla_minutes)
    print(f"  - {len(baseline_result['orders'])} orders, {len(baseline_result['peak_windows'])} peak windows")
    
    # Analyze comparisons
    comparison_results = []
    for i, comp_dir in enumerate(args.comparison_dirs):
        print(f"Analyzing comparison {i+1}: {comp_dir}")
        result = analyze_experiment(Path(comp_dir), args.window_size, args.sla_minutes)
        comparison_results.append(result)
        print(f"  - {len(result['orders'])} orders, {len(result['peak_windows'])} peak windows")
    
    # Write comparison report
    report_path = output_dir / "peak_window_comparison.md"
    write_comparison_report(report_path, baseline_result, comparison_results, labels)
    print(f"Comparison report written to: {report_path}")


if __name__ == "__main__":
    main()
