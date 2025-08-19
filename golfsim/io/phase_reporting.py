"""
Phase simulation reporting and statistics generation.

This module provides utilities for generating reports, statistics, and
output files from phase simulation results.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List

from ..simulation.pass_detection import format_time_from_baseline
from ..io.results import write_unified_coordinates_csv
from ..analysis.bev_cart_metrics import (
    calculate_bev_cart_metrics,
    format_metrics_report as format_bev_metrics_report,
)


def write_phase3_stats_file(
    result: Dict,
    save_path: Path,
    tee_time_s: int,
    bev_cart_loop_min: int,
    pass_events: List[Dict],
    sim_runtime_s: float,
) -> None:
    """
    Write a Phase 3 stats.md file with simulation results.
    
    Args:
        result: Sales simulation result dictionary
        save_path: Path where to save the stats file
        tee_time_s: When golfer started their round
        bev_cart_loop_min: Beverage cart loop time in minutes
        pass_events: List of pass event dictionaries
        sim_runtime_s: How long the simulation took to run
    """
    # Revenue and orders
    sales: List[Dict] = result.get("sales", []) or []
    revenue = float(result.get("revenue", 0.0))
    placed_order = len(sales) > 0

    # Pass stats
    first_pass_ts = pass_events[0]["timestamp_s"] if pass_events else None
    wait_first_min = ((first_pass_ts - tee_time_s) / 60.0) if first_pass_ts is not None else None

    # Compose lines
    lines: List[str] = [
        "# Beverage Cart + Golfers — Single Run",
        "",
        f"Simulation run time: {sim_runtime_s:.2f} seconds",
        f"Golfer tee time: {format_time_from_baseline(int(tee_time_s))}",
        f"Beverage cart loop time (configured): {int(bev_cart_loop_min)} min per 18 holes",
        f"Total passes observed: {len(pass_events)}",
    ]

    if first_pass_ts is not None:
        lines.append(f"First pass at: {format_time_from_baseline(int(first_pass_ts))} (wait {wait_first_min:.1f} min)")
    else:
        lines.append("First pass: n/a")

    # Per-pass summary
    if pass_events:
        holes = [int(e.get("hole_num", 0)) for e in pass_events]
        times = [format_time_from_baseline(int(e.get("timestamp_s", 0))) for e in pass_events]
        lines.append(f"Pass holes: {holes}")
        lines.append(f"Pass times: {times}")
        lines.append("")
        lines.append("## Pass details")
        for idx, e in enumerate(pass_events, 1):
            ts = int(e.get("timestamp_s", 0))
            hole = int(e.get("hole_num", 0))
            dist = e.get("distance_m")
            tstr = format_time_from_baseline(ts)
            if dist is not None:
                lines.append(f"- Pass {idx}: hole {hole} at {tstr} (distance {dist} m)")
            else:
                lines.append(f"- Pass {idx}: hole {hole} at {tstr}")
    else:
        lines.append("Pass holes: []")
        lines.append("Pass times: []")

    # Order and revenue
    lines += [
        "",
        f"Sales count: {len(sales)}",
        f"Revenue: {revenue:.2f}",
        f"Order placed by golfer: {'yes' if placed_order else 'no'}",
    ]

    # If any sales, include details for each sale
    if placed_order:
        lines.append("## Sales details")
        for s in sales:
            ts = int(s.get("timestamp_s", 0))
            hole = s.get("hole_num")
            lines.append(f"- hole {hole} at {format_time_from_baseline(ts)}")

    save_path.write_text("\n".join(lines), encoding="utf-8")


def save_phase3_output_files(
    simulation_result: Dict,
    output_dir: Path,
    include_coordinates: bool = True,
    include_visualizations: bool = True,
    include_stats: bool = True,
) -> None:
    """
    Save all output files for a Phase 3 simulation.
    
    Args:
        simulation_result: Result from run_phase3_beverage_cart_simulation
        output_dir: Directory to save files in
        include_coordinates: Whether to save coordinates CSV
        include_visualizations: Whether to generate visualization files
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    sales_result = simulation_result["sales_result"]
    golfer_points = simulation_result["golfer_points"]
    bev_points = simulation_result["bev_points"]
    pass_events = simulation_result["pass_events"]
    tee_time_s = simulation_result["tee_time_s"]
    run_idx = simulation_result["run_idx"]
    
    # Save sales data
    (output_dir / "sales.json").write_text(
        json.dumps(sales_result.get("sales", []), indent=2), 
        encoding="utf-8"
    )
    
    # Save full result: avoid clobbering if an upstream writer already produced a richer result.json
    result_path = output_dir / "result.json"
    if not result_path.exists():
        result_payload = {
            "type": simulation_result.get("simulation_type", "phase3"),
            "run_idx": int(simulation_result.get("run_idx", 1)),
            "sales_result": sales_result,
        }
        result_path.write_text(
            json.dumps(result_payload, indent=2),
            encoding="utf-8"
        )
    
    # Save coordinates if requested
    if include_coordinates:
        from ..io.results import write_coordinates_csv_with_visibility_and_totals
        cart_id = f"bev_cart_{run_idx}" if "sync" not in str(run_idx) else f"bev_cart_sync_{run_idx}"

        # Build tracks mapping; split golfers per group if group_id present
        tracks: Dict[str, List[Dict]] = {}
        if golfer_points:
            if any("group_id" in p for p in golfer_points):
                grouped: Dict[int, List[Dict]] = {}
                for p in golfer_points:
                    gid = int(p.get("group_id", 1))
                    grouped.setdefault(gid, []).append(p)
                for gid, pts in grouped.items():
                    tracks[f"golfer_group_{gid}"] = pts
            else:
                tracks["golfer_1"] = golfer_points
        if bev_points:
            tracks[cart_id] = bev_points

        # Normalize all streams so the first tee time is timestamp 0
        def _normalize_streams_to_baseline(points_by_id: Dict[str, List[Dict]], baseline_s: int) -> Dict[str, List[Dict]]:
            normalized: Dict[str, List[Dict]] = {}
            try:
                b = int(baseline_s)
            except Exception:
                b = 0
            for sid, pts in (points_by_id or {}).items():
                out: List[Dict] = []
                for p in pts or []:
                    try:
                        ts_raw = p.get("timestamp", p.get("timestamp_s", 0))
                        ts = int(float(ts_raw or 0))
                    except Exception:
                        ts = 0
                    if ts < b:
                        continue
                    q = dict(p)
                    q["timestamp"] = int(ts - b)
                    out.append(q)
                normalized[sid] = out
            return normalized

        baseline_s = int(tee_time_s) if isinstance(tee_time_s, (int, float)) else 0
        tracks_norm = _normalize_streams_to_baseline(tracks, baseline_s)

        write_coordinates_csv_with_visibility_and_totals(
            tracks_norm,
            output_dir / "coordinates.csv",
            sales_data=sales_result.get("sales", []),
            enable_visibility_tracking=True,
            enable_running_totals=True,
        )
    
    # Generate visualizations if requested
    if include_visualizations:
        _generate_phase3_visualizations(simulation_result, output_dir)
    
    # Generate stats file (optional)
    if include_stats:
        bev_cart_loop_min = 180  # Default
        if simulation_result["type"] == "standard" and "beverage_cart_service" in simulation_result:
            svc = simulation_result["beverage_cart_service"]
            bev_cart_loop_min = getattr(svc, "bev_cart_18_holes_minutes", 180)
        elif simulation_result["type"] == "synchronized":
            sync_timing = simulation_result.get("sync_timing", {})
            bev_cart_loop_min = sync_timing.get("bev_cart_hole_total_s", 600) // 60
        
        write_phase3_stats_file(
            sales_result,
            output_dir / "stats.md",
            tee_time_s,
            bev_cart_loop_min,
            pass_events,
            simulation_result.get("simulation_runtime_s", 0.0),
        )

    # Always generate beverage cart metrics report if bev cart coordinates are present
    try:
        bev_points = simulation_result.get("bev_points", []) or []
        if bev_points:
            sales = sales_result.get("sales", []) or []
            golfer_points = simulation_result.get("golfer_points", []) or []
            svc = simulation_result.get("beverage_cart_service")
            service_start_s = int(getattr(svc, "service_start_s", (9 - 7) * 3600) if svc else (9 - 7) * 3600)
            service_end_s = int(getattr(svc, "service_end_s", (17 - 7) * 3600) if svc else (17 - 7) * 3600)
            run_idx = int(simulation_result.get("run_idx", 1))
            cart_id = getattr(svc, "cart_id", "bev_cart_1") if svc else "bev_cart_1"

            metrics = calculate_bev_cart_metrics(
                sales_data=sales,
                coordinates=bev_points,
                golfer_data=golfer_points,
                service_start_s=service_start_s,
                service_end_s=service_end_s,
                simulation_id=f"phase3_run_{run_idx:02d}",
                cart_id=cart_id,
            )
            (output_dir / "metrics_report.md").write_text(
                format_bev_metrics_report(metrics), encoding="utf-8"
            )
    except Exception:
        # Non-fatal; proceed without metrics if any input is missing
        pass


