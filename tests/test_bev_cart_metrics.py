"""
Test beverage cart metrics calculation.
"""

from __future__ import annotations
from golfsim.simulation.beverage_cart_service import BeverageCartService
from golfsim.analysis.bev_cart_metrics import (
    calculate_bev_cart_metrics,
    _calculate_holes_covered,
    _calculate_customer_order_counts,
    _calculate_distance_m
)


def test_calculate_holes_covered():
    """Test hole coverage calculation."""
    coordinates = [
        {"current_hole": 1, "timestamp": 1000},
        {"current_hole": 2, "timestamp": 2000},
        {"current_hole": 1, "timestamp": 3000},  # Duplicate hole
        {"current_hole": 3, "timestamp": 4000},
        {"hole": 4, "timestamp": 5000},  # Different field name
    ]
    
    holes_covered = _calculate_holes_covered(coordinates)
    assert holes_covered == 4  # Should count unique holes 1, 2, 3, 4


def test_calculate_customer_order_counts():
    """Test customer order count calculation."""
    sales_data = [
        {"group_id": 1, "price": 10.0},
        {"group_id": 2, "price": 15.0},
        {"group_id": 1, "price": 20.0},  # Second order for group 1
        {"group_id": 3, "price": 12.0},
    ]
    
    customer_counts = _calculate_customer_order_counts(sales_data)
    assert customer_counts == {1: 2, 2: 1, 3: 1}


def test_calculate_distance_m():
    """Test distance calculation."""
    # Test distance between two points (should be small for nearby coordinates)
    lat1, lon1 = 40.7128, -74.0060  # New York
    lat2, lon2 = 40.7129, -74.0061  # Very close to NY
    
    distance = _calculate_distance_m(lat1, lon1, lat2, lon2)
    assert distance > 0
    assert distance < 100  # Should be very small distance
    
    # Test same point (should be 0)
    distance_same = _calculate_distance_m(lat1, lon1, lat1, lon1)
    assert distance_same == 0


def test_calculate_bev_cart_metrics_basic():
    """Test basic metrics calculation."""
    sales_data = [
        {"group_id": 1, "hole_num": 5, "timestamp_s": 8000, "price": 15.0},
        {"group_id": 2, "hole_num": 10, "timestamp_s": 12000, "price": 20.0},
        {"group_id": 1, "hole_num": 15, "timestamp_s": 16000, "price": 12.0},  # Repeat customer
    ]
    
    coordinates = [
        {"timestamp": 7200, "latitude": 40.0, "longitude": -74.0, "current_hole": 1},
        {"timestamp": 10800, "latitude": 40.1, "longitude": -74.1, "current_hole": 9},
        {"timestamp": 14400, "latitude": 40.2, "longitude": -74.2, "current_hole": 18},
    ]
    
    metrics = calculate_bev_cart_metrics(
        sales_data=sales_data,
        coordinates=coordinates,
        golfer_data=None,
        service_start_s=7200,
        service_end_s=36000,
        simulation_id="test_sim",
        cart_id="test_cart"
    )
    
    # Verify basic calculations
    assert metrics.total_revenue == 47.0
    assert metrics.total_orders == 3
    assert metrics.unique_customers == 2
    assert metrics.average_order_value == 47.0 / 3
    assert metrics.total_tips == 47.0 * 0.15  # 15% tip rate
    assert metrics.total_holes_covered == 3  # 1, 9, 18
    assert metrics.customers_with_multiple_orders == 1  # Group 1 ordered twice
    assert metrics.golfer_repeat_rate == 0.5  # 1 out of 2 customers repeated
    assert metrics.service_hours == 8.0  # (36000 - 7200) / 3600
    assert metrics.rounds_in_service_window == 2  # 8 hours / 3 hours per round


def test_calculate_bev_cart_metrics_no_sales():
    """Test metrics calculation with no sales."""
    coordinates = [
        {"timestamp": 7200, "latitude": 40.0, "longitude": -74.0, "current_hole": 1},
    ]
    
    metrics = calculate_bev_cart_metrics(
        sales_data=[],
        coordinates=coordinates,
        golfer_data=None,
        service_start_s=7200,
        service_end_s=36000,
        simulation_id="test_sim_no_sales",
        cart_id="test_cart"
    )
    
    # Verify zero values for sales-related metrics
    assert metrics.total_revenue == 0.0
    assert metrics.total_orders == 0
    assert metrics.unique_customers == 0
    assert metrics.average_order_value == 0.0
    assert metrics.total_tips == 0.0
    assert metrics.tips_per_order == 0.0
    assert metrics.order_penetration_rate == 0.0
    assert metrics.orders_per_cart_hour == 0.0
    assert metrics.golfer_repeat_rate == 0.0
    assert metrics.average_orders_per_customer == 0.0
    assert metrics.customers_with_multiple_orders == 0
    
    # Coverage metrics should still work
    assert metrics.total_holes_covered == 1
    assert metrics.service_hours == 8.0


def test_calculate_bev_cart_metrics_with_golfer_data():
    """Test metrics calculation with golfer data for visibility."""
    sales_data = [
        {"group_id": 1, "hole_num": 5, "timestamp_s": 8000, "price": 15.0},
    ]
    
    coordinates = [
        {"timestamp": 8000, "latitude": 40.0, "longitude": -74.0, "current_hole": 5},
    ]
    
    golfer_data = [
        {"timestamp": 8000, "latitude": 40.0001, "longitude": -74.0001, "type": "golfer"},  # Very close
        {"timestamp": 8000, "latitude": 40.1, "longitude": -74.1, "type": "golfer"},  # Far away
    ]
    
    metrics = calculate_bev_cart_metrics(
        sales_data=sales_data,
        coordinates=coordinates,
        golfer_data=golfer_data,
        service_start_s=7200,
        service_end_s=36000,
        simulation_id="test_sim_with_golfers",
        cart_id="test_cart",
        proximity_threshold_m=70.0,
        proximity_duration_s=30
    )
    
    # Should detect one visibility event (the close golfer)
    assert metrics.total_visibility_events == 1


if __name__ == "__main__":
    # Run tests
    test_calculate_holes_covered()
    test_calculate_customer_order_counts()
    test_calculate_distance_m()
    test_calculate_bev_cart_metrics_basic()
    test_calculate_bev_cart_metrics_no_sales()
    test_calculate_bev_cart_metrics_with_golfer_data()
    print("All tests passed!")
