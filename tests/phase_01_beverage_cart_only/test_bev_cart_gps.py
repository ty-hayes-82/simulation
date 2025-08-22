import simpy
from golfsim.simulation.beverage_cart_service import BeverageCartService

COURSE_DIR = "courses/pinetree_country_club"

def test_bev_cart_gps_monotonic_and_window():
    env = simpy.Environment()
    svc = BeverageCartService(env=env, course_dir=COURSE_DIR, cart_id="t_bev", track_coordinates=True)
    
    env.run(until=svc.service_end_s + 3600)

    coords = svc.coordinates
    assert coords, "Coordinates should be generated"
    
    # Check timestamps are monotonic increasing
    timestamps = [c["timestamp"] for c in coords]
    assert all(timestamps[i] <= timestamps[i+1] for i in range(len(timestamps)-1))

    # Check that coordinates are within service window
    assert all(svc.service_start_s <= ts <= svc.service_end_s for ts in timestamps)
