"""
Simulation Results I/O Module

Handles final packaging and exporting of simulation results for consumers like the web UI.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd

from golfsim.logging import get_logger


logger = get_logger(__name__)


@dataclass
class SimulationResult:
    # Minimal common fields; callers can add extras via metadata
    success: bool = True
    order_time_s: Optional[float] = None
    total_service_time_s: Optional[float] = None
    delivery_distance_m: Optional[float] = None
    delivery_travel_time_s: Optional[float] = None
    prediction_method: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        raw = asdict(self)
        # Remove None values for cleanliness
        return {k: v for k, v in raw.items() if v is not None}

    def to_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, default=str)
        logger.info("Saved simulation result JSON: %s", path)
        return path


def find_actual_delivery_location(results: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Find the actual location where delivery occurred based on runner coordinates.

    Supports both historical and current runner coordinate schemas:
      - { 'latitude', 'longitude', 'timestamp' }
      - { 'lat', 'lon', 'timestamp_s' }
    """
    runner_coords = results.get("runner_coordinates", [])
    delivered_time = results.get("delivered_s", 0)

    if not runner_coords or not delivered_time:
        return None

    def get_timestamp(entry: Dict[str, Any]) -> float:
        return float(entry.get("timestamp", entry.get("timestamp_s", 0)) or 0)

    # Find the coordinate entry closest to delivery time
    closest_entry: Optional[Dict[str, Any]] = None
    min_time_diff = float("inf")

    for coord_entry in runner_coords:
        time_val = get_timestamp(coord_entry)
        time_diff = abs(time_val - float(delivered_time))
        if time_diff < min_time_diff:
            min_time_diff = time_diff
            closest_entry = coord_entry

    if closest_entry is None:
        return None

    lat = closest_entry.get("latitude", closest_entry.get("lat"))
    lon = closest_entry.get("longitude", closest_entry.get("lon"))
    hole = closest_entry.get("hole")
    ts = get_timestamp(closest_entry)

    if lat is None or lon is None:
        return None

    return {
        "latitude": float(lat),
        "longitude": float(lon),
        "hole": hole,
        "timestamp_s": float(ts),
        "time_diff_s": float(min_time_diff),
    }


def sanitize_for_json(data: Dict[str, Any]) -> Dict[str, Any]:
    """Prepare a nested dict for JSON by removing non-serializable heavy objects.

    - Drops keys commonly containing NetworkX objects or large structures
    - Converts Path to str
    - Leaves coordinates arrays, scalars as is
    """
    def convert(value: Any) -> Any:
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {k: convert(v) for k, v in value.items()}
        if isinstance(value, list):
            return [convert(v) for v in value]
        # Best-effort: let json handle builtins
        return value

    pruned: Dict[str, Any] = {}
    for key, value in data.items():
        if key in {"trip_to_golfer", "trip_back", "trip_to_clubhouse"}:
            # Preserve essential routing data for visualization while removing heavy objects
            if isinstance(value, dict):
                lightweight_trip = {
                    "nodes": value.get("nodes", []),
                    "length_m": value.get("length_m"),
                    "time_s": value.get("time_s"),
                    "routing_type": value.get("routing_type")
                }
                pruned[key] = convert(lightweight_trip)
            continue
        pruned[key] = convert(value)
    return pruned


def write_coordinates_csvs(
    results: Dict[str, Any], output_dir: str | Path
) -> Dict[str, Path]:
    """Write golfer and runner coordinates to CSV if present; return file paths.

    Expected keys: 'golfer_coordinates', 'runner_coordinates'
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    written: Dict[str, Path] = {}

    for key in ("golfer_coordinates", "runner_coordinates"):
        if key in results and isinstance(results[key], list) and results[key]:
            df = pd.DataFrame(results[key])
            # Backward-compatible enhancement: ensure runner_id column exists for runner CSV
            if key == "runner_coordinates":
                if "runner_id" not in df.columns:
                    # Prefer 'id' or fall back to 'golfer_id' if legacy schema
                    if "id" in df.columns:
                        df.insert(0, "runner_id", df["id"].astype(str))
                    elif "golfer_id" in df.columns:
                        df.insert(0, "runner_id", df["golfer_id"].astype(str))
                    else:
                        df.insert(0, "runner_id", "runner_1")
            csv_file = output_dir / f"{key}.csv"
            df.to_csv(csv_file, index=False)
            written[key] = csv_file
            logger.info("Saved %s: %s", key, csv_file)
    return written


def save_results_bundle(results: Dict[str, Any], output_dir: str | Path) -> Dict[str, Path]:
    """Save a complete results bundle using unified utilities.

    - Writes coordinates CSVs
    - Writes sanitized JSON summary
    Returns a map of artifact names to paths.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    artifacts: Dict[str, Path] = {}

    # Coordinates
    artifacts.update(write_coordinates_csvs(results, output_dir))

    # JSON summary (sanitized)
    json_results = sanitize_for_json(results)
    json_path = output_dir / "simulation_results.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(json_results, f, indent=2, default=str)
    artifacts["simulation_results_json"] = json_path
    logger.info("Saved results JSON: %s", json_path)

    return artifacts


