#!/usr/bin/env python3
"""
Golf Delivery Simulation Results Analyzer

This script analyzes existing simulation results and creates comprehensive summaries
grouped by scenario type, showing detailed statistics and comparisons.
"""

import argparse
import json
import glob
import sys
import statistics
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any
import re

from golfsim.logging import init_logging, get_logger
from golfsim.config.loaders import load_tee_times_config
from utils import setup_encoding, add_log_level_argument, parse_csv_list

logger = get_logger(__name__)


    


def extract_scenario_from_path(path: str) -> str:
    """Extract scenario name from simulation output path."""
    # Pattern: multi_golfer_{scenario}_{timestamp}
    match = re.search(r'multi_golfer_([^_]+)_\d+', path)
    if match:
        return match.group(1)
    return "unknown"


def load_simulation_result(result_path: Path) -> Dict[str, Any]:
    """Load a single simulation result file."""
    try:
        with open(result_path, 'r') as f:
            data = json.load(f)

        if 'summary_stats' not in data:
            return {'success': False, 'error': 'Missing summary_stats'}

        summary_stats = data['summary_stats']

        # Extract key metrics with fallbacks
        total_orders = summary_stats.get('total_orders_generated', 0)
        processed_orders = summary_stats.get('orders_processed', 0)
        failed_orders = summary_stats.get(
            'orders_failed',
            summary_stats.get('orders_unprocessed', total_orders - processed_orders),
        )

        failure_rate = failed_orders / total_orders if total_orders > 0 else 0

        return {
            'success': True,
            'path': str(result_path.parent),
            'scenario': extract_scenario_from_path(str(result_path)),
            'metrics': {
                'total_orders': total_orders,
                'processed_orders': processed_orders,
                'failed_orders': failed_orders,
                'failure_rate': failure_rate,
                'success_rate': 1 - failure_rate,
                'avg_completion_time_min': summary_stats.get(
                    'avg_total_completion_min', summary_stats.get('avg_total_service_min', 0)
                ),
                'avg_queue_delay_min': summary_stats.get('avg_queue_delay_min', 0),
                'max_queue_delay_min': summary_stats.get('max_queue_delay_min', 0),
                'avg_delivery_time_min': summary_stats.get('avg_delivery_time_min', 0),
                'avg_drive_time_min': summary_stats.get('avg_total_drive_time_min', 0),
                'avg_delivery_distance_m': summary_stats.get('avg_delivery_distance_m', 0),
            },
            'detailed_stats': data.get('detailed_stats', []),
            'hourly_analysis': data.get('hourly_analysis', {}),
            'all_orders': data.get('all_orders', []),
        }

    except Exception as e:
        return {'success': False, 'error': str(e)}


def find_simulation_results(search_dirs: List[str]) -> List[Dict[str, Any]]:
    """Find all simulation result files in the specified directories."""
    results = []

    for search_dir in search_dirs:
        # Look for multi_golfer_*_*/multi_golfer_simulation_results.json
        pattern = f"{search_dir}/**/multi_golfer_simulation_results.json"
        result_files = glob.glob(pattern, recursive=True)

        logger.info("Found %d simulation results in %s", len(result_files), search_dir)

        for result_file in result_files:
            result_path = Path(result_file)
            result_data = load_simulation_result(result_path)

            if result_data['success']:
                results.append(result_data)
            else:
                logger.warning("Skipped %s: %s", result_path, result_data['error'])

    return results


