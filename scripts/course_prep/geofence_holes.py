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
import json
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
from shapely.strtree import STRtree

from golfsim.logging import init_logging
from golfsim.config.loaders import load_simulation_config

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
            logging.info(f"Estimated UTM CRS: {crs.to_string()}")
            return crs.to_string()
    except Exception:
        pass
    # Fallback: Web Mercator (not ideal, but better than WGS84 for distances)
    logging.warning("Could not estimate UTM CRS, falling back to EPSG:3857")
    return "EPSG:3857"


def _dedupe_xy(points: List[Tuple[float, float]], tol: float = 1e-6) -> List[Tuple[float, float]]:
    """Remove duplicate points within tolerance to avoid Voronoi issues."""
    seen = set()
    out = []
    for x, y in points:
        key = (round(x / tol), round(y / tol))
        if key in seen:
            continue
        seen.add(key)
        out.append((x, y))
    return out


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


def _build_voronoi_polygons(points: np.ndarray, clip_poly: Polygon) -> Tuple[List[Polygon], bool]:
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
        try:
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
            logging.info(f"Built {len(polygons)} Voronoi cells using SciPy")
            return polygons, True
        except Exception as e:
            logging.warning(f"SciPy Voronoi failed: {e}, falling back to Shapely")
    
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
    logging.info(f"Built {len(cells)} Voronoi cells using Shapely fallback")
    return cells, False


