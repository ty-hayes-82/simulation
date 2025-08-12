"""
Example: Delivery Runner Metrics Usage

This script demonstrates how to use the delivery runner metrics module
to calculate and analyze metrics for delivery runner simulations.
"""

from pathlib import Path
from golfsim.analysis.delivery_runner_metrics import (
    calculate_delivery_runner_metrics,
    summarize_delivery_runner_metrics,
    format_delivery_runner_metrics_report,
    format_delivery_runner_summary_report,
    DeliveryRunnerMetrics,
)


def create_sample_delivery_data():
    """Create sample delivery data for demonstration."""
    
    # Sample delivery statistics
    delivery_stats = [
        {
            'order_id': '001',
            'golfer_group_id': 1,
            'hole_num': 5,
            'order_time_s': 3600,  # 1 hour into round
            'queue_delay_s': 300,  # 5 minutes in queue
            'prep_time_s': 600,    # 10 minutes prep
            'delivery_time_s': 900, # 15 minutes delivery
            'return_time_s': 900,  # 15 minutes return
            'total_drive_time_s': 1800,
            'delivery_distance_m': 800,
            'total_completion_time_s': 2700,  # 45 minutes total
            'delivered_at_time_s': 6300,
        },
        {
            'order_id': '002',
            'golfer_group_id': 2,
            'hole_num': 8,
            'order_time_s': 7200,  # 2 hours into round
            'queue_delay_s': 0,    # No queue delay
            'prep_time_s': 600,    # 10 minutes prep
            'delivery_time_s': 1200, # 20 minutes delivery
            'return_time_s': 1200, # 20 minutes return
            'total_drive_time_s': 2400,
            'delivery_distance_m': 1200,
            'total_completion_time_s': 3000,  # 50 minutes total
            'delivered_at_time_s': 10200,
        },
        {
            'order_id': '003',
            'golfer_group_id': 3,
            'hole_num': 12,
            'order_time_s': 10800, # 3 hours into round
            'queue_delay_s': 600,  # 10 minutes in queue
            'prep_time_s': 600,    # 10 minutes prep
            'delivery_time_s': 1500, # 25 minutes delivery
            'return_time_s': 1500, # 25 minutes return
            'total_drive_time_s': 3000,
            'delivery_distance_m': 1500,
            'total_completion_time_s': 4200,  # 70 minutes total
            'delivered_at_time_s': 15000,
        }
    ]
    
    # Sample activity log
    activity_log = [
        {'activity_type': 'delivery_start', 'timestamp_s': 0, 'description': 'Starting delivery for order 001'},
        {'activity_type': 'delivery_complete', 'timestamp_s': 1800, 'description': 'Delivered order 001'},
        {'activity_type': 'prep_start', 'timestamp_s': 1800, 'description': 'Starting prep for order 002'},
        {'activity_type': 'prep_complete', 'timestamp_s': 2400, 'description': 'Completed prep for order 002'},
        {'activity_type': 'delivery_start', 'timestamp_s': 2400, 'description': 'Starting delivery for order 002'},
        {'activity_type': 'delivery_complete', 'timestamp_s': 4800, 'description': 'Delivered order 002'},
        {'activity_type': 'queue_status', 'timestamp_s': 4800, 'description': '1 order waiting'},
        {'activity_type': 'prep_start', 'timestamp_s': 4800, 'description': 'Starting prep for order 003'},
        {'activity_type': 'prep_complete', 'timestamp_s': 5400, 'description': 'Completed prep for order 003'},
        {'activity_type': 'delivery_start', 'timestamp_s': 5400, 'description': 'Starting delivery for order 003'},
        {'activity_type': 'delivery_complete', 'timestamp_s': 8400, 'description': 'Delivered order 003'},
        {'activity_type': 'idle', 'timestamp_s': 8400, 'description': 'Runner idle'},
    ]
    
    # Sample orders
    orders = [
        {'golfer_group_id': 1, 'hole_num': 5, 'order_time_s': 3600, 'status': 'processed'},
        {'golfer_group_id': 2, 'hole_num': 8, 'order_time_s': 7200, 'status': 'processed'},
        {'golfer_group_id': 3, 'hole_num': 12, 'order_time_s': 10800, 'status': 'processed'},
    ]
    
    # Sample failed orders
    failed_orders = [
        {'order_id': '004', 'reason': 'Service closed before order could be processed'},
    ]
    
    return delivery_stats, activity_log, orders, failed_orders