def group_results_by_scenario(results: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Group simulation results by scenario type."""
    grouped = {}

    for result in results:
        scenario = result['scenario']
        if scenario not in grouped:
            grouped[scenario] = []
        grouped[scenario].append(result)

    return grouped


def calculate_scenario_statistics(scenario_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Calculate comprehensive statistics for a scenario."""
    if not scenario_results:
        return None

    # Basic info
    scenario_name = scenario_results[0]['scenario']
    total_runs = len(scenario_results)

    # Aggregate all metrics
    metrics_stats = {}
    for metric_name in [
        'total_orders',
        'processed_orders',
        'failed_orders',
        'failure_rate',
        'success_rate',
        'avg_completion_time_min',
        'avg_queue_delay_min',
        'max_queue_delay_min',
        'avg_delivery_time_min',
        'avg_drive_time_min',
        'avg_delivery_distance_m',
    ]:

        values = [r['metrics'][metric_name] for r in scenario_results]

        # Filter out zero values for timing metrics to get realistic averages
        if 'time' in metric_name or 'delay' in metric_name:
            non_zero_values = [v for v in values if v > 0]
            if non_zero_values:
                values_for_stats = non_zero_values
            else:
                values_for_stats = values
        else:
            values_for_stats = values

        if values_for_stats:
            metrics_stats[metric_name] = {
                'mean': statistics.mean(values_for_stats),
                'median': statistics.median(values_for_stats),
                'std_dev': statistics.stdev(values_for_stats) if len(values_for_stats) > 1 else 0,
                'min': min(values_for_stats),
                'max': max(values_for_stats),
                'count': len(values_for_stats),
                'total_count': len(values),
            }
        else:
            metrics_stats[metric_name] = {
                'mean': 0,
                'median': 0,
                'std_dev': 0,
                'min': 0,
                'max': 0,
                'count': 0,
                'total_count': len(values),
            }

    # Performance assessment
    avg_failure_rate = metrics_stats['failure_rate']['mean']
    avg_completion_time = metrics_stats['avg_completion_time_min']['mean']

    if avg_failure_rate < 0.05 and avg_completion_time > 0:
        performance = "EXCELLENT"
    elif avg_failure_rate < 0.15 and avg_completion_time > 0:
        performance = "GOOD"
    elif avg_failure_rate < 0.30 and avg_completion_time > 0:
        performance = "FAIR"
    else:
        performance = "POOR"

    # Consistency analysis
    cv_failure = (
        (metrics_stats['failure_rate']['std_dev'] / metrics_stats['failure_rate']['mean'])
        if metrics_stats['failure_rate']['mean'] > 0
        else 0
    )
    cv_completion = (
        (
            metrics_stats['avg_completion_time_min']['std_dev']
            / metrics_stats['avg_completion_time_min']['mean']
        )
        if metrics_stats['avg_completion_time_min']['mean'] > 0
        else 0
    )

    consistency = (
        "High"
        if max(cv_failure, cv_completion) > 0.5
        else "Moderate" if max(cv_failure, cv_completion) > 0.25 else "Low"
    )

    return {
        'scenario': scenario_name,
        'total_runs': total_runs,
        'metrics': metrics_stats,
        'performance': performance,
        'consistency': consistency,
        'cv_failure_rate': cv_failure,
        'cv_completion_time': cv_completion,
    }


def generate_comprehensive_report(
    grouped_results: Dict[str, List[Dict[str, Any]]],
    tee_times_config: Dict[str, Any],
    output_file: Path,
):
    """Generate a comprehensive analysis report."""

    with open(output_file, 'w', encoding='utf-8', errors='replace') as f:
        f.write("# Golf Delivery Simulation Results Analysis\n\n")
        f.write(f"**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

        # Executive Summary
        total_scenarios = len(grouped_results)
        total_simulations = sum(len(results) for results in grouped_results.values())

        f.write("## Executive Summary\n\n")
        f.write(f"- **Scenarios Analyzed**: {total_scenarios}\n")
        f.write(f"- **Total Simulations**: {total_simulations}\n")
        f.write(f"- **Average Runs per Scenario**: {total_simulations/total_scenarios:.1f}\n\n")

        # Calculate statistics for each scenario
        scenario_statistics = {}
        for scenario, results in grouped_results.items():
            scenario_statistics[scenario] = calculate_scenario_statistics(results)

        # Performance Overview Table
        f.write("## Performance Overview\n\n")
        f.write(
            "| Scenario | Runs | Performance | Orders/Day | Success Rate | Avg Delivery | Consistency |\n"
        )
        f.write(
            "|----------|------|-------------|------------|--------------|--------------|-------------|\n"
        )

        for scenario, stats in scenario_statistics.items():
            if stats:
                f.write(
                    f"| {scenario} | {stats['total_runs']} | {stats['performance']} | "
                    f"{stats['metrics']['total_orders']['mean']:.1f} | "
                    f"{stats['metrics']['success_rate']['mean']:.1%} | "
                    f"{stats['metrics']['avg_completion_time_min']['mean']:.1f} min | "
                    f"{stats['consistency']} Variability |\n"
                )
        f.write("\n")

        # Best and Worst Performers
        valid_scenarios = [s for s in scenario_statistics.values() if s is not None]
        if valid_scenarios:
            best_scenario = max(valid_scenarios, key=lambda x: x['metrics']['success_rate']['mean'])
            worst_scenario = min(
                valid_scenarios, key=lambda x: x['metrics']['success_rate']['mean']
            )

            f.write("## Key Findings\n\n")
            f.write(f"Best Performing Scenario: {best_scenario['scenario']}\n")
            f.write(f"   - Success Rate: {best_scenario['metrics']['success_rate']['mean']:.1%}\n")
            f.write(
                f"   - Avg Delivery Time: {best_scenario['metrics']['avg_completion_time_min']['mean']:.1f} minutes\n"
            )
            f.write(f"   - Performance: {best_scenario['performance']}\n\n")

            f.write(f"Lowest Performing Scenario: {worst_scenario['scenario']}\n")
            f.write(f"   - Success Rate: {worst_scenario['metrics']['success_rate']['mean']:.1%}\n")
            f.write(
                f"   - Avg Delivery Time: {worst_scenario['metrics']['avg_completion_time_min']['mean']:.1f} minutes\n"
            )
            f.write(f"   - Performance: {worst_scenario['performance']}\n\n")

        # Detailed Analysis by Scenario
        f.write("## Detailed Scenario Analysis\n\n")

        for scenario, results in grouped_results.items():
            stats = scenario_statistics[scenario]
            if not stats:
                continue

            scenario_config = tee_times_config.get(scenario, {})

            f.write(f"### {scenario_config.get('name', scenario.replace('_', ' ').title())}\n\n")

            if scenario_config:
                f.write(f"**Configuration**:\n")
                f.write(f"- Description: {scenario_config.get('description', 'No description')}\n")
                f.write(
                    f"- Expected Daily Golfers: {scenario_config.get('total_daily_golfers', 'Unknown')}\n"
                )
                f.write(f"- Simulation Runs: {stats['total_runs']}\n\n")

            metrics = stats['metrics']

            f.write(f"**Performance Metrics**:\n")
            f.write(f"- **Overall Performance**: {stats['performance']}\n")
            f.write(
                f"- **Order Volume**: {metrics['total_orders']['mean']:.1f} ± {metrics['total_orders']['std_dev']:.1f} orders/day\n"
            )
            f.write(
                f"  - Range: {metrics['total_orders']['min']:.0f} - {metrics['total_orders']['max']:.0f}\n"
            )
            f.write(
                f"- **Processing Rate**: {metrics['processed_orders']['mean']:.1f} ± {metrics['processed_orders']['std_dev']:.1f} orders/day\n"
            )
            f.write(
                f"  - Range: {metrics['processed_orders']['min']:.0f} - {metrics['processed_orders']['max']:.0f}\n"
            )
            f.write(
                f"- **Success Rate**: {metrics['success_rate']['mean']:.1%} ± {metrics['success_rate']['std_dev']:.1%}\n"
            )
            f.write(
                f"  - Range: {metrics['success_rate']['min']:.1%} - {metrics['success_rate']['max']:.1%}\n\n"
            )

            f.write(f"**Timing Analysis**:\n")
            if metrics['avg_completion_time_min']['mean'] > 0:
                f.write(
                    f"- **Delivery Time**: {metrics['avg_completion_time_min']['mean']:.1f} ± {metrics['avg_completion_time_min']['std_dev']:.1f} minutes\n"
                )
                f.write(
                    f"  - Range: {metrics['avg_completion_time_min']['min']:.1f} - {metrics['avg_completion_time_min']['max']:.1f} minutes\n"
                )
                f.write(
                    f"- **Queue Delay**: {metrics['avg_queue_delay_min']['mean']:.1f} ± {metrics['avg_queue_delay_min']['std_dev']:.1f} minutes\n"
                )
                f.write(
                    f"- **Peak Queue**: {metrics['max_queue_delay_min']['mean']:.1f} ± {metrics['max_queue_delay_min']['std_dev']:.1f} minutes\n"
                )
            else:
                f.write(f"- **Delivery Time**: No successful deliveries recorded\n")
            f.write("\n")

            f.write(f"**Operational Metrics**:\n")
            f.write(
                f"- **Delivery Distance**: {metrics['avg_delivery_distance_m']['mean']:.0f} ± {metrics['avg_delivery_distance_m']['std_dev']:.0f} meters\n"
            )
            f.write(
                f"- **Drive Time**: {metrics['avg_drive_time_min']['mean']:.1f} ± {metrics['avg_drive_time_min']['std_dev']:.1f} minutes\n"
            )
            f.write(f"- **Consistency**: {stats['consistency']} variability\n\n")

            # Recommendations
            f.write(f"**Recommendations**:\n")
            avg_orders = metrics['total_orders']['mean']
            processed = metrics['processed_orders']['mean']
            success_rate = metrics['success_rate']['mean']

            if success_rate < 0.8:
                f.write(f"- Critical: Low success rate ({success_rate:.1%}) needs immediate attention\n")
                f.write(f"- Consider extending service hours or adding capacity\n")
            elif processed < avg_orders * 0.3:
                f.write(f"- Capacity Issue: High demand ({avg_orders:.0f}) vs low processing ({processed:.0f})\n")
                f.write(f"- Consider additional runner during peak times\n")
            elif success_rate > 0.95:
                f.write(f"- Excellent Performance: System handling demand well\n")
                f.write(f"- Current setup appears optimal for this scenario\n")
            else:
                f.write(f"- Good Performance: Minor optimizations possible\n")
                f.write(f"- Monitor for consistent performance\n")

            if stats['consistency'] == "High":
                f.write(f"- Consistency: High variability suggests unstable performance\n")
                f.write(f"- Review queue management and service hours alignment\n")

            f.write("\n")

        # Technical Summary
        f.write("## Technical Summary\n\n")
        f.write("**Analysis Parameters**:\n")
        f.write(f"- Simulation Results Analyzed: {total_simulations}\n")
        f.write(f"- Scenarios Covered: {total_scenarios}\n")
        f.write(
            f"- Metrics Evaluated: Order volume, processing rate, success rate, timing, operational efficiency\n\n"
        )

        f.write("**Performance Classifications**:\n")
        f.write("- **EXCELLENT**: <5% failure rate with efficient delivery times\n")
        f.write("- **GOOD**: <15% failure rate with reasonable delivery times\n")
        f.write("- **FAIR**: <30% failure rate with acceptable delivery times\n")
        f.write("- **POOR**: >30% failure rate or no successful deliveries\n\n")


def load_tee_times_config(course_dir: str) -> Dict[str, Any]:
    """Load the tee times configuration file."""
    try:
        config_path = Path(course_dir) / "config" / "tee_times_config.json"
        with open(config_path, 'r') as f:
            return json.load(f)
    except:
        return {}


def main():
    setup_encoding()

    parser = argparse.ArgumentParser(
        description="Analyze Golf Delivery Simulation Results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python analyze_simulation_results.py --search-dirs outputs
  python analyze_simulation_results.py --search-dirs outputs,old_outputs --course-dir courses/pinetree_country_club
  python analyze_simulation_results.py --search-dirs outputs --output results_analysis.md
        """,
    )

    parser.add_argument(
        "--search-dirs",
        default="outputs",
        help="Comma-separated directories to search for results (default: outputs)",
    )
    parser.add_argument(
        "--course-dir",
        default="courses/pinetree_country_club",
        help="Course directory for tee times config (default: courses/pinetree_country_club)",
    )
    parser.add_argument(
        "--output", help="Output file for analysis report (default: auto-generated)"
    )
    parser.add_argument(
        "--scenario-filter", help="Only analyze specific scenarios (comma-separated)"
    )

    add_log_level_argument(parser)

    args = parser.parse_args()

    init_logging(args.log_level)
    logger.info("GOLF DELIVERY SIMULATION RESULTS ANALYZER")

    # Parse search directories
    search_dirs = [d.strip() for d in args.search_dirs.split(',')]
    logger.info("Searching directories: %s", ", ".join(search_dirs))

    # Find all simulation results
    results = find_simulation_results(search_dirs)

    if not results:
        logger.error("No simulation results found")
        sys.exit(1)

    logger.info("Found %d valid simulation results", len(results))

    # Group results by scenario
    grouped_results = group_results_by_scenario(results)

    # Apply scenario filter if specified
    if args.scenario_filter:
        filter_scenarios = parse_csv_list(args.scenario_filter)
        grouped_results = {k: v for k, v in grouped_results.items() if k in filter_scenarios}
        logger.info("Filtered to scenarios: %s", ", ".join(grouped_results.keys()))

    logger.info("Analyzing %d scenarios", len(grouped_results))
    for scenario, scenario_results in grouped_results.items():
        logger.info("   - %s: %d simulations", scenario, len(scenario_results))

    # Load tee times configuration for context
    tee_times_config = load_tee_times_config(args.course_dir)
    if tee_times_config:
        logger.info("Loaded tee times configuration from %s", args.course_dir)
    else:
        logger.warning("Could not load tee times config from %s", args.course_dir)

    # Generate output filename
    if args.output:
        output_file = Path(args.output)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = Path(f"simulation_analysis_{timestamp}.md")

    # Generate comprehensive report
    logger.info("Generating comprehensive analysis report...")
    generate_comprehensive_report(grouped_results, tee_times_config, output_file)

    # Display quick summary
    logger.info("ANALYSIS SUMMARY")

    for scenario, results in grouped_results.items():
        stats = calculate_scenario_statistics(results)
        if stats:
            success_rate = stats['metrics']['success_rate']['mean']
            avg_orders = stats['metrics']['total_orders']['mean']
            performance = stats['performance']

            logger.info("%-20s: %6.1f%% success, %4.1f orders/day, %s", scenario, success_rate * 100, avg_orders, performance)

    logger.info("ANALYSIS COMPLETE!")
    logger.info("Full report: %s", output_file)


if __name__ == "__main__":
    main()