def _resolve_overlaps_pairwise(
    hole_polys: Dict[int, Polygon],
    hole_lines: Dict[int, LineString],
    max_iters: int = 3,
    area_tolerance: float = 1.0,
) -> Dict[int, Polygon]:
    """Resolve overlaps between hole polygons by assigning intersecting areas to the closer hole line.

    - Iterates a few times to catch cascading effects
    - Stable tie-break by lower hole id
    """
    ids = sorted(hole_polys.keys())
    for _ in range(max_iters):
        changed = False
        for i_idx in range(len(ids)):
            i = ids[i_idx]
            pi = hole_polys.get(i)
            if pi is None or pi.is_empty:
                continue
            for j_idx in range(i_idx + 1, len(ids)):
                j = ids[j_idx]
                pj = hole_polys.get(j)
                if pj is None or pj.is_empty:
                    continue
                inter = pi.intersection(pj)
                if inter.is_empty or inter.area <= area_tolerance:
                    continue
                # Decide winner by distance to centerlines
                c = inter.representative_point()
                di = c.distance(hole_lines.get(i, pi))
                dj = c.distance(hole_lines.get(j, pj))
                if di < dj or (abs(di - dj) <= 1e-9 and i < j):
                    # assign intersection to i; remove from j
                    hole_polys[j] = pj.difference(inter).buffer(0)
                else:
                    # assign to j; remove from i
                    hole_polys[i] = pi.difference(inter).buffer(0)
                # refresh local refs
                pi = hole_polys.get(i)
                pj = hole_polys.get(j)
                changed = True
        if not changed:
            break
    return hole_polys


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
    debug_export_dir: str | None = None,
    ensure_min_width_m: float = 12.0,
    enforce_disjoint: bool = False,
) -> None:
    """Main pipeline to split the course into 18 sections with improved robustness."""
    import time
    start_time = time.time()
    
    logging.info("=== Starting Course Geofencing ===")
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
    course_area = course_geom.area
    logging.info(f"Course area: {course_area:,.1f} m²")

    # Prepare holes & labels with improved validation
    logging.info("Processing hole centerlines...")
    hole_records: List[Tuple[int, LineString]] = []
    for _, row in holes_proj.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        merged = _merge_lines(geom)
        # Determine hole id using candidate properties
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
            logging.warning(f"No valid hole ID found for feature, using fallback: {hole_id}")
        hole_records.append((hole_id, merged))

    # Ensure we have 18 distinct holes
    unique_ids = sorted(set([hid for hid, _ in hole_records]))
    logging.info(f"Found {len(unique_ids)} unique hole IDs: {unique_ids}")
    if len(unique_ids) != 18:
        logging.warning(
            f"Detected {len(unique_ids)} unique hole ids (expected 18). Proceeding with deterministic processing."
        )
    
    # Sort hole records by hole ID for deterministic processing
    hole_records.sort(key=lambda x: x[0])

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

    # Densify to seed points with deduplication
    logging.info("Densifying centerlines into seed points...")
    seeds_xy: List[Tuple[float, float]] = []
    seed_hole_idx: List[int] = []
    hole_to_seed_indices: Dict[int, List[int]] = {}
    
    total_seeds_before_dedup = 0
    for hid, line in clipped_holes.items():
        pts = _densify_line(line, step_m=step_m)
        if len(pts) > max_points_per_hole:
            # Subsample uniformly
            indices = np.linspace(0, len(pts) - 1, num=max_points_per_hole, dtype=int)
            pts = [pts[i] for i in indices]
        
        # Convert to coordinate tuples and deduplicate
        hole_coords = [(p.x, p.y) for p in pts]
        total_seeds_before_dedup += len(hole_coords)
        hole_coords_deduped = _dedupe_xy(hole_coords, tol=1e-6)
        
        start_index = len(seeds_xy)
        for coord in hole_coords_deduped:
            seeds_xy.append(coord)
            seed_hole_idx.append(hid)
        hole_to_seed_indices[hid] = list(range(start_index, len(seeds_xy)))
        
        logging.debug(f"Hole {hid}: {len(hole_coords)} -> {len(hole_coords_deduped)} seeds after dedup")

    logging.info(f"Generated {len(seeds_xy)} seeds from {total_seeds_before_dedup} raw points ({len(seeds_xy)/total_seeds_before_dedup*100:.1f}% retained)")
    
    if len(seeds_xy) < 2:
        raise ValueError("Not enough seed points to build voronoi diagram.")

    points = np.asarray(seeds_xy, dtype=float)

    # Build Voronoi polygons (prefer SciPy with guaranteed order)
    logging.info("Building Voronoi tessellation...")
    vor_polys, used_scipy = _build_voronoi_polygons(points, course_geom)

    # Map cells back to holes using spatial index for efficiency
    logging.info("Mapping Voronoi cells to hole ids using spatial index...")
    seed_geoms = [Point(x, y) for (x, y) in seeds_xy]
    
    # Build spatial index for fast nearest-neighbor queries
    seed_tree = STRtree(seed_geoms)
    # Map geometry identity via stable WKB bytes to hole id (id() is unsafe)
    seed_wkb_to_hole: Dict[bytes, int] = {p.wkb: hid for p, hid in zip(seed_geoms, seed_hole_idx)}

    cells_by_hole: Dict[int, List[Polygon]] = {hid: [] for hid in unique_ids}
    
    # Classify cells to holes
    if used_scipy and len(vor_polys) == len(points):
        # Direct mapping: vor_polys[i] corresponds to points[i]
        for idx, cell in enumerate(vor_polys):
            if cell.is_empty:
                continue
            hid = seed_hole_idx[idx]
            clipped = cell.intersection(course_geom)
            if not clipped.is_empty:
                if isinstance(clipped, Polygon):
                    cells_by_hole[hid].append(clipped)
                elif isinstance(clipped, MultiPolygon):
                    cells_by_hole[hid].extend([p for p in clipped.geoms if isinstance(p, Polygon)])
                elif isinstance(clipped, GeometryCollection):
                    cells_by_hole[hid].extend([g for g in clipped.geoms if isinstance(g, Polygon)])
    else:
        # Fallback: spatial nearest to seeds
        for cell in vor_polys:
            if cell.is_empty:
                continue
            cpt = cell.representative_point()
            nearest_seed = seed_tree.nearest(cpt)
            hid: int | None = None
            # Shapely STRtree.nearest may return an index (np.int64) or a geometry
            if isinstance(nearest_seed, (int, np.integer)):
                hid = seed_hole_idx[int(nearest_seed)]
            else:
                hid = seed_wkb_to_hole.get(nearest_seed.wkb)
            if hid is None:
                # Fallback: compute explicit nearest by distance (rare)
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
                elif isinstance(clipped, GeometryCollection):
                    cells_by_hole[hid].extend(
                        [g for g in clipped.geoms if isinstance(g, Polygon)]
                    )
    
    # Log cell assignment summary
    for hid in sorted(unique_ids):
        cell_count = len(cells_by_hole[hid])
        logging.debug(f"Hole {hid}: {cell_count} Voronoi cells assigned")

    # Union cells by hole and enforce invariants
    logging.info("Dissolving cells per hole...")
    hole_polys: Dict[int, Polygon] = {}
    for hid, polys in cells_by_hole.items():
        if not polys:
            logging.warning(f"Hole {hid}: No cells assigned")
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

    # Enforce full coverage: assign ALL leftover area (no 10% cap)
    logging.info("Enforcing full coverage...")
    assigned_union = unary_union(list(hole_polys.values())) if hole_polys else None
    if assigned_union:
        leftover = course_geom.difference(assigned_union)
        if not leftover.is_empty:
            leftover_area = float(leftover.area)
            coverage_pct = (course_area - leftover_area) / course_area * 100
            logging.info(f"Initial coverage: {coverage_pct:.2f}%, leftover area: {leftover_area:,.1f} m²")
            
            # Always assign leftover area to nearest holes
            pieces: List[Polygon] = []
            if isinstance(leftover, Polygon):
                pieces = [leftover]
            elif isinstance(leftover, MultiPolygon):
                pieces = [p for p in leftover.geoms]
            else:
                pieces = []

            # Build spatial index of hole polygons for fast nearest assignment
            hole_ids_sorted = sorted(hole_polys.keys())
            hole_geoms = [hole_polys[hid] for hid in hole_ids_sorted]
            hole_wkb_to_id = {geom.wkb: hid for hid, geom in zip(hole_ids_sorted, hole_geoms)}
            
            if hole_geoms:
                hole_tree = STRtree(hole_geoms)
                
                for piece in pieces:
                    c = piece.representative_point()
                    nearest_hole = hole_tree.nearest(c)
                    if isinstance(nearest_hole, (int, np.integer)):
                        best_hole_id = hole_ids_sorted[int(nearest_hole)]
                    else:
                        best_hole_id = hole_wkb_to_id.get(nearest_hole.wkb)
                    if best_hole_id is None:
                        # Fallback by explicit distance to all hole polys
                        dists = [c.distance(g) for g in hole_geoms]
                        best_idx = int(np.argmin(dists))
                        best_hole_id = hole_ids_sorted[best_idx]
                    
                    # Union the piece with the nearest hole
                    hole_polys[best_hole_id] = unary_union(
                        [hole_polys[best_hole_id], piece]
                    ).buffer(0)
                
                logging.info(f"Assigned {len(pieces)} leftover pieces to nearest holes")
        else:
            logging.info("Full coverage achieved - no leftover area")

    # Ensure every hole has at least a minimal corridor polygon
    logging.info("Ensuring minimum corridor for holes with no area...")
    for hid in unique_ids:
        poly = hole_polys.get(hid)
        if poly is None or poly.is_empty or poly.area < 1.0:
            line = clipped_holes.get(hid)
            if line is None or line.is_empty:
                logging.warning(f"Hole {hid}: Missing line for fallback corridor")
                continue
            corridor = line.buffer(max(ensure_min_width_m, 1.0) / 2.0).intersection(course_geom)
            if corridor.is_empty:
                logging.warning(f"Hole {hid}: Corridor intersection empty")
                continue
            hole_polys[hid] = unary_union([hole_polys.get(hid), corridor]).buffer(0)

    # Assess area balance and decide if we should enforce disjointness automatically
    areas_list = [poly.area for poly in hole_polys.values() if poly and not poly.is_empty]
    expected_area = course_area / max(len(unique_ids), 1)
    imbalance = False
    if areas_list:
        max_area = max(areas_list)
        min_area = min(areas_list)
        if (max_area > expected_area * 3.0) or (min_area < expected_area * 0.15) or (len(hole_polys) != len(unique_ids)):
            imbalance = True
            logging.warning(
                f"Area imbalance detected (max={max_area:,.1f}, min={min_area:,.1f}, expected≈{expected_area:,.1f}); auto-enforcing disjoint."
            )
    need_disjoint = enforce_disjoint or imbalance

    # Enforce disjoint property: remove overlaps deterministically
    if need_disjoint:
        logging.info("Enforcing disjoint property (pairwise resolution)...")
        # First do a pairwise resolution pass to reduce overlaps intelligently
        hole_polys = _resolve_overlaps_pairwise(hole_polys, clipped_holes)
        # Then do a deterministic sweep to eliminate any tiny residual overlaps while preserving coverage
        sorted_hole_ids = sorted(hole_polys.keys())
        union_so_far = None
        for hid in sorted_hole_ids:
            geom = hole_polys[hid]
            if union_so_far is not None:
                remainder = geom.difference(union_so_far)
                if remainder.is_empty:
                    logging.warning(f"Hole {hid}: Became empty after overlap removal")
                    hole_polys[hid] = GeometryCollection()
                    continue
                hole_polys[hid] = remainder
            union_so_far = hole_polys[hid] if union_so_far is None else unary_union([union_so_far, hole_polys[hid]])
    
    # Recover holes that became empty by carving non-overlapping corridors
    empty_after_disjoint: List[int] = []
    if need_disjoint:
        empty_after_disjoint = [hid for hid in sorted_hole_ids if (hid not in hole_polys or hole_polys[hid].is_empty)]
    if empty_after_disjoint:
        logging.warning(f"Holes became empty after disjoint: {empty_after_disjoint}")
        for hid in empty_after_disjoint:
            line = clipped_holes.get(hid)
            if line is None or line.is_empty:
                continue
            width = max(ensure_min_width_m, 6.0)
            # Try a few widths to obtain a non-empty non-overlapping corridor
            corridor = None
            for factor in (1.0, 1.5, 2.0):
                candidate = line.buffer((width * factor) / 2.0).difference(union_so_far).intersection(course_geom)
                if not candidate.is_empty:
                    corridor = candidate
                    break
            if corridor is None or corridor.is_empty:
                continue
            hole_polys[hid] = corridor.buffer(0)
            union_so_far = unary_union([union_so_far, hole_polys[hid]]) if union_so_far is not None else hole_polys[hid]

    # Final disjoint pass after recovery to ensure no overlaps
    if need_disjoint:
        logging.info("Final disjointness enforcement after recovery...")
        union_so_far = None
        for hid in sorted(hole_polys.keys()):
            geom = hole_polys[hid]
            if geom.is_empty:
                continue
            if union_so_far is not None:
                geom = geom.difference(union_so_far)
                if geom.is_empty:
                    hole_polys[hid] = GeometryCollection()
                    continue
            hole_polys[hid] = geom
            union_so_far = geom if union_so_far is None else unary_union([union_so_far, geom])

    # Validate coverage and disjointness
    final_union = unary_union(list(hole_polys.values()))
    final_coverage = final_union.area / course_area * 100
    logging.info(f"Final coverage: {final_coverage:.2f}%")
    
    # Check for overlaps
    total_hole_area = sum(poly.area for poly in hole_polys.values())
    overlap_area = total_hole_area - final_union.area
    if overlap_area > 1.0:  # tolerance for floating point
        logging.warning(f"Overlaps detected: {overlap_area:,.1f} m²")
    else:
        logging.info("No significant overlaps detected")

    # Area validation check (post-processing)
    final_areas = {hid: poly.area for hid, poly in hole_polys.items() if poly and not poly.is_empty}
    if len(final_areas) != len(unique_ids):
        logging.warning(f"Output has {len(final_areas)} holes after processing (expected {len(unique_ids)}).")
    if final_areas:
        max_final = max(final_areas.values())
        min_final = min(final_areas.values())
        expected_final = course_area / max(len(unique_ids), 1)
        if (max_final > expected_final * 3.0) or (min_final < expected_final * 0.10):
            logging.warning(
                f"Post-validation area imbalance: max={max_final:,.1f}, min={min_final:,.1f}, expected≈{expected_final:,.1f}"
            )

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

        # Re-enforce disjointness after smoothing (deterministically)
        logging.info("Re-enforcing disjointness after smoothing...")
        union_so_far = None
        for hid in sorted(hole_polys.keys()):
            geom = hole_polys[hid]
            if union_so_far is not None:
                geom = geom.difference(union_so_far)
                if geom.is_empty:
                    continue
                hole_polys[hid] = geom
            union_so_far = geom if union_so_far is None else unary_union([union_so_far, geom])

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

    # Optional debug exports
    if debug_export_dir:
        try:
            dbg_dir = Path(debug_export_dir)
            dbg_dir.mkdir(parents=True, exist_ok=True)

            # Seeds
            try:
                seeds_fc = {
                    "type": "FeatureCollection",
                    "features": [
                        {"type": "Feature", "properties": {"hole": int(h)}, "geometry": {"type": "Point", "coordinates": [float(x), float(y)]}}
                        for (x, y), h in zip(seeds_xy, seed_hole_idx)
                    ],
                }
                (dbg_dir / "seeds.geojson").write_text(json.dumps(seeds_fc))
            except Exception:
                pass

            # Raw Voronoi cells
            try:
                cells_fc = {
                    "type": "FeatureCollection",
                    "features": [
                        {"type": "Feature", "properties": {}, "geometry": json.loads(gpd.GeoSeries([p], crs=proj_crs).to_crs(4326).to_json())["features"][0]["geometry"]}
                        for p in vor_polys if not p.is_empty
                    ],
                }
                (dbg_dir / "raw_voronoi_cells.geojson").write_text(json.dumps(cells_fc))
            except Exception:
                pass

            # Cells assigned (pre-dissolve)
            try:
                assigned_features = []
                for hid, polys in cells_by_hole.items():
                    for p in polys:
                        assigned_features.append({
                            "type": "Feature",
                            "properties": {"hole": int(hid)},
                            "geometry": json.loads(gpd.GeoSeries([p], crs=proj_crs).to_crs(4326).to_json())["features"][0]["geometry"],
                        })
                assigned_fc = {"type": "FeatureCollection", "features": assigned_features}
                (dbg_dir / "cells_assigned.geojson").write_text(json.dumps(assigned_fc))
            except Exception:
                pass

            # Holes dissolved pre-smooth
            try:
                pre_smooth_features = []
                for hid, p in hole_polys.items():
                    pre_smooth_features.append({
                        "type": "Feature",
                        "properties": {"hole": int(hid)},
                        "geometry": json.loads(gpd.GeoSeries([p], crs=proj_crs).to_crs(4326).to_json())["features"][0]["geometry"],
                    })
                (dbg_dir / "holes_dissolved_pre_smooth.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": pre_smooth_features}))
            except Exception:
                pass
        except Exception as e:
            logging.warning(f"Failed to write debug exports: {e}")

    out_gdf.to_file(output_path, driver="GeoJSON")
    logging.info(f"Wrote: {output_path}")