def demonstrate_individual_metrics():
    """Demonstrate calculating metrics for a single simulation."""
    
    print("=== Individual Delivery Runner Metrics Example ===\n")
    
    # Create sample data
    delivery_stats, activity_log, orders, failed_orders = create_sample_delivery_data()
    
    # Calculate metrics
    metrics = calculate_delivery_runner_metrics(
        delivery_stats=delivery_stats,
        activity_log=activity_log,
        orders=orders,
        failed_orders=failed_orders,
        revenue_per_order=25.0,
        sla_minutes=30,
        simulation_id="example_simulation",
        runner_id="runner_1",
        service_hours=10.0,
    )
    
    # Display key metrics
    print(f"Simulation ID: {metrics.simulation_id}")
    print(f"Runner ID: {metrics.runner_id}")
    print(f"Total Orders: {metrics.total_orders}")
    print(f"Successful Orders: {metrics.successful_orders}")
    print(f"Failed Orders: {metrics.failed_orders}")
    print(f"Total Rounds: {metrics.total_rounds}")
    print()
    
    print("Core Business Metrics:")
    print(f"  Revenue per Round (RPR): ${metrics.revenue_per_round:.2f}")
    print(f"  Order Penetration Rate: {metrics.order_penetration_rate:.1%}")
    print(f"  Average Order Value (AOV): ${metrics.average_order_value:.2f}")
    print(f"  Orders per Runner-Hour: {metrics.orders_per_runner_hour:.2f}")
    print()
    
    print("Service Quality Metrics:")
    print(f"  On-Time Rate: {metrics.on_time_rate:.1%}")
    print(f"  Delivery Cycle Time (P50): {metrics.delivery_cycle_time_p50:.1f} minutes")
    print(f"  Delivery Cycle Time (P90): {metrics.delivery_cycle_time_p90:.1f} minutes")
    print(f"  Dispatch Delay (Avg): {metrics.dispatch_delay_avg:.1f} minutes")
    print(f"  Travel Time (Avg): {metrics.travel_time_avg:.1f} minutes")
    print(f"  Failed Rate: {metrics.failed_rate:.1%}")
    print()
    
    print("Operational Metrics:")
    print(f"  Runner Utilization - Driving: {metrics.runner_utilization_driving_pct:.1f}%")
    print(f"  Runner Utilization - Waiting: {metrics.runner_utilization_waiting_pct:.1f}%")
    print(f"  Runner Utilization - Handoff: {metrics.runner_utilization_handoff_pct:.1f}%")
    print(f"  Runner Utilization - Deadhead: {metrics.runner_utilization_deadhead_pct:.1f}%")
    print(f"  Distance per Delivery (Avg): {metrics.distance_per_delivery_avg:.0f} meters")
    print(f"  Queue Depth (Avg): {metrics.queue_depth_avg:.1f} orders")
    print(f"  Capacity per 15-min Window: {metrics.capacity_15min_window} orders")
    print()
    
    print("Financial Analysis:")
    print(f"  Second Runner Break-Even: {metrics.second_runner_break_even_orders:.1f} orders")
    print()
    
    print("Zone Service Times:")
    for zone, service_time in metrics.zone_service_times.items():
        print(f"  {zone}: {service_time:.1f} minutes")
    print()
    
    return metrics


def demonstrate_multiple_simulations():
    """Demonstrate analyzing multiple simulations."""
    
    print("=== Multiple Simulations Analysis Example ===\n")
    
    # Create multiple sets of sample data with variations
    metrics_list = []
    
    for i in range(3):
        # Create sample data with slight variations
        delivery_stats, activity_log, orders, failed_orders = create_sample_delivery_data()
        
        # Vary the parameters slightly to simulate different scenarios
        revenue_per_order = 25.0 + (i * 2.0)  # $25, $27, $29
        sla_minutes = 30 - (i * 2)  # 30, 28, 26 minutes
        
        # Calculate metrics for this simulation
        metrics = calculate_delivery_runner_metrics(
            delivery_stats=delivery_stats,
            activity_log=activity_log,
            orders=orders,
            failed_orders=failed_orders,
            revenue_per_order=revenue_per_order,
            sla_minutes=sla_minutes,
            simulation_id=f"simulation_{i+1:02d}",
            runner_id="runner_1",
            service_hours=10.0,
        )
        
        metrics_list.append(metrics)
        
        print(f"Simulation {i+1}:")
        print(f"  RPR: ${metrics.revenue_per_round:.2f}")
        print(f"  Order Penetration Rate: {metrics.order_penetration_rate:.1%}")
        print(f"  On-Time Rate: {metrics.on_time_rate:.1%}")
        print(f"  Failed Rate: {metrics.failed_rate:.1%}")
        print()
    
    # Calculate summary statistics
    summaries = summarize_delivery_runner_metrics(metrics_list)
    
    print("Summary Statistics (Across 3 Simulations):")
    print(f"  RPR - Mean: ${summaries['revenue_per_round']['mean']:.2f}")
    print(f"  RPR - Range: ${summaries['revenue_per_round']['min']:.2f} - ${summaries['revenue_per_round']['max']:.2f}")
    print(f"  Order Penetration Rate - Mean: {summaries['order_penetration_rate']['mean']:.1%}")
    print(f"  On-Time Rate - Mean: {summaries['on_time_rate']['mean']:.1%}")
    print(f"  Failed Rate - Mean: {summaries['failed_rate']['mean']:.1%}")
    print()
    
    print(f"Total Revenue: ${summaries['total_revenue']:.2f}")
    print(f"Total Orders: {summaries['total_orders']}")
    print(f"Successful Orders: {summaries['successful_orders']}")
    print(f"Failed Orders: {summaries['failed_orders']}")
    print()
    
    return metrics_list, summaries


