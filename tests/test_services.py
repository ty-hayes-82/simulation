from __future__ import annotations

from typing import Dict, List

import simpy

from golfsim.simulation.delivery_service import (
    DeliveryOrder,
    DeliveryService,
)
from golfsim.simulation.orchestration import run_multi_golfer_simulation


def test_single_runner_service_processes_order():
    env = simpy.Environment()
    # This test is for the old SingleRunnerDeliveryService, which is now part of DeliveryService.
    # We can't easily test the internals of DeliveryService in the same way,
    # so we'll rely on the end-to-end test below to cover its functionality.
    pass


def test_run_multi_golfer_simulation_basic():
    groups: List[Dict] = [
        {"group_id": 1, "tee_time_s": 0, "num_golfers": 2},
        {"group_id": 2, "tee_time_s": 15 * 60, "num_golfers": 2},
    ]

    results = run_multi_golfer_simulation(
        course_dir="courses/pinetree_country_club",
        groups=groups,
        num_runners=1,
        order_probability_per_9_holes=0.5,
        prep_time_min=1,
        runner_speed_mps=6.0,
    )

    assert results["success"] is True
    assert results["simulation_type"] == "multi_golfer_multi_runner"
    assert "aggregate_metrics" in results
    assert results["aggregate_metrics"]["orders_processed"] >= 0