def normalize_coordinate_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a coordinate entry to unified schema fields.

    Returns dict with keys: id, latitude, longitude, timestamp, type, hole
    Enhanced with visibility tracking fields for golfer points.
    """
    def _get_first(*keys, default=None):
        for k in keys:
            if k in entry and entry[k] is not None:
                return entry[k]
        return default

    raw_type = str(_get_first("type", default="")).lower()
    if "runner" in raw_type:
        norm_type = "runner"
    elif "bev" in raw_type or "beverage" in raw_type:
        norm_type = "bevcart"
    elif "golf" in raw_type:
        norm_type = "golfer"
    else:
        norm_type = raw_type or "unknown"

    hole_val = _get_first("current_hole", "hole")
    if hole_val is None or hole_val == "":
        hole_val = "clubhouse"

    base_entry = {
        "id": str(_get_first("id", default="")),
        "latitude": float(_get_first("latitude", "lat", default=0.0)),
        "longitude": float(_get_first("longitude", "lon", default=0.0)),
        "timestamp": int(float(_get_first("timestamp", "timestamp_s", default=0))),
        "type": norm_type,
        "hole": hole_val,
    }
    
    # Add visibility tracking fields if present (for golfer points)
    visibility_status = _get_first("visibility_status", "visibility_color")
    if visibility_status is not None:
        base_entry["visibility_status"] = str(visibility_status)
        
    time_since_sighting = _get_first("time_since_last_sighting_min")
    if time_since_sighting is not None:
        base_entry["time_since_last_sighting_min"] = float(time_since_sighting)
        
    pulsing = _get_first("pulsing")
    if pulsing is not None:
        base_entry["pulsing"] = bool(pulsing)
    
    # Add running totals fields if present (for beverage cart points)
    total_orders = _get_first("total_orders")
    if total_orders is not None:
        base_entry["total_orders"] = total_orders
        
    total_revenue = _get_first("total_revenue")
    if total_revenue is not None:
        base_entry["total_revenue"] = total_revenue
        
    avg_per_order = _get_first("avg_per_order")
    if avg_per_order is not None:
        base_entry["avg_per_order"] = avg_per_order
        
    revenue_per_hour = _get_first("revenue_per_hour")
    if revenue_per_hour is not None:
        base_entry["revenue_per_hour"] = revenue_per_hour

    # Optional: rolling average order time in minutes (for runner points)
    avg_order_time_min = _get_first("avg_order_time_min")
    if avg_order_time_min is not None:
        base_entry["avg_order_time_min"] = avg_order_time_min

    return base_entry


def write_unified_coordinates_csv(points_by_id: Dict[str, List[Dict[str, Any]]], save_path: str | Path) -> Path:
    """Write a single CSV combining one or more streams into the unified format.

    Columns: id,latitude,longitude,timestamp,type,hole,visibility_status,time_since_last_sighting_min,pulsing
    Each input point can contain latitude/lat, longitude/lon, timestamp/timestamp_s, current_hole/hole, type, id.
    The provided key is used as 'id' if the entry lacks an explicit id.
    Enhanced with visibility tracking fields for golfer points.
    """
    save_path = Path(save_path)
    save_path.parent.mkdir(parents=True, exist_ok=True)

    # Base fieldnames plus visibility tracking fields and running totals
    fieldnames = [
        "id", "latitude", "longitude", "timestamp", "type", "hole",
        "visibility_status", "time_since_last_sighting_min", "pulsing",
        "total_orders", "total_revenue", "avg_per_order", "revenue_per_hour",
        "avg_order_time_min",
    ]
    
    # Use csv module to avoid pandas dependency here
    import csv as _csv
    with save_path.open("w", newline="", encoding="utf-8") as f:
        writer = _csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        for stream_id, points in points_by_id.items():
            for p in points or []:
                entry = dict(p)
                if "id" not in entry or not entry.get("id"):
                    entry["id"] = stream_id
                row = normalize_coordinate_entry(entry)
                writer.writerow(row)

    logger.info("Saved unified coordinates CSV: %s", save_path)
    return save_path


def write_coordinates_csv_with_visibility_and_totals(
    points_by_id: Dict[str, List[Dict[str, Any]]], 
    save_path: str | Path,
    sales_data: Optional[List[Dict[str, Any]]] = None,
    enable_visibility_tracking: bool = True,
    enable_running_totals: bool = True,
    visibility_thresholds: Optional[Dict[str, float]] = None,
    service_start_s: int = 7200,
    service_end_s: int = 36000
) -> Path:
    """Write coordinates CSV with optional visibility tracking and running totals.
    
    Args:
        points_by_id: Dictionary mapping entity IDs to their GPS points
        save_path: Path to save the CSV file
        sales_data: Sales data for calculating running totals
        enable_visibility_tracking: Whether to apply visibility tracking to golfer points
        enable_running_totals: Whether to add running totals for beverage cart
        visibility_thresholds: Custom thresholds for visibility status transitions
        service_start_s: Service start time in seconds since 7 AM
        service_end_s: Service end time in seconds since 7 AM
        
    Returns:
        Path to the saved CSV file
    """
    # Add running totals if enabled and we have sales data
    enhanced_points_by_id = {}
    if enable_running_totals and sales_data:
        from .running_totals import enhance_coordinates_with_running_totals
        
        for entity_id, points in points_by_id.items():
            enhanced_points = enhance_coordinates_with_running_totals(
                points, sales_data, None, service_start_s, service_end_s
            )
            enhanced_points_by_id[entity_id] = enhanced_points
    else:
        enhanced_points_by_id = points_by_id.copy()
    
    # Call the original function with enhanced points
    return write_coordinates_csv_with_visibility(
        enhanced_points_by_id, save_path, enable_visibility_tracking, visibility_thresholds
    )


def write_coordinates_csv_with_visibility(
    points_by_id: Dict[str, List[Dict[str, Any]]], 
    save_path: str | Path,
    enable_visibility_tracking: bool = True,
    visibility_thresholds: Optional[Dict[str, float]] = None
) -> Path:
    """Write coordinates CSV with optional visibility tracking for golfer points.
    
    Args:
        points_by_id: Dictionary mapping entity IDs to their GPS points
        save_path: Path to save the CSV file
        enable_visibility_tracking: Whether to apply visibility tracking to golfer points
        visibility_thresholds: Custom thresholds for visibility status transitions
        
    Returns:
        Path to the saved CSV file
    """
    if not enable_visibility_tracking:
        # Use standard CSV writer if visibility tracking is disabled
        return write_unified_coordinates_csv(points_by_id, save_path)
    
    # Import visibility service only when needed
    from ..simulation.visibility_tracking import create_visibility_service
    
    # Set up visibility tracking service
    thresholds = visibility_thresholds or {}
    visibility_service = create_visibility_service(
        proximity_threshold_m=thresholds.get("proximity_threshold_m", 100.0),
        green_to_yellow_min=thresholds.get("green_to_yellow_min", 20.0),
        yellow_to_orange_min=thresholds.get("yellow_to_orange_min", 40.0),
        orange_to_red_min=thresholds.get("orange_to_red_min", 60.0),
        red_pulsing_enabled=thresholds.get("red_pulsing_enabled", True)
    )
    
    # Separate golfer and non-golfer points
    golfer_points = []
    cart_points = []
    other_points = []
    
    enhanced_points_by_id = {}
    
    for entity_id, points in points_by_id.items():
        if not points:
            enhanced_points_by_id[entity_id] = []
            continue
            
        # Classify points by type
        first_point_type = str(points[0].get("type", "")).lower()
        entity_id_lower = entity_id.lower()
        
        # Check if this is golfer data (by entity ID or type)
        if ("golf" in first_point_type or "golf" in entity_id_lower or 
            first_point_type in ["hole", "transfer"]):  # Phase 3 uses "hole"/"transfer" for golfer movement
            golfer_points.extend(points)
            enhanced_points_by_id[entity_id] = points  # Will be enhanced later
        elif "bev" in first_point_type or "cart" in first_point_type:
            cart_points.extend(points)
            enhanced_points_by_id[entity_id] = points
        else:
            other_points.extend(points)
            enhanced_points_by_id[entity_id] = points
    
    # Process visibility tracking if we have both golfers and carts
    if golfer_points and cart_points:
        logger.info("Processing visibility tracking for %d golfer points and %d cart points", 
                   len(golfer_points), len(cart_points))
        
        visibility_service.process_coordinates_batch(golfer_points, cart_points)
        
        # Enhance golfer points with visibility information
        for entity_id, points in enhanced_points_by_id.items():
            if points:
                first_point_type = str(points[0].get("type", "")).lower()
                entity_id_lower = entity_id.lower()
                
                # Check if this is golfer data (same logic as classification above)
                if ("golf" in first_point_type or "golf" in entity_id_lower or 
                    first_point_type in ["hole", "transfer"]):
                    enhanced_points_by_id[entity_id] = visibility_service.annotate_golfer_points_with_visibility(points)
                    logger.debug("Enhanced %d points for entity %s", len(points), entity_id)
        
        # Log visibility summary
        summary = visibility_service.get_visibility_summary()
        logger.info("Visibility tracking summary: %d golfers, %d visibility events", 
                   summary["total_golfers"], summary["total_visibility_events"])
    else:
        logger.info("Skipping visibility tracking: insufficient data (golfers: %d, carts: %d)", 
                   len(golfer_points), len(cart_points))
    
    # Write enhanced CSV
    return write_unified_coordinates_csv(enhanced_points_by_id, save_path)


def copy_to_public_coordinates(
    run_dir: Path, simulation_id: str, mode: str, golfer_group_count: int,
    description: Optional[str] = None
) -> None:
    """Copy simulation files to public/coordinates/ for React map animation."""
    if golfer_group_count != 1:
        return
        
    try:
        react_public_dir = Path("my-map-animation") / "public"
        public_coords_dir = react_public_dir / "coordinates"
        public_coords_dir.mkdir(parents=True, exist_ok=True)
        
        source_coords = run_dir / "coordinates.csv"
        source_metrics = run_dir / "simulation_metrics.json"
        
        if source_coords.exists():
            shutil.copy2(source_coords, public_coords_dir / "coordinates.csv")

        if source_metrics.exists():
            shutil.copy2(source_metrics, public_coords_dir / "simulation_metrics.json")
            
        coord_count = sum(1 for line in source_coords.open("r", encoding="utf-8")) - 1 if source_coords.exists() else 0
        manifest_data = {
            "simulations": [{"id": "coordinates", "name": f"{mode.title()} Simulation", "filename": "coordinates.csv", "description": description or f"{coord_count} coordinate points"}],
            "defaultSimulation": "coordinates"
        }
        
        manifest_path = public_coords_dir / "manifest.json"
        with manifest_path.open("w", encoding="utf-8") as f:
            json.dump(manifest_data, f, indent=2)

    except Exception as e:
        logger.warning("Failed to copy coordinates to public: %s", e)

def sync_run_outputs_to_public(run_dir: Path, description: Optional[str] = None) -> None:
    """Copy key artifacts from a run directory into my-map-animation/public/ and my-map-animation/public/coordinates/."""
    try:
        public_root = Path("my-map-animation") / "public"
        coords_dir = public_root / "coordinates"
        public_root.mkdir(parents=True, exist_ok=True)
        coords_dir.mkdir(parents=True, exist_ok=True)

        src_coords = run_dir / "coordinates.csv"
        if src_coords.exists():
            shutil.copy2(src_coords, coords_dir / "coordinates.csv")
            shutil.copy2(src_coords, public_root / "coordinates.csv")

        src_metrics = run_dir / "simulation_metrics.json"
        if src_metrics.exists():
            shutil.copy2(src_metrics, coords_dir / "simulation_metrics.json")
            shutil.copy2(src_metrics, public_root / "simulation_metrics.json")
        
        coord_count = sum(1 for _ in src_coords.open("r")) - 1 if src_coords.exists() else 0
        manifest_data = {
            "simulations": [{"id": "coordinates", "name": "Simulation", "filename": "coordinates.csv", "description": description or f"{coord_count} coordinate points"}],
            "defaultSimulation": "coordinates"
        }
        with (coords_dir / "manifest.json").open("w") as f: json.dump(manifest_data, f, indent=2)
        with (public_root / "manifest.json").open("w") as f: json.dump(manifest_data, f, indent=2)

    except Exception as e:
        logger.warning("Failed to sync outputs to public: %s", e)