def demonstrate_report_generation():
    """Demonstrate generating formatted reports."""
    
    print("=== Report Generation Example ===\n")
    
    # Create sample data and calculate metrics
    delivery_stats, activity_log, orders, failed_orders = create_sample_delivery_data()
    
    metrics = calculate_delivery_runner_metrics(
        delivery_stats=delivery_stats,
        activity_log=activity_log,
        orders=orders,
        failed_orders=failed_orders,
        revenue_per_order=25.0,
        sla_minutes=30,
        simulation_id="report_example",
        runner_id="runner_1",
        service_hours=10.0,
    )
    
    # Generate individual metrics report
    individual_report = format_delivery_runner_metrics_report(metrics)
    
    # Create multiple simulations for summary report
    metrics_list = [metrics]  # Just one for this example
    summaries = summarize_delivery_runner_metrics(metrics_list)
    summary_report = format_delivery_runner_summary_report(summaries, len(metrics_list))
    
    # Save reports to files
    output_dir = Path("examples/output")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save individual report
    individual_file = output_dir / "delivery_metrics_example.md"
    with open(individual_file, 'w', encoding='utf-8') as f:
        f.write(individual_report)
    
    # Save summary report
    summary_file = output_dir / "delivery_metrics_summary_example.md"
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write(summary_report)
    
    print(f"Generated individual metrics report: {individual_file}")
    print(f"Generated summary report: {summary_file}")
    print()
    
    # Display a snippet of the individual report
    print("Sample of Individual Metrics Report:")
    print("=" * 50)
    lines = individual_report.split('\n')[:20]  # First 20 lines
    for line in lines:
        print(line)
    print("...")
    print()


def demonstrate_custom_analysis():
    """Demonstrate custom analysis using the metrics."""
    
    print("=== Custom Analysis Example ===\n")
    
    # Create sample data
    delivery_stats, activity_log, orders, failed_orders = create_sample_delivery_data()
    
    # Calculate base metrics
    metrics = calculate_delivery_runner_metrics(
        delivery_stats=delivery_stats,
        activity_log=activity_log,
        orders=orders,
        failed_orders=failed_orders,
        revenue_per_order=25.0,
        sla_minutes=30,
        simulation_id="custom_analysis",
        runner_id="runner_1",
        service_hours=10.0,
    )
    
    # Perform custom analysis
    print("Custom Analysis Results:")
    print()
    
    # Revenue analysis
    revenue_per_hour = metrics.total_revenue / metrics.active_runner_hours
    print(f"Revenue per Hour: ${revenue_per_hour:.2f}")
    
    # Efficiency analysis
    if metrics.total_orders > 0:
        efficiency_score = (metrics.on_time_rate * 0.4 + 
                          (1 - metrics.failed_rate) * 0.3 + 
                          (metrics.orders_per_runner_hour / 2) * 0.3)  # Normalized to 0-1
        print(f"Efficiency Score: {efficiency_score:.1%}")
    
    # Capacity analysis
    utilization_rate = (metrics.runner_utilization_driving_pct + 
                       metrics.runner_utilization_waiting_pct + 
                       metrics.runner_utilization_handoff_pct) / 100
    print(f"Active Utilization Rate: {utilization_rate:.1%}")
    
    # Cost analysis
    estimated_cost_per_order = 5.0  # Variable cost per order
    estimated_runner_cost_per_hour = 25.0  # Runner labor cost
    total_cost = (estimated_cost_per_order * metrics.successful_orders + 
                 estimated_runner_cost_per_hour * metrics.active_runner_hours)
    profit_margin = (metrics.total_revenue - total_cost) / metrics.total_revenue if metrics.total_revenue > 0 else 0
    print(f"Profit Margin: {profit_margin:.1%}")
    
    # Service quality analysis
    if metrics.delivery_cycle_time_p50 > 0:
        service_quality_score = min(1.0, 30 / metrics.delivery_cycle_time_p50)  # 30 min target
        print(f"Service Quality Score: {service_quality_score:.1%}")
    
    print()


def main():
    """Main function to run all demonstrations."""
    
    print("Delivery Runner Metrics Usage Examples")
    print("=" * 50)
    print()
    
    # Run all demonstrations
    demonstrate_individual_metrics()
    demonstrate_multiple_simulations()
    demonstrate_report_generation()
    demonstrate_custom_analysis()
    
    print("All examples completed successfully!")
    print("Check the 'examples/output' directory for generated report files.")


if __name__ == "__main__":
    main()
