"""
Course modeling utilities to build the traditional path and golfer trajectories.
"""

from __future__ import annotations

from typing import Dict, List

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.geometry import LineString, Point


def _nearest_point_idx(points: List[Point], target: Point) -> int:
    dists = [p.distance(target) for p in points]
    return int(np.argmin(dists))


def _to_points(gdf: gpd.GeoDataFrame) -> List[Point]:
    pts = []
    for g in gdf.geometry:
        if g.geom_type == "Point":
            pts.append(g)
        elif g.geom_type in ("Polygon", "MultiPolygon", "LineString", "MultiLineString"):
            pts.append(g.representative_point())
    return pts


def build_traditional_route(
    data: Dict[str, gpd.GeoDataFrame | shapely.geometry.base.BaseGeometry], strict_18: bool = True
) -> Dict[str, object]:
    """
    Build a 'traditional' 1..18 sequence and a continuous golfer route.
    Uses tees/greens where available; otherwise, representative points on holes.

    Returns:
      {
        "hole_sequence": [1,2,...,18],
        "hole_lines": {hole_no: LineString(tee->green)},
        "route": LineString(concatenated 18 holes),
        "tee_points": GeoDataFrame,
        "green_points": GeoDataFrame
      }
    """
    tees = data["tees"].copy()
    greens = data["greens"].copy()
    holes = data["holes"].copy()

    # Build hole numbers from 'ref' if available; else infer ordering by spatial sweep (west→east then north→south)
    if "ref" in holes.columns and holes["ref"].notna().any():
        # keep numeric parts
        def _num(x):
            try:
                return int(str(x).strip())
            except Exception:
                return None

        _ = [_num(x) for x in holes.get("ref", pd.Series([None] * len(holes)))]

    # Construct representative tee/green points per hole
    tee_pts = _to_points(tees)
    green_pts = _to_points(greens)

    # If no tees/greens, fallback to hole centroids as proxies (pair sequentially)
    hole_centers = (
        [geom.representative_point() for geom in holes.geometry] if len(holes) > 0 else []
    )

    hole_lines = {}
    sequence = list(range(1, 19)) if strict_18 else list(range(1, max(19, len(holes) + 1)))

    # naive pairing: for each hole number, take nearest tee and green based on clustering
    # If tees/greens are fewer than 18, fallback to centroid-based straight segments.
    for h in sequence:
        if len(tee_pts) > 0 and len(green_pts) > 0:
            # pick nearest tee to a sweeping anchor: use hole index as proxy
            anchor = (
                hole_centers[h - 1]
                if h - 1 < len(hole_centers)
                else tee_pts[min(h - 1, len(tee_pts) - 1)]
            )
            ti = _nearest_point_idx(tee_pts, anchor)
            gi = _nearest_point_idx(green_pts, anchor)
            line = LineString([tee_pts[ti], green_pts[gi]])
        elif len(hole_centers) >= 2:
            # consecutive centers
            a = hole_centers[h - 1]
            b = hole_centers[h % len(hole_centers)]
            line = LineString([a, b])
        else:
            # degenerate case: create a tiny segment at course centroid
            c = data["course_poly"].centroid
            line = LineString([c, Point(c.x + 1e-5, c.y + 1e-5)])
        hole_lines[h] = line

    # Concatenate
    coords = []
    for h in sequence:
        if h in hole_lines:
            if len(coords) > 0:
                # ensure continuity: append tee if not equal
                if coords[-1] != hole_lines[h].coords[0]:
                    coords.extend(list(hole_lines[h].coords))
                else:
                    coords.extend(list(hole_lines[h].coords)[1:])
            else:
                coords.extend(list(hole_lines[h].coords))
    route = LineString(coords)

    return {
        "hole_sequence": sequence,
        "hole_lines": hole_lines,
        "route": route,
        "tee_points": tees,
        "green_points": greens,
    }
