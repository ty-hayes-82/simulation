#!/usr/bin/env python3
"""
Script to fix GeoJSON validation errors:
1. Remove deprecated 'crs' member
2. Fix polygon winding order to follow right-hand rule (counterclockwise for exterior rings)
"""

import json
import sys
from typing import List, Tuple


def calculate_polygon_area(coordinates: List[List[float]]) -> float:
    """
    Calculate the signed area of a polygon using the shoelace formula.
    For geographic coordinates (longitude, latitude):
    - Positive area indicates clockwise winding
    - Negative area indicates counterclockwise winding
    """
    if len(coordinates) < 3:
        return 0.0
    
    area = 0.0
    n = len(coordinates)
    
    for i in range(n):
        j = (i + 1) % n
        # coordinates are [longitude, latitude]
        area += coordinates[i][0] * coordinates[j][1]
        area -= coordinates[j][0] * coordinates[i][1]
    
    return area / 2.0


def is_clockwise(coordinates: List[List[float]]) -> bool:
    """
    Check if a polygon ring is wound clockwise.
    For geographic coordinates, positive area = clockwise.
    """
    return calculate_polygon_area(coordinates) > 0


def fix_polygon_winding(coordinates: List[List[List[float]]]) -> List[List[List[float]]]:
    """
    Fix polygon winding order to follow the right-hand rule for GeoJSON.
    According to RFC 7946:
    - Exterior rings MUST be counterclockwise (negative area)
    - Interior rings (holes) MUST be clockwise (positive area)
    """
    fixed_coordinates = []
    
    for ring_index, ring in enumerate(coordinates):
        if len(ring) < 4:  # Need at least 4 points for a valid ring
            fixed_coordinates.append(ring)
            continue
        
        # Ensure the ring is closed (first and last points should be the same)
        if ring[0] != ring[-1]:
            ring = ring + [ring[0]]
            
        is_cw = is_clockwise(ring)
        
        if ring_index == 0:  # Exterior ring
            # Should be counterclockwise (NOT clockwise)
            if is_cw:  # Currently clockwise, need to reverse
                reversed_ring = ring[::-1]
                fixed_coordinates.append(reversed_ring)
                print(f"  Fixed exterior ring (was clockwise, now counterclockwise)")
            else:
                fixed_coordinates.append(ring)
        else:  # Interior ring (hole)
            # Should be clockwise
            if not is_cw:  # Currently counterclockwise, need to reverse
                reversed_ring = ring[::-1]
                fixed_coordinates.append(reversed_ring)
                print(f"  Fixed interior ring {ring_index} (was counterclockwise, now clockwise)")
            else:
                fixed_coordinates.append(ring)
    
    return fixed_coordinates


def fix_geojson(input_file: str, output_file: str = None) -> None:
    """
    Fix GeoJSON validation errors in the specified file.
    """
    if output_file is None:
        output_file = input_file
    
    try:
        # Read the GeoJSON file
        with open(input_file, 'r', encoding='utf-8') as f:
            geojson_data = json.load(f)
        
        # Fix 1: Remove deprecated 'crs' member
        if 'crs' in geojson_data:
            print(f"Removing deprecated 'crs' member")
            del geojson_data['crs']
        
        # Fix 2: Fix polygon winding order
        if 'features' in geojson_data:
            fixed_features = 0
            for feature in geojson_data['features']:
                if (feature.get('geometry', {}).get('type') in ['Polygon', 'MultiPolygon'] and 
                    'coordinates' in feature['geometry']):
                    
                    geometry_type = feature['geometry']['type']
                    coordinates = feature['geometry']['coordinates']
                    
                    if geometry_type == 'Polygon':
                        # Single polygon
                        original_coords = coordinates
                        fixed_coords = fix_polygon_winding(coordinates)
                        if fixed_coords != original_coords:
                            feature['geometry']['coordinates'] = fixed_coords
                            fixed_features += 1
                            if 'properties' in feature and 'hole' in feature['properties']:
                                print(f"Fixed winding order for hole {feature['properties']['hole']}")
                    
                    elif geometry_type == 'MultiPolygon':
                        # Multiple polygons
                        fixed_multipolygon = []
                        polygon_changed = False
                        for polygon_index, polygon in enumerate(coordinates):
                            original_coords = polygon
                            fixed_coords = fix_polygon_winding(polygon)
                            fixed_multipolygon.append(fixed_coords)
                            if fixed_coords != original_coords:
                                polygon_changed = True
                                if 'properties' in feature and 'hole' in feature['properties']:
                                    print(f"Fixed winding order for hole {feature['properties']['hole']}, polygon {polygon_index}")
                        
                        if polygon_changed:
                            feature['geometry']['coordinates'] = fixed_multipolygon
                            fixed_features += 1
            
            print(f"Fixed winding order for {fixed_features} polygon features")
        
        # Write the fixed GeoJSON
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(geojson_data, f, indent=None, separators=(',', ':'))
        
        print(f"Fixed GeoJSON saved to: {output_file}")
        
    except FileNotFoundError:
        print(f"Error: File '{input_file}' not found")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in '{input_file}': {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Error processing file: {e}")
        sys.exit(1)


def main():
    """Main function to handle command line arguments."""
    if len(sys.argv) < 2:
        print("Usage: python fix_geojson.py <input_file> [output_file]")
        print("If output_file is not provided, the input file will be overwritten.")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    
    fix_geojson(input_file, output_file)


if __name__ == "__main__":
    main()
