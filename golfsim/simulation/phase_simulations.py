"""
Phase-specific simulation orchestration.

This module provides high-level simulation functions for different phases
of the golf delivery simulation system.
"""

from __future__ import annotations

import json
import random
import runpy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import simpy
from shapely.geometry import LineString

from ..config.loaders import load_simulation_config, load_tee_times_config
from ..io.results import write_unified_coordinates_csv, write_coordinates_csv_with_visibility
from .bev_cart_pass import simulate_beverage_cart_sales
from .engine import (
    get_node_timing,
    simulate_beverage_cart_gps
)
from .pass_detection import (
    extract_pass_events_from_sales_data,
    compute_group_hole_at_time,
    find_proximity_pass_events,
)
from .services import BeverageCartService


def _generate_beverage_cart_gps_from_nodes(
    course_dir: str,
    cart_id: str,
    service_start_s: int,
    service_end_s: int,
    crossings_data: Optional[Dict[str, Any]] = None
) -> List[Dict]:
    """
    Generate beverage cart GPS coordinates using the exact same nodes as crossings calculation.
    
    This ensures GPS coordinates and crossing calculations are perfectly aligned.
    """
    from .crossings import load_nodes_geojson_with_holes
    from pathlib import Path
    
    try:
        nodes_geojson = str(Path(course_dir) / "geojson" / "generated" / "lcm_course_nodes.geojson")
        nodes, node_holes = load_nodes_geojson_with_holes(nodes_geojson)
    except Exception:
        from .crossings import load_nodes_geojson
        nodes = load_nodes_geojson(nodes_geojson)
        node_holes = None
    
    if not nodes:
        return []
    
    # Create GPS points every 60 seconds from start to end
    coordinates = []
    total_nodes = len(nodes)
    
    # Beverage cart follows reverse path (18->1), so reverse the nodes
    reverse_nodes = list(reversed(nodes))
    if node_holes:
        reverse_holes = list(reversed(node_holes))
    else:
        reverse_holes = list(range(18, 0, -1)) * (total_nodes // 18 + 1)
        reverse_holes = reverse_holes[:total_nodes]
    
    # Calculate time per complete loop (default 180 minutes = 10800 seconds)
    loop_duration_s = 180 * 60
    
    for timestamp in range(service_start_s, service_end_s + 1, 60):
        # Calculate position within current loop
        time_in_service = timestamp - service_start_s
        loop_progress = (time_in_service % loop_duration_s) / loop_duration_s
        
        # Find node index based on progress through loop
        node_idx = int(loop_progress * total_nodes) % total_nodes
        lat, lon = reverse_nodes[node_idx]
        
        # Determine current hole - beverage cart should show the same hole number
        # as golfers when they're at the same physical location
        if node_holes and 0 <= node_idx < len(nodes):
            # Use the original node holes (not reversed) since we want geographic consistency
            original_idx = total_nodes - 1 - node_idx  # Map reverse index to original
            current_hole = node_holes[original_idx] if 0 <= original_idx < len(node_holes) else 1
        else:
            # Estimate hole based on position - use forward hole numbering for geographic consistency
            hole_progress = loop_progress * 18
            current_hole = max(1, min(18, int(hole_progress) + 1))
        
        coordinates.append({
            "latitude": lat,
            "longitude": lon,
            "timestamp": timestamp,
            "type": "bev_cart",
            "hole": current_hole,  # Use same field name as golfer for consistency
        })
    
    return coordinates


def choose_tee_time_from_config(course_dir: str) -> int:
    """
    Choose a deterministic tee time aligned to configuration.
    
    Args:
        course_dir: Path to course configuration directory
        
    Returns:
        Tee time in seconds since 7 AM baseline
    """
    cfg = load_tee_times_config(course_dir)
    scenarios = cfg.scenarios or {}
    key = "testing_rainy_day" if "testing_rainy_day" in scenarios else (
        next(iter(scenarios.keys())) if scenarios else None
    )
    
    if key is None:
        return (9 - 7) * 3600  # Default to 9 AM
        
    hourly = scenarios[key].get("hourly_golfers", {})
    for hhmm, count in hourly.items():
        try:
            if int(count) > 0:
                hh, mm = hhmm.split(":")
                return (int(hh) - 7) * 3600 + int(mm) * 60
        except (ValueError, TypeError):
            continue
            
    return (9 - 7) * 3600  # Fallback to 9 AM


def load_hole_geometry(course_dir: str) -> Dict[int, LineString]:
    """
    Load hole geometry from course GeoJSON files.
    
    Args:
        course_dir: Path to course directory
        
    Returns:
        Dictionary mapping hole numbers to LineString geometries
    """
    hole_lines: Dict[int, LineString] = {}
    holes_file = Path(course_dir) / "geojson" / "holes.geojson"
    
    if holes_file.exists():
        holes_data = json.loads(holes_file.read_text(encoding="utf-8"))
        for feature in holes_data.get("features", []):
            props = feature.get("properties", {})
            raw_num = props.get("hole", props.get("ref"))
            try:
                hole_num = int(raw_num) if raw_num is not None else None
            except (TypeError, ValueError):
                hole_num = None
                
            if hole_num and feature.get("geometry", {}).get("type") == "LineString":
                coords = feature["geometry"]["coordinates"]
                hole_lines[hole_num] = LineString(coords)
                
    return hole_lines


def generate_golfer_track(course_dir: str, tee_time_s: int) -> List[Dict]:
    """
    Generate golfer GPS track using the simple track generator.
    
    Args:
        course_dir: Path to course directory
        tee_time_s: When golfer starts their round
        
    Returns:
        List of golfer GPS coordinate dictionaries
    """
    gen_module = runpy.run_path("scripts/sim/generate_simple_tracks.py")
    generate_tracks = gen_module["generate_tracks"]
    tracks = generate_tracks(course_dir)
    golfer_points: List[Dict] = tracks.get("golfer", [])
    
    # Align timestamps to tee time
    for p in golfer_points:
        p["timestamp"] = int(p.get("timestamp", 0)) + int(tee_time_s)
        p["type"] = p.get("type", "golfer")
        
    return golfer_points


def run_phase3_beverage_cart_simulation(
    course_dir: str,
    run_idx: int,
    use_synchronized_timing: bool = False
) -> Dict:
    """
    Run a complete Phase 3 simulation (beverage cart + 1 golfer group).
    
    Args:
        course_dir: Path to course configuration
        run_idx: Simulation run index for random seeding
        use_synchronized_timing: Whether to use GCD/LCM synchronized timing
        
    Returns:
        Dictionary with simulation results and metadata
    """
    # Seed RNG for reproducibility
    random.seed(run_idx)
    
    # Load configuration
    sim_cfg = load_simulation_config(course_dir)
    # Random tee time between 09:00 and 11:00 (seconds since 07:00 baseline)
    # Reproducible per run_idx due to seeding above
    nine_am_s = (9 - 7) * 3600
    eleven_am_s = (11 - 7) * 3600
    tee_time_s = int(random.randint(nine_am_s, eleven_am_s))
    group = {"group_id": 1, "tee_time_s": int(tee_time_s), "num_golfers": 4}
    
    # Generate golfer track
    golfer_points = generate_golfer_track(course_dir, tee_time_s)
    
    if use_synchronized_timing:
        return _run_simplified_simulation(
            course_dir, sim_cfg, group, golfer_points, run_idx
        )
    else:
        return _run_standard_simulation(
            course_dir, sim_cfg, group, golfer_points, run_idx
        )


def _run_standard_simulation(
    course_dir: str,
    sim_cfg,
    group: Dict,
    golfer_points: List[Dict],
    run_idx: int
) -> Dict:
    """Run standard Phase 3 simulation without synchronized timing."""
    tee_time_s = group["tee_time_s"]
    
    # Ensure random seed is set for this specific simulation
    random.seed(run_idx)
    
    # Compute crossings to determine when sales opportunities occur
    from .crossings import compute_crossings_from_files
    from pathlib import Path
    
    try:
        nodes_geojson = str(Path(course_dir) / "geojson" / "generated" / "holes_connected.geojson")
        holes_geojson = None
        config_json = str(Path(course_dir) / "config" / "simulation_config.json")
        
        def seconds_to_clock_str(sec_since_7am: int) -> str:
            total = max(0, int(sec_since_7am))
            hh = 7 + (total // 3600)
            mm = (total % 3600) // 60
            ss = total % 60
            return f"{hh:02d}:{mm:02d}:{ss:02d}"
        
        bev_start_s = (9 - 7) * 3600  # 9 AM
        bev_start_clock = seconds_to_clock_str(bev_start_s)
        groups_start_clock = seconds_to_clock_str(tee_time_s)
        
        crossings_data = compute_crossings_from_files(
            nodes_geojson=nodes_geojson,
            holes_geojson=holes_geojson,
            config_json=config_json,
            v_fwd_mph=None,
            v_bwd_mph=None,
            bev_start=bev_start_clock,
            groups_start=groups_start_clock,
            groups_end=groups_start_clock,
            groups_count=1,
            random_seed=run_idx,
            tee_mode="interval",
            groups_interval_min=30.0,
        )
    except Exception:
        crossings_data = None
    
    # Simulate sales using beverage cart pass detection based on actual crossings
    sales_result = simulate_beverage_cart_sales(
        course_dir=course_dir,
        groups=[group],
        pass_order_probability=float(sim_cfg.bev_cart_order_probability),
        price_per_order=float(sim_cfg.bev_cart_avg_order_usd),
        minutes_between_holes=2.0,
        golfer_points=golfer_points,
        crossings_data=crossings_data,
    )
    
    # Generate beverage cart GPS using exact same nodes as crossings calculation
    bev_points = _generate_beverage_cart_gps_from_nodes(
        course_dir=course_dir,
        cart_id=f"bev_cart_{run_idx}",
        service_start_s=7200,  # 9 AM
        service_end_s=36000,   # 5 PM
        crossings_data=crossings_data
    )
    
    # Use exact crossing data for pass events instead of proximity detection
    pass_events = []
    if crossings_data and crossings_data.get("groups"):
        first_group = crossings_data["groups"][0]
        for crossing in first_group.get("crossings", []):
            timestamp = crossing.get("timestamp")
            if timestamp:
                if hasattr(timestamp, 'hour'):
                    crossing_timestamp_s = ((timestamp.hour - 7) * 3600 + 
                                          timestamp.minute * 60 + 
                                          timestamp.second)
                else:
                    crossing_timestamp_s = crossing.get("t_cross_s", 0)
                
                pass_events.append({
                    "timestamp_s": int(crossing_timestamp_s),
                    "hole_num": crossing.get("hole") or 1,
                    "event_type": "exact_crossing",
                    "node_index": crossing.get("node_index", 0),
                })
    
    return {
        "type": "standard",
        "run_idx": run_idx,
        "sales_result": sales_result,
        "golfer_points": golfer_points,
        "bev_points": bev_points,
        "pass_events": pass_events,
        "tee_time_s": tee_time_s,
        "beverage_cart_service": None,  # Using direct GPS generation instead of service
    }


def _run_simplified_simulation(
    course_dir: str,
    sim_cfg,
    group: Dict,
    golfer_points: List[Dict],
    run_idx: int
) -> Dict:
    """Run simulation with simplified node-per-minute timing."""
    tee_time_s = group["tee_time_s"]
    
    # Ensure random seed is set for this specific simulation
    random.seed(run_idx)
    
    # Use simple node-per-minute timing
    node_timing = get_node_timing(
        golfer_total_minutes=sim_cfg.speeds.golfer_total_minutes,
        time_quantum_s=sim_cfg.speeds.time_quantum_s
    )
    
    # Beverage cart service hours (9 AM to 5 PM)
    bev_cart_start_s = 2 * 3600  # 9 AM (2 hours after 7 AM baseline)
    bev_cart_end_s = 10 * 3600   # 5 PM (10 hours after 7 AM baseline)
    
    # Generate beverage cart GPS using simplified approach
    bev_points = simulate_beverage_cart_gps(
        course_dir=course_dir,
        clubhouse_lonlat=sim_cfg.clubhouse,
        start_time_s=bev_cart_start_s,
        end_time_s=bev_cart_end_s,
        golfer_total_minutes=sim_cfg.speeds.golfer_total_minutes,
        cart_id=f"bev_cart_{run_idx}",
        track_coordinates=True,
        time_quantum_s=sim_cfg.speeds.time_quantum_s,
    )
    
    # Simulate sales with node-based timing
    sales_result = simulate_beverage_cart_sales(
        course_dir=course_dir,
        groups=[group],
        pass_order_probability=float(sim_cfg.bev_cart_order_probability_per_9_holes),
        price_per_order=float(sim_cfg.bev_cart_avg_order_usd),
        golfer_points=golfer_points,
    )
    
    # Compute pass events using proximity-based detection
    pass_events = find_proximity_pass_events(
        tee_time_s=tee_time_s,
        beverage_cart_points=bev_points,
        golfer_points=golfer_points,
        proximity_threshold_m=100.0,
        min_pass_interval_s=1200,
    )
    
    return {
        "type": "simplified", 
        "run_idx": f"simplified_{run_idx}",
        "sales_result": sales_result,
        "golfer_points": golfer_points,
        "bev_points": bev_points,
        "pass_events": pass_events,
        "tee_time_s": tee_time_s,
        "node_timing": node_timing,
    }


def run_phase4_beverage_cart_simulation(
    course_dir: str,
    run_idx: int,
    use_synchronized_timing: bool = False
) -> Dict:
    """
    Run a complete Phase 4 simulation (beverage cart + 4 golfer groups spaced 15 minutes apart).
    
    Args:
        course_dir: Path to course configuration
        run_idx: Simulation run index for random seeding
        use_synchronized_timing: Whether to use GCD/LCM synchronized timing
        
    Returns:
        Dictionary with simulation results and metadata
    """
    # Seed RNG for reproducibility
    random.seed(run_idx)
    
    # Load configuration
    sim_cfg = load_simulation_config(course_dir)
    
    # Create 4 groups spaced 15 minutes apart, starting at random time between 09:00 and 10:00
    nine_am_s = (9 - 7) * 3600
    ten_am_s = (10 - 7) * 3600
    first_tee_time_s = int(random.randint(nine_am_s, ten_am_s))
    
    groups = []
    all_golfer_points = []
    
    for i in range(4):
        group_tee_time_s = first_tee_time_s + (i * 15 * 60)  # 15 minutes apart
        group = {
            "group_id": i + 1, 
            "tee_time_s": int(group_tee_time_s), 
            "num_golfers": 4
        }
        groups.append(group)
        
        # Generate golfer track for this group
        golfer_points = generate_golfer_track(course_dir, group_tee_time_s)
        # Tag points with group_id for identification
        for p in golfer_points:
            p["group_id"] = i + 1
        all_golfer_points.extend(golfer_points)
    
    if use_synchronized_timing:
        return _run_phase4_simplified_simulation(
            course_dir, sim_cfg, groups, all_golfer_points, run_idx
        )
    else:
        return _run_phase4_standard_simulation(
            course_dir, sim_cfg, groups, all_golfer_points, run_idx
        )


def _run_phase4_standard_simulation(
    course_dir: str,
    sim_cfg,
    groups: List[Dict],
    all_golfer_points: List[Dict],
    run_idx: int
) -> Dict:
    """Run standard Phase 4 simulation without synchronized timing."""
    
    # Ensure random seed is set for this specific simulation
    random.seed(run_idx)
    
    # Compute crossings for all groups to determine when sales opportunities occur
    from .crossings import compute_crossings_from_files
    from pathlib import Path
    
    try:
        nodes_geojson = str(Path(course_dir) / "geojson" / "generated" / "holes_connected.geojson")
        holes_geojson = None
        config_json = str(Path(course_dir) / "config" / "simulation_config.json")
        
        def seconds_to_clock_str(sec_since_7am: int) -> str:
            total = max(0, int(sec_since_7am))
            hh = 7 + (total // 3600)
            mm = (total % 3600) // 60
            ss = total % 60
            return f"{hh:02d}:{mm:02d}:{ss:02d}"
        
        bev_start_s = (9 - 7) * 3600  # 9 AM
        bev_start_clock = seconds_to_clock_str(bev_start_s)
        
        # Use first and last group tee times for range
        first_tee_time_s = groups[0]["tee_time_s"]
        last_tee_time_s = groups[-1]["tee_time_s"]
        groups_start_clock = seconds_to_clock_str(first_tee_time_s)
        groups_end_clock = seconds_to_clock_str(last_tee_time_s)
        
        crossings_data = compute_crossings_from_files(
            nodes_geojson=nodes_geojson,
            holes_geojson=holes_geojson,
            config_json=config_json,
            v_fwd_mph=None,
            v_bwd_mph=None,
            bev_start=bev_start_clock,
            groups_start=groups_start_clock,
            groups_end=groups_end_clock,
            groups_count=4,
            random_seed=run_idx,
            tee_mode="interval",
            groups_interval_min=15.0,
        )
    except Exception:
        crossings_data = None
    
    # Simulate sales using beverage cart pass detection based on actual crossings
    sales_result = simulate_beverage_cart_sales(
        course_dir=course_dir,
        groups=groups,
        pass_order_probability=float(sim_cfg.bev_cart_order_probability),
        price_per_order=float(sim_cfg.bev_cart_avg_order_usd),
        minutes_between_holes=2.0,
        minutes_per_hole=None,
        golfer_points=all_golfer_points,
        crossings_data=crossings_data,
    )
    
    # Generate beverage cart GPS using exact same nodes as crossings calculation
    bev_points = _generate_beverage_cart_gps_from_nodes(
        course_dir=course_dir,
        cart_id=f"bev_cart_{run_idx}",
        service_start_s=7200,  # 9 AM
        service_end_s=36000,   # 5 PM
        crossings_data=crossings_data
    )
    
    # Use exact crossing data for pass events instead of proximity detection
    pass_events = []
    if crossings_data and crossings_data.get("groups"):
        for group_idx, group_data in enumerate(crossings_data["groups"]):
            for crossing in group_data.get("crossings", []):
                timestamp = crossing.get("timestamp")
                if timestamp:
                    if hasattr(timestamp, 'hour'):
                        crossing_timestamp_s = ((timestamp.hour - 7) * 3600 + 
                                              timestamp.minute * 60 + 
                                              timestamp.second)
                    else:
                        crossing_timestamp_s = crossing.get("t_cross_s", 0)
                    
                    pass_events.append({
                        "timestamp_s": int(crossing_timestamp_s),
                        "hole_num": crossing.get("hole") or 1,
                        "event_type": "exact_crossing",
                        "node_index": crossing.get("node_index", 0),
                        "group_id": group_idx + 1,
                    })
    
    return {
        "type": "standard",
        "run_idx": run_idx,
        "sales_result": sales_result,
        "golfer_points": all_golfer_points,
        "bev_points": bev_points,
        "pass_events": pass_events,
        "groups": groups,
        "first_tee_time_s": first_tee_time_s,
        "last_tee_time_s": last_tee_time_s,
        "beverage_cart_service": None,  # Using direct GPS generation instead of service
    }


def _run_phase4_simplified_simulation(
    course_dir: str,
    sim_cfg,
    groups: List[Dict],
    all_golfer_points: List[Dict],
    run_idx: int
) -> Dict:
    """Run Phase 4 simulation with simplified node-per-minute timing."""
    first_tee_time_s = groups[0]["tee_time_s"]
    
    # Ensure random seed is set for this specific simulation
    random.seed(run_idx)
    
    # Use simple node-per-minute timing
    node_timing = get_node_timing(
        golfer_total_minutes=sim_cfg.speeds.golfer_total_minutes,
        time_quantum_s=sim_cfg.speeds.time_quantum_s
    )
    
    # Beverage cart service hours (9 AM to 5 PM)
    bev_cart_start_s = 2 * 3600  # 9 AM (2 hours after 7 AM baseline)
    bev_cart_end_s = 10 * 3600   # 5 PM (10 hours after 7 AM baseline)
    
    # Generate beverage cart GPS using simplified approach
    bev_points = simulate_beverage_cart_gps(
        course_dir=course_dir,
        clubhouse_lonlat=sim_cfg.clubhouse,
        start_time_s=bev_cart_start_s,
        end_time_s=bev_cart_end_s,
        golfer_total_minutes=sim_cfg.speeds.golfer_total_minutes,
        cart_id=f"bev_cart_{run_idx}",
        track_coordinates=True,
        time_quantum_s=sim_cfg.speeds.time_quantum_s,
    )
    
    # Simulate sales with simplified timing for all groups
    sales_result = simulate_beverage_cart_sales(
        course_dir=course_dir,
        groups=groups,
        pass_order_probability=float(sim_cfg.bev_cart_order_probability_per_9_holes),
        price_per_order=float(sim_cfg.bev_cart_avg_order_usd),
        golfer_points=all_golfer_points,
    )
    
    # Compute pass events using proximity-based detection
    pass_events = find_proximity_pass_events(
        tee_time_s=first_tee_time_s,
        beverage_cart_points=bev_points,
        golfer_points=all_golfer_points,
        proximity_threshold_m=100.0,
        min_pass_interval_s=1200,
    )
    
    return {
        "type": "simplified", 
        "run_idx": f"simplified_{run_idx}",
        "sales_result": sales_result,
        "golfer_points": all_golfer_points,
        "bev_points": bev_points,
        "pass_events": pass_events,
        "groups": groups,
        "first_tee_time_s": first_tee_time_s,
        "last_tee_time_s": groups[-1]["tee_time_s"],
        "node_timing": node_timing,
    }


def build_groups_from_scenario(
    scenario_config: Dict[str, Any], 
    scenario_name: str,
    random_seed: int
) -> List[Dict]:
    """
    Build golfer groups from a tee times scenario configuration.
    
    Args:
        scenario_config: Single scenario from tee_times_config.json
        scenario_name: Name of the scenario for identification
        random_seed: Seed for random tee time generation within hours
        
    Returns:
        List of group dictionaries with group_id, tee_time_s, num_golfers
    """
    import random
    
    random.seed(random_seed)
    
    hourly_golfers = scenario_config.get("hourly_golfers", {})
    groups = []
    group_id = 1
    

    
    try:
        for hour_str, count in hourly_golfers.items():
            if not isinstance(count, int) or count <= 0:
                continue
                
            # Parse hour (e.g., "07:00" -> 7)
            try:
                hour_parts = hour_str.split(":")
                hour = int(hour_parts[0])
                minute = int(hour_parts[1]) if len(hour_parts) > 1 else 0
            except (ValueError, IndexError):
                continue
                
            # Convert to seconds since 7 AM baseline
            base_time_s = (hour - 7) * 3600 + minute * 60
            
            # Distribute golfers throughout the hour
            # Each group is 4 golfers, so number of groups = ceil(count / 4)
            num_groups = (count + 3) // 4  # Ceiling division
            
            for i in range(num_groups):
                # Calculate golfers in this group (last group might have fewer than 4)
                remaining_golfers = count - (i * 4)
                group_golfers = min(4, remaining_golfers)
                
                # Random tee time within this hour (0-3599 seconds)
                random_offset_s = random.randint(0, 3599)
                tee_time_s = base_time_s + random_offset_s
                
                groups.append({
                    "group_id": group_id,
                    "tee_time_s": int(tee_time_s),
                    "num_golfers": int(group_golfers),
                    "scenario": scenario_name,
                    "hour": hour_str,
                })
                group_id += 1
                print(f"DEBUG: Created group {group_id-1} with {group_golfers} golfers at {hour_str}")
    except Exception as e:
        print(f"DEBUG: Error in hourly_golfers loop: {e}")
        import traceback
        traceback.print_exc()
        raise
    
    # Sort groups by tee time
    groups.sort(key=lambda g: g["tee_time_s"])
    
    # Renumber group_ids to be sequential
    for i, group in enumerate(groups, 1):
        group["group_id"] = i
    
    return groups


def run_phase5_beverage_cart_simulation(
    course_dir: str,
    scenario_name: str,
    run_idx: int,
    use_synchronized_timing: bool = False
) -> Dict:
    """
    Run a complete Phase 5 simulation (beverage cart + many groups from tee times scenario).
    
    Args:
        course_dir: Path to course configuration
        scenario_name: Name of scenario from tee_times_config.json to use
        run_idx: Simulation run index for random seeding
        use_synchronized_timing: Whether to use GCD/LCM synchronized timing
        
    Returns:
        Dictionary with simulation results and metadata
    """
    # Seed RNG for reproducibility
    random.seed(run_idx)
    
    # Load configurations
    sim_cfg = load_simulation_config(course_dir)
    tee_times_cfg = load_tee_times_config(course_dir)
    
    # Get the specified scenario
    scenarios = tee_times_cfg.scenarios or {}
    if scenario_name not in scenarios:
        raise ValueError(f"Scenario '{scenario_name}' not found in tee_times_config.json")
    
    scenario_config = scenarios[scenario_name]
    
    # Build groups from scenario
    groups = build_groups_from_scenario(scenario_config, scenario_name, run_idx)
    
    if not groups:
        raise ValueError(f"No valid groups generated from scenario '{scenario_name}'")
    
    # Generate golfer tracks for all groups
    all_golfer_points = []
    for group in groups:
        golfer_points = generate_golfer_track(course_dir, group["tee_time_s"])
        # Tag points with group_id for identification
        for p in golfer_points:
            p["group_id"] = group["group_id"]
        all_golfer_points.extend(golfer_points)
    
    if use_synchronized_timing:
        return _run_phase5_simplified_simulation(
            course_dir, sim_cfg, groups, all_golfer_points, run_idx, scenario_name
        )
    else:
        return _run_phase5_standard_simulation(
            course_dir, sim_cfg, groups, all_golfer_points, run_idx, scenario_name
        )


def _run_phase5_standard_simulation(
    course_dir: str,
    sim_cfg,
    groups: List[Dict],
    all_golfer_points: List[Dict],
    run_idx: int,
    scenario_name: str
) -> Dict:
    """Run standard Phase 5 simulation without synchronized timing."""
    # Ensure random seed is set for this specific simulation
    random.seed(run_idx)
    
    # Compute crossings for all groups to determine when sales opportunities occur
    from .crossings import compute_crossings_from_files
    from pathlib import Path
    
    try:
        nodes_geojson = str(Path(course_dir) / "geojson" / "generated" / "holes_connected.geojson")
        holes_geojson = None
        config_json = str(Path(course_dir) / "config" / "simulation_config.json")
        
        def seconds_to_clock_str(sec_since_7am: int) -> str:
            total = max(0, int(sec_since_7am))
            hh = 7 + (total // 3600)
            mm = (total % 3600) // 60
            ss = total % 60
            return f"{hh:02d}:{mm:02d}:{ss:02d}"
        
        bev_start_s = (9 - 7) * 3600  # 9 AM
        bev_start_clock = seconds_to_clock_str(bev_start_s)
        
        # Use first and last group tee times for range
        first_tee_time_s = min(g["tee_time_s"] for g in groups)
        last_tee_time_s = max(g["tee_time_s"] for g in groups)
        groups_start_clock = seconds_to_clock_str(first_tee_time_s)
        groups_end_clock = seconds_to_clock_str(last_tee_time_s)
        
        crossings_data = compute_crossings_from_files(
            nodes_geojson=nodes_geojson,
            holes_geojson=holes_geojson,
            config_json=config_json,
            v_fwd_mph=None,
            v_bwd_mph=None,
            bev_start=bev_start_clock,
            groups_start=groups_start_clock,
            groups_end=groups_end_clock,
            groups_count=len(groups),
            random_seed=run_idx,
            tee_mode="random",  # Use random tee mode since groups have explicit times
            groups_interval_min=30.0,  # Not used in random mode
        )
    except Exception:
        crossings_data = None
    
    # Simulate sales using beverage cart pass detection based on actual crossings
    sales_result = simulate_beverage_cart_sales(
        course_dir=course_dir,
        groups=groups,
        pass_order_probability=float(sim_cfg.bev_cart_order_probability),
        price_per_order=float(sim_cfg.bev_cart_avg_order_usd),
        minutes_between_holes=2.0,
        minutes_per_hole=None,
        golfer_points=all_golfer_points,
        crossings_data=crossings_data,
    )
    
    # Generate beverage cart GPS using exact same nodes as crossings calculation
    bev_points = _generate_beverage_cart_gps_from_nodes(
        course_dir=course_dir,
        cart_id=f"bev_cart_{run_idx}",
        service_start_s=7200,  # 9 AM
        service_end_s=36000,   # 5 PM
        crossings_data=crossings_data
    )
    
    # Use exact crossing data for pass events instead of proximity detection
    pass_events = []
    if crossings_data and crossings_data.get("groups"):
        for group_idx, group_data in enumerate(crossings_data["groups"]):
            for crossing in group_data.get("crossings", []):
                timestamp = crossing.get("timestamp")
                if timestamp:
                    if hasattr(timestamp, 'hour'):
                        crossing_timestamp_s = ((timestamp.hour - 7) * 3600 + 
                                              timestamp.minute * 60 + 
                                              timestamp.second)
                    else:
                        crossing_timestamp_s = crossing.get("t_cross_s", 0)
                    
                    pass_events.append({
                        "timestamp_s": int(crossing_timestamp_s),
                        "hole_num": crossing.get("hole") or 1,
                        "event_type": "exact_crossing",
                        "node_index": crossing.get("node_index", 0),
                        "group_id": group_idx + 1,
                    })
    
    return {
        "type": "standard",
        "run_idx": run_idx,
        "scenario_name": scenario_name,
        "sales_result": sales_result,
        "golfer_points": all_golfer_points,
        "bev_points": bev_points,
        "pass_events": pass_events,
        "groups": groups,
        "first_tee_time_s": first_tee_time_s,
        "last_tee_time_s": last_tee_time_s,
        "beverage_cart_service": None,  # Using direct GPS generation instead of service
    }


def _run_phase5_simplified_simulation(
    course_dir: str,
    sim_cfg,
    groups: List[Dict],
    all_golfer_points: List[Dict],
    run_idx: int,
    scenario_name: str
) -> Dict:
    """Run Phase 5 simulation with simplified node-per-minute timing."""
    first_tee_time_s = min(g["tee_time_s"] for g in groups)
    
    # Ensure random seed is set for this specific simulation
    random.seed(run_idx)
    
    # Use simple node-per-minute timing
    node_timing = get_node_timing(
        golfer_total_minutes=sim_cfg.speeds.golfer_total_minutes,
        time_quantum_s=sim_cfg.speeds.time_quantum_s
    )
    
    # Beverage cart service hours (9 AM to 5 PM)
    bev_cart_start_s = 2 * 3600  # 9 AM (2 hours after 7 AM baseline)
    bev_cart_end_s = 10 * 3600   # 5 PM (10 hours after 7 AM baseline)
    
    # Generate beverage cart GPS using simplified approach
    bev_points = simulate_beverage_cart_gps(
        course_dir=course_dir,
        clubhouse_lonlat=sim_cfg.clubhouse,
        start_time_s=bev_cart_start_s,
        end_time_s=bev_cart_end_s,
        golfer_total_minutes=sim_cfg.speeds.golfer_total_minutes,
        cart_id=f"bev_cart_{run_idx}",
        track_coordinates=True,
        time_quantum_s=sim_cfg.speeds.time_quantum_s,
    )
    
    # Simulate sales with simplified timing for all groups
    sales_result = simulate_beverage_cart_sales(
        course_dir=course_dir,
        groups=groups,
        pass_order_probability=float(sim_cfg.bev_cart_order_probability_per_9_holes),
        price_per_order=float(sim_cfg.bev_cart_avg_order_usd),
        golfer_points=all_golfer_points,
    )
    
    # Compute pass events using proximity-based detection
    pass_events = find_proximity_pass_events(
        golfer_points=all_golfer_points,
        bev_points=bev_points,
        proximity_threshold_m=50.0
    )
    
    return {
        "type": "simplified",
        "run_idx": run_idx,
        "scenario_name": scenario_name,
        "sales_result": sales_result,
        "golfer_points": all_golfer_points,
        "bev_points": bev_points,
        "pass_events": pass_events,
        "groups": groups,
        "first_tee_time_s": first_tee_time_s,
        "last_tee_time_s": max(g["tee_time_s"] for g in groups),
        "beverage_cart_service": None,  # Using direct GPS generation
        "node_timing": node_timing,
    }