def _get_ref_int(val) -> int:
    try:
        return int(val)
    except Exception:
        # push invalid refs to the end
        return 10 ** 9


def _flatten_holes_path(
    holes_gdf: gpd.GeoDataFrame,
    close_loop: bool,
    hole_prop_candidates: Tuple[str, ...] = (
        "ref",
        "hole",
        "Hole",
        "HOLE",
        "number",
        "Number",
        "id",
        "Id",
        "REF",
        "Ref",
    ),
) -> List[Tuple[float, float]]:
    """Return ordered (lon, lat) path across holes 1..18 sorted by a hole id property.

    Tries multiple property names; falls back to file order if none found.
    If a feature is MultiLineString, the longest LineString part is used.
    Consecutive duplicate coordinates are removed. Optionally closes loop.
    """
    if holes_gdf.empty:
        raise ValueError("Holes GeoDataFrame is empty")

    # Choose best available hole id property; fallback to file order
    chosen_prop: str | None = None
    for prop in hole_prop_candidates:
        if prop in holes_gdf.columns:
            chosen_prop = prop
            break

    holes_sorted = holes_gdf.copy()
    if chosen_prop is not None:
        holes_sorted["_ref_int"] = holes_sorted[chosen_prop].apply(_get_ref_int)
        holes_sorted.sort_values("_ref_int", inplace=True)
    else:
        holes_sorted = holes_sorted.reset_index(drop=True)

    coords: List[Tuple[float, float]] = []
    for _, row in holes_sorted.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        if geom.geom_type == "LineString":
            seq = list(geom.coords)  # type: ignore[attr-defined]
        else:
            try:
                longest = max(geom.geoms, key=lambda g: g.length)
                seq = list(longest.coords)  # type: ignore[attr-defined]
            except Exception:
                continue
        for (lon, lat) in seq:
            coords.append((float(lon), float(lat)))

    # Deduplicate consecutive identical points
    deduped: List[Tuple[float, float]] = []
    last: Tuple[float, float] | None = None
    for pt in coords:
        if last is None or (pt[0] != last[0] or pt[1] != last[1]):
            deduped.append(pt)
            last = pt

    if close_loop and len(deduped) > 1:
        deduped.append(deduped[0])

    if len(deduped) < 2:
        raise ValueError("Not enough coordinates to form a path")

    return deduped


