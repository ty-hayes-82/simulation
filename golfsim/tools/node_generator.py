"""
Course node generation utilities.

This module provides functions to generate course nodes for simulation,
including basic node generation and LCM-based optimal node generation.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Tuple


def generate_simple_course_nodes(
    holes_geojson_path: str, 
    output_path: str, 
    points_per_hole: int = 10
) -> int:
    """
    Generate simple course nodes from holes.geojson.
    
    Args:
        holes_geojson_path: Path to holes.geojson file
        output_path: Output path for lcm_course_nodes.geojson
        points_per_hole: Number of points to generate per hole
        
    Returns:
        Number of nodes generated
    """
    with open(holes_geojson_path, 'r', encoding='utf-8') as f:
        holes_data = json.load(f)
    
    # Extract hole features and sort by hole number
    holes = []
    for feature in holes_data.get('features', []):
        props = feature.get('properties', {})
        hole_num = props.get('hole') or props.get('ref') or props.get('number')
        
        if hole_num is not None:
            try:
                hole_num = int(hole_num)
                holes.append((hole_num, feature))
            except (ValueError, TypeError):
                pass
    
    # Sort holes by number
    holes.sort(key=lambda x: x[0])
    
    # Generate sequential nodes along the course
    features = []
    node_id = 1
    
    for hole_num, hole_feature in holes:
        geom = hole_feature.get('geometry', {})
        if geom.get('type') == 'LineString':
            coords = geom.get('coordinates', [])
            if len(coords) >= 2:
                # Generate points along this hole
                total_coords = len(coords)
                step = max(1, total_coords // points_per_hole)
                
                for i in range(0, total_coords, step):
                    if i < len(coords):
                        lon, lat = coords[i][:2]
                        
                        feature = {
                            "type": "Feature",
                            "geometry": {
                                "type": "Point",
                                "coordinates": [lon, lat]
                            },
                            "properties": {
                                "node_id": node_id,
                                "sequence_position": float(node_id),
                                "hole": hole_num
                            }
                        }
                        features.append(feature)
                        node_id += 1
    
    # Create the GeoJSON
    course_nodes = {
        "type": "FeatureCollection",
        "features": features
    }
    
    # Save to file
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(course_nodes, f, indent=2)
    
    return len(features)


def generate_lcm_course_nodes(
    course_dir: str,
    output_path: str = None
) -> int:
    """
    Generate LCM-optimized course nodes using the sophisticated algorithm.
    
    Args:
        course_dir: Course directory path
        output_path: Optional output path (defaults to generated/lcm_course_nodes.geojson)
        
    Returns:
        Number of nodes generated
    """
    # Import the LCM generator script as a module
    import runpy
    
    # Use the sophisticated LCM generator from the virtual environment
    lcm_script_path = Path(".venv/src/golf-delivery-sim/scripts/sim/generate_lcm_course_nodes.py")
    
    if lcm_script_path.exists():
        # Run the LCM generator
        gen_module = runpy.run_path(str(lcm_script_path))
        
        # The script generates the file automatically, just return success
        generated_path = Path(course_dir) / "geojson" / "generated" / "lcm_course_nodes.geojson"
        if generated_path.exists():
            with open(generated_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return len(data.get('features', []))
    
    # Fallback to simple generation if LCM script not available
    holes_path = Path(course_dir) / "geojson" / "holes.geojson"
    if not output_path:
        output_path = Path(course_dir) / "geojson" / "generated" / "lcm_course_nodes.geojson"
    
    return generate_simple_course_nodes(str(holes_path), str(output_path))


def ensure_course_nodes_exist(course_dir: str) -> bool:
    """
    Ensure that course nodes exist, generating them if necessary.
    
    Args:
        course_dir: Course directory path
        
    Returns:
        True if nodes exist or were successfully generated
    """
    nodes_path = Path(course_dir) / "geojson" / "generated" / "lcm_course_nodes.geojson"
    
    if nodes_path.exists():
        return True
    
    try:
        count = generate_lcm_course_nodes(course_dir)
        return count > 0
    except Exception:
        return False
