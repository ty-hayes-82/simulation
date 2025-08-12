from __future__ import annotations

import simpy

from golfsim.simulation.services import BeverageCartService


COURSE_DIR = "courses/pinetree_country_club"


def test_bev_cart_gps_monotonic_and_window():
    env = simpy.Environment()
    svc = BeverageCartService(env=env, course_dir=COURSE_DIR, cart_id="t_bev", track_coordinates=True)
    env.run(until=svc.service_end_s)

    coords = svc.coordinates
    assert isinstance(coords, list) and len(coords) > 0

    # Timestamps monotonic with consistent cadence; within 09:00–17:00 window (relative to 07:00 start)
    times = [c.get("timestamp", 0) for c in coords]
    assert times[0] >= (9 - 7) * 3600
    assert times[-1] <= (17 - 7) * 3600
    diffs = [b - a for a, b in zip(times, times[1:])]
    # All steps should be positive and mostly equal (allow minor jitter from LCM/timing rounding)
    assert all(d > 0 for d in diffs)
    if diffs:
        median = sorted(diffs)[len(diffs) // 2]
        # Allow 5% tolerance around the median cadence
        tol = max(1, int(round(median * 0.05)))
        assert all(abs(d - median) <= tol for d in diffs), (median, diffs[:20])

    # Directional correctness: holes must proceed 18→1 repeatedly
    holes = [int(c.get("current_hole", 0) or 0) for c in coords]
    assert holes, "no hole annotations"
    # Basic sanity
    assert all(1 <= h <= 18 for h in holes)
    assert 18 in holes and 1 in holes
    # Start on 18 at service open
    assert holes[0] == 18

    # Check each step is same-hole, decrement by 1, or wrap 1→18
    for prev, nxt in zip(holes, holes[1:]):
        if nxt == prev:
            continue
        if prev == 1:
            assert nxt == 18, f"Expected wrap 1→18, got 1→{nxt}"
        else:
            assert nxt == prev - 1, f"Expected decrement by 1 from {prev}, got {nxt}"


