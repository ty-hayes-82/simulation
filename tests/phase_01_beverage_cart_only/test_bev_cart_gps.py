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


