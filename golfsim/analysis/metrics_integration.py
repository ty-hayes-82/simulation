"""
Metrics integration utility for golf delivery simulations.

This module provides utilities to detect simulation types and automatically
generate appropriate metrics based on the services used in a simulation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .bev_cart_metrics import (
    calculate_bev_cart_metrics,
    format_metrics_report as format_bev_metrics_report,
    BevCartMetrics,
)
from .delivery_runner_metrics import (
    calculate_delivery_runner_metrics,
    format_delivery_runner_metrics_report,
    DeliveryRunnerMetrics,
)

logger = logging.getLogger(__name__)


def detect_simulation_services(
    simulation_result: Dict[str, Any],
    bev_cart_coordinates: Optional[List[Dict[str, Any]]] = None,
    bev_cart_service: Optional[Any] = None,
) -> Tuple[bool, bool]:
    """
    Detect which simulation services were used based on the simulation result.
    
    Args:
        simulation_result: Complete simulation result dict
        bev_cart_coordinates: Optional beverage cart GPS coordinates
        bev_cart_service: Optional BeverageCartService instance
        
    Returns:
        Tuple of (has_bev_cart, has_delivery_runner)
    """
    has_bev_cart = False
    has_delivery_runner = False
    
    # Check for beverage cart indicators
    if bev_cart_service is not None:
        has_bev_cart = True
    elif bev_cart_coordinates and len(bev_cart_coordinates) > 0:
        has_bev_cart = True
    elif "bev_points" in simulation_result and simulation_result["bev_points"]:
        has_bev_cart = True
    elif simulation_result.get("simulation_type", "").find("bev") >= 0:
        has_bev_cart = True
    elif "sales_result" in simulation_result and simulation_result["sales_result"].get("sales"):
        # Sales data usually indicates beverage cart simulation
        has_bev_cart = True
    
    # Check for delivery runner indicators
    if "delivery_stats" in simulation_result and simulation_result["delivery_stats"]:
        has_delivery_runner = True
    elif "activity_log" in simulation_result and simulation_result["activity_log"]:
        has_delivery_runner = True
    elif "orders" in simulation_result and simulation_result["orders"]:
        has_delivery_runner = True
    elif simulation_result.get("simulation_type", "").find("delivery") >= 0:
        has_delivery_runner = True
    elif simulation_result.get("simulation_type", "") == "multi_golfer_single_runner":
        has_delivery_runner = True
    
    return has_bev_cart, has_delivery_runner


def generate_bev_cart_metrics(
    sales_data: List[Dict[str, Any]],
    coordinates: List[Dict[str, Any]],
    golfer_data: Optional[List[Dict[str, Any]]] = None,
    service_start_s: int = 7200,  # 9 AM
    service_end_s: int = 36000,   # 5 PM
    simulation_id: str = "unknown",
    cart_id: str = "bev_cart_1",
    **kwargs
) -> BevCartMetrics:
    """
    Generate beverage cart metrics with error handling.
    
    Args:
        sales_data: List of sales records
        coordinates: List of GPS coordinates
        golfer_data: Optional golfer GPS data
        service_start_s: Service start time in seconds since 7 AM
        service_end_s: Service end time in seconds since 7 AM
        simulation_id: Unique identifier for this simulation
        cart_id: Cart identifier
        **kwargs: Additional parameters passed to calculate_bev_cart_metrics
        
    Returns:
        BevCartMetrics object
    """
    try:
        return calculate_bev_cart_metrics(
            sales_data=sales_data,
            coordinates=coordinates,
            golfer_data=golfer_data,
            service_start_s=service_start_s,
            service_end_s=service_end_s,
            simulation_id=simulation_id,
            cart_id=cart_id,
            **kwargs
        )
    except Exception as e:
        logger.warning("Failed to calculate beverage cart metrics: %s", e)
        # Return default metrics object
        return BevCartMetrics(
            revenue_per_round=0.0,
            average_order_value=0.0,
            total_revenue=0.0,
            order_penetration_rate=0.0,
            orders_per_cart_hour=0.0,
            total_orders=0,
            unique_customers=0,
            tip_rate=0.0,
            tips_per_order=0.0,
            total_tips=0.0,
            holes_covered_per_hour=0.0,
            minutes_per_hole_per_cart=0.0,
            total_holes_covered=0,
            golfer_repeat_rate=0.0,
            average_orders_per_customer=0.0,
            customers_with_multiple_orders=0,
            golfer_visibility_interval_minutes=0.0,
            total_visibility_events=0,
            service_hours=0.0,
            rounds_in_service_window=0,
            simulation_id=simulation_id,
            cart_id=cart_id,
        )


def generate_delivery_runner_metrics(
    delivery_stats: List[Dict[str, Any]],
    activity_log: List[Dict[str, Any]],
    orders: List[Dict[str, Any]],
    failed_orders: List[Dict[str, Any]],
    revenue_per_order: float = 25.0,
    sla_minutes: int = 30,
    simulation_id: str = "unknown",
    runner_id: str = "runner_1",
    service_hours: float = 10.0,
    **kwargs
) -> DeliveryRunnerMetrics:
    """
    Generate delivery runner metrics with error handling.
    
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
        **kwargs: Additional parameters passed to calculate_delivery_runner_metrics
        
    Returns:
        DeliveryRunnerMetrics object
    """
    try:
        return calculate_delivery_runner_metrics(
            delivery_stats=delivery_stats,
            activity_log=activity_log,
            orders=orders,
            failed_orders=failed_orders,
            revenue_per_order=revenue_per_order,
            sla_minutes=sla_minutes,
            simulation_id=simulation_id,
            runner_id=runner_id,
            service_hours=service_hours,
            **kwargs
        )
    except Exception as e:
        logger.warning("Failed to calculate delivery runner metrics: %s", e)
        # Return default metrics object - this is more complex, so we'll create a minimal one
        return DeliveryRunnerMetrics(
            revenue_per_round=0.0,
            order_penetration_rate=0.0,
            average_order_value=0.0,
            orders_per_runner_hour=0.0,
            on_time_rate=0.0,
            delivery_cycle_time_p50=0.0,
            delivery_cycle_time_p90=0.0,
            dispatch_delay_avg=0.0,
            travel_time_avg=0.0,
            failed_rate=0.0,
            runner_utilization_driving_pct=0.0,
            runner_utilization_waiting_pct=0.0,
            runner_utilization_handoff_pct=0.0,
            runner_utilization_deadhead_pct=0.0,
            distance_per_delivery_avg=0.0,
            queue_depth_avg=0.0,
            queue_wait_avg=0.0,
            capacity_15min_window=0,
            second_runner_break_even_orders=0.0,
            zone_service_times={},
            total_revenue=0.0,
            total_orders=0,
            successful_orders=0,
            failed_orders=0,
            total_rounds=0,
            active_runner_hours=0.0,
            simulation_id=simulation_id,
            runner_id=runner_id,
        )


def save_metrics_to_directory(
    output_dir: Path,
    bev_cart_metrics: Optional[BevCartMetrics] = None,
    delivery_runner_metrics: Optional[DeliveryRunnerMetrics] = None,
    run_suffix: str = "",
) -> None:
    """
    Save metrics to files in the specified directory.
    
    Args:
        output_dir: Directory to save metrics files
        bev_cart_metrics: Optional beverage cart metrics to save
        delivery_runner_metrics: Optional delivery runner metrics to save
        run_suffix: Optional suffix for filenames (e.g., "_01" for run 1)
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save beverage cart metrics
    if bev_cart_metrics:
        try:
            # Markdown report
            bev_report = format_bev_metrics_report(bev_cart_metrics)
            bev_md_path = output_dir / f"bev_cart_metrics{run_suffix}.md"
            bev_md_path.write_text(bev_report, encoding="utf-8")
            logger.info("Saved beverage cart metrics to: %s", bev_md_path)
        except Exception as e:
            logger.warning("Failed to save beverage cart metrics: %s", e)
    
    # Save delivery runner metrics
    if delivery_runner_metrics:
        try:
            # Markdown report
            delivery_report = format_delivery_runner_metrics_report(delivery_runner_metrics)
            delivery_md_path = output_dir / f"delivery_runner_metrics{run_suffix}.md"
            delivery_md_path.write_text(delivery_report, encoding="utf-8")
            
            # Also save as JSON for programmatic access
            delivery_json = {
                'simulation_id': delivery_runner_metrics.simulation_id,
                'runner_id': delivery_runner_metrics.runner_id,
                'revenue_per_round': delivery_runner_metrics.revenue_per_round,
                'orders_per_runner_hour': delivery_runner_metrics.orders_per_runner_hour,
                'on_time_rate': delivery_runner_metrics.on_time_rate,
                'delivery_cycle_time_p90': delivery_runner_metrics.delivery_cycle_time_p90,
                'delivery_cycle_time_avg': delivery_runner_metrics.delivery_cycle_time_avg,
                'failed_rate': delivery_runner_metrics.failed_rate,
                'second_runner_break_even_orders': delivery_runner_metrics.second_runner_break_even_orders,
                'queue_wait_avg': delivery_runner_metrics.queue_wait_avg,
                'runner_utilization_driving_pct': delivery_runner_metrics.runner_utilization_driving_pct,
                'runner_utilization_waiting_pct': delivery_runner_metrics.runner_utilization_waiting_pct,
                'distance_per_delivery_avg': delivery_runner_metrics.distance_per_delivery_avg,
                'zone_service_times': delivery_runner_metrics.zone_service_times,
                'total_revenue': delivery_runner_metrics.total_revenue,
                'total_orders': delivery_runner_metrics.total_orders,
                'successful_orders': delivery_runner_metrics.successful_orders,
                'failed_orders': delivery_runner_metrics.failed_orders,
                'total_rounds': delivery_runner_metrics.total_rounds,
                'active_runner_hours': delivery_runner_metrics.active_runner_hours,
            }
            delivery_json_path = output_dir / f"delivery_runner_metrics{run_suffix}.json"
            delivery_json_path.write_text(json.dumps(delivery_json, indent=2), encoding="utf-8")
            
            logger.info("Saved delivery runner metrics to: %s and %s", delivery_md_path, delivery_json_path)
        except Exception as e:
            logger.warning("Failed to save delivery runner metrics: %s", e)


