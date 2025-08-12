"""
Analyze beverage cart metrics from simulation results.

This script processes existing simulation outputs and calculates comprehensive
bev-cart metrics for analysis and reporting.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

from golfsim.logging import init_logging
from golfsim.analysis.bev_cart_metrics import (
    calculate_bev_cart_metrics,
    summarize_bev_cart_metrics,
    format_metrics_report,
    format_summary_report,
    BevCartMetrics
)

logger = logging.getLogger(__name__)


def load_sales_data(sales_file: Path) -> List[Dict]:
    """Load sales data from JSON file."""
    try:
        with open(sales_file, 'r') as f:
            data = json.load(f)
        
        # Handle different sales data formats
        if isinstance(data, dict):
            if "sales" in data:
                return data["sales"]
            elif "activity_log" in data:
                # Convert activity log to sales format
                sales = []
                for entry in data["activity_log"]:
                    if entry.get("event") == "sale":
                        sales.append({
                            "group_id": entry.get("group_id"),
                            "hole_num": entry.get("hole_num"),
                            "timestamp_s": entry.get("timestamp_s"),
                            "price": entry.get("revenue", 0.0)
                        })
                return sales
            else:
                logger.warning(f"Unknown sales data format in {sales_file}")
                return []
        elif isinstance(data, list):
            return data
        else:
            logger.warning(f"Unexpected data type in {sales_file}")
            return []
    except Exception as e:
        logger.error(f"Error loading sales data from {sales_file}: {e}")
        return []


def load_coordinates_data(coords_file: Path) -> List[Dict]:
    """Load coordinates data from JSON or CSV file."""
    try:
        if coords_file.suffix.lower() == '.json':
            with open(coords_file, 'r') as f:
                data = json.load(f)
            
            # Handle different coordinate formats
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                # Look for coordinates in nested structure
                for key in ["coordinates", "bev_cart_coordinates", "gps_coordinates"]:
                    if key in data and isinstance(data[key], list):
                        return data[key]
                logger.warning(f"No coordinates found in {coords_file}")
                return []
            else:
                logger.warning(f"Unexpected coordinate data format in {coords_file}")
                return []
        else:
            # Handle CSV format
            import csv
            coords = []
            with open(coords_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    coord = {
                        "timestamp": int(row.get("timestamp", 0)),
                        "latitude": float(row.get("latitude", 0.0)),
                        "longitude": float(row.get("longitude", 0.0)),
                        "type": row.get("type", "bev_cart"),
                        "current_hole": int(row.get("current_hole", 0))
                    }
                    coords.append(coord)
            return coords
    except Exception as e:
        logger.error(f"Error loading coordinates from {coords_file}: {e}")
        return []


def load_golfer_data(golfer_file: Optional[Path]) -> Optional[List[Dict]]:
    """Load golfer GPS data if available."""
    if not golfer_file or not golfer_file.exists():
        return None
    
    try:
        if golfer_file.suffix.lower() == '.json':
            with open(golfer_file, 'r') as f:
                data = json.load(f)
            
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                # Look for golfer coordinates
                for key in ["golfer_coordinates", "golfers", "coordinates"]:
                    if key in data and isinstance(data[key], list):
                        return data[key]
                return None
            else:
                return None
        else:
            # Handle CSV format
            import csv
            golfers = []
            with open(golfer_file, 'r') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    if row.get("type") == "golfer":
                        golfer = {
                            "timestamp": int(row.get("timestamp", 0)),
                            "latitude": float(row.get("latitude", 0.0)),
                            "longitude": float(row.get("longitude", 0.0)),
                            "type": "golfer",
                            "group_id": row.get("group_id")
                        }
                        golfers.append(golfer)
            return golfers if golfers else None
    except Exception as e:
        logger.error(f"Error loading golfer data from {golfer_file}: {e}")
        return None


def analyze_single_simulation(
    simulation_dir: Path,
    simulation_id: str,
    cart_id: str = "bev_cart_1",
    tip_rate_percentage: float = 15.0,
    proximity_threshold_m: float = 70.0,
    proximity_duration_s: int = 30,
    service_start_s: int = 7200,
    service_end_s: int = 36000
) -> Optional[BevCartMetrics]:
    """
    Analyze metrics for a single simulation directory.
    
    Args:
        simulation_dir: Path to simulation output directory
        simulation_id: Unique identifier for this simulation
        cart_id: Cart identifier
        tip_rate_percentage: Tip rate as percentage
        proximity_threshold_m: Distance threshold for visibility
        proximity_duration_s: Minimum duration for visibility event
        service_start_s: Service start time in seconds
        service_end_s: Service end time in seconds
        
    Returns:
        BevCartMetrics object or None if analysis fails
    """
    logger.info(f"Analyzing simulation: {simulation_id}")
    
    # Look for sales data
    sales_data = []
    sales_files = [
        simulation_dir / "bev_cart_activity_log.json",
        simulation_dir / "sales_data.json",
        simulation_dir / "activity_log.json"
    ]
    
    for sales_file in sales_files:
        if sales_file.exists():
            sales_data = load_sales_data(sales_file)
            if sales_data:
                logger.info(f"Loaded {len(sales_data)} sales from {sales_file}")
                break
    
    # Look for coordinates data
    coordinates = []
    coord_files = [
        simulation_dir / "bev_cart_coordinates.json",
        simulation_dir / "coordinates.csv",
        simulation_dir / "coordinates.json"
    ]
    
    for coord_file in coord_files:
        if coord_file.exists():
            coordinates = load_coordinates_data(coord_file)
            if coordinates:
                logger.info(f"Loaded {len(coordinates)} coordinates from {coord_file}")
                break
    
    # Look for golfer data
    golfer_data = None
    golfer_files = [
        simulation_dir / "golfer_coordinates.json",
        simulation_dir / "coordinates.csv"  # May contain both cart and golfer data
    ]
    
    for golfer_file in golfer_files:
        if golfer_file.exists():
            golfer_data = load_golfer_data(golfer_file)
            if golfer_data:
                logger.info(f"Loaded {len(golfer_data)} golfer coordinates from {golfer_file}")
                break
    
    if not coordinates:
        logger.warning(f"No coordinates found for {simulation_id}")
        return None
    
    # Calculate metrics
    try:
        metrics = calculate_bev_cart_metrics(
            sales_data=sales_data,
            coordinates=coordinates,
            golfer_data=golfer_data,
            service_start_s=service_start_s,
            service_end_s=service_end_s,
            simulation_id=simulation_id,
            cart_id=cart_id,
            tip_rate_percentage=tip_rate_percentage,
            proximity_threshold_m=proximity_threshold_m,
            proximity_duration_s=proximity_duration_s
        )
        
        logger.info(f"Calculated metrics for {simulation_id}: ${metrics.total_revenue:.2f} revenue, {metrics.total_orders} orders")
        return metrics
        
    except Exception as e:
        logger.error(f"Error calculating metrics for {simulation_id}: {e}")
        return None


def analyze_multiple_simulations(
    output_dir: Path,
    pattern: str = "sim_*",
    tip_rate_percentage: float = 15.0,
    proximity_threshold_m: float = 70.0,
    proximity_duration_s: int = 30,
    service_start_s: int = 7200,
    service_end_s: int = 36000
) -> List[BevCartMetrics]:
    """
    Analyze metrics for multiple simulation directories.
    
    Args:
        output_dir: Root directory containing simulation outputs
        pattern: Glob pattern to match simulation directories
        tip_rate_percentage: Tip rate as percentage
        proximity_threshold_m: Distance threshold for visibility
        proximity_duration_s: Minimum duration for visibility event
        service_start_s: Service start time in seconds
        service_end_s: Service end time in seconds
        
    Returns:
        List of BevCartMetrics objects
    """
    all_metrics = []
    
    # Find simulation directories
    simulation_dirs = list(output_dir.glob(pattern))
    if not simulation_dirs:
        logger.warning(f"No simulation directories found matching pattern '{pattern}' in {output_dir}")
        return all_metrics
    
    logger.info(f"Found {len(simulation_dirs)} simulation directories to analyze")
    
    for sim_dir in sorted(simulation_dirs):
        if not sim_dir.is_dir():
            continue
        
        # Extract simulation ID from directory name
        simulation_id = sim_dir.name
        
        # Try to extract cart ID from directory structure
        cart_id = "bev_cart_1"
        if "bev_cart" in simulation_id:
            cart_id = simulation_id
        
        metrics = analyze_single_simulation(
            simulation_dir=sim_dir,
            simulation_id=simulation_id,
            cart_id=cart_id,
            tip_rate_percentage=tip_rate_percentage,
            proximity_threshold_m=proximity_threshold_m,
            proximity_duration_s=proximity_duration_s,
            service_start_s=service_start_s,
            service_end_s=service_end_s
        )
        
        if metrics:
            all_metrics.append(metrics)
    
    logger.info(f"Successfully analyzed {len(all_metrics)} simulations")
    return all_metrics


def main():
    parser = argparse.ArgumentParser(description="Analyze beverage cart metrics from simulation results")
    parser.add_argument("output_dir", type=Path, help="Directory containing simulation outputs")
    parser.add_argument("--pattern", default="sim_*", help="Glob pattern for simulation directories")
    parser.add_argument("--tip-rate", type=float, default=15.0, help="Tip rate percentage (default: 15.0)")
    parser.add_argument("--proximity-threshold", type=float, default=70.0, help="Proximity threshold in meters (default: 70.0)")
    parser.add_argument("--proximity-duration", type=int, default=30, help="Minimum proximity duration in seconds (default: 30)")
    parser.add_argument("--service-start", type=int, default=7200, help="Service start time in seconds (default: 7200)")
    parser.add_argument("--service-end", type=int, default=36000, help="Service end time in seconds (default: 36000)")
    parser.add_argument("--output", type=Path, help="Output file for summary report")
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable verbose logging")
    
    args = parser.parse_args()
    
    # Setup logging
    log_level = "DEBUG" if args.verbose else "INFO"
    init_logging(log_level)
    
    if not args.output_dir.exists():
        logger.error(f"Output directory does not exist: {args.output_dir}")
        return 1
    
    # Analyze simulations
    all_metrics = analyze_multiple_simulations(
        output_dir=args.output_dir,
        pattern=args.pattern,
        tip_rate_percentage=args.tip_rate,
        proximity_threshold_m=args.proximity_threshold,
        proximity_duration_s=args.proximity_duration,
        service_start_s=args.service_start,
        service_end_s=args.service_end
    )
    
    if not all_metrics:
        logger.warning("No metrics calculated")
        return 1
    
    # Generate summary
    summary = summarize_bev_cart_metrics(all_metrics)
    summary_report = format_summary_report(summary)
    
    # Write individual reports
    for metrics in all_metrics:
        report = format_metrics_report(metrics)
        report_file = args.output_dir / f"{metrics.simulation_id}_metrics_report.md"
        report_file.write_text(report, encoding="utf-8")
        logger.info(f"Wrote individual report: {report_file}")
    
    # Write summary report
    if args.output:
        output_file = args.output
    else:
        output_file = args.output_dir / "bev_cart_metrics_summary.md"
    
    output_file.write_text(summary_report, encoding="utf-8")
    logger.info(f"Wrote summary report: {output_file}")
    
    # Print summary to console
    print("\n" + "="*80)
    print("BEVERAGE CART METRICS SUMMARY")
    print("="*80)
    print(summary_report)
    
    return 0


if __name__ == "__main__":
    exit(main())
