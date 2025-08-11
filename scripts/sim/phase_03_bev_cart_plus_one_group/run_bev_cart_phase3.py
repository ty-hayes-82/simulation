"""
Phase 3 simulation runner: Beverage cart + 1 golfer group.

This script orchestrates Phase 3 simulations using the core simulation modules.
All business logic has been moved to reusable modules.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from golfsim.logging import init_logging
from golfsim.simulation.phase_simulations import run_phase3_beverage_cart_simulation
from golfsim.io.phase_reporting import save_phase3_output_files, write_phase3_summary

# Use shared closed-form crossings utilities for accurate pass/meet computation
from golfsim.simulation.crossings import (
    compute_crossings_from_files as _compute_crossings_from_files,
    serialize_crossings_summary as _serialize_crossings_summary,
)


def run_single_simulation(
    course_dir: str, 
    run_idx: int, 
    output_root: Path, 
    use_synchronized_timing: bool = False
) -> Dict:
    """
    Run a single Phase 3 simulation and save outputs.
    
    Args:
        course_dir: Path to course configuration
        run_idx: Run index for identification and seeding
        output_root: Root directory for outputs
        use_synchronized_timing: Whether to use synchronized timing
        
    Returns:
        Summary dictionary with key metrics
    """
    start_time = time.time()
    
    # Run the simulation using core modules
    result = run_phase3_beverage_cart_simulation(
        course_dir=course_dir,
        run_idx=run_idx,
        use_synchronized_timing=use_synchronized_timing
    )
    
    # Add timing information
    result["simulation_runtime_s"] = time.time() - start_time
    
    # Determine output directory name
    if use_synchronized_timing:
        run_dir = output_root / f"sim_sync_{run_idx:02d}"
    else:
        run_dir = output_root / f"sim_{run_idx:02d}"
    
    # Save all output files
    save_phase3_output_files(result, run_dir)
    
    # Return summary for aggregation
    sales_result = result["sales_result"]
    summary: Dict = {
        "run_idx": run_idx,
        "revenue": float(sales_result.get("revenue", 0.0)),
        "num_sales": int(len(sales_result.get("sales", []))),
        "num_pass_intervals": int(len(sales_result.get("pass_intervals_per_group", {}).get("1", []))),
        "tee_time_s": result.get("tee_time_s"),
    }
    # Attach accurate crossings computation using actual tee time and bev cart service start
    try:
        # Extract actual times from result
        tee_time_s: int = int(result.get("tee_time_s"))
        # Beverage cart service start from service object if present
        svc = result.get("beverage_cart_service")
        bev_start_s: int = int(getattr(svc, "service_start_s", (9 - 7) * 3600) if svc else (9 - 7) * 3600)

        def seconds_to_clock_str(sec_since_7am: int) -> str:
            total = max(0, int(sec_since_7am))
            hh = 7 + (total // 3600)
            mm = (total % 3600) // 60
            ss = total % 60
            return f"{hh:02d}:{mm:02d}:{ss:02d}"

        bev_start_clock = seconds_to_clock_str(bev_start_s)
        groups_start_clock = seconds_to_clock_str(tee_time_s)
        # Single group; end clock can equal start in interval mode (ignored)
        groups_end_clock = groups_start_clock

        nodes_geojson = str(Path(course_dir) / "geojson" / "generated" / "lcm_course_nodes.geojson")
        holes_geojson = str(Path(course_dir) / "geojson" / "generated" / "holes_geofenced.geojson")
        config_json = str(Path(course_dir) / "config" / "simulation_config.json")

        crossings = _compute_crossings_from_files(
            nodes_geojson=nodes_geojson,
            holes_geojson=holes_geojson,
            config_json=config_json,
            v_fwd_mph=None,
            v_bwd_mph=None,
            bev_start=bev_start_clock,
            groups_start=groups_start_clock,
            groups_end=groups_end_clock,
            groups_count=1,
            random_seed=run_idx,
            tee_mode="interval",
            groups_interval_min=30.0,
        )

        # Store a concise, serializable view
        summary["crossings"] = _serialize_crossings_summary(crossings)
        # Convenience: total crossings and first crossing
        groups = crossings.get("groups", [])
        first_group = groups[0] if groups else {}
        first_crossings = first_group.get("crossings", [])
        summary["num_crossings"] = sum(len(g.get("crossings", [])) for g in groups)
        if first_crossings:
            first = first_crossings[0]
            summary["first_crossing"] = {
                "timestamp": first.get("timestamp").isoformat() if first.get("timestamp") else None,
                "node_index": first.get("node_index"),
                "hole": first.get("hole"),
            }
    except Exception:
        # Non-fatal; continue without crossings if any input is missing
        pass
    return summary


def main(use_synchronized_timing: bool = False) -> None:
    """
    Run Phase 3 simulation with optional synchronized timing.
    
    Args:
        use_synchronized_timing: If True, use GCD/LCM synchronized timing for optimal meetings
    """
    init_logging("INFO")
    course_dir = "courses/pinetree_country_club"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path("outputs") / f"{ts}_phase_03"
    output_root.mkdir(parents=True, exist_ok=True)

    all_results: List[Dict] = []
    
    # Add demo of synchronized timing if requested
    if use_synchronized_timing:
        print("\n=== SYNCHRONIZED TIMING DEMO ===")
        demo_result = run_single_simulation(course_dir, 1, output_root, use_synchronized_timing=True)
        print(f"Demo completed in {demo_result.get('simulation_runtime_s', 0):.1f}s")
    
    # Run standard simulations
    for i in range(1, 6):
        print(f"Running sim {i}/5...")
        result = run_single_simulation(course_dir, i, output_root, use_synchronized_timing=False)
        all_results.append(result)
        print(f"  Completed in {result.get('simulation_runtime_s', 0):.1f}s")

    # Write summary
    write_phase3_summary(all_results, output_root)
    print(f"Complete. Results saved to: {output_root}")


if __name__ == "__main__":
    import sys
    use_sync = "--sync" in sys.argv
    main(use_synchronized_timing=use_sync)