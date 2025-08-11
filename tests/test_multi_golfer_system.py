#!/usr/bin/env python3
"""
Test Suite for Multi-Golfer Delivery System

This module contains comprehensive tests for validating the multi-golfer
delivery simulation system across all development phases.

Test Categories:
1. Phase 2: 2 golfers + 1 delivery runner
2. Phase 3: 5 golfers + 1 delivery runner
3. Phase 4: 5 golfers + 2 delivery runners
4. Phase 5: 10 groups (40+ golfers) + dynamic runners

Usage:
    # Run all tests
    python -m pytest tests/test_multi_golfer_system.py -v

    # Run only Phase 2 tests
    python -m pytest tests/test_multi_golfer_system.py::TestPhase2DualGolfer -v

    # Run with coverage
    python -m pytest tests/test_multi_golfer_system.py --cov=golfsim --cov-report=html
"""

import pytest
import json
import tempfile
from pathlib import Path
from typing import Dict, List
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

pytest.skip(
    "multi_golfer script not available; skipping transitional system tests during refactor",
    allow_module_level=True,
)


class TestPhase2DualGolfer:
    """Test Phase 2: 2 golfers + 1 delivery runner system."""

    def test_dual_golfer_basic_simulation(self):
        """Test basic 2-golfer simulation runs successfully."""
        with tempfile.TemporaryDirectory() as temp_dir:
            results = run_multi_golfer_simulation_v1(
                num_golfers=2, order_holes=[8, 16], prep_time_min=10, runner_speed_mps=6.0
            )

            # Validate basic structure
            assert results['simulation_type'] == 'multi_golfer_v1_transitional'
            assert results['num_golfers'] == 2
            assert len(results['individual_results']) == 2
            assert 'aggregate_metrics' in results
            assert 'optimization_analysis' in results

    def test_dual_golfer_order_sequencing(self):
        """Test that orders are properly sequenced and analyzed."""
        results = run_multi_golfer_simulation_v1(
            num_golfers=2,
            order_holes=[6, 12],  # Different holes for timing analysis
            prep_time_min=10,
        )

        optimization = results['optimization_analysis']

        # Should have timing analysis for 2 golfers
        assert 'delivery_timing_analysis' in optimization
        timing = optimization['delivery_timing_analysis']

        if 'order_sequence' in timing:
            assert len(timing['order_sequence']) == 2
            assert 'time_gaps_between_orders_s' in timing

    def test_dual_golfer_distance_optimization(self):
        """Test distance optimization analysis between golfers."""
        results = run_multi_golfer_simulation_v1(
            num_golfers=2,
            order_holes=[8, 9],  # Adjacent holes for optimization potential
            prep_time_min=10,
        )

        optimization = results['optimization_analysis']

        # Should identify route optimization potential
        assert 'route_optimization_potential' in optimization
        route_opt = optimization['route_optimization_potential']

        if 'delivery_location_distances' in route_opt:
            assert len(route_opt['delivery_location_distances']) >= 1

    def test_dual_golfer_performance_metrics(self):
        """Test that performance metrics meet Phase 2 targets."""
        results = run_multi_golfer_simulation_v1(
            num_golfers=2, order_holes=[10, 14], prep_time_min=10
        )

        aggregate = results['aggregate_metrics']

        # Performance targets for Phase 2
        assert aggregate['average_service_time_s'] < 15 * 60  # < 15 minutes average
        assert aggregate['total_delivery_distance_m'] > 0
        assert aggregate['average_delivery_distance_m'] > 0

        # Each individual simulation should be successful
        for result in results['individual_results']:
            assert result.get('delivery_distance_m', 0) > 0
            assert result.get('total_service_time_s', 0) > 0

    def test_dual_golfer_batching_analysis(self):
        """Test batching opportunity analysis."""
        results = run_multi_golfer_simulation_v1(
            num_golfers=2,
            order_holes=[7, 8],  # Close holes for batching potential
            prep_time_min=10,
        )

        optimization = results['optimization_analysis']

        # Should analyze batching opportunities
        assert 'batching_opportunities' in optimization
        batching = optimization['batching_opportunities']

        assert 'batching_threshold_s' in batching
        assert batching['batching_threshold_s'] == 600  # 10 minutes

    def test_dual_golfer_recommendations(self):
        """Test that system generates actionable recommendations."""
        results = run_multi_golfer_simulation_v1(
            num_golfers=2, order_holes=[5, 6], prep_time_min=10
        )

        recommendations = results['optimization_analysis']['recommendations']

        # Should have at least one recommendation
        assert len(recommendations) >= 1

        # Should include Phase 2 readiness recommendation
        phase2_ready = any('PHASE 2 READY' in rec for rec in recommendations)
        assert phase2_ready


class TestPhase3FiveGolfer:
    """Test Phase 3: 5 golfers + 1 delivery runner system."""

    @pytest.mark.slow
    def test_five_golfer_scalability(self):
        """Test system can handle 5 golfers efficiently."""
        results = run_multi_golfer_simulation_v1(
            num_golfers=5, order_holes=[3, 7, 11, 15, 18], prep_time_min=10
        )

        # Validate scaling
        assert results['num_golfers'] == 5
        assert len(results['individual_results']) == 5

        # Performance should remain reasonable
        aggregate = results['aggregate_metrics']
        assert aggregate['average_service_time_s'] < 18 * 60  # < 18 minutes average for 5 golfers

    @pytest.mark.slow
    def test_five_golfer_optimization_potential(self):
        """Test optimization analysis for 5 golfers."""
        results = run_multi_golfer_simulation_v1(
            num_golfers=5,
            order_holes=[1, 2, 3, 4, 5],  # Sequential holes for max optimization
            prep_time_min=10,
        )

        optimization = results['optimization_analysis']

        # Should have multiple optimization opportunities
        route_opt = optimization.get('route_optimization_potential', {})
        if 'delivery_location_distances' in route_opt:
            # With 5 golfers, should have 10 pairwise distances (C(5,2) = 10)
            assert len(route_opt['delivery_location_distances']) == 10

        # Should identify multiple batching opportunities
        batching = optimization.get('batching_opportunities', {})
        assert 'potential_batches' in batching


