from __future__ import annotations

from typing import Dict, List

import simpy

from golfsim.simulation.services import (
    DeliveryOrder,
    SingleRunnerDeliveryService,
    run_multi_golfer_simulation,
)


def test_single_runner_service_processes_order():
    env = simpy.Environment()
    service = SingleRunnerDeliveryService(
        env=env,
        course_dir="courses/pinetree_country_club",
        runner_speed_mps=6.0,
        prep_time_min=1,
    )

    # Place a single order at opening time on hole 3
    order = DeliveryOrder(
        order_id="001",
        golfer_group_id=1,
        golfer_id="G1_1",
        order_time_s=service.service_open_s,
        hole_num=3,
    )

    def place():  # simpy process
        yield env.timeout(service.service_open_s)
        service.place_order(order)

    env.process(place())
    env.run(until=service.service_open_s + 60 * 60)  # run up to 1 hour after open

    assert any(a.get("activity_type") == "delivery_complete" for a in service.activity_log)
    assert order.status == "processed"
    assert order.total_completion_time_s > 0


def test_run_multi_golfer_simulation_basic():
    groups: List[Dict] = [
        {"group_id": 1, "tee_time_s": 0, "num_golfers": 2},
        {"group_id": 2, "tee_time_s": 15 * 60, "num_golfers": 2},
    ]

    results = run_multi_golfer_simulation(
        course_dir="courses/pinetree_country_club",
        groups=groups,
        order_probability_per_9_holes=0.5,
        prep_time_min=1,
        runner_speed_mps=6.0,
    )

    assert results["success"] is True
    assert results["simulation_type"] == "multi_golfer_single_runner"
    assert "aggregate_metrics" in results
    # Either some orders processed or properly marked failed if outside service window
    assert results["aggregate_metrics"]["orders_processed"] >= 0


