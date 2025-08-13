#!/usr/bin/env python3
"""
LCM Course Node Generator

This script generates optimal course nodes using Lowest Common Multiplier (LCM) logic.
For a golfer taking 240 minutes and beverage cart taking 180 minutes to complete 
the same 18-hole course, the LCM is 720 - meaning we need exactly 720 nodes for
perfect synchronization.

The script creates nodes along the course path where both entities can meet at
synchronized timing intervals.
"""

import json
import math
from pathlib import Path
from typing import Dict, List, Tuple

from shapely.geometry import LineString


def load_simulation_config(config_path: str) -> Dict:
    """Load simulation configuration from JSON file."""
    with open(config_path, 'r') as f:
        return json.load(f)


def load_hole_geometry(holes_geojson_path: str) -> Dict[int, LineString]:
    """Load hole geometry from GeoJSON file."""
    hole_lines = {}
    
    with open(holes_geojson_path, 'r') as f:
        holes_data = json.load(f)
    
    for feature in holes_data.get("features", []):
        props = feature.get("properties", {})
        raw_num = props.get("hole", props.get("ref"))
        
        try:
            hole_num = int(raw_num) if raw_num is not None else None
        except (TypeError, ValueError):
            hole_num = None
            
        if hole_num and feature.get("geometry", {}).get("type") == "LineString":
            coords = feature["geometry"]["coordinates"]
            hole_lines[hole_num] = LineString(coords)
    
    return hole_lines


def calculate_lcm_parameters(golfer_minutes: int, bev_cart_minutes: int) -> Dict:
    """Calculate LCM parameters for optimal node generation."""
    
    # Calculate LCM
    gcd = math.gcd(golfer_minutes, bev_cart_minutes)
    lcm = abs(golfer_minutes * bev_cart_minutes) // gcd
    
    # Calculate cycles
    golfer_cycles = lcm // golfer_minutes
    bev_cart_cycles = lcm // bev_cart_minutes
    
    # Time quantum (GCD represents the finest time resolution needed)
    time_quantum_min = gcd
    
    print(f"LCM Analysis:")
    print(f"  Golfer: {golfer_minutes} min/round")
    print(f"  Bev cart: {bev_cart_minutes} min/round")
    print(f"  GCD: {gcd} minutes")
    print(f"  LCM: {lcm} minutes")
    print(f"  Golfer completes {golfer_cycles} rounds in LCM period")
    print(f"  Bev cart completes {bev_cart_cycles} rounds in LCM period")
    print(f"  Optimal nodes: {lcm} (one per minute)")
    print(f"  Time quantum: {time_quantum_min} minutes")
    
    return {
        'golfer_minutes': golfer_minutes,
        'bev_cart_minutes': bev_cart_minutes,
        'gcd': gcd,
        'lcm': lcm,
        'golfer_cycles': golfer_cycles,
        'bev_cart_cycles': bev_cart_cycles,
        'time_quantum_min': time_quantum_min,
        'total_nodes': lcm
    }


def build_course_path(hole_lines: Dict[int, LineString], clubhouse_coords: Tuple[float, float]) -> List[Dict]:
    """Build the complete course path from holes 1-18."""
    
    path_segments = []
    cumulative_distance = 0.0
    
    # Process holes 1-18 in sequence
    for hole_num in range(1, 19):
        if hole_num in hole_lines:
            hole_line = hole_lines[hole_num]
            hole_distance = hole_line.length * 111139  # Convert degrees to meters
        else:
            # Fallback geometry if hole is missing
            if hole_num == 1:
                start_coords = clubhouse_coords
            else:
                # Use previous hole's end or clubhouse
                start_coords = clubhouse_coords
            
            end_coords = (start_coords[0] + 0.001, start_coords[1] + 0.001)  # Small offset
            hole_line = LineString([start_coords, end_coords])
            hole_distance = 100.0  # Fallback 100m
        
        path_segments.append({
            'type': 'hole',
            'hole_number': hole_num,
            'geometry': hole_line,
            'distance_m': hole_distance,
            'start_distance': cumulative_distance,
            'end_distance': cumulative_distance + hole_distance
        })
        
        cumulative_distance += hole_distance
        
        # Add transfer to next hole (except after hole 18)
        if hole_num < 18:
            next_hole_num = hole_num + 1
            if next_hole_num in hole_lines:
                next_hole_line = hole_lines[next_hole_num]
                # Transfer from end of current hole to start of next
                transfer_line = LineString([
                    hole_line.coords[-1],
                    next_hole_line.coords[0]
                ])
                transfer_distance = transfer_line.length * 111139
            else:
                # Fallback transfer
                end_point = hole_line.coords[-1]
                transfer_end = (end_point[0] + 0.0005, end_point[1] + 0.0005)
                transfer_line = LineString([end_point, transfer_end])
                transfer_distance = 50.0  # Fallback 50m
            
            path_segments.append({
                'type': 'transfer',
                'hole_number': hole_num,
                'geometry': transfer_line,
                'distance_m': transfer_distance,
                'start_distance': cumulative_distance,
                'end_distance': cumulative_distance + transfer_distance
            })
            
            cumulative_distance += transfer_distance
    
    # Add final transfer back to clubhouse
    last_hole_line = hole_lines.get(18)
    if last_hole_line:
        final_transfer = LineString([last_hole_line.coords[-1], clubhouse_coords])
        final_distance = final_transfer.length * 111139
    else:
        final_transfer = LineString([clubhouse_coords, clubhouse_coords])
        final_distance = 50.0
    
    path_segments.append({
        'type': 'transfer_to_clubhouse',
        'hole_number': 18,
        'geometry': final_transfer,
        'distance_m': final_distance,
        'start_distance': cumulative_distance,
        'end_distance': cumulative_distance + final_distance
    })
    
    total_distance = cumulative_distance + final_distance
    
    # Add normalized position to each segment
    for segment in path_segments:
        segment['start_position'] = segment['start_distance'] / total_distance
        segment['end_position'] = segment['end_distance'] / total_distance
    
    print(f"Course path built: {len(path_segments)} segments, {total_distance:.0f}m total")
    
    return path_segments