class TestSystemValidation:
    """System-wide validation tests."""

    def test_simulation_consistency(self):
        """Test that repeated simulations produce consistent results."""
        # Run same simulation multiple times
        results1 = run_multi_golfer_simulation_v1(
            num_golfers=2, order_holes=[10, 10], prep_time_min=10  # Same hole for both golfers
        )

        results2 = run_multi_golfer_simulation_v1(
            num_golfers=2, order_holes=[10, 10], prep_time_min=10
        )

        # Results should be similar (within 10% variance)
        dist1 = results1['aggregate_metrics']['total_delivery_distance_m']
        dist2 = results2['aggregate_metrics']['total_delivery_distance_m']

        variance = abs(dist1 - dist2) / max(dist1, dist2)
        assert variance < 0.1  # Less than 10% variance

    def test_parameter_validation(self):
        """Test parameter validation and error handling."""
        # Test invalid number of golfers
        with pytest.raises((ValueError, TypeError)):
            run_multi_golfer_simulation_v1(
                num_golfers=0, order_holes=[], prep_time_min=10  # Invalid
            )

        # Test invalid prep time
        with pytest.raises((ValueError, TypeError)):
            run_multi_golfer_simulation_v1(
                num_golfers=2, order_holes=[8, 16], prep_time_min=-5  # Invalid
            )

    def test_optimization_analysis_structure(self):
        """Test that optimization analysis has required structure."""
        results = run_multi_golfer_simulation_v1(
            num_golfers=2, order_holes=[12, 13], prep_time_min=10
        )

        optimization = results['optimization_analysis']

        # Required sections
        required_keys = [
            'delivery_timing_analysis',
            'route_optimization_potential',
            'batching_opportunities',
            'recommendations',
        ]

        for key in required_keys:
            assert key in optimization, f"Missing optimization analysis key: {key}"

    def test_results_json_serializable(self):
        """Test that results can be serialized to JSON."""
        results = run_multi_golfer_simulation_v1(
            num_golfers=2, order_holes=[5, 15], prep_time_min=10
        )

        # Should be able to serialize to JSON without errors
        json_str = json.dumps(results, default=str)
        assert len(json_str) > 100  # Should be substantial content

        # Should be able to deserialize
        deserialized = json.loads(json_str)
        assert deserialized['num_golfers'] == 2


class TestPerformanceBenchmarks:
    """Performance benchmarking tests."""

    def test_phase2_performance_targets(self):
        """Validate Phase 2 performance targets are met."""
        results = run_multi_golfer_simulation_v1(
            num_golfers=2, order_holes=[8, 16], prep_time_min=10
        )

        aggregate = results['aggregate_metrics']

        # Phase 2 Success Metrics (from roadmap):
        # - Delivery efficiency >85% vs single golfer baseline
        # - Order fulfillment time <12 minutes average
        # - System handles 10+ orders per hour

        assert aggregate['average_service_time_s'] < 12 * 60  # < 12 minutes

        # Test efficiency vs individual golfers
        total_individual_distance = sum(
            r.get('delivery_distance_m', 0) for r in results['individual_results']
        )

        # Multi-golfer should be at least as efficient as sum of individuals
        # (In Phase 2 transitional, they're equivalent, but validates the metric)
        assert aggregate['total_delivery_distance_m'] == total_individual_distance

    @pytest.mark.slow
    def test_system_load_handling(self):
        """Test system performance under load."""
        # Test maximum golfers for current implementation
        results = run_multi_golfer_simulation_v1(
            num_golfers=5,
            order_holes=[2, 6, 10, 14, 18],
            prep_time_min=8,  # Faster prep time to stress test
        )

        # Should complete without errors
        assert results['num_golfers'] == 5
        assert len(results['individual_results']) == 5

        # Performance should degrade gracefully
        aggregate = results['aggregate_metrics']
        assert aggregate['average_service_time_s'] < 25 * 60  # < 25 minutes for 5 golfers


# Test fixtures and utilities
@pytest.fixture
def sample_course_config():
    """Provide sample course configuration for testing."""
    return {
        "course_name": "Test Golf Course",
        "clubhouse": {"latitude": 34.0379, "longitude": -84.5928},
        "delivery_runner_speed_mph": 10.0,
        "delivery_prep_time_sec": 600,
    }


@pytest.fixture
def temp_output_dir():
    """Provide temporary output directory for tests."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


# Performance test markers
def pytest_configure(config):
    """Configure pytest markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')"
    )


if __name__ == "__main__":
    # Run basic validation if called directly
    print("Running Multi-Golfer System Tests")
    print("=" * 40)

    # Run a quick smoke test
    try:
        test_instance = TestPhase2DualGolfer()
        test_instance.test_dual_golfer_basic_simulation()
        print("Basic dual golfer test passed")

        validation_instance = TestSystemValidation()
        validation_instance.test_optimization_analysis_structure()
        print("Optimization analysis structure test passed")

        print("\n🎉 Basic tests passed! Run full test suite with:")
        print("   python -m pytest tests/test_multi_golfer_system.py -v")

    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
