from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import List, Dict

import simpy

from golfsim.logging import init_logging
from golfsim.simulation.services import BeverageCartService
from golfsim.simulation.bev_cart_pass import simulate_beverage_cart_sales
from golfsim.analysis.bev_cart_metrics import (
    calculate_bev_cart_metrics,
    summarize_bev_cart_metrics,
    format_metrics_report,
    format_summary_report
)
from golfsim.viz.matplotlib_viz import render_beverage_cart_plot
from golfsim.io.results import write_unified_coordinates_csv


def _write_geojson(coordinates: List[Dict], save_path: Path) -> None:
    """
    Write a simple GeoJSON FeatureCollection of Point features for the beverage cart track.
    """
    features = []
    for c in coordinates:
        lon = float(c.get("longitude", 0.0))
        lat = float(c.get("latitude", 0.0))
        ts = int(c.get("timestamp", 0))
        feat = {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {
                "timestamp": ts,
                "type": c.get("type", "bev_cart"),
                "current_hole": int(c.get("current_hole", 0)),
            },
        }
        features.append(feat)
    fc = {"type": "FeatureCollection", "features": features}
    save_path.write_text(json.dumps(fc, indent=2), encoding="utf-8")


def _write_csv(coordinates: List[Dict], save_path: Path) -> None:
    """
    Write GPS coordinates to CSV with headers.
    """
    fieldnames = ["timestamp", "latitude", "longitude", "type", "current_hole"]
    with save_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for c in coordinates:
            writer.writerow(
                {
                    "timestamp": int(c.get("timestamp", 0)),
                    "latitude": float(c.get("latitude", 0.0)),
                    "longitude": float(c.get("longitude", 0.0)),
                    "type": c.get("type", "bev_cart"),
                    "current_hole": int(c.get("current_hole", 0)),
                }
            )


def _write_metrics_json(metrics, save_path: Path) -> None:
    """Write metrics to JSON file."""
    metrics_dict = {
        "simulation_id": metrics.simulation_id,
        "cart_id": metrics.cart_id,
        "timestamp": datetime.now().isoformat(),
        "metrics": {
            "revenue_per_round": metrics.revenue_per_round,
            "average_order_value": metrics.average_order_value,
            "total_revenue": metrics.total_revenue,
            "order_penetration_rate": metrics.order_penetration_rate,
            "orders_per_cart_hour": metrics.orders_per_cart_hour,
            "total_orders": metrics.total_orders,
            "unique_customers": metrics.unique_customers,
            "tip_rate": metrics.tip_rate,
            "tips_per_order": metrics.tips_per_order,
            "total_tips": metrics.total_tips,
            "holes_covered_per_hour": metrics.holes_covered_per_hour,
            "minutes_per_hole_per_cart": metrics.minutes_per_hole_per_cart,
            "total_holes_covered": metrics.total_holes_covered,
            "golfer_repeat_rate": metrics.golfer_repeat_rate,
            "average_orders_per_customer": metrics.average_orders_per_customer,
            "customers_with_multiple_orders": metrics.customers_with_multiple_orders,
            "golfer_visibility_interval_minutes": metrics.golfer_visibility_interval_minutes,
            "total_visibility_events": metrics.total_visibility_events,
            "service_hours": metrics.service_hours,
            "rounds_in_service_window": metrics.rounds_in_service_window,
        }
    }
    save_path.write_text(json.dumps(metrics_dict, indent=2), encoding="utf-8")


def run_once(run_idx: int, course_dir: str, output_root: Path) -> Dict:
    env = simpy.Environment()
    cart_id = f"bev_cart_{run_idx}"
    
    # Create beverage cart service
    svc = BeverageCartService(env=env, course_dir=course_dir, cart_id=cart_id, track_coordinates=True)
    
    # Simulate sales (for bev-cart only, we'll create mock sales data)
    # In a real scenario, this would come from golfer interactions
    mock_sales_data = _generate_mock_sales_data(run_idx, svc.service_start_s, svc.service_end_s)
    
    env.run(until=svc.service_end_s)

    run_dir = output_root / f"sim_{run_idx:02d}"
    run_dir.mkdir(parents=True, exist_ok=True)

    # Calculate comprehensive metrics
    metrics = calculate_bev_cart_metrics(
        sales_data=mock_sales_data,
        coordinates=svc.coordinates,
        golfer_data=None,  # No golfer data for bev-cart only simulation
        service_start_s=svc.service_start_s,
        service_end_s=svc.service_end_s,
        simulation_id=f"phase1_run_{run_idx:02d}",
        cart_id=cart_id,
        tip_rate_percentage=15.0,
        proximity_threshold_m=70.0,
        proximity_duration_s=30
    )

    # Raw JSON artifacts for completeness
    coords_json_path = run_dir / "bev_cart_coordinates.json"
    log_json_path = run_dir / "bev_cart_activity_log.json"
    metrics_json_path = run_dir / "bev_cart_metrics.json"
    coords_json_path.write_text(json.dumps(svc.coordinates, indent=2), encoding="utf-8")
    log_json_path.write_text(json.dumps(svc.activity_log, indent=2), encoding="utf-8")
    _write_metrics_json(metrics, metrics_json_path)

    # Always render a PNG for cart locations
    png_path = run_dir / "bev_cart_route.png"
    render_beverage_cart_plot(svc.coordinates, course_dir=course_dir, save_path=png_path)

    # Unified CSV only (disable GeoJSON for now)
    csv_path = run_dir / "coordinates.csv"
    write_unified_coordinates_csv({svc.cart_id: svc.coordinates}, csv_path)

    # Write metrics report
    metrics_report_path = run_dir / "metrics_report.md"
    metrics_report_path.write_text(format_metrics_report(metrics), encoding="utf-8")

    result: Dict = {
        "run_idx": run_idx,
        "points": len(svc.coordinates),
        "first": int(svc.coordinates[0]["timestamp"]) if svc.coordinates else None,
        "last": int(svc.coordinates[-1]["timestamp"]) if svc.coordinates else None,
        "png": str(png_path),
        "geojson": "",
        "csv": str(csv_path),
        "metrics": metrics,
        "total_revenue": metrics.total_revenue,
        "total_orders": metrics.total_orders,
        "revenue_per_round": metrics.revenue_per_round,
        "orders_per_cart_hour": metrics.orders_per_cart_hour,
    }
    
    _write_stats_md(result, run_dir / "stats.md")
    return result


