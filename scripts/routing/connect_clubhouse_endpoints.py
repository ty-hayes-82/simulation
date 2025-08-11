#!/usr/bin/env python3
"""
Script to connect all open endpoints in cart_paths.geojson to the clubhouse
to create one continuous figure-8 network.

This script:
1. Loads the cart_paths.geojson file
2. Identifies all endpoints (coordinates that appear only once)
3. Connects these endpoints to the clubhouse location
4. Saves the result as a new GeoJSON file
"""

import argparse
import json
import os
from typing import List, Tuple, Dict, Set
from collections import Counter
import math

from golfsim.logging import init_logging, get_logger
from utils.cli import add_log_level_argument, add_course_dir_argument

logger = get_logger(__name__)


def load_geojson(file_path: str) -> Dict:
    """Load GeoJSON file and return the data."""
    with open(file_path, 'r') as f:
        return json.load(f)


def save_geojson(data: Dict, file_path: str) -> None:
    """Save GeoJSON data to file."""
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=2)


def get_linestring_endpoints(coordinates: List[List[float]]) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    """Get the first and last coordinates of a LineString."""
    start = tuple(coordinates[0])
    end = tuple(coordinates[-1])
    return start, end


def find_open_endpoints(features: List[Dict]) -> Set[Tuple[float, float]]:
    """
    Find all open endpoints in the cart path network.
    An endpoint is 'open' if it appears only once across all LineStrings.
    """
    endpoint_counts = Counter()
    
    for feature in features:
        if feature['geometry']['type'] == 'LineString':
            coordinates = feature['geometry']['coordinates']
            start, end = get_linestring_endpoints(coordinates)
            endpoint_counts[start] += 1
            endpoint_counts[end] += 1
    
    # Find coordinates that appear only once (open endpoints)
    open_endpoints = {coord for coord, count in endpoint_counts.items() if count == 1}
    return open_endpoints


def calculate_distance(coord1: Tuple[float, float], coord2: Tuple[float, float]) -> float:
    """Calculate Euclidean distance between two coordinates."""
    lon1, lat1 = coord1
    lon2, lat2 = coord2
    return math.sqrt((lon2 - lon1)**2 + (lat2 - lat1)**2)


def create_connection_linestring(start: Tuple[float, float], end: Tuple[float, float]) -> Dict:
    """Create a new LineString feature connecting two points with minimal properties."""
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [list(start), list(end)]
        },
        "properties": {
            "type": "connection"
        }
    }