def _generate_phase3_visualizations(simulation_result: Dict, output_dir: Path) -> None:
    """Generate visualization files for Phase 3 simulation."""
    # Import here to avoid circular dependencies
    from ..viz.matplotlib_viz import render_beverage_cart_plot
    
    bev_points = simulation_result["bev_points"] 
    run_idx = simulation_result["run_idx"]
    
    # Determine title based on simulation type
    if simulation_result["type"] == "synchronized":
        sync_calc = simulation_result.get("sync_calc", {})
        offset_min = sync_calc.get("sync_offset_s", 0) / 60
        title = f"Synchronized Beverage Cart Route (Phase 3) - Offset {offset_min:.1f}min"
    else:
        title = "Beverage Cart Route (Phase 3)"
    
    # Route PNG intentionally omitted per requirements


def write_phase3_summary(results: List[Dict], output_root: Path) -> None:
    """
    Write a summary.md file for multiple Phase 3 simulation runs.
    
    Args:
        results: List of simulation result dictionaries
        output_root: Root directory for output files
    """
    if not results:
        return
        
    revenues = [float(r.get("revenue", 0.0)) for r in results]
    sales_counts = [int(r.get("num_sales", 0)) for r in results]
    total_revenue = sum(revenues)
    total_sales = sum(sales_counts)
    
    lines: List[str] = [
        "# Beverage Cart + Golfers Summary",
        "",
        f"Runs: {len(results)}",
        f"Revenue per run: min={min(revenues):.2f}, max={max(revenues):.2f}, mean={(sum(revenues)/len(revenues)):.2f}",
        f"Sales per run: min={min(sales_counts)}, max={max(sales_counts)}, mean={(sum(sales_counts)/len(sales_counts)):.1f}",
        f"Total revenue (all runs): ${total_revenue:.2f}",
        f"Total sales (all runs): {total_sales}",
        "",
        "## Run Details",
    ]
    
    for r in results:
        ridx = r.get("run_idx", 0)
        tee_time_s = r.get("tee_time_s", 0)
        revenue = r.get("revenue", 0.0)
        num_sales = r.get("num_sales", 0)
        
        # Format tee time
        tee_time_str = format_time_from_baseline(int(tee_time_s))
        
        lines.append(f"### Run {ridx:02d}")
        lines.append(f"- **Golfer Tee Time**: {tee_time_str}")
        
        # Get crossings information if available
        crossings_data = r.get("crossings")
        if crossings_data and crossings_data.get("groups"):
            first_group = crossings_data["groups"][0]
            bev_start = crossings_data.get("bev_start", "Unknown")
            if isinstance(bev_start, str) and "T" in bev_start:
                bev_start_time = bev_start.split("T")[1][:5]  # Extract HH:MM
            else:
                bev_start_time = "Unknown"
            
            lines.append(f"- **Bev Cart Service Start**: {bev_start_time}")
            
            crossings = first_group.get("crossings", [])
            if crossings:
                lines.append(f"- **Crossings Found**: {len(crossings)}")
                for i, crossing in enumerate(crossings, 1):
                    timestamp = crossing.get("timestamp", "Unknown")
                    if isinstance(timestamp, str) and "T" in timestamp:
                        crossing_time = timestamp.split("T")[1][:8]  # Extract HH:MM:SS
                    else:
                        crossing_time = "Unknown"
                    node_idx = crossing.get("node_index", "Unknown")
                    hole = crossing.get("hole", "Unknown")
                    lines.append(f"  - **Crossing {i}**: {crossing_time} at node {node_idx} (Hole {hole})")
            else:
                lines.append("- **Crossings Found**: 0")
        else:
            lines.append("- **Bev Cart Service Start**: 09:00 (default)")
            lines.append("- **Crossings Found**: Not computed")
        
        # Purchase information
        if num_sales > 0:
            lines.append(f"- **Purchases**: Yes, {num_sales} sale(s) totaling ${revenue:.2f}")
        else:
            lines.append("- **Purchases**: No")
        
        lines.append("")
        
    lines.append("## Artifacts")
    for r in results:
        ridx = r.get("run_idx", 0)
        lines.append(f"- Run {ridx:02d}: sales.json + result.json + coordinates.csv")
        
    lines.append("")
    (output_root / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def save_phase5_output_files(result: Dict, run_dir: Path) -> None:
    """
    Save all output files for a Phase 5 simulation run.
    
    Args:
        result: Simulation result dictionary
        run_dir: Directory to save outputs to
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # Save coordinates CSV (combined golfer and beverage cart)
    golfer_points = result.get("golfer_points", [])
    bev_points = result.get("bev_points", [])
    
    all_coordinates = []
    
    # Add golfer coordinates with entity_id
    for point in golfer_points:
        coord = point.copy()
        group_id = coord.get("group_id", 1)
        coord["entity_id"] = f"golfer_{group_id}"
        all_coordinates.append(coord)
    
    # Add beverage cart coordinates with entity_id
    for point in bev_points:
        coord = point.copy()
        coord["entity_id"] = "bev_cart_1"
        all_coordinates.append(coord)
    
    # Sort by timestamp for logical ordering
    all_coordinates.sort(key=lambda x: x.get("timestamp_s", 0))
    
    # Write coordinates CSV
    if all_coordinates:
        # Group coordinates by entity_id for the unified CSV writer
        points_by_id = {}
        for coord in all_coordinates:
            entity_id = coord.get("entity_id", "unknown")
            if entity_id not in points_by_id:
                points_by_id[entity_id] = []
            points_by_id[entity_id].append(coord)
        
        write_unified_coordinates_csv(points_by_id, run_dir / "coordinates.csv")
    
    # Route PNG intentionally omitted per requirements
    
    # Save sales results
    sales_result = result.get("sales_result", {})
    with open(run_dir / "sales.json", "w", encoding="utf-8") as f:
        json.dump(sales_result, f, indent=2, default=str)
    
    # Save complete result
    result_copy = result.copy()
    # Remove large arrays to keep file manageable, keep only metadata
    result_copy.pop("golfer_points", None)
    result_copy.pop("bev_points", None)
    
    with open(run_dir / "result.json", "w", encoding="utf-8") as f:
        json.dump(result_copy, f, indent=2, default=str)
    
    # Generate stats markdown
    write_phase5_stats_file(
        result=result,
        save_path=run_dir / "stats.md",
        scenario_name=result.get("scenario_name", "unknown"),
        groups=result.get("groups", []),
        sales_result=sales_result,
        pass_events=result.get("pass_events", []),
        sim_runtime_s=result.get("simulation_runtime_s", 0.0),
    )


def write_phase5_stats_file(
    result: Dict,
    save_path: Path,
    scenario_name: str,
    groups: List[Dict],
    sales_result: Dict,
    pass_events: List[Dict],
    sim_runtime_s: float,
) -> None:
    """
    Write a Phase 5 stats.md file with simulation results.
    
    Args:
        result: Full simulation result dictionary
        save_path: Path where to save the stats file
        scenario_name: Name of the tee times scenario used
        groups: List of golfer groups
        sales_result: Sales simulation results
        pass_events: List of pass event dictionaries
        sim_runtime_s: How long the simulation took to run
    """
    # Basic metrics
    revenue = float(sales_result.get("revenue", 0.0))
    sales = sales_result.get("sales", []) or []
    num_sales = len(sales)
    total_groups = len(groups)
    
    # Group distribution
    group_by_hour = {}
    for group in groups:
        hour = group.get("hour", "unknown")
        if hour not in group_by_hour:
            group_by_hour[hour] = {"groups": 0, "golfers": 0}
        group_by_hour[hour]["groups"] += 1
        group_by_hour[hour]["golfers"] += group.get("num_golfers", 4)
    
    # Timing information
    if groups:
        first_tee_time_s = min(g.get("tee_time_s", 0) for g in groups)
        last_tee_time_s = max(g.get("tee_time_s", 0) for g in groups)
        total_span_hours = (last_tee_time_s - first_tee_time_s) / 3600.0
    else:
        first_tee_time_s = last_tee_time_s = 0
        total_span_hours = 0
    
    # Pass statistics
    total_passes = len(pass_events)
    pass_by_group = {}
    for event in pass_events:
        group_id = event.get("group_id", 0)
        if group_id not in pass_by_group:
            pass_by_group[group_id] = 0
        pass_by_group[group_id] += 1
    
    lines = [
        f"# Phase 5 — Beverage cart + many groups ({scenario_name})",
        "",
        f"**Simulation runtime**: {sim_runtime_s:.2f} seconds",
        f"**Scenario**: {scenario_name}",
        f"**Total groups**: {total_groups}",
        f"**Total golfers**: {sum(g.get('num_golfers', 4) for g in groups)}",
        f"**Tee time span**: {format_time_from_baseline(int(first_tee_time_s))} to {format_time_from_baseline(int(last_tee_time_s))} ({total_span_hours:.1f}h)",
        "",
        "## Group Distribution by Hour",
        "",
    ]
    
    for hour in sorted(group_by_hour.keys()):
        data = group_by_hour[hour]
        lines.append(f"- **{hour}**: {data['groups']} groups, {data['golfers']} golfers")
    
    lines.extend([
        "",
        "## Sales Performance",
        "",
        f"- **Revenue**: ${revenue:.2f}",
        f"- **Sales count**: {num_sales}",
        f"- **Average per sale**: ${revenue / num_sales:.2f}" if num_sales > 0 else "- **Average per sale**: $0.00",
        "",
        "## Pass Events",
        "",
        f"- **Total passes**: {total_passes}",
        f"- **Groups with passes**: {len(pass_by_group)} of {total_groups}",
    ])
    
    if pass_by_group:
        lines.append("- **Passes per group**:")
        for group_id in sorted(pass_by_group.keys()):
            count = pass_by_group[group_id]
            lines.append(f"  - Group {group_id}: {count} passes")
    
    # Add crossings information if available
    crossings_data = result.get("crossings", {})
    if crossings_data and crossings_data.get("groups"):
        lines.extend([
            "",
            "## Crossings Analysis",
            "",
        ])
        
        total_crossings = sum(len(g.get("crossings", [])) for g in crossings_data["groups"])
        lines.append(f"- **Total crossings**: {total_crossings}")
        
        for i, group_data in enumerate(crossings_data["groups"], 1):
            crossings = group_data.get("crossings", [])
            if crossings:
                lines.append(f"- **Group {i}**: {len(crossings)} crossings")
    
    lines.extend([
        "",
        "## Configuration",
        "",
        f"- **Beverage cart service**: 09:00–17:00",
        f"- **Order probability**: {sales_result.get('pass_order_probability', 'unknown')}",
        f"- **Average order value**: ${sales_result.get('price_per_order', 'unknown')}",
        "",
        "## Artifacts",
        "",
        "- `coordinates.csv` — Combined GPS tracks (golfers + beverage cart)",
        "- `sales.json` — Detailed sales and pass data",
        "- `result.json` — Complete simulation metadata",
        "",
    ])
    
    save_path.write_text("\n".join(lines), encoding="utf-8")


def write_phase5_summary(results: List[Dict], output_root: Path, scenario_name: str) -> None:
    """
    Write a Phase 5 summary.md file across multiple simulation runs.
    
    Args:
        results: List of simulation result summaries
        output_root: Root output directory
        scenario_name: Name of the scenario used
    """
    num_runs = len(results)
    
    if not results:
        lines = [
            f"# Phase 5 Summary — {scenario_name}",
            "",
            "No simulation results to summarize.",
            "",
        ]
        (output_root / "summary.md").write_text("\n".join(lines), encoding="utf-8")
        return
    
    # Aggregate statistics
    revenues = [r.get("revenue", 0.0) for r in results]
    sales_counts = [r.get("num_sales", 0) for r in results]
    pass_counts = [r.get("num_pass_intervals", 0) for r in results]
    group_counts = [r.get("groups", 0) for r in results]
    
    mean_revenue = sum(revenues) / len(revenues) if revenues else 0
    mean_sales = sum(sales_counts) / len(sales_counts) if sales_counts else 0
    mean_passes = sum(pass_counts) / len(pass_counts) if pass_counts else 0
    mean_groups = sum(group_counts) / len(group_counts) if group_counts else 0
    
    lines = [
        f"# Phase 5 Summary — {scenario_name}",
        "",
        f"**Simulation runs**: {num_runs}",
        f"**Scenario**: {scenario_name}",
        f"**Generated at**: {format_time_from_baseline(0)}",  # Will show current time
        "",
        "## Aggregate Performance",
        "",
        f"- **Mean revenue**: ${mean_revenue:.2f} (range: ${min(revenues):.2f}–${max(revenues):.2f})",
        f"- **Mean sales**: {mean_sales:.1f} (range: {min(sales_counts)}–{max(sales_counts)})",
        f"- **Mean groups**: {mean_groups:.1f}",
        f"- **Mean passes**: {mean_passes:.1f} (range: {min(pass_counts)}–{max(pass_counts)})",
        "",
        "## Per-Run Results",
        "",
    ]
    
    for r in results:
        run_idx = r.get("run_idx", 0)
        revenue = r.get("revenue", 0.0)
        sales = r.get("num_sales", 0)
        groups = r.get("groups", 0)
        passes = r.get("num_pass_intervals", 0)
        first_tee = r.get("first_tee_time_s", 0)
        last_tee = r.get("last_tee_time_s", 0)
        
        lines.append(f"### Run {run_idx:02d}")
        lines.append(f"- **Revenue**: ${revenue:.2f}")
        lines.append(f"- **Sales**: {sales}")
        lines.append(f"- **Groups**: {groups}")
        lines.append(f"- **Passes**: {passes}")
        lines.append(f"- **Tee times**: {format_time_from_baseline(int(first_tee))} to {format_time_from_baseline(int(last_tee))}")
        
        # Show first crossing if available
        first_crossing = r.get("first_crossing")
        if first_crossing:
            crossing_time = first_crossing.get("timestamp", "")
            if isinstance(crossing_time, str) and "T" in crossing_time:
                crossing_time = crossing_time.split("T")[1][:8]
            node = first_crossing.get("node_index", "unknown")
            hole = first_crossing.get("hole", "unknown")
            lines.append(f"- **First crossing**: {crossing_time} at node {node} (hole {hole})")
        
        lines.append("")
    
    lines.extend([
        "## Scenario Details",
        "",
        f"This Phase 5 simulation used the '{scenario_name}' scenario from tee_times_config.json.",
        "Each run generated golfer groups based on the hourly_golfers distribution,",
        "with random tee times within each specified hour.",
        "",
        "## Files Generated",
        "",
    ])
    
    for r in results:
        run_idx = r.get("run_idx", 0)
        lines.append(f"- **sim_{run_idx:02d}/**: coordinates.csv, sales.json, result.json, stats.md")
    
    lines.append("")
    (output_root / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def write_phase4_stats_file(
    result: Dict,
    save_path: Path,
    groups: List[Dict],
    bev_cart_loop_min: int,
    pass_events: List[Dict],
    sim_runtime_s: float,
) -> None:
    """
    Write a Phase 4 stats.md file with simulation results.
    
    Args:
        result: Sales simulation result dictionary
        save_path: Path where to save the stats file
        groups: List of golfer groups with their tee times
        bev_cart_loop_min: Beverage cart loop time in minutes
        pass_events: List of pass event dictionaries
        sim_runtime_s: How long the simulation took to run
    """
    # Revenue and orders
    sales: List[Dict] = result.get("sales", []) or []
    revenue = float(result.get("revenue", 0.0))
    placed_order = len(sales) > 0
    
    # Group tee times
    first_tee_time_s = groups[0]["tee_time_s"]
    last_tee_time_s = groups[-1]["tee_time_s"]

    # Pass stats
    first_pass_ts = pass_events[0]["timestamp_s"] if pass_events else None
    wait_first_min = ((first_pass_ts - first_tee_time_s) / 60.0) if first_pass_ts is not None else None

    # Compose lines
    lines: List[str] = [
        "# Phase 4 — Beverage cart + 4 groups (15-min intervals)",
        "",
        f"Simulation run time: {sim_runtime_s:.2f} seconds",
        f"Group 1 tee time: {format_time_from_baseline(int(first_tee_time_s))}",
        f"Group 4 tee time: {format_time_from_baseline(int(last_tee_time_s))}",
        f"Beverage cart loop time (configured): {int(bev_cart_loop_min)} min per 18 holes",
        f"Total passes observed: {len(pass_events)}",
    ]

    if first_pass_ts is not None:
        lines.append(f"First pass at: {format_time_from_baseline(int(first_pass_ts))} (wait {wait_first_min:.1f} min)")
    else:
        lines.append("First pass: n/a")

    # Group details
    lines.append("")
    lines.append("## Group Details")
    for i, group in enumerate(groups, 1):
        tee_time_str = format_time_from_baseline(int(group["tee_time_s"]))
        lines.append(f"- Group {i}: tee time {tee_time_str}")

    # Per-pass summary
    if pass_events:
        # Group passes by group_id
        passes_by_group = {}
        for e in pass_events:
            group_id = e.get("group_id", 1)
            if group_id not in passes_by_group:
                passes_by_group[group_id] = []
            passes_by_group[group_id].append(e)
        
        lines.append("")
        lines.append("## Pass Summary by Group")
        for group_id in sorted(passes_by_group.keys()):
            group_passes = passes_by_group[group_id]
            holes = [int(e.get("hole_num", 0)) for e in group_passes]
            times = [format_time_from_baseline(int(e.get("timestamp_s", 0))) for e in group_passes]
            lines.append(f"Group {group_id}: {len(group_passes)} passes at holes {holes}")
            lines.append(f"           Times: {times}")
        
        lines.append("")
        lines.append("## All Pass Details")
        for idx, e in enumerate(pass_events, 1):
            ts = int(e.get("timestamp_s", 0))
            hole = int(e.get("hole_num", 0))
            group_id = e.get("group_id", "?")
            dist = e.get("distance_m")
            tstr = format_time_from_baseline(ts)
            if dist is not None:
                lines.append(f"- Pass {idx}: Group {group_id}, hole {hole} at {tstr} (distance {dist} m)")
            else:
                lines.append(f"- Pass {idx}: Group {group_id}, hole {hole} at {tstr}")
    else:
        lines.append("Pass holes: []")
        lines.append("Pass times: []")

    # Order and revenue
    lines += [
        "",
        f"Sales count: {len(sales)}",
        f"Revenue: {revenue:.2f}",
        f"Orders placed by golfers: {'yes' if placed_order else 'no'}",
    ]

    # If any sales, include details for each sale
    if placed_order:
        lines.append("## Sales details")
        for s in sales:
            ts = int(s.get("timestamp_s", 0))
            hole = s.get("hole_num")
            group_id = s.get("group_id", "?")
            lines.append(f"- Group {group_id}: hole {hole} at {format_time_from_baseline(ts)}")

    save_path.write_text("\n".join(lines), encoding="utf-8")


def save_phase4_output_files(
    simulation_result: Dict,
    output_dir: Path,
    include_coordinates: bool = True,
    include_visualizations: bool = True,
    include_stats: bool = True,
) -> None:
    """
    Save all output files for a Phase 4 simulation.
    
    Args:
        simulation_result: Result from run_phase4_beverage_cart_simulation
        output_dir: Directory to save files in
        include_coordinates: Whether to save coordinates CSV
        include_visualizations: Whether to generate visualization files
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    sales_result = simulation_result["sales_result"]
    golfer_points = simulation_result["golfer_points"]
    bev_points = simulation_result["bev_points"]
    pass_events = simulation_result["pass_events"]
    groups = simulation_result["groups"]
    run_idx = simulation_result["run_idx"]
    
    # Save sales data
    (output_dir / "sales.json").write_text(
        json.dumps(sales_result.get("sales", []), indent=2), 
        encoding="utf-8"
    )
    
    # Save full result
    (output_dir / "result.json").write_text(
        json.dumps(sales_result, indent=2), 
        encoding="utf-8"
    )
    
    # Save coordinates if requested
    if include_coordinates:
        from ..io.results import write_coordinates_csv_with_visibility_and_totals
        cart_id = f"bev_cart_{run_idx}" if "sync" not in str(run_idx) else f"bev_cart_sync_{run_idx}"
        
        # Group golfer points by group_id for separate columns
        golfer_points_by_group = {}
        for point in golfer_points:
            group_id = point.get("group_id", 1)
            key = f"golfer_group_{group_id}"
            if key not in golfer_points_by_group:
                golfer_points_by_group[key] = []
            golfer_points_by_group[key].append(point)
        
        # Combine all tracks
        all_tracks = {cart_id: bev_points}
        all_tracks.update(golfer_points_by_group)
        
        write_coordinates_csv_with_visibility_and_totals(
            all_tracks, 
            output_dir / "coordinates.csv",
            sales_data=sales_result.get("sales", []),
            enable_visibility_tracking=True,
            enable_running_totals=True
        )
    
    # Generate visualizations if requested
    if include_visualizations:
        _generate_phase4_visualizations(simulation_result, output_dir)
    
    # Generate stats file (optional)
    if include_stats:
        bev_cart_loop_min = 180  # Default
        if simulation_result["type"] == "standard" and "beverage_cart_service" in simulation_result:
            svc = simulation_result["beverage_cart_service"]
            bev_cart_loop_min = getattr(svc, "bev_cart_18_holes_minutes", 180)
        elif simulation_result["type"] == "synchronized":
            sync_timing = simulation_result.get("sync_timing", {})
            bev_cart_loop_min = sync_timing.get("bev_cart_hole_total_s", 600) // 60
        
        write_phase4_stats_file(
            sales_result,
            output_dir / "stats.md",
            groups,
            bev_cart_loop_min,
            pass_events,
            simulation_result.get("simulation_runtime_s", 0.0),
        )

    # Always generate beverage cart metrics report if bev cart coordinates are present
    try:
        bev_points = simulation_result.get("bev_points", []) or []
        if bev_points:
            sales = sales_result.get("sales", []) or []
            golfer_points = simulation_result.get("golfer_points", []) or []
            svc = simulation_result.get("beverage_cart_service")
            service_start_s = int(getattr(svc, "service_start_s", (9 - 7) * 3600) if svc else (9 - 7) * 3600)
            service_end_s = int(getattr(svc, "service_end_s", (17 - 7) * 3600) if svc else (17 - 7) * 3600)
            run_idx = int(simulation_result.get("run_idx", 1))
            cart_id = getattr(svc, "cart_id", "bev_cart_1") if svc else "bev_cart_1"

            metrics = calculate_bev_cart_metrics(
                sales_data=sales,
                coordinates=bev_points,
                golfer_data=golfer_points,
                service_start_s=service_start_s,
                service_end_s=service_end_s,
                simulation_id=f"phase4_run_{run_idx:02d}",
                cart_id=cart_id,
            )
            (output_dir / "metrics_report.md").write_text(
                format_bev_metrics_report(metrics), encoding="utf-8"
            )
    except Exception:
        # Non-fatal; proceed without metrics if any input is missing
        pass


def _generate_phase4_visualizations(simulation_result: Dict, output_dir: Path) -> None:
    """Generate visualization files for Phase 4 simulation."""
    # Import here to avoid circular dependencies
    from ..viz.matplotlib_viz import render_beverage_cart_plot
    
    bev_points = simulation_result["bev_points"] 
    run_idx = simulation_result["run_idx"]
    
    # Determine title based on simulation type
    if simulation_result["type"] == "synchronized":
        sync_calc = simulation_result.get("sync_calc", {})
        offset_min = sync_calc.get("sync_offset_s", 0) / 60
        title = f"Synchronized Beverage Cart Route (Phase 4) - Offset {offset_min:.1f}min"
    else:
        title = "Beverage Cart Route (Phase 4)"
    
    # Render beverage cart route
    render_beverage_cart_plot(
        bev_points,
        course_dir="courses/pinetree_country_club",  # TODO: Make this configurable
        save_path=output_dir / "bev_cart_route.png",
        title=title
    )


def write_phase4_summary(results: List[Dict], output_root: Path) -> None:
    """
    Write a summary.md file for multiple Phase 4 simulation runs.
    
    Args:
        results: List of simulation result dictionaries
        output_root: Root directory for output files
    """
    if not results:
        return
        
    revenues = [float(r.get("revenue", 0.0)) for r in results]
    sales_counts = [int(r.get("num_sales", 0)) for r in results]
    total_revenue = sum(revenues)
    total_sales = sum(sales_counts)
    
    lines: List[str] = [
        "# Phase 4 — Bev cart + 4 groups (15-min intervals, 5-run summary)",
        "",
        f"Runs: {len(results)}",
        f"Revenue per run: min={min(revenues):.2f}, max={max(revenues):.2f}, mean={(sum(revenues)/len(revenues)):.2f}",
        f"Sales per run: min={min(sales_counts)}, max={max(sales_counts)}, mean={(sum(sales_counts)/len(sales_counts)):.1f}",
        f"Total revenue (all runs): ${total_revenue:.2f}",
        f"Total sales (all runs): {total_sales}",
        "",
        "## Run Details",
    ]
    
    for r in results:
        ridx = r.get("run_idx", 0)
        first_tee_time_s = r.get("first_tee_time_s", 0)
        last_tee_time_s = r.get("last_tee_time_s", 0)
        revenue = r.get("revenue", 0.0)
        num_sales = r.get("num_sales", 0)
        
        # Format tee times
        first_tee_time_str = format_time_from_baseline(int(first_tee_time_s))
        last_tee_time_str = format_time_from_baseline(int(last_tee_time_s))
        
        lines.append(f"### Run {ridx:02d}")
        lines.append(f"- **First Group Tee Time**: {first_tee_time_str}")
        lines.append(f"- **Last Group Tee Time**: {last_tee_time_str}")
        
        # Get crossings information if available
        crossings_data = r.get("crossings")
        if crossings_data and crossings_data.get("groups"):
            bev_start = crossings_data.get("bev_start", "Unknown")
            if isinstance(bev_start, str) and "T" in bev_start:
                bev_start_time = bev_start.split("T")[1][:5]  # Extract HH:MM
            else:
                bev_start_time = "Unknown"
            
            lines.append(f"- **Bev Cart Service Start**: {bev_start_time}")
            
            total_crossings = sum(len(g.get("crossings", [])) for g in crossings_data["groups"])
            lines.append(f"- **Total Crossings Found**: {total_crossings}")
            
            for i, group_data in enumerate(crossings_data["groups"], 1):
                crossings = group_data.get("crossings", [])
                lines.append(f"  - **Group {i}**: {len(crossings)} crossings")
                for j, crossing in enumerate(crossings, 1):
                    timestamp = crossing.get("timestamp", "Unknown")
                    if isinstance(timestamp, str) and "T" in timestamp:
                        crossing_time = timestamp.split("T")[1][:8]  # Extract HH:MM:SS
                    else:
                        crossing_time = "Unknown"
                    node_idx = crossing.get("node_index", "Unknown")
                    hole = crossing.get("hole", "Unknown")
                    lines.append(f"    - **Crossing {j}**: {crossing_time} at node {node_idx} (Hole {hole})")
        else:
            lines.append("- **Bev Cart Service Start**: 09:00 (default)")
            lines.append("- **Crossings Found**: Not computed")
        
        # Purchase information
        if num_sales > 0:
            lines.append(f"- **Purchases**: Yes, {num_sales} sale(s) totaling ${revenue:.2f}")
        else:
            lines.append("- **Purchases**: No")
        
        lines.append("")
        
    lines.append("## Artifacts")
    for r in results:
        ridx = r.get("run_idx", 0)
        lines.append(f"- Run {ridx:02d}: bev_cart_route.png + sales.json + result.json + coordinates.csv")
        
    lines.append("")
    (output_root / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def save_phase5_output_files(result: Dict, run_dir: Path) -> None:
    """
    Save all output files for a Phase 5 simulation run.
    
    Args:
        result: Simulation result dictionary
        run_dir: Directory to save outputs to
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # Save coordinates CSV (combined golfer and beverage cart)
    golfer_points = result.get("golfer_points", [])
    bev_points = result.get("bev_points", [])
    
    all_coordinates = []
    
    # Add golfer coordinates with entity_id
    for point in golfer_points:
        coord = point.copy()
        group_id = coord.get("group_id", 1)
        coord["entity_id"] = f"golfer_{group_id}"
        all_coordinates.append(coord)
    
    # Add beverage cart coordinates with entity_id
    for point in bev_points:
        coord = point.copy()
        coord["entity_id"] = "bev_cart_1"
        all_coordinates.append(coord)
    
    # Sort by timestamp for logical ordering
    all_coordinates.sort(key=lambda x: x.get("timestamp_s", 0))
    
    # Write coordinates CSV
    if all_coordinates:
        # Group coordinates by entity_id for the unified CSV writer
        points_by_id = {}
        for coord in all_coordinates:
            entity_id = coord.get("entity_id", "unknown")
            if entity_id not in points_by_id:
                points_by_id[entity_id] = []
            points_by_id[entity_id].append(coord)
        
        write_unified_coordinates_csv(points_by_id, run_dir / "coordinates.csv")
    
    # Save beverage cart route visualization (if bev_points exist)
    if bev_points:
        try:
            from ..visualization.plotting import plot_beverage_cart_route
            plot_beverage_cart_route(bev_points, run_dir / "bev_cart_route.png")
        except ImportError:
            pass  # Visualization optional
    
    # Save sales results
    sales_result = result.get("sales_result", {})
    with open(run_dir / "sales.json", "w", encoding="utf-8") as f:
        json.dump(sales_result, f, indent=2, default=str)
    
    # Save complete result
    result_copy = result.copy()
    # Remove large arrays to keep file manageable, keep only metadata
    result_copy.pop("golfer_points", None)
    result_copy.pop("bev_points", None)
    
    with open(run_dir / "result.json", "w", encoding="utf-8") as f:
        json.dump(result_copy, f, indent=2, default=str)
    
    # Generate stats markdown
    write_phase5_stats_file(
        result=result,
        save_path=run_dir / "stats.md",
        scenario_name=result.get("scenario_name", "unknown"),
        groups=result.get("groups", []),
        sales_result=sales_result,
        pass_events=result.get("pass_events", []),
        sim_runtime_s=result.get("simulation_runtime_s", 0.0),
    )


def write_phase5_stats_file(
    result: Dict,
    save_path: Path,
    scenario_name: str,
    groups: List[Dict],
    sales_result: Dict,
    pass_events: List[Dict],
    sim_runtime_s: float,
) -> None:
    """
    Write a Phase 5 stats.md file with simulation results.
    
    Args:
        result: Full simulation result dictionary
        save_path: Path where to save the stats file
        scenario_name: Name of the tee times scenario used
        groups: List of golfer groups
        sales_result: Sales simulation results
        pass_events: List of pass event dictionaries
        sim_runtime_s: How long the simulation took to run
    """
    # Basic metrics
    revenue = float(sales_result.get("revenue", 0.0))
    sales = sales_result.get("sales", []) or []
    num_sales = len(sales)
    total_groups = len(groups)
    
    # Group distribution
    group_by_hour = {}
    for group in groups:
        hour = group.get("hour", "unknown")
        if hour not in group_by_hour:
            group_by_hour[hour] = {"groups": 0, "golfers": 0}
        group_by_hour[hour]["groups"] += 1
        group_by_hour[hour]["golfers"] += group.get("num_golfers", 4)
    
    # Timing information
    if groups:
        first_tee_time_s = min(g.get("tee_time_s", 0) for g in groups)
        last_tee_time_s = max(g.get("tee_time_s", 0) for g in groups)
        total_span_hours = (last_tee_time_s - first_tee_time_s) / 3600.0
    else:
        first_tee_time_s = last_tee_time_s = 0
        total_span_hours = 0
    
    # Pass statistics
    total_passes = len(pass_events)
    pass_by_group = {}
    for event in pass_events:
        group_id = event.get("group_id", 0)
        if group_id not in pass_by_group:
            pass_by_group[group_id] = 0
        pass_by_group[group_id] += 1
    
    lines = [
        f"# Phase 5 — Beverage cart + many groups ({scenario_name})",
        "",
        f"**Simulation runtime**: {sim_runtime_s:.2f} seconds",
        f"**Scenario**: {scenario_name}",
        f"**Total groups**: {total_groups}",
        f"**Total golfers**: {sum(g.get('num_golfers', 4) for g in groups)}",
        f"**Tee time span**: {format_time_from_baseline(int(first_tee_time_s))} to {format_time_from_baseline(int(last_tee_time_s))} ({total_span_hours:.1f}h)",
        "",
        "## Group Distribution by Hour",
        "",
    ]
    
    for hour in sorted(group_by_hour.keys()):
        data = group_by_hour[hour]
        lines.append(f"- **{hour}**: {data['groups']} groups, {data['golfers']} golfers")
    
    lines.extend([
        "",
        "## Sales Performance",
        "",
        f"- **Revenue**: ${revenue:.2f}",
        f"- **Sales count**: {num_sales}",
        f"- **Average per sale**: ${revenue / num_sales:.2f}" if num_sales > 0 else "- **Average per sale**: $0.00",
        "",
        "## Pass Events",
        "",
        f"- **Total passes**: {total_passes}",
        f"- **Groups with passes**: {len(pass_by_group)} of {total_groups}",
    ])
    
    if pass_by_group:
        lines.append("- **Passes per group**:")
        for group_id in sorted(pass_by_group.keys()):
            count = pass_by_group[group_id]
            lines.append(f"  - Group {group_id}: {count} passes")
    
    # Add crossings information if available
    crossings_data = result.get("crossings", {})
    if crossings_data and crossings_data.get("groups"):
        lines.extend([
            "",
            "## Crossings Analysis",
            "",
        ])
        
        total_crossings = sum(len(g.get("crossings", [])) for g in crossings_data["groups"])
        lines.append(f"- **Total crossings**: {total_crossings}")
        
        for i, group_data in enumerate(crossings_data["groups"], 1):
            crossings = group_data.get("crossings", [])
            if crossings:
                lines.append(f"- **Group {i}**: {len(crossings)} crossings")
    
    lines.extend([
        "",
        "## Configuration",
        "",
        f"- **Beverage cart service**: 09:00–17:00",
        f"- **Order probability**: {sales_result.get('pass_order_probability', 'unknown')}",
        f"- **Average order value**: ${sales_result.get('price_per_order', 'unknown')}",
        "",
        "## Artifacts",
        "",
        "- `coordinates.csv` — Combined GPS tracks (golfers + beverage cart)",
        "- `bev_cart_route.png` — Beverage cart route visualization",
        "- `sales.json` — Detailed sales and pass data",
        "- `result.json` — Complete simulation metadata",
        "",
    ])
    
    save_path.write_text("\n".join(lines), encoding="utf-8")


def write_phase5_summary(results: List[Dict], output_root: Path, scenario_name: str) -> None:
    """
    Write a Phase 5 summary.md file across multiple simulation runs.
    
    Args:
        results: List of simulation result summaries
        output_root: Root output directory
        scenario_name: Name of the scenario used
    """
    num_runs = len(results)
    
    if not results:
        lines = [
            f"# Phase 5 Summary — {scenario_name}",
            "",
            "No simulation results to summarize.",
            "",
        ]
        (output_root / "summary.md").write_text("\n".join(lines), encoding="utf-8")
        return
    
    # Aggregate statistics
    revenues = [r.get("revenue", 0.0) for r in results]
    sales_counts = [r.get("num_sales", 0) for r in results]
    pass_counts = [r.get("num_pass_intervals", 0) for r in results]
    group_counts = [r.get("groups", 0) for r in results]
    
    mean_revenue = sum(revenues) / len(revenues) if revenues else 0
    mean_sales = sum(sales_counts) / len(sales_counts) if sales_counts else 0
    mean_passes = sum(pass_counts) / len(pass_counts) if pass_counts else 0
    mean_groups = sum(group_counts) / len(group_counts) if group_counts else 0
    
    lines = [
        f"# Phase 5 Summary — {scenario_name}",
        "",
        f"**Simulation runs**: {num_runs}",
        f"**Scenario**: {scenario_name}",
        f"**Generated at**: {format_time_from_baseline(0)}",  # Will show current time
        "",
        "## Aggregate Performance",
        "",
        f"- **Mean revenue**: ${mean_revenue:.2f} (range: ${min(revenues):.2f}–${max(revenues):.2f})",
        f"- **Mean sales**: {mean_sales:.1f} (range: {min(sales_counts)}–{max(sales_counts)})",
        f"- **Mean groups**: {mean_groups:.1f}",
        f"- **Mean passes**: {mean_passes:.1f} (range: {min(pass_counts)}–{max(pass_counts)})",
        "",
        "## Per-Run Results",
        "",
    ]
    
    for r in results:
        run_idx = r.get("run_idx", 0)
        revenue = r.get("revenue", 0.0)
        sales = r.get("num_sales", 0)
        groups = r.get("groups", 0)
        passes = r.get("num_pass_intervals", 0)
        first_tee = r.get("first_tee_time_s", 0)
        last_tee = r.get("last_tee_time_s", 0)
        
        lines.append(f"### Run {run_idx:02d}")
        lines.append(f"- **Revenue**: ${revenue:.2f}")
        lines.append(f"- **Sales**: {sales}")
        lines.append(f"- **Groups**: {groups}")
        lines.append(f"- **Passes**: {passes}")
        lines.append(f"- **Tee times**: {format_time_from_baseline(int(first_tee))} to {format_time_from_baseline(int(last_tee))}")
        
        # Show first crossing if available
        first_crossing = r.get("first_crossing")
        if first_crossing:
            crossing_time = first_crossing.get("timestamp", "")
            if isinstance(crossing_time, str) and "T" in crossing_time:
                crossing_time = crossing_time.split("T")[1][:8]
            node = first_crossing.get("node_index", "unknown")
            hole = first_crossing.get("hole", "unknown")
            lines.append(f"- **First crossing**: {crossing_time} at node {node} (hole {hole})")
        
        lines.append("")
    
    lines.extend([
        "## Scenario Details",
        "",
        f"This Phase 5 simulation used the '{scenario_name}' scenario from tee_times_config.json.",
        "Each run generated golfer groups based on the hourly_golfers distribution,",
        "with random tee times within each specified hour.",
        "",
        "## Files Generated",
        "",
    ])
    
    for r in results:
        run_idx = r.get("run_idx", 0)
        lines.append(f"- **sim_{run_idx:02d}/**: coordinates.csv, bev_cart_route.png, sales.json, result.json, stats.md")
    
    lines.append("")
    (output_root / "summary.md").write_text("\n".join(lines), encoding="utf-8")