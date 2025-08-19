import argparse
import json
from pathlib import Path
from typing import Any, Dict, Union, Optional

import geopandas as gpd

from golfsim.viz.heatmap_viz import (
    load_geofenced_holes,
    extract_order_data,
    calculate_delivery_time_stats,
)
from golfsim.logging import init_logging


def build_feature_collection(
    hole_polygons: Dict[int, Any],
    hole_stats: Dict[int, Dict[str, float]],
) -> Dict[str, Any]:
    """Build a GeoJSON FeatureCollection of hole polygons with delivery stats.

    Each feature contains properties:
      - hole: int
      - has_data: bool
      - avg_time, min_time, max_time, count (when available)
    """
    features: list[Dict[str, Any]] = []

    for hole_num, geom in hole_polygons.items():
        props: Dict[str, Any] = {"hole": int(hole_num)}
        stats = hole_stats.get(hole_num)
        if stats:
            props.update(
                {
                    "has_data": True,
                    "avg_time": float(stats.get("avg_time", 0.0)),
                    "min_time": float(stats.get("min_time", 0.0)),
                    "max_time": float(stats.get("max_time", 0.0)),
                    "count": int(stats.get("count", 0)),
                }
            )
        else:
            props.update({"has_data": False})

        # Convert shapely geometry to GeoJSON-like mapping
        gdf = gpd.GeoDataFrame({"geometry": [geom]}, crs="EPSG:4326")
        feature_geom = json.loads(gdf.to_json())["features"][0]["geometry"]

        features.append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": feature_geom,
            }
        )

    return {"type": "FeatureCollection", "features": features}


def load_results(results_file: Path) -> Dict[str, Any]:
    with results_file.open("r", encoding="utf-8") as f:
        return json.load(f)


def resolve_results_path(results_file: Optional[Path], output_dir: Optional[Path]) -> Path:
    if results_file:
        return results_file
    if output_dir:
        # Prefer results.json inside the given directory
        candidate = output_dir / "results.json"
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Could not resolve results.json. Provide --results-file or --output-dir with results.json inside.")


def main() -> None:
    init_logging()

    parser = argparse.ArgumentParser(
        description="Export hole delivery stats as GeoJSON for React viewer",
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--results-file", type=Path, help="Path to simulation results.json")
    input_group.add_argument("--output-dir", type=Path, help="Path to a run directory containing results.json")

    parser.add_argument(
        "--course-dir",
        type=Path,
        default=Path("courses/pinetree_country_club"),
        help="Path to course directory (defaults to courses/pinetree_country_club)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("my-map-animation/public/hole_delivery_times.geojson"),
        help="Output GeoJSON path (default: my-map-animation/public/hole_delivery_times.geojson)",
    )

    args = parser.parse_args()

    results_path = resolve_results_path(args.results_file, args.output_dir)
    results = load_results(results_path)

    # Extract order-level delivery times
    orders = results.get("orders", [])
    delivery_stats = results.get("delivery_stats", [])
    order_data = extract_order_data(results)

    # Compute per-hole statistics
    hole_stats = calculate_delivery_time_stats(order_data)

    # Load hole polygons from geofenced file
    hole_polygons = load_geofenced_holes(args.course_dir)

    # Build and save GeoJSON
    feature_collection = build_feature_collection(hole_polygons, hole_stats)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(feature_collection, f)

    print(f"Exported hole delivery GeoJSON to: {args.output}")


if __name__ == "__main__":
    main()


