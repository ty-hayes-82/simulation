#!/usr/bin/env python3
"""
Analyze 3-hole blocking triad experiments to identify optimal hole restrictions.

This script reads the completed triad experiment results and compares performance
across different 3-hole blocking sequences to recommend targeted restrictions.

Usage:
  python scripts/optimization/analyze_triad_experiments.py \
    --triads-root outputs/experiments/triads/real_tee_sheet/orders_028 \
    --output-dir outputs/experiments/triads/analysis \
    --baseline-scenario real_tee_sheet \
    --baseline-orders 28
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class TriadMetrics:
    triad_name: str
    blocked_holes: List[int]
    runs_count: int
    on_time_rate_mean: float
    on_time_rate_std: float
    failed_rate_mean: float
    failed_rate_std: float
    p90_mean: float
    p90_std: float
    orders_per_runner_hour_mean: float
    orders_per_runner_hour_std: float
    total_orders_mean: float
    successful_orders_mean: float
    improvement_score: float = 0.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze 3-hole blocking triad experiments")
    parser.add_argument("--triads-root", required=True, help="Root directory of triad experiments")
    parser.add_argument("--output-dir", required=True, help="Output directory for analysis results")
    parser.add_argument("--baseline-dir", help="Baseline experiment directory (if different from standard location)")
    parser.add_argument("--baseline-scenario", default="real_tee_sheet", help="Baseline scenario name")
    parser.add_argument("--baseline-orders", type=int, default=28, help="Baseline order count")
    parser.add_argument("--target-on-time", type=float, default=0.95, help="Target on-time rate")
    parser.add_argument("--max-failed-rate", type=float, default=0.05, help="Maximum failed rate")
    parser.add_argument("--max-p90", type=float, default=40.0, help="Maximum p90 delivery time (minutes)")
    return parser.parse_args()


def extract_triad_holes(triad_name: str) -> List[int]:
    """Extract hole numbers from triad name like 'triad_3_5'."""
    try:
        parts = triad_name.split('_')
        if len(parts) >= 3:
            start = int(parts[1])
            end = int(parts[2])
            return list(range(start, end + 1))
    except (ValueError, IndexError):
        pass
    return []


def load_triad_metrics(triad_dir: Path) -> Optional[TriadMetrics]:
    """Load metrics from a single triad experiment directory."""
    if not triad_dir.is_dir():
        return None
    
    triad_name = triad_dir.name
    blocked_holes = extract_triad_holes(triad_name)
    
    # Collect metrics from all runs
    metrics_data = []
    for run_dir in triad_dir.iterdir():
        if not run_dir.is_dir() or not run_dir.name.startswith('run_'):
            continue
        
        metrics_file = run_dir / f"delivery_runner_metrics_{run_dir.name}.json"
        if metrics_file.exists():
            try:
                with metrics_file.open('r', encoding='utf-8') as f:
                    data = json.load(f)
                    metrics_data.append(data)
            except Exception:
                continue
    
    if not metrics_data:
        return None
    
    # Calculate aggregated statistics
    def safe_mean(values: List[float]) -> float:
        return statistics.mean(values) if values else 0.0
    
    def safe_stdev(values: List[float]) -> float:
        return statistics.stdev(values) if len(values) > 1 else 0.0
    
    on_time_rates = [m.get("on_time_rate", 0.0) for m in metrics_data]
    failed_rates = [m.get("failed_rate", 0.0) for m in metrics_data]
    p90_times = [m.get("delivery_cycle_time_p90", 0.0) for m in metrics_data]
    orders_per_hour = [m.get("orders_per_runner_hour", 0.0) for m in metrics_data]
    total_orders = [m.get("total_orders", 0) for m in metrics_data]
    successful_orders = [m.get("successful_orders", 0) for m in metrics_data]
    
    return TriadMetrics(
        triad_name=triad_name,
        blocked_holes=blocked_holes,
        runs_count=len(metrics_data),
        on_time_rate_mean=safe_mean(on_time_rates),
        on_time_rate_std=safe_stdev(on_time_rates),
        failed_rate_mean=safe_mean(failed_rates),
        failed_rate_std=safe_stdev(failed_rates),
        p90_mean=safe_mean(p90_times),
        p90_std=safe_stdev(p90_times),
        orders_per_runner_hour_mean=safe_mean(orders_per_hour),
        orders_per_runner_hour_std=safe_stdev(orders_per_hour),
        total_orders_mean=safe_mean(total_orders),
        successful_orders_mean=safe_mean(successful_orders),
    )


def load_baseline_metrics(baseline_exp_dir: Path, scenario: str, orders: int) -> Optional[TriadMetrics]:
    """Load baseline metrics (no hole blocking) for comparison."""
    # Look for baseline experiment with 1 runner and specified orders
    baseline_dir = baseline_exp_dir / scenario / f"orders_{orders:03d}" / "runners_1"
    
    if not baseline_dir.exists():
        return None
    
    # Collect metrics from all runs
    metrics_data = []
    for i in range(1, 6):  # Assume up to 5 runs
        metrics_file = baseline_dir / f"run_{i:02d}" / f"delivery_runner_metrics_run_{i:02d}.json"
        if metrics_file.exists():
            try:
                with metrics_file.open('r', encoding='utf-8') as f:
                    data = json.load(f)
                    metrics_data.append(data)
            except Exception:
                continue
    
    if not metrics_data:
        return None
    
    # Calculate aggregated statistics (same as triad metrics)
    def safe_mean(values: List[float]) -> float:
        return statistics.mean(values) if values else 0.0
    
    def safe_stdev(values: List[float]) -> float:
        return statistics.stdev(values) if len(values) > 1 else 0.0
    
    on_time_rates = [m.get("on_time_rate", 0.0) for m in metrics_data]
    failed_rates = [m.get("failed_rate", 0.0) for m in metrics_data]
    p90_times = [m.get("delivery_cycle_time_p90", 0.0) for m in metrics_data]
    orders_per_hour = [m.get("orders_per_runner_hour", 0.0) for m in metrics_data]
    total_orders = [m.get("total_orders", 0) for m in metrics_data]
    successful_orders = [m.get("successful_orders", 0) for m in metrics_data]
    
    return TriadMetrics(
        triad_name="baseline",
        blocked_holes=[],
        runs_count=len(metrics_data),
        on_time_rate_mean=safe_mean(on_time_rates),
        on_time_rate_std=safe_stdev(on_time_rates),
        failed_rate_mean=safe_mean(failed_rates),
        failed_rate_std=safe_stdev(failed_rates),
        p90_mean=safe_mean(p90_times),
        p90_std=safe_stdev(p90_times),
        orders_per_runner_hour_mean=safe_mean(orders_per_hour),
        orders_per_runner_hour_std=safe_stdev(orders_per_hour),
        total_orders_mean=safe_mean(total_orders),
        successful_orders_mean=safe_mean(successful_orders),
    )


def calculate_improvement_score(triad: TriadMetrics, baseline: TriadMetrics) -> float:
    """Calculate improvement score relative to baseline."""
    if baseline.on_time_rate_mean == 0:
        return 0.0
    
    # Weighted improvement score
    on_time_improvement = (triad.on_time_rate_mean - baseline.on_time_rate_mean) / baseline.on_time_rate_mean
    failed_improvement = (baseline.failed_rate_mean - triad.failed_rate_mean) / max(baseline.failed_rate_mean, 0.001)
    p90_improvement = (baseline.p90_mean - triad.p90_mean) / max(baseline.p90_mean, 1.0)
    
    # Penalize for order reduction
    order_penalty = (baseline.total_orders_mean - triad.total_orders_mean) / max(baseline.total_orders_mean, 1.0)
    
    # Composite score (higher is better)
    score = (0.4 * on_time_improvement + 0.3 * failed_improvement + 0.2 * p90_improvement - 0.1 * order_penalty)
    return score


def meets_targets(triad: TriadMetrics, target_on_time: float, max_failed: float, max_p90: float) -> bool:
    """Check if triad meets SLA targets."""
    return (
        triad.on_time_rate_mean >= target_on_time and
        triad.failed_rate_mean <= max_failed and
        triad.p90_mean <= max_p90
    )


def write_analysis_csv(output_path: Path, triads: List[TriadMetrics], baseline: Optional[TriadMetrics]) -> None:
    """Write detailed analysis to CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with output_path.open('w', newline='', encoding='utf-8') as f:
        fieldnames = [
            'triad_name', 'blocked_holes', 'runs_count',
            'on_time_rate_mean', 'on_time_rate_std',
            'failed_rate_mean', 'failed_rate_std',
            'p90_mean', 'p90_std',
            'orders_per_runner_hour_mean', 'orders_per_runner_hour_std',
            'total_orders_mean', 'successful_orders_mean',
            'improvement_score', 'meets_targets'
        ]
        
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        
        # Add baseline if available
        if baseline:
            writer.writerow({
                'triad_name': baseline.triad_name,
                'blocked_holes': '',
                'runs_count': baseline.runs_count,
                'on_time_rate_mean': round(baseline.on_time_rate_mean, 4),
                'on_time_rate_std': round(baseline.on_time_rate_std, 4),
                'failed_rate_mean': round(baseline.failed_rate_mean, 4),
                'failed_rate_std': round(baseline.failed_rate_std, 4),
                'p90_mean': round(baseline.p90_mean, 2),
                'p90_std': round(baseline.p90_std, 2),
                'orders_per_runner_hour_mean': round(baseline.orders_per_runner_hour_mean, 3),
                'orders_per_runner_hour_std': round(baseline.orders_per_runner_hour_std, 3),
                'total_orders_mean': round(baseline.total_orders_mean, 1),
                'successful_orders_mean': round(baseline.successful_orders_mean, 1),
                'improvement_score': 0.0,
                'meets_targets': meets_targets(baseline, 0.95, 0.05, 40.0)
            })
        
        # Add triads
        for triad in triads:
            writer.writerow({
                'triad_name': triad.triad_name,
                'blocked_holes': '-'.join(map(str, triad.blocked_holes)),
                'runs_count': triad.runs_count,
                'on_time_rate_mean': round(triad.on_time_rate_mean, 4),
                'on_time_rate_std': round(triad.on_time_rate_std, 4),
                'failed_rate_mean': round(triad.failed_rate_mean, 4),
                'failed_rate_std': round(triad.failed_rate_std, 4),
                'p90_mean': round(triad.p90_mean, 2),
                'p90_std': round(triad.p90_std, 2),
                'orders_per_runner_hour_mean': round(triad.orders_per_runner_hour_mean, 3),
                'orders_per_runner_hour_std': round(triad.orders_per_runner_hour_std, 3),
                'total_orders_mean': round(triad.total_orders_mean, 1),
                'successful_orders_mean': round(triad.successful_orders_mean, 1),
                'improvement_score': round(triad.improvement_score, 4),
                'meets_targets': meets_targets(triad, 0.95, 0.05, 40.0)
            })


