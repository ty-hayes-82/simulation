from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

import geopandas as gpd

from golfsim.logging import init_logging, get_logger


logger = get_logger(__name__)


def haversine_meters(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Return great-circle distance in meters between two lon/lat points.

    Uses a mean Earth radius of 6371 km.
    """
    # Convert degrees to radians
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return 6371000.0 * c


def _flatten_hole_lines_in_order(
    holes_gdf: gpd.GeoDataFrame, close_loop: bool
) -> List[Tuple[float, float]]:
    """Return a continuous list of (lon, lat) coordinates for holes 1..18.

    - Sorts by the `ref` property numerically
    - Concatenates each hole `LineString` vertices in order
    - Optionally appends the first point at the end to close the loop
    """
    if holes_gdf.empty:
        raise ValueError("Holes GeoDataFrame is empty")

    # Ensure we have the reference numbers as integers
    def _get_ref(v) -> int:
        try:
            return int(v)
        except Exception:
            return 10**9  # push invalid refs to the end

    holes_gdf = holes_gdf.copy()
    if "ref" not in holes_gdf.columns:
        raise ValueError("Expected 'ref' property in holes GeoJSON")

    holes_gdf["_ref_int"] = holes_gdf["ref"].apply(_get_ref)
    holes_gdf.sort_values("_ref_int", inplace=True)

    path_coords: List[Tuple[float, float]] = []
    for _, row in holes_gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type != "LineString":
            # If MultiLineString or others, take the longest LineString part
            try:
                longest = max(geom.geoms, key=lambda g: g.length)
                coords_seq: Iterable[Tuple[float, float]] = longest.coords  # type: ignore[attr-defined]
            except Exception:
                continue
        else:
            coords_seq = geom.coords  # type: ignore[attr-defined]

        for (lon, lat) in coords_seq:
            path_coords.append((float(lon), float(lat)))

    # Optionally close the loop by returning to the first coordinate
    if close_loop and len(path_coords) > 1:
        path_coords.append(path_coords[0])

    # Deduplicate consecutive identical coordinates to avoid zero-length steps
    deduped: List[Tuple[float, float]] = []
    last: Tuple[float, float] | None = None
    for pt in path_coords:
        if last is None or (pt[0] != last[0] or pt[1] != last[1]):
            deduped.append(pt)
            last = pt

    if len(deduped) < 2:
        raise ValueError("Not enough coordinates to form a path")

    return deduped


def _cumulative_distances(coords: Sequence[Tuple[float, float]]) -> List[float]:
    """Compute cumulative haversine distances along a polyline."""
    cum: List[float] = [0.0]
    total = 0.0
    for i in range(1, len(coords)):
        lon1, lat1 = coords[i - 1]
        lon2, lat2 = coords[i]
        d = haversine_meters(lon1, lat1, lon2, lat2)
        total += d
        cum.append(total)
    return cum


def _interpolate_between(p1: Tuple[float, float], p2: Tuple[float, float], frac: float) -> Tuple[float, float]:
    """Simple linear interpolation in lon/lat space for small steps.

    For short segments typical to hole centerlines, linear interpolation is sufficient.
    """
    lon = p1[0] + frac * (p2[0] - p1[0])
    lat = p1[1] + frac * (p2[1] - p1[1])
    return (lon, lat)


def resample_path_uniform(
    coords: Sequence[Tuple[float, float]], num_points: int
) -> List[Tuple[float, float]]:
    """Resample a path to a fixed number of points, uniformly by arc length.

    Includes the starting point. If `num_points` > 1, the final point will be at
    the full path length (end of path).
    """
    if num_points <= 0:
        raise ValueError("num_points must be positive")
    if len(coords) < 2:
        return list(coords)

    cum = _cumulative_distances(coords)
    total_len = cum[-1]
    if total_len <= 0:
        return [coords[0]] * num_points

    targets = [i * (total_len / max(num_points - 1, 1)) for i in range(num_points)]

    resampled: List[Tuple[float, float]] = []
    j = 0
    for t in targets:
        while j < len(cum) - 1 and cum[j + 1] < t:
            j += 1
        if j >= len(cum) - 1:
            resampled.append(coords[-1])
            continue
        seg_len = max(cum[j + 1] - cum[j], 1e-9)
        frac = (t - cum[j]) / seg_len
        resampled.append(_interpolate_between(coords[j], coords[j + 1], frac))

    return resampled


def write_outputs(
    output_dir: Path,
    ordered_coords: Sequence[Tuple[float, float]],
    sampled_points: Sequence[Tuple[float, float]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1) LineString of the ordered holes path
    line_geojson = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "holes_1_18_path"},
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[lon, lat] for (lon, lat) in ordered_coords],
                },
            }
        ],
    }
    (output_dir / "holes_path_line.geojson").write_text(json.dumps(line_geojson, indent=2))

    # 2) Sampled points as a FeatureCollection
    points_features = [
        {
            "type": "Feature",
            "properties": {"idx": i},
            "geometry": {"type": "Point", "coordinates": [lon, lat]},
        }
        for i, (lon, lat) in enumerate(sampled_points)
    ]
    points_geojson = {"type": "FeatureCollection", "features": points_features}
    (output_dir / "holes_path_sampled_points.geojson").write_text(
        json.dumps(points_geojson, indent=2)
    )

    # 3) Raw points JSON for direct consumption
    raw = {"coordinates": [[lon, lat] for (lon, lat) in sampled_points]}
    (output_dir / "holes_path_points.json").write_text(json.dumps(raw, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a path from hole 1 to 18 and resample into minute-based segments. "
            "Outputs GeoJSON and JSON under outputs/holes_path/."
        )
    )
    parser.add_argument(
        "--course-dir",
        type=str,
        default=str(Path("courses") / "pinetree_country_club"),
        help="Course directory containing a geojson/holes.geojson file",
    )
    parser.add_argument(
        "--total-minutes",
        type=int,
        required=True,
        help="Total minutes to complete the 18-hole loop. Determines number of segments.",
    )
    parser.add_argument(
        "--points-per-minute",
        type=int,
        default=1,
        help=(
            "How many points to sample per minute. For example, 2 means 2 points per minute. "
            "Total points = total_minutes * points_per_minute."
        ),
    )
    parser.add_argument(
        "--close-loop",
        action="store_true",
        help="Close the loop by returning to the starting point after hole 18.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(Path("outputs") / "holes_path"),
        help="Directory to write outputs",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        help="Logging level: DEBUG, INFO, WARNING, ERROR",
    )

    args = parser.parse_args()
    init_logging(args.log_level)

    try:
        course_dir = Path(args.course_dir)
        holes_path = course_dir / "geojson" / "holes.geojson"
        if not holes_path.exists():
            raise FileNotFoundError(f"Missing holes GeoJSON: {holes_path}")

        logger.info("Loading holes from %s", holes_path)
        holes_gdf = gpd.read_file(holes_path).to_crs(4326)

        ordered_coords = _flatten_hole_lines_in_order(holes_gdf, close_loop=bool(args.close_loop))
        logger.info("Built ordered path with %d vertices", len(ordered_coords))

        total_minutes: int = int(args.total_minutes)
        points_per_minute: int = max(1, int(args.points_per_minute))
        total_points = max(2, total_minutes * points_per_minute)
        logger.info("Resampling path into %d points (%d min x %d ppm)", total_points, total_minutes, points_per_minute)

        sampled_points = resample_path_uniform(ordered_coords, total_points)

        output_dir = Path(args.output_dir)
        write_outputs(output_dir, ordered_coords, sampled_points)
        logger.info("Wrote outputs to %s", output_dir)
        return 0
    except Exception as exc:
        logger.error("Failed to build holes loop segments: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


