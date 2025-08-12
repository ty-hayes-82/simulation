"""
Example: Using Beverage Cart Metrics

This example demonstrates how to calculate and analyze beverage cart metrics
using the comprehensive metrics system.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Dict

from golfsim.analysis.bev_cart_metrics import (
    calculate_bev_cart_metrics,
    summarize_bev_cart_metrics,
    format_metrics_report,
    format_summary_report,
    BevCartMetrics
)


def create_sample_sales_data() -> List[Dict]:
    """Create sample sales data for demonstration."""
    return [
        {
            "group_id": 1,
            "hole_num": 5,
            "timestamp_s": 8000,  # 10:13 AM
            "price": 15.50
        },
        {
            "group_id": 2,
            "hole_num": 8,
            "timestamp_s": 12000,  # 10:20 AM
            "price": 22.00
        },
        {
            "group_id": 1,  # Repeat customer
            "hole_num": 12,
            "timestamp_s": 16000,  # 10:27 AM
            "price": 18.75
        },
        {
            "group_id": 3,
            "hole_num": 15,
            "timestamp_s": 20000,  # 10:33 AM
            "price": 12.25
        },
        {
            "group_id": 4,
            "hole_num": 18,
            "timestamp_s": 24000,  # 10:40 AM
            "price": 25.00
        }
    ]


def create_sample_coordinates() -> List[Dict]:
    """Create sample GPS coordinates for demonstration."""
    coordinates = []
    
    # Generate coordinates for each hole (1-18) over 8 hours
    for hour in range(8):
        for minute in range(0, 60, 10):  # Every 10 minutes
            timestamp = 7200 + (hour * 3600) + (minute * 60)  # Start at 9 AM
            
            # Calculate which hole we're at based on time
            hole = ((hour * 6) + (minute // 10)) % 18 + 1
            
            coordinates.append({
                "timestamp": timestamp,
                "latitude": 40.0 + (hole * 0.001),  # Slight variation by hole
                "longitude": -74.0 + (hole * 0.001),
                "current_hole": hole,
                "type": "bev_cart"
            })
    
    return coordinates


def create_sample_golfer_data() -> List[Dict]:
    """Create sample golfer GPS data for visibility metrics."""
    golfers = []
    
    # Create golfer positions that occasionally come close to the cart
    for timestamp in range(8000, 24000, 300):  # Every 5 minutes
        # Sometimes golfers are close to the cart
        if timestamp % 2000 == 0:  # Every ~33 minutes
            golfers.append({
                "timestamp": timestamp,
                "latitude": 40.0 + 0.0001,  # Very close to cart
                "longitude": -74.0 + 0.0001,
                "type": "golfer",
                "group_id": 1
            })
        else:
            golfers.append({
                "timestamp": timestamp,
                "latitude": 40.1,  # Far from cart
                "longitude": -74.1,
                "type": "golfer",
                "group_id": 2
            })
    
    return golfers


def main():
    """Main example function."""
    print("=" * 80)
    print("BEVERAGE CART METRICS EXAMPLE")
    print("=" * 80)
    
    # Create sample data
    sales_data = create_sample_sales_data()
    coordinates = create_sample_coordinates()
    golfer_data = create_sample_golfer_data()
    
    print(f"Created sample data:")
    print(f"- {len(sales_data)} sales transactions")
    print(f"- {len(coordinates)} GPS coordinates")
    print(f"- {len(golfer_data)} golfer positions")
    print()
    
    # Calculate metrics for single simulation
    print("Calculating metrics for single simulation...")
    metrics = calculate_bev_cart_metrics(
        sales_data=sales_data,
        coordinates=coordinates,
        golfer_data=golfer_data,
        service_start_s=7200,  # 9 AM
        service_end_s=36000,   # 5 PM
        simulation_id="example_sim_01",
        cart_id="bev_cart_example",
        tip_rate_percentage=18.0,  # 18% tip rate
        proximity_threshold_m=70.0,
        proximity_duration_s=30
    )
    
    # Display individual metrics report
    print("\n" + "=" * 80)
    print("INDIVIDUAL SIMULATION METRICS")
    print("=" * 80)
    report = format_metrics_report(metrics)
    print(report)
    
    # Create multiple simulations for summary analysis
    print("\n" + "=" * 80)
    print("MULTIPLE SIMULATION SUMMARY")
    print("=" * 80)
    
    all_metrics = [metrics]
    
    # Create variations for demonstration
    for i in range(2, 6):
        # Vary the sales data slightly
        varied_sales = []
        for sale in sales_data:
            varied_sale = sale.copy()
            varied_sale["price"] = sale["price"] * (0.9 + (i * 0.05))  # Vary prices
            varied_sales.append(varied_sale)
        
        varied_metrics = calculate_bev_cart_metrics(
            sales_data=varied_sales,
            coordinates=coordinates,
            golfer_data=golfer_data,
            service_start_s=7200,
            service_end_s=36000,
            simulation_id=f"example_sim_{i:02d}",
            cart_id=f"bev_cart_example_{i}",
            tip_rate_percentage=18.0,
            proximity_threshold_m=70.0,
            proximity_duration_s=30
        )
        all_metrics.append(varied_metrics)
    
    # Generate summary
    summary = summarize_bev_cart_metrics(all_metrics)
    summary_report = format_summary_report(summary)
    print(summary_report)
    
    # Save results to files
    output_dir = Path("examples/output")
    output_dir.mkdir(exist_ok=True)
    
    # Save individual metrics
    for metrics in all_metrics:
        metrics_file = output_dir / f"{metrics.simulation_id}_metrics.json"
        metrics_dict = {
            "simulation_id": metrics.simulation_id,
            "cart_id": metrics.cart_id,
            "metrics": {
                "revenue_per_round": metrics.revenue_per_round,
                "average_order_value": metrics.average_order_value,
                "total_revenue": metrics.total_revenue,
                "order_penetration_rate": metrics.order_penetration_rate,
                "orders_per_cart_hour": metrics.orders_per_cart_hour,
                "total_orders": metrics.total_orders,
                "unique_customers": metrics.unique_customers,
                "tip_rate": metrics.tip_rate,
                "tips_per_order": metrics.tips_per_order,
                "total_tips": metrics.total_tips,
                "holes_covered_per_hour": metrics.holes_covered_per_hour,
                "minutes_per_hole_per_cart": metrics.minutes_per_hole_per_cart,
                "total_holes_covered": metrics.total_holes_covered,
                "golfer_repeat_rate": metrics.golfer_repeat_rate,
                "average_orders_per_customer": metrics.average_orders_per_customer,
                "customers_with_multiple_orders": metrics.customers_with_multiple_orders,
                "golfer_visibility_interval_minutes": metrics.golfer_visibility_interval_minutes,
                "total_visibility_events": metrics.total_visibility_events,
                "service_hours": metrics.service_hours,
                "rounds_in_service_window": metrics.rounds_in_service_window,
            }
        }
        
        with open(metrics_file, 'w') as f:
            json.dump(metrics_dict, f, indent=2)
    
    # Save summary
    summary_file = output_dir / "metrics_summary.md"
    with open(summary_file, 'w') as f:
        f.write(summary_report)
    
    print(f"\nResults saved to: {output_dir}")
    print("Files created:")
    for metrics in all_metrics:
        print(f"- {metrics.simulation_id}_metrics.json")
    print("- metrics_summary.md")
    
    print("\n" + "=" * 80)
    print("EXAMPLE COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
