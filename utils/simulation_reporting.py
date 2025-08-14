"""
Shared simulation result reporting utilities.

This module provides common functions for reporting simulation results
across different simulation scripts to reduce code duplication.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from golfsim.logging import get_logger
from golfsim.io.results import find_actual_delivery_location

logger = get_logger(__name__)


def log_simulation_results(results: Dict, run_idx: Optional[int] = None, track_coords: bool = False) -> None:
    """
    Log comprehensive simulation results in a consistent format.
    
    Args:
        results: Simulation results dictionary
        run_idx: Optional run index for multi-run simulations
        track_coords: Whether coordinates were tracked
    """
    prefix = f"Simulation {run_idx} " if run_idx is not None else "Simulation "
    
    logger.info(f"{prefix}Results:")
    logger.info("   Order time: %.1f minutes into round", results['order_time_s']/60)
    logger.info("   Service time: %.1f minutes", results['total_service_time_s']/60)
    logger.info("   Delivery distance: %.0f meters", results['delivery_distance_m'])
    logger.info("   Preparation time: %.1f minutes", results['prep_time_s']/60)
    logger.info("   Travel time (out+back): %.1f minutes", results['delivery_travel_time_s']/60)
    
    # Show route efficiency if available
    trip_to_golfer = results.get('trip_to_golfer', {})
    if 'efficiency' in trip_to_golfer and trip_to_golfer['efficiency'] is not None:
        logger.info("   Route efficiency: %.1f%% vs straight line", trip_to_golfer['efficiency'])
    
    # Show actual delivery location if coordinates were tracked
    if track_coords:
        delivery_location = find_actual_delivery_location(results)
        if delivery_location:
            hole = delivery_location.get('hole')
            if hole:
                logger.info("   Actual delivery location: Hole %s at %.6f, %.6f",
                            hole, delivery_location['latitude'], delivery_location['longitude'])
            else:
                logger.info("   Actual delivery location: %.6f, %.6f",
                            delivery_location['latitude'], delivery_location['longitude'])
    
    if results.get('prediction_method'):
        logger.info("   Prediction method: %s", results['prediction_method'])


def write_simulation_stats(results: Dict, save_path: Path, title: str = "Simulation Results") -> None:
    """
    Write a concise stats.md file for simulation results.
    
    Args:
        results: Simulation results dictionary
        save_path: Path where to save the stats file
        title: Title for the stats file
    """
    order_time_min = float(results.get("order_time_s", 0.0)) / 60.0
    service_time_min = float(results.get("total_service_time_s", 0.0)) / 60.0
    delivery_distance_m = float(results.get("delivery_distance_m", 0.0))
    travel_time_min = float(results.get("delivery_travel_time_s", 0.0)) / 60.0
    prep_time_min = float(results.get("prep_time_s", 0.0)) / 60.0

    lines = [
        f"# {title}",
        "",
        f"Order placed: {order_time_min:.1f} min into round",
        f"Service time (order→delivery): {service_time_min:.1f} min",
        f"Prep time: {prep_time_min:.1f} min",
        f"Travel time (out+back): {travel_time_min:.1f} min",
        f"Delivery distance (out+back): {delivery_distance_m:.0f} m",
    ]

    # Optional efficiency metrics
    trip_to_golfer = results.get("trip_to_golfer", {})
    if isinstance(trip_to_golfer, dict):
        eff = trip_to_golfer.get("efficiency")
        if isinstance(eff, (int, float)):
            lines.append(f"Route efficiency (to golfer): {float(eff):.1f}%")

    # Show prediction method if available
    if results.get('prediction_method'):
        lines.append(f"Prediction method: {results['prediction_method']}")

    save_path.write_text("\n".join(lines), encoding="utf-8")


def write_multi_run_summary(all_runs: List[Dict], output_root: Path, title: str = "Multi-Run Summary") -> None:
    """
    Write a summary of multiple simulation runs.
    
    Args:
        all_runs: List of simulation result dictionaries
        output_root: Root directory for outputs
        title: Title for the summary
    """
    if not all_runs:
        output_root.joinpath("summary.md").write_text("No runs.", encoding="utf-8")
        return

    service_times = [float(r.get("total_service_time_s", 0.0)) / 60.0 for r in all_runs]
    distances = [float(r.get("delivery_distance_m", 0.0)) for r in all_runs]

    lines = [
        f"# {title}",
        "",
        f"Runs: {len(all_runs)}",
        f"Service time (min): min={min(service_times):.1f}, max={max(service_times):.1f}, mean={(sum(service_times)/len(service_times)):.1f}",
        f"Delivery distance (m): min={min(distances):.0f}, max={max(distances):.0f}, mean={(sum(distances)/len(distances)):.0f}",
        "",
        "## Runs",
        "",
    ]

    for idx, r in enumerate(all_runs, 1):
        order_min = float(r.get("order_time_s", 0.0)) / 60.0
        svc_min = float(r.get("total_service_time_s", 0.0)) / 60.0
        dist_m = float(r.get("delivery_distance_m", 0.0))
        lines.extend(
            [
                f"### sim_{idx:02d}",
                f"- Order time: {order_min:.1f} min",
                f"- Service time: {svc_min:.1f} min",
                f"- Distance: {dist_m:.0f} m",
                "",
            ]
        )

    output_root.joinpath("summary.md").write_text("\n".join(lines), encoding="utf-8")


def handle_simulation_error(error: Exception, run_idx: Optional[int] = None, exit_on_first: bool = True) -> bool:
    """
    Handle simulation errors consistently.
    
    Args:
        error: The exception that occurred
        run_idx: Optional run index for multi-run simulations
        exit_on_first: Whether to exit on first run failure
        
    Returns:
        True if should continue, False if should exit
    """
    prefix = f"Simulation {run_idx} " if run_idx is not None else "Simulation "
    
    if isinstance(error, FileNotFoundError):
        logger.error(f"{prefix}Data file not found: {error}")
        logger.error("Make sure the course directory exists and contains required data files")
    else:
        logger.error(f"{prefix}Error: {error}")
        import traceback
        traceback.print_exc()
    
    if exit_on_first and (run_idx is None or run_idx == 1):
        return False  # Exit
    return True  # Continue


def create_argparse_epilog(examples: List[str]) -> str:
    """
    Create a consistent epilog for argparse help text.
    
    Args:
        examples: List of example command strings
        
    Returns:
        Formatted epilog string
    """
    return "\nExamples:\n" + "\n".join(f"  {example}" for example in examples)
