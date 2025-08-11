"""
Phase 5 simulation runner: Beverage cart + many groups from tee times scenarios.

This script orchestrates Phase 5 simulations using all scenarios from tee_times_config.json.
Each scenario is run multiple times with the beverage cart and groups generated from the scenario's
hourly_golfers distribution.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from golfsim.logging import init_logging
from golfsim.simulation.phase_simulations import run_phase5_beverage_cart_simulation
from golfsim.io.phase_reporting import save_phase5_output_files, write_phase5_summary
from golfsim.config.loaders import load_tee_times_config


def _safe_count_pass_intervals(sales_result, groups):
    """Safely count pass intervals, handling both dict and list formats."""
    try:
        if not isinstance(sales_result, dict):
            return 0
        
        pass_intervals = sales_result.get("pass_intervals_per_group", {})
        
        if isinstance(pass_intervals, dict):
            return sum(
                len(pass_intervals.get(str(i), []))
                for i in range(1, len(groups) + 1)
            )
        else:
            # If it's not a dict, just return 0
            return 0
    except Exception:
        return 0

# Use shared closed-form crossings utilities for accurate pass/meet computation
from golfsim.simulation.crossings import (
    compute_crossings_from_files as _compute_crossings_from_files,
    serialize_crossings_summary as _serialize_crossings_summary,
)


def run_single_simulation(
    course_dir: str, 
    scenario_name: str,
    run_idx: int, 
    output_root: Path, 
    use_synchronized_timing: bool = False
) -> Dict:
    """
    Run a single Phase 5 simulation and save outputs.
    
    Args:
        course_dir: Path to course configuration
        scenario_name: Name of scenario from tee_times_config.json to use
        run_idx: Run index for identification and seeding
        output_root: Root directory for outputs
        use_synchronized_timing: Whether to use synchronized timing
        
    Returns:
        Summary dictionary with key metrics
    """
    start_time = time.time()
    
    # Run the simulation using core modules
    try:
        result = run_phase5_beverage_cart_simulation(
            course_dir=course_dir,
            scenario_name=scenario_name,
            run_idx=run_idx,
            use_synchronized_timing=use_synchronized_timing
        )
    except Exception as e:
        print(f"ERROR in run_phase5_beverage_cart_simulation: {e}")
        import traceback
        traceback.print_exc()
        raise
    
    # Add timing information
    result["simulation_runtime_s"] = time.time() - start_time
    
    # Determine output directory name
    if use_synchronized_timing:
        run_dir = output_root / scenario_name / f"sim_sync_{run_idx:02d}"
    else:
        run_dir = output_root / scenario_name / f"sim_{run_idx:02d}"
    
    # Save all output files
    save_phase5_output_files(result, run_dir)
    
    # Return summary for aggregation
    sales_result = result["sales_result"]
    groups = result["groups"]
    first_tee_time_s = result["first_tee_time_s"]
    last_tee_time_s = result["last_tee_time_s"]
    

    
    summary: Dict = {
        "run_idx": run_idx,
        "scenario_name": scenario_name,
        "revenue": float(sales_result.get("revenue", 0.0)),
        "num_sales": int(len(sales_result.get("sales", []))),
        "num_pass_intervals": _safe_count_pass_intervals(sales_result, groups),
        "first_tee_time_s": first_tee_time_s,
        "last_tee_time_s": last_tee_time_s,
        "groups": len(groups),
        "total_golfers": sum(g.get("num_golfers", 4) for g in groups),
    }
    
    # Attach accurate crossings computation using actual tee times and bev cart service start
    try:
        # Extract actual times from result
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
        groups_start_clock = seconds_to_clock_str(first_tee_time_s)
        groups_end_clock = seconds_to_clock_str(last_tee_time_s)

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
            groups_count=len(groups),
            random_seed=run_idx,
            tee_mode="random",  # Use random mode since groups have explicit times
            groups_interval_min=30.0,  # Not used in random mode
        )

        # Store a concise, serializable view
        summary["crossings"] = _serialize_crossings_summary(crossings)
        # Convenience: total crossings and first crossing
        groups_data = crossings.get("groups", [])
        summary["num_crossings"] = sum(len(g.get("crossings", [])) for g in groups_data)
        
        # Find first crossing across all groups
        first_crossing = None
        for group_data in groups_data:
            group_crossings = group_data.get("crossings", [])
            if group_crossings:
                crossing = group_crossings[0]
                if first_crossing is None or crossing.get("timestamp") < first_crossing.get("timestamp"):
                    first_crossing = crossing
        
        if first_crossing:
            summary["first_crossing"] = {
                "timestamp": first_crossing.get("timestamp").isoformat() if first_crossing.get("timestamp") else None,
                "node_index": first_crossing.get("node_index"),
                "hole": first_crossing.get("hole"),
            }
    except Exception:
        # Non-fatal; continue without crossings if any input is missing
        pass
    return summary


def run_scenario(
    course_dir: str,
    scenario_name: str,
    output_root: Path,
    num_runs: int = 5,
    use_synchronized_timing: bool = False
) -> List[Dict]:
    """
    Run multiple simulations for a single scenario.
    
    Args:
        course_dir: Path to course configuration
        scenario_name: Name of scenario to run
        output_root: Root directory for outputs
        num_runs: Number of simulation runs to perform
        use_synchronized_timing: Whether to use synchronized timing
        
    Returns:
        List of simulation result summaries
    """
    print(f"\n=== Running scenario: {scenario_name} ===")
    
    all_results: List[Dict] = []
    
    # Add demo of synchronized timing if requested
    if use_synchronized_timing:
        print("  Running synchronized timing demo...")
        demo_result = run_single_simulation(
            course_dir, scenario_name, 1, output_root, use_synchronized_timing=True
        )
        print(f"  Demo completed in {demo_result.get('simulation_runtime_s', 0):.1f}s")
    
    # Run standard simulations
    for i in range(1, num_runs + 1):
        print(f"  Running sim {i}/{num_runs}...")
        result = run_single_simulation(
            course_dir, scenario_name, i, output_root, use_synchronized_timing=False
        )
        all_results.append(result)
        print(f"    Completed in {result.get('simulation_runtime_s', 0):.1f}s")
        print(f"    Revenue: ${result.get('revenue', 0.0):.2f}, Sales: {result.get('num_sales', 0)}, Groups: {result.get('groups', 0)}")

    # Write scenario summary
    scenario_output_dir = output_root / scenario_name
    write_phase5_summary(all_results, scenario_output_dir, scenario_name)
    print(f"  Scenario results saved to: {scenario_output_dir}")
    
    # Show scenario summary stats
    revenues = [r.get("revenue", 0.0) for r in all_results]
    sales_counts = [r.get("num_sales", 0) for r in all_results]
    group_counts = [r.get("groups", 0) for r in all_results]
    print(f"  Summary: Revenue ${min(revenues):.2f}-${max(revenues):.2f}, "
          f"Sales {min(sales_counts)}-{max(sales_counts)}, "
          f"Groups {min(group_counts)}-{max(group_counts)}")
    
    return all_results


def main(use_synchronized_timing: bool = False, scenarios_filter: List[str] = None) -> None:
    """
    Run Phase 5 simulation across all scenarios with optional synchronized timing.
    
    Args:
        use_synchronized_timing: If True, use GCD/LCM synchronized timing for optimal meetings
        scenarios_filter: If provided, only run specified scenarios
    """
    init_logging("INFO")
    course_dir = "courses/pinetree_country_club"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path("outputs") / f"{ts}_phase_05"
    output_root.mkdir(parents=True, exist_ok=True)

    # Load tee times configuration
    tee_times_cfg = load_tee_times_config(course_dir)
    scenarios = tee_times_cfg.scenarios or {}
    
    if not scenarios:
        print("No scenarios found in tee_times_config.json")
        return
    
    # Filter scenarios if requested
    if scenarios_filter:
        scenarios = {k: v for k, v in scenarios.items() if k in scenarios_filter}
        if not scenarios:
            print(f"No matching scenarios found for filter: {scenarios_filter}")
            return
        print(f"Running filtered scenarios: {list(scenarios.keys())}")
    else:
        print(f"Running all scenarios: {list(scenarios.keys())}")

    all_scenario_results = {}
    
    # Run each scenario
    for scenario_name in scenarios.keys():
        try:
            results = run_scenario(
                course_dir=course_dir,
                scenario_name=scenario_name,
                output_root=output_root,
                num_runs=5,
                use_synchronized_timing=use_synchronized_timing
            )
            all_scenario_results[scenario_name] = results
        except Exception as e:
            print(f"  ERROR in scenario {scenario_name}: {e}")
            continue

    # Write master summary
    write_master_summary(all_scenario_results, output_root)
    print(f"\nComplete. All results saved to: {output_root}")


def write_master_summary(all_scenario_results: Dict[str, List[Dict]], output_root: Path) -> None:
    """
    Write a master summary.md file across all scenarios.
    
    Args:
        all_scenario_results: Dictionary mapping scenario names to their results
        output_root: Root output directory
    """
    lines = [
        "# Phase 5 Master Summary — Beverage Cart + Many Groups (All Scenarios)",
        "",
        f"**Generated at**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**Total scenarios**: {len(all_scenario_results)}",
        "",
        "## Scenario Performance Overview",
        "",
    ]
    
    # Summary table
    lines.append("| Scenario | Runs | Avg Groups | Avg Revenue | Avg Sales | Min-Max Revenue |")
    lines.append("|----------|------|------------|-------------|-----------|-----------------|")
    
    for scenario_name, results in all_scenario_results.items():
        if not results:
            continue
        
        num_runs = len(results)
        avg_groups = sum(r.get("groups", 0) for r in results) / num_runs
        revenues = [r.get("revenue", 0.0) for r in results]
        avg_revenue = sum(revenues) / num_runs
        avg_sales = sum(r.get("num_sales", 0) for r in results) / num_runs
        min_revenue = min(revenues)
        max_revenue = max(revenues)
        
        lines.append(f"| {scenario_name} | {num_runs} | {avg_groups:.1f} | ${avg_revenue:.2f} | {avg_sales:.1f} | ${min_revenue:.2f}-${max_revenue:.2f} |")
    
    lines.extend([
        "",
        "## Detailed Results by Scenario",
        "",
    ])
    
    # Detailed breakdown
    for scenario_name, results in all_scenario_results.items():
        if not results:
            continue
            
        lines.append(f"### {scenario_name}")
        lines.append("")
        
        revenues = [r.get("revenue", 0.0) for r in results]
        sales_counts = [r.get("num_sales", 0) for r in results]
        group_counts = [r.get("groups", 0) for r in results]
        golfer_counts = [r.get("total_golfers", 0) for r in results]
        
        lines.extend([
            f"- **Runs**: {len(results)}",
            f"- **Groups per run**: {min(group_counts)}-{max(group_counts)} (avg {sum(group_counts)/len(group_counts):.1f})",
            f"- **Golfers per run**: {min(golfer_counts)}-{max(golfer_counts)} (avg {sum(golfer_counts)/len(golfer_counts):.1f})",
            f"- **Revenue**: ${min(revenues):.2f}-${max(revenues):.2f} (avg ${sum(revenues)/len(revenues):.2f})",
            f"- **Sales**: {min(sales_counts)}-{max(sales_counts)} (avg {sum(sales_counts)/len(sales_counts):.1f})",
            f"- **Results**: `{scenario_name}/`",
            "",
        ])
    
    lines.extend([
        "## Files Generated",
        "",
        "Each scenario contains:",
        "- `sim_01/` through `sim_05/` - Individual simulation runs",
        "- `summary.md` - Scenario-specific summary",
        "",
        "Each simulation run contains:",
        "- `coordinates.csv` - Combined GPS tracks (golfers + beverage cart)",
        "- `bev_cart_route.png` - Beverage cart route visualization",
        "- `sales.json` - Detailed sales and pass data",
        "- `result.json` - Complete simulation metadata",
        "- `stats.md` - Run-specific statistics",
        "",
    ])
    
    (output_root / "summary.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description="Phase 5 simulation runner")
    parser.add_argument("--sync", action="store_true", help="Use synchronized timing")
    parser.add_argument("--scenarios", nargs="*", help="Filter to specific scenarios")
    
    args = parser.parse_args()
    
    main(use_synchronized_timing=args.sync, scenarios_filter=args.scenarios)