def interpolate_along_linestring(line: LineString, fraction: float) -> Tuple[float, float]:
    """Interpolate coordinates along a LineString at the given fraction (0.0 to 1.0)."""
    if fraction <= 0.0:
        return line.coords[0]
    elif fraction >= 1.0:
        return line.coords[-1]
    else:
        point = line.interpolate(fraction, normalized=True)
        return (point.x, point.y)


def generate_lcm_nodes(path_segments: List[Dict], lcm_params: Dict) -> List[Dict]:
    """Generate exactly LCM number of nodes along the course path."""
    
    nodes = []
    total_nodes = lcm_params['total_nodes']
    total_distance = path_segments[-1]['end_distance']
    
    golfer_minutes = lcm_params['golfer_minutes']
    bev_cart_minutes = lcm_params['bev_cart_minutes']
    time_quantum = lcm_params['time_quantum_min']
    
    print(f"Generating {total_nodes} nodes along {total_distance:.0f}m course...")
    
    # Generate nodes at regular intervals
    for node_idx in range(total_nodes):
        # Calculate position along course (0.0 to 1.0)
        course_progress = node_idx / (total_nodes - 1) if total_nodes > 1 else 0.0
        target_distance = course_progress * total_distance
        
        # Find which segment contains this distance
        target_segment = None
        segment_progress = 0.0
        
        for segment in path_segments:
            if target_distance <= segment['end_distance']:
                target_segment = segment
                if segment['distance_m'] > 0:
                    segment_progress = (target_distance - segment['start_distance']) / segment['distance_m']
                else:
                    segment_progress = 0.0
                segment_progress = max(0.0, min(1.0, segment_progress))
                break
        
        if target_segment is None:
            target_segment = path_segments[-1]
            segment_progress = 1.0
        
        # Get coordinates
        lon, lat = interpolate_along_linestring(target_segment['geometry'], segment_progress)
        
        # Determine node type
        if target_segment['type'] == 'hole':
            if segment_progress < 0.1:
                node_type = 'tee'
            elif segment_progress > 0.9:
                node_type = 'green'
            else:
                node_type = 'fairway'
        else:
            node_type = 'transfer'
        
        # Calculate time-based entity assignments
        current_time = node_idx * time_quantum
        
        # Determine which entities would be at this position at this time
        entity_types = []
        
        # Golfer position at this time (cycles through 0-1 every golfer_minutes)
        golfer_time_in_cycle = current_time % golfer_minutes
        golfer_expected_progress = golfer_time_in_cycle / golfer_minutes
        
        # Bev cart position at this time (cycles through 0-1 every bev_cart_minutes)
        bev_cart_time_in_cycle = current_time % bev_cart_minutes
        bev_cart_expected_progress = bev_cart_time_in_cycle / bev_cart_minutes
        
        # Check if each entity would be at this position (with tolerance)
        tolerance = 0.01  # 1% position tolerance
        
        if abs(golfer_expected_progress - course_progress) < tolerance:
            entity_types.append('golfer')
        
        if abs(bev_cart_expected_progress - course_progress) < tolerance:
            entity_types.append('bev_cart')
        
        # If no entity specifically assigned, make it available to both
        if not entity_types:
            entity_types = ['golfer', 'bev_cart']
        
        # Determine if this is a meeting point
        is_meeting_point = len(entity_types) > 1
        
        node = {
            'longitude': lon,
            'latitude': lat,
            'hole_number': target_segment['hole_number'],
            'node_type': node_type,
            'entity_types': entity_types,
            'sequence_position': course_progress,
            'distance_from_start': target_distance,
            'time_minute': current_time,
            'is_meeting_point': is_meeting_point
        }
        
        nodes.append(node)
    
    # Calculate statistics
    meeting_points = [n for n in nodes if n['is_meeting_point']]
    golfer_nodes = [n for n in nodes if 'golfer' in n['entity_types']]
    bev_cart_nodes = [n for n in nodes if 'bev_cart' in n['entity_types']]
    
    print(f"Generated nodes:")
    print(f"  Total: {len(nodes)}")
    print(f"  Meeting points: {len(meeting_points)}")
    print(f"  Golfer accessible: {len(golfer_nodes)}")
    print(f"  Bev cart accessible: {len(bev_cart_nodes)}")
    
    return nodes