def write_recommendations_md(output_path: Path, triads: List[TriadMetrics], baseline: Optional[TriadMetrics], 
                           target_on_time: float, max_failed: float, max_p90: float) -> None:
    """Write GM recommendations markdown."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Sort triads by improvement score
    sorted_triads = sorted(triads, key=lambda t: t.improvement_score, reverse=True)
    
    # Find best performing triads that meet targets
    meeting_targets = [t for t in sorted_triads if meets_targets(t, target_on_time, max_failed, max_p90)]
    
    lines = []
    lines.append("# 3-Hole Blocking Triad Analysis\n\n")
    lines.append("## Executive Summary\n\n")
    
    if baseline:
        lines.append(f"**Baseline Performance (No Blocking):**\n")
        lines.append(f"- On-time rate: {baseline.on_time_rate_mean:.1%} ± {baseline.on_time_rate_std:.1%}\n")
        lines.append(f"- Failed rate: {baseline.failed_rate_mean:.1%} ± {baseline.failed_rate_std:.1%}\n")
        lines.append(f"- P90 delivery time: {baseline.p90_mean:.1f} ± {baseline.p90_std:.1f} minutes\n")
        lines.append(f"- Orders per runner hour: {baseline.orders_per_runner_hour_mean:.2f}\n")
        lines.append(f"- Total orders: {baseline.total_orders_mean:.0f}\n\n")
    
    if meeting_targets:
        lines.append("## ✅ Recommended Hole Restrictions (Meet SLA Targets)\n\n")
        lines.append("| Rank | Blocked Holes | On-Time Rate | Failed Rate | P90 (min) | Orders/Hour | Improvement Score |\n")
        lines.append("|------|---------------|--------------|-------------|-----------|-------------|-------------------|\n")
        
        for i, triad in enumerate(meeting_targets[:5], 1):  # Top 5
            holes_str = ', '.join(map(str, triad.blocked_holes))
            lines.append(f"| {i} | {holes_str} | {triad.on_time_rate_mean:.1%} | {triad.failed_rate_mean:.1%} | {triad.p90_mean:.1f} | {triad.orders_per_runner_hour_mean:.2f} | {triad.improvement_score:.3f} |\n")
        
        lines.append("\n")
        
        # Detailed recommendations
        best_triad = meeting_targets[0]
        lines.append("### 🎯 Primary Recommendation\n\n")
        lines.append(f"**Block holes {', '.join(map(str, best_triad.blocked_holes))}** for 1-runner days with {int(baseline.total_orders_mean if baseline else 28)} orders.\n\n")
        lines.append("**Benefits:**\n")
        if baseline:
            on_time_improvement = (best_triad.on_time_rate_mean - baseline.on_time_rate_mean) * 100
            failed_improvement = (baseline.failed_rate_mean - best_triad.failed_rate_mean) * 100
            p90_improvement = baseline.p90_mean - best_triad.p90_mean
            lines.append(f"- On-time rate improves by {on_time_improvement:+.1f} percentage points\n")
            lines.append(f"- Failed rate improves by {failed_improvement:+.1f} percentage points\n")
            lines.append(f"- P90 delivery time improves by {p90_improvement:+.1f} minutes\n")
        lines.append(f"- Maintains {best_triad.orders_per_runner_hour_mean:.2f} orders per runner hour\n\n")
    else:
        lines.append("## ⚠️ No Restrictions Meet All SLA Targets\n\n")
        lines.append("Consider relaxing targets or increasing staffing. Best performing restrictions:\n\n")
        
        lines.append("| Rank | Blocked Holes | On-Time Rate | Failed Rate | P90 (min) | Improvement Score |\n")
        lines.append("|------|---------------|--------------|-------------|-----------|-------------------|\n")
        
        for i, triad in enumerate(sorted_triads[:5], 1):  # Top 5
            holes_str = ', '.join(map(str, triad.blocked_holes))
            lines.append(f"| {i} | {holes_str} | {triad.on_time_rate_mean:.1%} | {triad.failed_rate_mean:.1%} | {triad.p90_mean:.1f} | {triad.improvement_score:.3f} |\n")
        
        lines.append("\n")
    
    # Analysis by hole position
    lines.append("## Analysis by Course Position\n\n")
    front_nine = [t for t in triads if t.blocked_holes and max(t.blocked_holes) <= 9]
    back_nine = [t for t in triads if t.blocked_holes and min(t.blocked_holes) >= 10]
    mixed = [t for t in triads if t.blocked_holes and min(t.blocked_holes) <= 9 and max(t.blocked_holes) >= 10]
    
    if front_nine:
        best_front = max(front_nine, key=lambda t: t.improvement_score)
        lines.append(f"**Best Front Nine Restriction:** Holes {', '.join(map(str, best_front.blocked_holes))} (Score: {best_front.improvement_score:.3f})\n")
    
    if back_nine:
        best_back = max(back_nine, key=lambda t: t.improvement_score)
        lines.append(f"**Best Back Nine Restriction:** Holes {', '.join(map(str, best_back.blocked_holes))} (Score: {best_back.improvement_score:.3f})\n")
    
    if mixed:
        best_mixed = max(mixed, key=lambda t: t.improvement_score)
        lines.append(f"**Best Mixed Restriction:** Holes {', '.join(map(str, best_mixed.blocked_holes))} (Score: {best_mixed.improvement_score:.3f})\n")
    
    lines.append(f"\n**SLA Targets:** On-time ≥ {target_on_time:.0%}, Failed ≤ {max_failed:.0%}, P90 ≤ {max_p90:.0f} min\n")
    
    with output_path.open('w', encoding='utf-8') as f:
        f.writelines(lines)


def load_baseline_from_dir(baseline_dir: Path) -> Optional[TriadMetrics]:
    """Load baseline metrics from a specific directory."""
    if not baseline_dir.exists():
        return None
    
    # Collect metrics from all runs
    metrics_data = []
    for run_dir in baseline_dir.iterdir():
        if not run_dir.is_dir() or not run_dir.name.startswith('run_'):
            continue
        
        # Look for metrics file
        for metrics_file in run_dir.glob("delivery_runner_metrics_*.json"):
            try:
                with metrics_file.open('r', encoding='utf-8') as f:
                    data = json.load(f)
                    metrics_data.append(data)
                break  # Only take first metrics file per run
            except Exception:
                continue
    
    if not metrics_data:
        return None
    
    # Calculate aggregated statistics (same as triad metrics)
    def safe_mean(values: List[float]) -> float:
        return statistics.mean(values) if values else 0.0
    
    def safe_stdev(values: List[float]) -> float:
        return statistics.stdev(values) if len(values) > 1 else 0.0
    
    on_time_rates = [m.get("on_time_rate", 0.0) for m in metrics_data]
    failed_rates = [m.get("failed_rate", 0.0) for m in metrics_data]
    p90_times = [m.get("delivery_cycle_time_p90", 0.0) for m in metrics_data]
    orders_per_hour = [m.get("orders_per_runner_hour", 0.0) for m in metrics_data]
    total_orders = [m.get("total_orders", 0) for m in metrics_data]
    successful_orders = [m.get("successful_orders", 0) for m in metrics_data]
    
    return TriadMetrics(
        triad_name="baseline",
        blocked_holes=[],
        runs_count=len(metrics_data),
        on_time_rate_mean=safe_mean(on_time_rates),
        on_time_rate_std=safe_stdev(on_time_rates),
        failed_rate_mean=safe_mean(failed_rates),
        failed_rate_std=safe_stdev(failed_rates),
        p90_mean=safe_mean(p90_times),
        p90_std=safe_stdev(p90_times),
        orders_per_runner_hour_mean=safe_mean(orders_per_hour),
        orders_per_runner_hour_std=safe_stdev(orders_per_hour),
        total_orders_mean=safe_mean(total_orders),
        successful_orders_mean=safe_mean(successful_orders),
    )


def main() -> None:
    args = parse_args()
    
    triads_root = Path(args.triads_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load baseline metrics
    baseline = None
    if args.baseline_dir:
        baseline = load_baseline_from_dir(Path(args.baseline_dir))
    else:
        baseline_exp_dir = triads_root.parent.parent  # Go up to experiments root
        baseline = load_baseline_metrics(baseline_exp_dir, args.baseline_scenario, args.baseline_orders)
    
    # Load all triad metrics
    triads = []
    for triad_dir in triads_root.iterdir():
        if triad_dir.is_dir() and triad_dir.name.startswith('triad_'):
            triad_metrics = load_triad_metrics(triad_dir)
            if triad_metrics:
                # Calculate improvement score relative to baseline
                if baseline:
                    triad_metrics.improvement_score = calculate_improvement_score(triad_metrics, baseline)
                triads.append(triad_metrics)
    
    if not triads:
        print("No triad data found!")
        return
    
    print(f"Loaded {len(triads)} triad experiments")
    if baseline:
        print(f"Baseline: {baseline.on_time_rate_mean:.1%} on-time, {baseline.failed_rate_mean:.1%} failed, {baseline.p90_mean:.1f}min p90")
    
    # Write analysis outputs
    csv_path = output_dir / "triad_analysis.csv"
    write_analysis_csv(csv_path, triads, baseline)
    print(f"Analysis CSV written to: {csv_path}")
    
    md_path = output_dir / "triad_recommendations.md"
    write_recommendations_md(md_path, triads, baseline, args.target_on_time, args.max_failed_rate, args.max_p90)
    print(f"Recommendations written to: {md_path}")


if __name__ == "__main__":
    main()