def connect_endpoints_to_clubhouse(cart_paths_file: str, clubhouse_coords: Tuple[float, float], 
                                 output_file: str, max_distance_yards: float = 200) -> None:
    """
    Main function to connect open endpoints within a specified distance to the clubhouse.
    
    Args:
        cart_paths_file: Path to the cart_paths.geojson file
        clubhouse_coords: (longitude, latitude) of the clubhouse
        output_file: Path where to save the new GeoJSON file
        max_distance_yards: Maximum distance in yards to connect endpoints to clubhouse
    """
    logger.info(f"Loading cart paths from: {cart_paths_file}")
    cart_data = load_geojson(cart_paths_file)
    
    logger.info("Finding open endpoints...")
    open_endpoints = find_open_endpoints(cart_data['features'])
    logger.info(f"Found {len(open_endpoints)} open endpoints")
    
    # Convert max distance from yards to decimal degrees (approximate)
    max_distance_meters = max_distance_yards * 0.9144  # Convert yards to meters
    max_distance_degrees = max_distance_meters / 111000  # Rough conversion to decimal degrees
    
    # Filter endpoints by distance to clubhouse
    nearby_endpoints = []
    for endpoint in open_endpoints:
        distance_degrees = calculate_distance(endpoint, clubhouse_coords)
        distance_meters = distance_degrees * 111000
        distance_yards = distance_meters / 0.9144
        
        if distance_yards <= max_distance_yards:
            nearby_endpoints.append(endpoint)
            logger.debug(f"  Nearby endpoint: ({endpoint[0]:.6f}, {endpoint[1]:.6f}) - Distance: {distance_yards:.1f} yards")
        else:
            logger.debug(f"  Skipping distant endpoint: ({endpoint[0]:.6f}, {endpoint[1]:.6f}) - Distance: {distance_yards:.1f} yards")
    
    logger.info(f"Found {len(nearby_endpoints)} endpoints within {max_distance_yards} yards of clubhouse")
    
    # Simplify existing cart path features by keeping only essential properties
    simplified_features = []
    for feature in cart_data['features']:
        if feature['geometry']['type'] == 'LineString':
            simplified_feature = {
                "type": "Feature",
                "geometry": feature['geometry'],  # Keep all coordinate points
                "properties": {
                    "type": "cartpath"
                }
            }
            simplified_features.append(simplified_feature)
    
    # Connect each nearby open endpoint to the clubhouse
    logger.info(f"Connecting nearby endpoints to clubhouse at: {clubhouse_coords}")
    connections_added = 0
    
    for endpoint in nearby_endpoints:
        # Create a connection from endpoint to clubhouse
        connection_feature = create_connection_linestring(endpoint, clubhouse_coords)
        simplified_features.append(connection_feature)
        connections_added += 1
    
    # Create the new GeoJSON structure
    new_geojson = {
        "type": "FeatureCollection",
        "features": simplified_features
    }
    
    logger.info(f"Added {connections_added} connections to clubhouse")
    logger.info(f"Total features: {len(simplified_features)} (original: {len(cart_data['features'])})")
    
    # Save the new GeoJSON file
    logger.info(f"Saving connected network to: {output_file}")
    save_geojson(new_geojson, output_file)
    logger.info("Done!")
    
    if connections_added == 0:
        logger.warning("Note: No endpoints were within the specified distance range.")
    else:
        logger.info(f"Successfully connected {connections_added} nearby endpoints to create a more connected network.")


def main():
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description="Connect open cart path endpoints to clubhouse"
    )
    add_log_level_argument(parser)
    add_course_dir_argument(parser)
    parser.add_argument(
        "--max-distance", type=float, default=200.0,
        help="Maximum connection distance in yards (default: 200)"
    )
    parser.add_argument(
        "--clubhouse-lat", type=float, default=34.0379,
        help="Clubhouse latitude (default: 34.0379)"
    )
    parser.add_argument(
        "--clubhouse-lon", type=float, default=-84.5928,
        help="Clubhouse longitude (default: -84.5928)"
    )
    
    args = parser.parse_args()
    init_logging(args.log_level)
    
    # Configuration
    cart_paths_file = os.path.join(args.course_dir, "geojson", "cart_paths.geojson")
    output_file = os.path.join(args.course_dir, "geojson", "cart_paths_connected.geojson")
    
    # Clubhouse coordinates from arguments
    # Note: GeoJSON uses [longitude, latitude] format
    clubhouse_coords = (args.clubhouse_lon, args.clubhouse_lat)
    
    logger.info("Cart Path Endpoint Connection Script")
    logger.info(f"Course directory: {args.course_dir}")
    logger.info(f"Clubhouse coordinates: {clubhouse_coords}")
    logger.info(f"Max connection distance: {args.max_distance} yards")
    
    # Check if input file exists
    if not os.path.exists(cart_paths_file):
        logger.error(f"Cart paths file not found: {cart_paths_file}")
        return 1
    
    # Connect endpoints to clubhouse
    connect_endpoints_to_clubhouse(cart_paths_file, clubhouse_coords, output_file, args.max_distance)
    
    logger.info(f"New connected cart path network saved as: {output_file}")
    logger.info(f"This creates a more connected network by linking nearby endpoints (within {args.max_distance} yards) to the clubhouse.")
    return 0


if __name__ == "__main__":
    main()