def _generate_mock_sales_data(run_idx: int, service_start_s: int, service_end_s: int) -> List[Dict]:
    """
    Generate mock sales data for bev-cart only simulation.
    In a real scenario, this would come from actual golfer interactions.
    """
    import random
    
    # Set seed for reproducible results
    random.seed(run_idx)
    
    sales_data = []
    service_duration_s = service_end_s - service_start_s
    
    # Generate 2-5 mock sales during the service window
    num_sales = random.randint(2, 5)
    
    for i in range(num_sales):
        # Random time within service window
        sale_time = service_start_s + random.randint(0, service_duration_s)
        
        # Random hole (1-18)
        hole_num = random.randint(1, 18)
        
        # Random order value between $8-$25
        order_value = random.uniform(8.0, 25.0)
        
        # Mock group ID
        group_id = random.randint(1, 10)
        
        sale = {
            "group_id": group_id,
            "hole_num": hole_num,
            "timestamp_s": sale_time,
            "price": round(order_value, 2),
        }
        sales_data.append(sale)
    
    # Sort by timestamp
    sales_data.sort(key=lambda x: x["timestamp_s"])
    return sales_data


def _write_stats_md(results: Dict, save_path: Path) -> None:
    lines = [
        "# Beverage Cart Run Stats",
        "",
        f"Points: {results.get('points', 0)}",
        f"First timestamp: {results.get('first', 'NA')}",
        f"Last timestamp: {results.get('last', 'NA')}",
        "",
        "## Key Metrics",
        f"Total Revenue: ${results.get('total_revenue', 0):.2f}",
        f"Total Orders: {results.get('total_orders', 0)}",
        f"Revenue per Round: ${results.get('revenue_per_round', 0):.2f}",
        f"Orders per Cart Hour: {results.get('orders_per_cart_hour', 0):.2f}",
    ]
    save_path.write_text("\n".join(lines), encoding="utf-8")


def write_summary_md(results: List[Dict], output_root: Path) -> None:
    if not results:
        return
    
    # Extract metrics for summary
    all_metrics = [r.get("metrics") for r in results if r.get("metrics")]
    
    points = [r.get("points", 0) for r in results]
    firsts = [r.get("first", 0) for r in results]
    lasts = [r.get("last", 0) for r in results]
    revenues = [r.get("total_revenue", 0) for r in results]
    orders = [r.get("total_orders", 0) for r in results]

    lines = [
        "# Phase 1 — Beverage cart only with metrics (5-run summary)",
        "",
        f"Runs: {len(results)}",
        f"Coordinates per run: min={min(points)}, max={max(points)}, mean={sum(points)/len(points):.1f}",
        f"First timestamps: min={min(firsts)}, max={max(firsts)} (expect >= 7200)",
        f"Last timestamps: min={min(lasts)}, max={max(lasts)} (expect <= 36000)",
        "",
        "## Revenue Summary",
        f"Total Revenue: min=${min(revenues):.2f}, max=${max(revenues):.2f}, mean=${sum(revenues)/len(revenues):.2f}",
        f"Total Orders: min={min(orders)}, max={max(orders)}, mean={sum(orders)/len(orders):.1f}",
        "",
        "## Artifacts",
        *[
            (
                f"- Run {r['run_idx']:02d}: PNG={r['png']} | CSV={r['csv']} | Revenue=${r.get('total_revenue', 0):.2f}"
            )
            for r in results
        ],
        "",
    ]
    
    # Add comprehensive metrics summary if available
    if all_metrics:
        summary = summarize_bev_cart_metrics(all_metrics)
        summary_report = format_summary_report(summary)
        lines.extend([
            "## Comprehensive Metrics Summary",
            "",
            summary_report
        ])
        
        # Write detailed summary to separate file
        summary_path = output_root / "comprehensive_metrics_summary.md"
        summary_path.write_text(summary_report, encoding="utf-8")
    
    (output_root / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    init_logging("INFO")
    course_dir = "courses/pinetree_country_club"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path("outputs") / f"{ts}_phase_01_with_metrics"
    output_root.mkdir(parents=True, exist_ok=True)

    all_results: List[Dict] = []
    for i in range(1, 6):
        result = run_once(i, course_dir, output_root)
        all_results.append(result)

    write_summary_md(all_results, output_root)


if __name__ == "__main__":
    main()
