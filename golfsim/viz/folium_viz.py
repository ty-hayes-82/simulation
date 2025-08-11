"""
Folium visualization helpers for course, golfer route, and runner paths (static tracks for demo).
"""

from __future__ import annotations

import folium
from shapely.geometry import LineString, mapping


def map_course(course_poly, hole_lines: dict, route: LineString):
    c = course_poly.centroid
    m = folium.Map(location=[c.y, c.x], zoom_start=16, control_scale=True)
    # course polygon
    folium.GeoJson(mapping(course_poly), name="course").add_to(m)
    # holes
    for h, line in hole_lines.items():
        folium.PolyLine([(p[1], p[0]) for p in line.coords], tooltip=f"Hole {h}", weight=3).add_to(
            m
        )
    # full route
    folium.PolyLine(
        [(p[1], p[0]) for p in route.coords], tooltip="Golfer Route", weight=2, opacity=0.5
    ).add_to(m)
    folium.LayerControl().add_to(m)
    return m
