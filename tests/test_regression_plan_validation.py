from __future__ import annotations

"""
Plan-aligned regression tests to ensure core behaviors in docs/testing_plan.md remain stable.

Covers:
- Phase 1: Beverage cart GPS generation time bounds and monotonic timestamps
- Phase 1B/1C basics: simulate_beverage_cart_sales returns required keys; 2-group revenue >= 1 group (probabilistic; allow equality)
- Phase 2: Single runner multi-golfer system returns aggregates and no crashes
- Phase 4/6: Throughput monotonicity across group sizes (sanity across seeds)
"""

from pathlib import Path
import json
import random

import simpy

from golfsim.simulation.services import BeverageCartService, run_multi_golfer_simulation
from golfsim.simulation.bev_cart_pass import simulate_beverage_cart_sales


COURSE_DIR = "courses/pinetree_country_club"


def test_phase1_bev_cart_gps_monotonic_and_window():
    env = simpy.Environment()
    svc = BeverageCartService(env=env, course_dir=COURSE_DIR, cart_id="t_bev", track_coordinates=True)
    env.run(until=svc.service_end_s)

    coords = svc.coordinates
    assert isinstance(coords, list) and len(coords) > 0

    # Timestamps monotonic with consistent cadence; within 09:00–17:00 window
    times = [c.get("timestamp", 0) for c in coords]
    assert times[0] >= (9 - 7) * 3600
    assert times[-1] <= (17 - 7) * 3600
    diffs = [b - a for a, b in zip(times, times[1:])]
    assert all(d > 0 for d in diffs)
    if diffs:
        median = sorted(diffs)[len(diffs) // 2]
        tol = max(1, int(round(median * 0.05)))
        assert all(abs(d - median) <= tol for d in diffs)


def test_phase1b_bev_cart_sales_keys_present():
    groups = [{"group_id": 1, "tee_time_s": 7200, "num_golfers": 4}]
    res = simulate_beverage_cart_sales(
        course_dir=COURSE_DIR,
        groups=groups,
        pass_order_probability=0.4,
        price_per_order=12.0,
    )

    # Required keys
    for key in ("sales", "revenue", "pass_intervals_per_group", "activity_log", "metadata"):
        assert key in res


def test_phase1c_two_groups_have_higher_or_equal_mean_revenue():
    one_group = [{"group_id": 1, "tee_time_s": 7200, "num_golfers": 4}]
    two_groups = [
        {"group_id": 1, "tee_time_s": 7200, "num_golfers": 4},
        {"group_id": 2, "tee_time_s": 7800, "num_golfers": 4},
    ]

    # Average over multiple seeds for stability
    trials = 10
    revs1 = []
    revs2 = []
    for seed in range(trials):
        random.seed(seed)
        revs1.append(
            simulate_beverage_cart_sales(
                course_dir=COURSE_DIR, groups=one_group, pass_order_probability=0.4, price_per_order=12.0
            )["revenue"]
        )
        random.seed(seed)
        revs2.append(
            simulate_beverage_cart_sales(
                course_dir=COURSE_DIR, groups=two_groups, pass_order_probability=0.4, price_per_order=12.0
            )["revenue"]
        )

    mean1 = sum(revs1) / trials
    mean2 = sum(revs2) / trials
    assert mean2 >= mean1


def test_phase4_throughput_scales_monotonic_on_average():
    import statistics as st
    # Compare average revenue across increasing group counts
    cases = [2, 4, 8]
    trials = 6
    means = []
    for n in cases:
        groups = [
            {"group_id": i + 1, "tee_time_s": 7200 + i * 600, "num_golfers": 4}
            for i in range(n)
        ]
        revs = []
        for seed in range(trials):
            random.seed(seed)
            revs.append(
                simulate_beverage_cart_sales(
                    course_dir=COURSE_DIR,
                    groups=groups,
                    pass_order_probability=0.4,
                    price_per_order=12.0,
                )["revenue"]
            )
        means.append(st.mean(revs))
    # Monotonic non-decreasing
    assert all(b >= a for a, b in zip(means, means[1:])), f"non-monotonic means: {means}"


def test_phase2_single_runner_one_group_basic_flow():
    groups = [{"group_id": 1, "tee_time_s": 7200, "num_golfers": 4}]
    results = run_multi_golfer_simulation(
        course_dir=COURSE_DIR,
        groups=groups,
        order_probability_per_9_holes=0.9,
        prep_time_min=10,
        runner_speed_mps=6.0,
        create_visualization=False,
    )

    assert results["success"] is True
    assert "aggregate_metrics" in results
    # Either processed or explicitly failed, but basic flow should produce structured outputs
    agg = results["aggregate_metrics"]
    assert "orders_processed" in agg and "orders_failed" in agg


def test_phase6_incremental_groups_monotonic_trends():
    # Check that processed increases and average order time does not decrease with load
    sizes = [1, 2, 4]
    processed_list = []
    avg_time_list = []
    for n in sizes:
        groups = [
            {"group_id": i + 1, "tee_time_s": 7200 + i * 600, "num_golfers": 4}
            for i in range(n)
        ]
        results = run_multi_golfer_simulation(
            course_dir=COURSE_DIR,
            groups=groups,
            order_probability_per_9_holes=0.6,
            prep_time_min=10,
            runner_speed_mps=6.0,
            create_visualization=False,
        )
        agg = results.get("aggregate_metrics", {})
        processed_list.append(agg.get("orders_processed", 0))
        avg_time_list.append(agg.get("average_order_time_s", 0.0))
    assert all(b >= a for a, b in zip(processed_list, processed_list[1:])), processed_list
    assert all(b >= a for a, b in zip(avg_time_list, avg_time_list[1:])), avg_time_list