def generate_and_save_metrics(
    simulation_result: Dict[str, Any],
    output_dir: Path,
    bev_cart_coordinates: Optional[List[Dict[str, Any]]] = None,
    bev_cart_service: Optional[Any] = None,
    golfer_data: Optional[List[Dict[str, Any]]] = None,
    run_suffix: str = "",
    simulation_id: str = "unknown",
    **metrics_kwargs
) -> Tuple[Optional[BevCartMetrics], Optional[DeliveryRunnerMetrics]]:
    """
    Automatically detect simulation type and generate appropriate metrics.
    
    Args:
        simulation_result: Complete simulation result dict
        output_dir: Directory to save metrics files
        bev_cart_coordinates: Optional beverage cart GPS coordinates
        bev_cart_service: Optional BeverageCartService instance
        golfer_data: Optional golfer GPS data
        run_suffix: Optional suffix for filenames
        simulation_id: Unique identifier for this simulation
        **metrics_kwargs: Additional parameters for metrics calculations
        
    Returns:
        Tuple of (bev_cart_metrics, delivery_runner_metrics) - either may be None
    """
    has_bev_cart, has_delivery_runner = detect_simulation_services(
        simulation_result, bev_cart_coordinates, bev_cart_service
    )
    
    bev_cart_metrics = None
    delivery_runner_metrics = None
    
    # Generate beverage cart metrics if applicable
    if has_bev_cart:
        logger.info("Detected beverage cart simulation - generating bev cart metrics")
        
        # Extract sales data
        sales_data = []
        if "sales_result" in simulation_result:
            sales_data = simulation_result["sales_result"].get("sales", [])
        elif "sales" in simulation_result:
            sales_data = simulation_result["sales"]
        
        # Extract coordinates
        coordinates = bev_cart_coordinates or []
        if not coordinates and "bev_points" in simulation_result:
            coordinates = simulation_result["bev_points"]
        
        # Extract service timing if available
        service_start_s = metrics_kwargs.get("service_start_s", 7200)
        service_end_s = metrics_kwargs.get("service_end_s", 36000)
        
        if bev_cart_service:
            service_start_s = getattr(bev_cart_service, "service_start_s", service_start_s)
            service_end_s = getattr(bev_cart_service, "service_end_s", service_end_s)
        
        bev_cart_metrics = generate_bev_cart_metrics(
            sales_data=sales_data,
            coordinates=coordinates,
            golfer_data=golfer_data,
            service_start_s=service_start_s,
            service_end_s=service_end_s,
            simulation_id=simulation_id,
            cart_id=metrics_kwargs.get("cart_id", "bev_cart_1"),
            **{k: v for k, v in metrics_kwargs.items() if k.startswith("tip_") or k.startswith("proximity_")}
        )
    
    # Generate delivery runner metrics if applicable
    if has_delivery_runner:
        logger.info("Detected delivery runner simulation - generating delivery runner metrics")
        
        delivery_stats = simulation_result.get("delivery_stats", [])
        activity_log = simulation_result.get("activity_log", [])
        orders = simulation_result.get("orders", [])
        failed_orders = simulation_result.get("failed_orders", [])
        
        delivery_runner_metrics = generate_delivery_runner_metrics(
            delivery_stats=delivery_stats,
            activity_log=activity_log,
            orders=orders,
            failed_orders=failed_orders,
            revenue_per_order=metrics_kwargs.get("revenue_per_order", 25.0),
            sla_minutes=metrics_kwargs.get("sla_minutes", 30),
            simulation_id=simulation_id,
            runner_id=metrics_kwargs.get("runner_id", "runner_1"),
            service_hours=metrics_kwargs.get("service_hours", 10.0),
        )
    
    # Save metrics to files
    save_metrics_to_directory(
        output_dir=output_dir,
        bev_cart_metrics=bev_cart_metrics,
        delivery_runner_metrics=delivery_runner_metrics,
        run_suffix=run_suffix,
    )
    
    return bev_cart_metrics, delivery_runner_metrics