def save_nodes_geojson(nodes: List[Dict], output_path: str, metadata: Dict) -> None:
    """Save nodes as GeoJSON file."""
    
    features = []
    
    for i, node in enumerate(nodes):
        feature = {
            "type": "Feature",
            "properties": {
                "node_id": i,
                "hole_number": node['hole_number'],
                "node_type": node['node_type'],
                "entity_types": node['entity_types'],
                "sequence_position": round(node['sequence_position'], 6),
                "distance_from_start": round(node['distance_from_start'], 2),
                "time_minute": node['time_minute'],
                "is_meeting_point": node['is_meeting_point']
            },
            "geometry": {
                "type": "Point",
                "coordinates": [node['longitude'], node['latitude']]
            }
        }
        features.append(feature)
    
    geojson_data = {
        "type": "FeatureCollection",
        "metadata": {
            "generated_by": "LCM Course Node Generator",
            "course_name": metadata.get('course_name', 'Unknown'),
            "golfer_minutes": metadata['golfer_minutes'],
            "bev_cart_minutes": metadata['bev_cart_minutes'],
            "lcm_minutes": metadata['lcm'],
            "total_nodes": len(nodes),
            "meeting_points": len([n for n in nodes if n['is_meeting_point']]),
            "description": f"Optimal course nodes using LCM logic for {metadata['golfer_minutes']}min golfer and {metadata['bev_cart_minutes']}min beverage cart"
        },
        "features": features
    }
    
    with open(output_path, 'w') as f:
        json.dump(geojson_data, f, indent=2)
    
    print(f"Saved {len(features)} nodes to {output_path}")


def main():
    """Main function to generate LCM course nodes."""
    
    # Paths
    config_path = "courses/pinetree_country_club/config/simulation_config.json"
    holes_path = "courses/pinetree_country_club/geojson/holes.geojson"
    output_dir = Path("courses/pinetree_country_club/geojson/generated")
    output_dir.mkdir(exist_ok=True)
    
    print("=== LCM Course Node Generator ===")
    
    # Load configuration
    print(f"Loading config from {config_path}")
    config = load_simulation_config(config_path)
    
    # Extract timing parameters
    golfer_minutes = config.get('golfer_18_holes_minutes', 240)
    bev_cart_minutes = config.get('bev_cart_18_holes_minutes', 180)
    clubhouse_coords = (config['clubhouse']['longitude'], config['clubhouse']['latitude'])
    
    print(f"Course: {config.get('course_name', 'Unknown')}")
    print(f"Clubhouse: {clubhouse_coords}")
    
    # Calculate LCM parameters
    lcm_params = calculate_lcm_parameters(golfer_minutes, bev_cart_minutes)
    
    # Load hole geometry
    print(f"\nLoading holes from {holes_path}")
    hole_lines = load_hole_geometry(holes_path)
    print(f"Loaded {len(hole_lines)} holes: {sorted(hole_lines.keys())}")
    
    # Build course path
    print("\nBuilding course path...")
    path_segments = build_course_path(hole_lines, clubhouse_coords)
    
    # Generate LCM nodes
    print(f"\nGenerating LCM nodes...")
    nodes = generate_lcm_nodes(path_segments, lcm_params)
    
    # Save results
    output_file = output_dir / "lcm_course_nodes.geojson"
    print(f"\nSaving results...")
    
    metadata = {
        'course_name': config.get('course_name', 'Unknown'),
        'golfer_minutes': golfer_minutes,
        'bev_cart_minutes': bev_cart_minutes,
        'lcm': lcm_params['lcm']
    }
    
    save_nodes_geojson(nodes, str(output_file), metadata)
    
    print(f"\n=== Generation Complete ===")
    print(f"Created {len(nodes)} optimal nodes")
    print(f"LCM synchronization: {lcm_params['lcm']} minutes")
    print(f"Output: {output_file}")
    
    return 0


if __name__ == "__main__":
    exit(main())
