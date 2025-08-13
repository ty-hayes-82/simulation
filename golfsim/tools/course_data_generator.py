"""
Unified course data generation utilities.

This module provides a central class for generating all necessary course data
files required by the simulation system.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, List, Optional

from .node_generator import generate_lcm_course_nodes, ensure_course_nodes_exist
from .track_generator import generate_simple_tracks


class CourseDataGenerator:
    """Unified course data generation and validation."""
    
    def __init__(self, course_dir: str):
        self.course_dir = Path(course_dir)
        self.geojson_dir = self.course_dir / "geojson"
        self.generated_dir = self.geojson_dir / "generated"
        
    def ensure_all_required_files(self) -> Dict[str, bool]:
        """
        Ensure all required files exist, generating missing ones.
        
        Returns:
            Dict mapping file names to whether they exist/were generated successfully
        """
        results = {}
        
        # Core course files (should already exist)
        core_files = [
            "holes.geojson",
            "course_polygon.geojson", 
            "tees.geojson",
            "greens.geojson"
        ]
        
        for filename in core_files:
            file_path = self.geojson_dir / filename
            results[filename] = file_path.exists()
        
        # Generated files (create if missing)
        results["lcm_course_nodes.geojson"] = self._ensure_course_nodes()
        results["holes_geofenced.geojson"] = self._ensure_holes_geofenced()
        
        return results
    
    def _ensure_course_nodes(self) -> bool:
        """Ensure course nodes exist."""
        return ensure_course_nodes_exist(str(self.course_dir))
    
    def _ensure_holes_geofenced(self) -> bool:
        """Ensure geofenced holes exist."""
        output_path = self.generated_dir / "holes_geofenced.geojson"
        
        if output_path.exists():
            return True
            
        # Generate simple geofenced holes
        holes_path = self.geojson_dir / "holes.geojson"
        if not holes_path.exists():
            return False
            
        try:
            return self._generate_simple_holes_geofenced(holes_path, output_path)
        except Exception:
            return False
    
    def _generate_simple_holes_geofenced(
        self, 
        holes_path: Path, 
        output_path: Path
    ) -> bool:
        """Generate simple geofenced holes from holes.geojson."""
        with open(holes_path, 'r', encoding='utf-8') as f:
            holes_data = json.load(f)
        
        features = []
        
        for feature in holes_data.get('features', []):
            props = feature.get('properties', {})
            hole_num = props.get('hole') or props.get('ref') or props.get('number')
            
            if hole_num is not None:
                geom = feature.get('geometry', {})
                
                # For LineString holes, create a simple buffer polygon
                if geom.get('type') == 'LineString':
                    coords = geom.get('coordinates', [])
                    if len(coords) >= 2:
                        # Simple approach: create a rectangular polygon around the line
                        lons = [c[0] for c in coords]
                        lats = [c[1] for c in coords]
                        
                        min_lon, max_lon = min(lons), max(lons)
                        min_lat, max_lat = min(lats), max(lats)
                        
                        # Add small buffer
                        buffer = 0.001  # roughly 100m
                        min_lon -= buffer
                        max_lon += buffer
                        min_lat -= buffer
                        max_lat += buffer
                        
                        # Create rectangular polygon
                        polygon_coords = [[
                            [min_lon, min_lat],
                            [max_lon, min_lat],
                            [max_lon, max_lat],
                            [min_lon, max_lat],
                            [min_lon, min_lat]
                        ]]
                        
                        polygon_feature = {
                            "type": "Feature",
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": polygon_coords
                            },
                            "properties": {
                                "hole": int(hole_num)
                            }
                        }
                        features.append(polygon_feature)
        
        holes_geofenced = {
            "type": "FeatureCollection", 
            "features": features
        }
        
        os.makedirs(output_path.parent, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(holes_geofenced, f, indent=2)
        
        return True
    
    def generate_tracks(self) -> Dict[str, List[Dict]]:
        """Generate golfer and beverage cart tracks."""
        return generate_simple_tracks(str(self.course_dir))
    
    def validate_course_data(self) -> Dict[str, any]:
        """
        Validate all course data and return status report.
        
        Returns:
            Dict with validation results and statistics
        """
        results = self.ensure_all_required_files()
        
        # Count holes if available
        holes_count = 0
        holes_path = self.geojson_dir / "holes.geojson"
        if holes_path.exists():
            try:
                with open(holes_path, 'r', encoding='utf-8') as f:
                    holes_data = json.load(f)
                holes_count = len(holes_data.get('features', []))
            except Exception:
                pass
        
        # Count nodes if available
        nodes_count = 0
        nodes_path = self.generated_dir / "lcm_course_nodes.geojson"
        if nodes_path.exists():
            try:
                with open(nodes_path, 'r', encoding='utf-8') as f:
                    nodes_data = json.load(f)
                nodes_count = len(nodes_data.get('features', []))
            except Exception:
                pass
        
        return {
            "course_dir": str(self.course_dir),
            "files_status": results,
            "all_files_ready": all(results.values()),
            "holes_count": holes_count,
            "nodes_count": nodes_count,
            "required_files": list(results.keys()),
            "missing_files": [k for k, v in results.items() if not v]
        }