def _haversine_meters(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    import math as _math
    phi1 = _math.radians(lat1)
    phi2 = _math.radians(lat2)
    dphi = _math.radians(lat2 - lat1)
    dlambda = _math.radians(lon2 - lon1)
    a = _math.sin(dphi / 2) ** 2 + _math.cos(phi1) * _math.cos(phi2) * _math.sin(dlambda / 2) ** 2
    c = 2 * _math.atan2((_math.sqrt(a)), _math.sqrt(1 - a))
    return 6371000.0 * c


def _resample_path_uniform(coords: List[Tuple[float, float]], num_points: int) -> List[Tuple[float, float]]:
    if num_points <= 0:
        raise ValueError("num_points must be positive")
    if len(coords) < 2:
        return list(coords)

    # cumulative distances
    cum: List[float] = [0.0]
    total = 0.0
    for i in range(1, len(coords)):
        (lon1, lat1) = coords[i - 1]
        (lon2, lat2) = coords[i]
        d = _haversine_meters(lon1, lat1, lon2, lat2)
        total += d
        cum.append(total)

    if total <= 0:
        return [coords[0]] * num_points

    targets = [i * (total / max(num_points - 1, 1)) for i in range(num_points)]

    def _lerp(p1: Tuple[float, float], p2: Tuple[float, float], frac: float) -> Tuple[float, float]:
        return (p1[0] + frac * (p2[0] - p1[0]), p1[1] + frac * (p2[1] - p1[1]))

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
        resampled.append(_lerp(coords[j], coords[j + 1], frac))

    return resampled


def generate_holes_connected(geojson_dir: Path, output_path: Path | None = None) -> Path:
    """Generate a clubhouse-anchored continuous path across holes and minute nodes.

    - Reads holes.geojson under geojson_dir
    - Reads simulation_config.json under course_dir to get clubhouse and golfer minutes
    - Builds a continuous path: clubhouse -> hole 1..18 path -> clubhouse
    - Resamples into exactly N points where N == golfer_18_holes_minutes
    - Writes FeatureCollection to output_path (or geojson/generated/holes_connected.geojson)
    Returns the written output path.
    """
    if not isinstance(geojson_dir, Path):
        geojson_dir = Path(str(geojson_dir))

    course_dir = geojson_dir.parent

    # Load config for clubhouse and minutes
    cfg = load_simulation_config(course_dir)
    clubhouse_lon, clubhouse_lat = cfg.clubhouse  # loaders returns (lon, lat)
    minutes = int(cfg.golfer_18_holes_minutes)
    minutes = max(1, minutes)

    holes_path = geojson_dir / "holes.geojson"
    if not holes_path.exists():
        raise FileNotFoundError(f"Missing holes.geojson at {holes_path}")

    holes_gdf = gpd.read_file(holes_path).to_crs(4326)

    # Build ordered path across holes and anchor at clubhouse (start and end)
    ordered = _flatten_holes_path(holes_gdf, close_loop=False)
    path_coords: List[Tuple[float, float]] = []
    # start at clubhouse
    path_coords.append((float(clubhouse_lon), float(clubhouse_lat)))
    path_coords.extend(ordered)
    # end back at clubhouse
    path_coords.append((float(clubhouse_lon), float(clubhouse_lat)))

    # Resample into exactly `minutes` points (one per minute)
    sampled = _resample_path_uniform(path_coords, minutes)

    # Compose single FeatureCollection with line + points
    features = []
    features.append(
        {
            "type": "Feature",
            "properties": {"name": "holes_connected_path"},
            "geometry": {"type": "LineString", "coordinates": [[x, y] for (x, y) in path_coords]},
        }
    )
    for idx, (x, y) in enumerate(sampled):
        features.append(
            {
                "type": "Feature",
                "properties": {"idx": int(idx)},
                "geometry": {"type": "Point", "coordinates": [x, y]},
            }
        )

    fc = {"type": "FeatureCollection", "features": features}

    if output_path is None:
        gen_dir = geojson_dir / "generated"
        gen_dir.mkdir(parents=True, exist_ok=True)
        output_path = gen_dir / "holes_connected.geojson"

    output_path = Path(output_path)
    output_path.write_text(json.dumps(fc, indent=2))
    logging.info(f"Wrote: {output_path}")
    return output_path


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
        "--debug_dir",
        type=str,
        default=None,
        help="Optional directory to write debug artifacts (seeds, cells, dissolved).",
    )
    parser.add_argument(
        "--enforce_disjoint",
        action="store_true",
        help="If set, enforce disjoint hole polygons via overlap resolution.",
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
        debug_export_dir=args.debug_dir,
        enforce_disjoint=bool(args.enforce_disjoint),
    )

    # Also generate a connected path + minute nodes alongside the geofenced output
    try:
        geojson_dir = boundary_path.parent
        generate_holes_connected(geojson_dir)
    except Exception as e:
        logging.warning(f"Failed to generate holes_connected.geojson automatically: {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
