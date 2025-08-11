#!/usr/bin/env python3
"""
Split a golf course polygon into 18 hole sections using centerline GeoJSON.

Approach (high level):
- Read the course boundary polygon and the 18 hole centerlines.
- Project to a local UTM CRS for accurate distance calculations.
- Densify each hole line into seed points (every N meters).
- Build a Voronoi tessellation from all seeds; union cells by hole id.
- Clip to the course boundary, then assign any leftover slivers to the nearest hole.
- Optionally smooth boundaries.
- Write 18 polygons (one per hole) to GeoJSON with basic attributes.

This is a practical, distance-based partitioning that closely follows each hole’s centerline.
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from typing import Dict, List, Tuple
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPolygon,
    Point,
    Polygon,
)
from shapely.ops import linemerge, unary_union

from golfsim.logging import init_logging

# Optional dependencies (used if available)
try:
    from scipy.spatial import Voronoi

    _HAS_SCIPY = True
except Exception:  # pragma: no cover - optional
    _HAS_SCIPY = False

# Shapely voronoi_diagram (fallback if SciPy not available)
try:
    from shapely.ops import voronoi_diagram as shapely_voronoi

    _HAS_SHAPELY_VORONOI = True
except Exception:  # pragma: no cover - optional
    _HAS_SHAPELY_VORONOI = False


def _estimate_local_crs(gdf: gpd.GeoDataFrame) -> str:
    """Estimate a suitable projected CRS (UTM) for distance-based ops."""
    try:
        crs = gdf.estimate_utm_crs()
        if crs:
            return crs.to_string()
    except Exception:
        pass
    # Fallback: Web Mercator (not ideal, but better than WGS84 for distances)
    return "EPSG:3857"


def _ensure_polygon_or_multipolygon(geom) -> Polygon | MultiPolygon:
    """Return a Polygon or MultiPolygon. Dissolve collections to polygons without dropping parts."""
    if geom is None or geom.is_empty:
        raise ValueError("Empty or invalid course boundary geometry.")
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    if isinstance(geom, GeometryCollection):
        poly = unary_union([g for g in geom.geoms if isinstance(g, (Polygon, MultiPolygon))])
        if isinstance(poly, (Polygon, MultiPolygon)):
            return poly
    raise ValueError("Course boundary must be a polygon or multipolygon.")


def _merge_lines(geom) -> LineString:
    """Merge LineString / MultiLineString segments into a single LineString if possible.
    If disjoint, return a MultiLineString with merged parts.
    """
    if geom is None or geom.is_empty:
        raise ValueError("Empty hole line geometry.")
    if isinstance(geom, LineString):
        return geom
    if isinstance(geom, MultiLineString):
        merged = linemerge(geom)
        if isinstance(merged, LineString):
            return merged
        # Not fully connected; keep as MultiLineString
        return merged
    raise ValueError("Hole line must be LineString or MultiLineString.")


def _densify_line(line, step_m: float) -> List[Point]:
    """Sample points along a LineString/MultiLineString every step_m meters (projected CRS)."""
    points: List[Point] = []
    if isinstance(line, LineString):
        total = line.length
        if total == 0:
            return [Point(line.coords[0])]
        num_segments = max(1, int(math.floor(total / step_m)))
        distances = np.linspace(0.0, total, num=num_segments + 1)
        for distance in distances:
            points.append(line.interpolate(distance))
        return points
    elif isinstance(line, MultiLineString):
        for segment in line.geoms:
            points.extend(_densify_line(segment, step_m))
        return points
    else:
        raise ValueError("Geometry must be LineString or MultiLineString for densify.")


def _voronoi_finite_polygons_2d(vor: Voronoi, radius: float | None = None) -> Tuple[List[List[int]], np.ndarray]:
    """Reconstruct infinite Voronoi regions in a 2D diagram to finite regions."""
    if vor.points.shape[1] != 2:
        raise ValueError("Requires 2D input")

    new_regions: List[List[int]] = []
    new_vertices = vor.vertices.tolist()

    center = vor.points.mean(axis=0)
    if radius is None:
        radius = vor.points.ptp().max() * 2

    # Map all ridges for a point
    all_ridges: Dict[int, List[Tuple[int, int, int]]] = {}
    for (p1, p2), (v1, v2) in zip(vor.ridge_points, vor.ridge_vertices):
        all_ridges.setdefault(p1, []).append((p2, v1, v2))
        all_ridges.setdefault(p2, []).append((p1, v1, v2))

    # Reconstruct infinite regions
    for p1, region_idx in enumerate(vor.point_region):
        vertices = vor.regions[region_idx]
        if all(v >= 0 for v in vertices):
            new_regions.append(vertices)
            continue

        # Reconstruct a non-finite region
        ridges = all_ridges[p1]
        new_region = [v for v in vertices if v >= 0]

        for p2, v1, v2 in ridges:
            if v1 >= 0 and v2 >= 0:
                continue
            # Compute the missing endpoint at infinity
            tangent = vor.points[p2] - vor.points[p1]
            tangent /= np.linalg.norm(tangent)
            normal = np.array([-tangent[1], tangent[0]])

            midpoint = vor.points[[p1, p2]].mean(axis=0)
            direction = np.sign(np.dot(midpoint - center, normal)) * normal
            existing_vertex = vor.vertices[[v for v in (v1, v2) if v >= 0]][0]
            far_point = existing_vertex + direction * radius

            new_vertices.append(far_point.tolist())
            new_region.append(len(new_vertices) - 1)

        # Order region's vertices counterclockwise
        vs = np.asarray([new_vertices[v] for v in new_region])
        centroid = vs.mean(axis=0)
        angles = np.arctan2(vs[:, 1] - centroid[1], vs[:, 0] - centroid[0])
        new_region = [v for _, v in sorted(zip(angles, new_region))]

        new_regions.append(new_region)

    return new_regions, np.asarray(new_vertices)


def _build_voronoi_polygons(points: np.ndarray, clip_poly: Polygon) -> List[Polygon]:
    """
    Build finite Voronoi polygons for given 2D points, clipped to clip_poly bounds.
    Prefers SciPy for generator mapping; falls back to Shapely voronoi_diagram.
    Returns a list of polygons aligned with the input point order (if SciPy present),
    otherwise a list of polygons with no guaranteed order (fallback path).
    """
    bounds = clip_poly.bounds  # (minx, miny, maxx, maxy)
    # Add a margin so cells extend beyond the boundary before clipping
    margin = max(bounds[2] - bounds[0], bounds[3] - bounds[1]) * 0.5
    bbox = Polygon(
        [
            (bounds[0] - margin, bounds[1] - margin),
            (bounds[2] + margin, bounds[1] - margin),
            (bounds[2] + margin, bounds[3] + margin),
            (bounds[0] - margin, bounds[3] + margin),
        ]
    )

    if _HAS_SCIPY:
        vor = Voronoi(points)
        regions, vertices = _voronoi_finite_polygons_2d(vor, radius=margin * 2.0)
        polygons: List[Polygon] = []
        # Align each region with its generating point (by index)
        for region in regions:
            poly = Polygon(vertices[region])
            if not poly.is_valid:
                poly = poly.buffer(0)
            poly = poly.intersection(bbox)
            polygons.append(poly)
        # SciPy yields one region per input point, in order of points
        return polygons
    else:
        if not _HAS_SHAPELY_VORONOI:
            raise RuntimeError(
                "Neither SciPy nor shapely.voronoi_diagram is available. Install scipy or upgrade shapely/GEOS."
            )
        # Shapely fallback: doesn't preserve a direct mapping; we'll get a collection of cells
        # We'll handle mapping later by nearest seed classification.
        from shapely import geometry as _geometry  # type: ignore

        multipoints = _geometry.MultiPoint([Point(x, y) for x, y in points])
        vor_gc = shapely_voronoi(multipoints, envelope=bbox)
        cells: List[Polygon] = []
        if isinstance(vor_gc, (GeometryCollection, MultiPolygon)):
            for geom in vor_gc.geoms:
                if isinstance(geom, Polygon):
                    cells.append(geom.intersection(bbox))
        elif isinstance(vor_gc, Polygon):
            cells = [vor_gc.intersection(bbox)]
        else:
            cells = []
        return cells


def split_course_into_holes(
    course_polygon_path: str,
    hole_lines_path: str,
    output_path: str,
    step_m: float = 25.0,
    smooth_m: float = 0.0,
    max_points_per_hole: int = 250,
    hole_prop_candidates: Tuple[str, ...] = (
        "hole",
        "Hole",
        "HOLE",
        "number",
        "Number",
        "id",
        "Id",
        "ref",
        "Ref",
        "REF",
    ),
) -> None:
    """Main pipeline to split the course into 18 sections."""
    logging.info("Loading inputs...")
    course_gdf = gpd.read_file(course_polygon_path)
    holes_gdf = gpd.read_file(hole_lines_path)

    if course_gdf.empty:
        raise ValueError("Course polygon file contains no features.")
    if holes_gdf.empty:
        raise ValueError("Hole lines file contains no features.")

    # Dissolve boundary polygon(s) but retain all parts (Polygon or MultiPolygon)
    dissolved = unary_union(course_gdf.geometry)
    course_geom_ll = _ensure_polygon_or_multipolygon(dissolved)
    course_gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[course_geom_ll], crs=course_gdf.crs)

    # Determine projected CRS and reproject
    proj_crs = _estimate_local_crs(course_gdf)
    logging.info(f"Using projected CRS: {proj_crs}")
    course_proj = course_gdf.to_crs(proj_crs)
    holes_proj = holes_gdf.to_crs(proj_crs)

    course_geom = _ensure_polygon_or_multipolygon(course_proj.geometry.iloc[0])

    # Prepare holes & labels
    hole_records: List[Tuple[int, LineString]] = []
    for _, row in holes_proj.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        merged = _merge_lines(geom)
        # Determine hole id
        hole_id: int | None = None
        for key in hole_prop_candidates:
            if key in row and row[key] is not None:
                try:
                    hole_id = int(row[key])
                    break
                except Exception:
                    pass
        if hole_id is None:
            # Fallback: 1-based index in file order
            hole_id = len(hole_records) + 1
        hole_records.append((hole_id, merged))

    # Ensure we have 18 distinct holes
    unique_ids = sorted(set([hid for hid, _ in hole_records]))
    if len(unique_ids) != 18:
        logging.warning(
            f"Detected {len(unique_ids)} unique hole ids (expected 18). Proceeding anyway."
        )

    # Clip hole lines to boundary (optional but safer)
    clipped_holes: Dict[int, LineString] = {}
    for hid, geom in hole_records:
        inter = geom.intersection(course_geom)
        if inter.is_empty:
            logging.warning(
                f"Hole {hid}: line outside course boundary, keeping original geometry."
            )
            inter = geom
        clipped_holes[hid] = _merge_lines(inter) if not isinstance(inter, LineString) else inter

    # Densify to seed points
    logging.info("Densifying centerlines into seed points...")
    seeds_xy: List[Tuple[float, float]] = []
    seed_hole_idx: List[int] = []
    hole_to_seed_indices: Dict[int, List[int]] = {}

    for hid, line in clipped_holes.items():
        pts = _densify_line(line, step_m=step_m)
        if len(pts) > max_points_per_hole:
            # Subsample uniformly
            indices = np.linspace(0, len(pts) - 1, num=max_points_per_hole, dtype=int)
            pts = [pts[i] for i in indices]
        start_index = len(seeds_xy)
        for p in pts:
            seeds_xy.append((p.x, p.y))
            seed_hole_idx.append(hid)
        hole_to_seed_indices[hid] = list(range(start_index, len(seeds_xy)))

    if len(seeds_xy) < 2:
        raise ValueError("Not enough seed points to build voronoi diagram.")

    points = np.asarray(seeds_xy, dtype=float)

    # Build Voronoi polygons (prefer SciPy with guaranteed order)
    logging.info("Building Voronoi tessellation...")
    vor_polys = _build_voronoi_polygons(points, course_geom)

    # Map cells back to holes:
    # - SciPy path: vor_polys[i] corresponds to points[i]
    # - Shapely path: classify each cell by nearest seed (by centroid)
    logging.info("Mapping Voronoi cells to hole ids...")
    seed_geoms = [Point(x, y) for (x, y) in seeds_xy]

    cells_by_hole: Dict[int, List[Polygon]] = {hid: [] for hid in unique_ids}
    if _HAS_SCIPY and len(vor_polys) == len(points):
        for i, cell in enumerate(vor_polys):
            hid = seed_hole_idx[i]
            if cell.is_empty:
                continue
            # Clip to course polygon
            clipped = cell.intersection(course_geom)
            if not clipped.is_empty:
                if isinstance(clipped, (Polygon, MultiPolygon)):
                    if isinstance(clipped, Polygon):
                        cells_by_hole[hid].append(clipped)
                    else:
                        cells_by_hole[hid].extend(
                            [p for p in clipped.geoms if isinstance(p, Polygon)]
                        )
    else:
        # Fallback: classify each cell by nearest seed (using centroid)
        for cell in vor_polys:
            if cell.is_empty:
                continue
            cpt = cell.representative_point()
            # nearest seed
            dists = [cpt.distance(pt) for pt in seed_geoms]
            j = int(np.argmin(dists))
            hid = seed_hole_idx[j]
            clipped = cell.intersection(course_geom)
            if not clipped.is_empty:
                if isinstance(clipped, Polygon):
                    cells_by_hole[hid].append(clipped)
                elif isinstance(clipped, MultiPolygon):
                    cells_by_hole[hid].extend(
                        [p for p in clipped.geoms if isinstance(p, Polygon)]
                    )

    # Union cells by hole
    logging.info("Dissolving cells per hole...")
    hole_polys: Dict[int, Polygon] = {}
    for hid, polys in cells_by_hole.items():
        if not polys:
            continue
        merged = unary_union(polys)
        if isinstance(merged, Polygon):
            hole_polys[hid] = merged
        elif isinstance(merged, MultiPolygon):
            # Keep the largest piece
            hole_polys[hid] = max(merged.geoms, key=lambda p: p.area).buffer(0)
        else:
            # Unexpected type; try buffer(0) to fix
            hole_polys[hid] = merged.buffer(0)

    # Assign leftover area (if any) to nearest hole by centerline distance
    logging.info("Assigning leftover slivers...")
    assigned_union = unary_union(list(hole_polys.values())) if hole_polys else None
    if assigned_union:
        leftover = course_geom.difference(assigned_union)
        if not leftover.is_empty:
            pieces: List[Polygon] = []
            if isinstance(leftover, Polygon):
                pieces = [leftover]
            elif isinstance(leftover, MultiPolygon):
                pieces = [p for p in leftover.geoms]
            else:
                pieces = []

            # Build hole centerline geometries for nearest assignment
            hole_lines = {hid: geom for hid, geom in clipped_holes.items()}

            for piece in pieces:
                c = piece.representative_point()
                # find nearest hole centerline
                best_hole_id: int | None = None
                best_distance = float("inf")
                for hid, line in hole_lines.items():
                    d = c.distance(line)
                    if d < best_distance:
                        best_distance = d
                        best_hole_id = hid
                if best_hole_id is not None:
                    hole_polys[best_hole_id] = unary_union(
                        [hole_polys.get(best_hole_id), piece]
                    ).buffer(0)

    # Optional smoothing
    if smooth_m and smooth_m > 0:
        logging.info(f"Smoothing boundaries with ±{smooth_m} m buffer...")
        for hid in list(hole_polys.keys()):
            p = hole_polys[hid]
            p2 = p.buffer(smooth_m).buffer(-smooth_m)
            if p2.is_empty:
                continue
            if isinstance(p2, Polygon):
                hole_polys[hid] = p2
            elif isinstance(p2, MultiPolygon):
                # Keep largest
                hole_polys[hid] = max(p2.geoms, key=lambda q: q.area)

    # Prepare output GeoDataFrame
    logging.info("Preparing output...")
    out_records = []
    for hid in sorted(hole_polys.keys()):
        poly = hole_polys[hid].intersection(course_geom).buffer(0)
        if poly.is_empty:
            continue
        area_m2 = poly.area
        out_records.append({"hole": int(hid), "area_m2": float(area_m2), "geometry": poly})

    out_gdf = gpd.GeoDataFrame(out_records, crs=proj_crs)
    # Reproject back to original CRS if present
    target_crs = course_gdf.crs if course_gdf.crs else "EPSG:4326"
    try:
        out_gdf = out_gdf.to_crs(target_crs)
    except Exception:
        pass

    # Basic sanity check: do we have 18 features?
    if len(out_gdf) != 18:
        logging.warning(
            f"Output has {len(out_gdf)} hole polygons (expected 18). Check inputs/parameters."
        )

    out_gdf.to_file(output_path, driver="GeoJSON")
    logging.info(f"Wrote: {output_path}")


def _parse_args(argv: List[str] | None = None):
    parser = argparse.ArgumentParser(
        description="Split course polygon into 18 hole sections via Voronoi of centerlines."
    )
    parser.add_argument(
        "--boundary",
        required=True,
        help="Path to course boundary GeoJSON (Polygon/MultiPolygon).",
    )
    parser.add_argument(
        "--holes",
        required=True,
        help="Path to hole centerlines GeoJSON (18 LineString/MultiLineString features).",
    )
    parser.add_argument(
        "--out",
        required=False,
        help="Output filename or path. If omitted, a default name is used. The file will be saved under the generated directory.",
    )
    parser.add_argument(
        "--generated_dir",
        default="generated",
        help="Directory name under the boundary file's folder where outputs will be saved (default: generated).",
    )
    parser.add_argument(
        "--step",
        type=float,
        default=25.0,
        help="Densify step in meters along centerlines (default: 25).",
    )
    parser.add_argument(
        "--smooth",
        type=float,
        default=0.0,
        help="Optional boundary smoothing (meters), uses buffer(+/-).",
    )
    parser.add_argument(
        "--max_points_per_hole",
        type=int,
        default=250,
        help="Cap on seed points per hole to control tessellation cost.",
    )
    parser.add_argument(
        "--log",
        default="INFO",
        help="Logging level (DEBUG, INFO, WARNING).",
    )
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = _parse_args(argv)
    init_logging(level=str(args.log))

    # Resolve output path to always live under a "generated" directory next to the boundary file
    boundary_path = Path(args.boundary)
    generated_root = boundary_path.parent / args.generated_dir
    generated_root.mkdir(parents=True, exist_ok=True)

    if args.out:
        out_name = Path(args.out).name if Path(args.out).suffix else Path(args.out).name
    else:
        out_name = "holes_geofenced.geojson"
    output_path = str(generated_root / out_name)

    logging.info(f"Output will be written to: {output_path}")

    split_course_into_holes(
        course_polygon_path=args.boundary,
        hole_lines_path=args.holes,
        output_path=output_path,
        step_m=args.step,
        smooth_m=args.smooth,
        max_points_per_hole=args.max_points_per_hole,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
