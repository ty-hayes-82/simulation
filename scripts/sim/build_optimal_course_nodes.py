#!/usr/bin/env python3
"""
Dynamic Course Node Builder using LCM Logic

This script creates optimal node counts and mappings for golf course simulations
by using Lowest Common Multiplier (LCM) logic to synchronize timing between
golfers and beverage carts. It generates a comprehensive course model with
precise timing coordination points.

Features:
- LCM-based synchronization for optimal meeting points
- Dynamic node generation based on course geometry
- Configurable timing parameters from simulation config
- GPS coordinate interpolation along hole LineStrings
- Support for both golfer (1→18) and beverage cart (18→1) directions
"""

import json
import math
from dataclasses import dataclass
from functools import reduce
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

from shapely.geometry import LineString, Point

from golfsim.config.loaders import load_simulation_config
from golfsim.logging import init_logging


@dataclass
class CourseNode:
    """Represents a single spatial node in the course simulation."""
    longitude: float
    latitude: float
    hole_number: int
    node_type: str  # 'tee', 'fairway', 'green', 'transfer', 'clubhouse'
    entity_types: List[str]  # ['golfer'], ['bev_cart'], or ['golfer', 'bev_cart'] for meeting points
    sequence_position: float  # 0.0 to 1.0 position along the entity's path
    distance_from_start: float = 0.0  # Total distance from start of round
    
    def to_dict(self) -> Dict:
        """Convert node to dictionary format for JSON export."""
        return {
            'longitude': self.longitude,
            'latitude': self.latitude,
            'hole_number': self.hole_number,
            'node_type': self.node_type,
            'entity_types': self.entity_types,
            'sequence_position': self.sequence_position,
            'distance_from_start': self.distance_from_start,
            'is_meeting_point': len(self.entity_types) > 1
        }


@dataclass
class SpatialParameters:
    """Computed spatial parameters for optimal node placement."""
    golfer_total_distance: float
    bev_cart_total_distance: float
    golfer_speed_ratio: float  # Relative speed compared to base
    bev_cart_speed_ratio: float
    meeting_point_positions: List[float]  # Sequence positions where meetings occur
    optimal_node_density: float  # Nodes per unit distance
    golfer_nodes_per_hole: int
    bev_cart_nodes_per_hole: int


def _gcd(a: int, b: int) -> int:
    """Calculate Greatest Common Divisor."""
    while b:
        a, b = b, a % b
    return a


def _gcd_list(values: List[int]) -> int:
    """Calculate GCD of a list of integers."""
    vals = [abs(int(v)) for v in values if int(v) != 0]
    if not vals:
        return 1
    return reduce(_gcd, vals)


def _lcm(a: int, b: int) -> int:
    """Calculate Lowest Common Multiplier."""
    return abs(a * b) // _gcd(a, b)


def _lcm_list(values: List[int]) -> int:
    """Calculate LCM of a list of integers."""
    vals = [abs(int(v)) for v in values if int(v) != 0]
    if not vals:
        return 1
    return reduce(_lcm, vals)


def load_hole_geometry(course_dir: str) -> Dict[int, LineString]:
    """
    Load hole geometry from course GeoJSON files.
    
    Args:
        course_dir: Path to course directory
        
    Returns:
        Dictionary mapping hole numbers to LineString geometries
    """
    hole_lines: Dict[int, LineString] = {}
    holes_file = Path(course_dir) / "geojson" / "holes.geojson"
    
    if holes_file.exists():
        holes_data = json.loads(holes_file.read_text(encoding="utf-8"))
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


def calculate_optimal_spatial_parameters(
    golfer_18_holes_minutes: int = 255,
    bev_cart_18_holes_minutes: int = 180,
    hole_lines: Dict[int, LineString] = None,
    target_meetings_per_round: int = 6,
) -> SpatialParameters:
    """
    Calculate optimal spatial parameters using true LCM logic for shared path at different speeds.
    
    Both golfer and beverage cart follow the EXACT SAME PATH but at different speeds.
    The true LCM of their cycle times determines optimal meeting points.
    
    Args:
        golfer_18_holes_minutes: Total minutes for golfer to complete 18 holes
        bev_cart_18_holes_minutes: Total minutes for bev cart to complete 18 holes
        hole_lines: Dictionary mapping hole numbers to LineString geometries
        target_meetings_per_round: Desired number of meeting points per round
        
    Returns:
        SpatialParameters with optimal node placement values
    """
    if hole_lines is None:
        hole_lines = {}
    
    # Calculate total distance for the SHARED PATH (both entities use same route)
    total_course_distance = 0.0
    
    # Path: 1→18 including transfers (same for both entities)
    for hole_num in range(1, 19):
        if hole_num in hole_lines:
            hole_line = hole_lines[hole_num]
            total_course_distance += hole_line.length * 111139  # Convert to meters
        else:
            total_course_distance += 400  # Fallback: 400m per hole
            
        # Add transfer distance (except after hole 18)
        if hole_num < 18:
            total_course_distance += 100  # Estimate 100m between holes
    
    # Calculate effective speeds for the shared path
    golfer_speed_mps = total_course_distance / (golfer_18_holes_minutes * 60)
    bev_cart_speed_mps = total_course_distance / (bev_cart_18_holes_minutes * 60)
    
    # Calculate speed ratios
    golfer_speed_ratio = golfer_speed_mps
    bev_cart_speed_ratio = bev_cart_speed_mps
    
    # TRUE LCM CALCULATION for synchronized meeting points
    golfer_time_units = int(golfer_18_holes_minutes)
    bev_cart_time_units = int(bev_cart_18_holes_minutes)
    
    # Find the true LCM of the cycle times
    time_lcm = _lcm(golfer_time_units, bev_cart_time_units)
    
    # In the LCM period:
    golfer_cycles = time_lcm // golfer_time_units      # How many rounds golfer completes
    bev_cart_cycles = time_lcm // bev_cart_time_units  # How many rounds bev cart completes
    
    print(f"DEBUG: LCM Analysis")
    print(f"  Golfer: {golfer_time_units} min/round × {golfer_cycles} rounds = {time_lcm} min")
    print(f"  Bev cart: {bev_cart_time_units} min/round × {bev_cart_cycles} rounds = {time_lcm} min")
    print(f"  True LCM: {time_lcm} minutes")
    
    # Calculate optimal node count based on LCM
    # The LCM gives us the optimal total number of time units where they sync
    optimal_total_nodes = time_lcm  # One node per minute for perfect synchronization
    
    # However, we can reduce this by using the GCD as our time quantum
    time_gcd = math.gcd(golfer_time_units, bev_cart_time_units)
    optimal_time_quantum_min = time_gcd  # Each node represents this many minutes
    
    # This gives us a more manageable node count
    practical_node_count = time_lcm // time_gcd
    
    print(f"  Time GCD: {time_gcd} minutes")
    print(f"  Practical node count: {practical_node_count} nodes")
    print(f"  Each node represents: {optimal_time_quantum_min} minutes of travel")
    
    # Calculate meeting points within one complete cycle
    # They meet when their positions on the shared path coincide
    meeting_positions = []
    
    # During one LCM period, find all synchronization points
    for minute in range(0, time_lcm, time_gcd):
        # Calculate position of golfer and bev cart at this time
        golfer_progress = (minute % golfer_time_units) / golfer_time_units
        bev_cart_progress = (minute % bev_cart_time_units) / bev_cart_time_units
        
        # If they're at approximately the same position on the course
        if abs(golfer_progress - bev_cart_progress) < 0.01:  # 1% tolerance
            meeting_positions.append(golfer_progress)
    
    # Remove duplicates and sort
    meeting_positions = sorted(list(set(meeting_positions)))
    
    print(f"  Meeting points found: {len(meeting_positions)}")
    print(f"  Meeting positions: {[f'{pos:.3f}' for pos in meeting_positions]}")
    
    # Calculate node density based on total distance and practical node count
    optimal_node_density = practical_node_count / total_course_distance
    
    # Calculate nodes per hole for even distribution
    nodes_per_hole = max(3, practical_node_count // 18)
    
    return SpatialParameters(
        golfer_total_distance=total_course_distance,
        bev_cart_total_distance=total_course_distance,  # Same path!
        golfer_speed_ratio=golfer_speed_ratio,
        bev_cart_speed_ratio=bev_cart_speed_ratio,
        meeting_point_positions=meeting_positions,
        optimal_node_density=optimal_node_density,
        golfer_nodes_per_hole=nodes_per_hole,
        bev_cart_nodes_per_hole=nodes_per_hole  # Same for both since same path
    )


def interpolate_along_linestring(line: LineString, fraction: float) -> Tuple[float, float]:
    """
    Interpolate a point along a LineString at the given fraction.
    
    Args:
        line: Shapely LineString geometry
        fraction: Position along line (0.0 = start, 1.0 = end)
        
    Returns:
        Tuple of (longitude, latitude)
    """
    if fraction <= 0.0:
        return line.coords[0]
    elif fraction >= 1.0:
        return line.coords[-1]
    else:
        # Use Shapely's interpolate method for precise positioning
        point = line.interpolate(fraction, normalized=True)
        return (point.x, point.y)


def build_shared_path_segments(
    hole_lines: Dict[int, LineString],
    clubhouse_coords: Tuple[float, float],
    spatial_params: SpatialParameters
) -> List[Dict]:
    """
    Build detailed segments for the shared path that both golfer and bev cart use.
    
    Since both entities follow the EXACT SAME PATH at different speeds, we only
    need one set of segments for the shared route.
    
    Args:
        hole_lines: Dictionary mapping hole numbers to LineString geometries
        clubhouse_coords: (longitude, latitude) of clubhouse
        spatial_params: Calculated spatial parameters
        
    Returns:
        List of segment dictionaries with geometry and spatial data for shared path
    """
    segments = []
    cumulative_distance = 0.0
    
    # Both entities follow 1→18 sequence (same path)
    sequence = list(range(1, 19))  # 1→18
    nodes_per_hole = spatial_params.golfer_nodes_per_hole  # Same for both
    total_distance = spatial_params.golfer_total_distance  # Same for both
    
    for i, hole_num in enumerate(sequence):
        # Get hole geometry or create fallback
        line = hole_lines.get(hole_num)
        if not isinstance(line, LineString):
            if hole_lines:
                # Use first available hole as fallback
                any_line = next(iter(hole_lines.values()))
                start = any_line.coords[0]
            else:
                start = clubhouse_coords
            line = LineString([start, start])
        
        # Calculate segment distance
        segment_distance = line.length * 111139  # Convert to meters
        if segment_distance == 0:
            segment_distance = 400  # Fallback distance
        
        # Calculate optimal number of nodes for this segment
        segment_nodes = max(2, int(segment_distance * spatial_params.optimal_node_density))
        
        segments.append({
            'type': 'hole',
            'hole_number': hole_num,
            'geometry': line,
            'distance_m': segment_distance,
            'nodes_count': segment_nodes,
            'sequence_index': i,
            'start_distance': cumulative_distance,
            'end_distance': cumulative_distance + segment_distance,
            'start_position': cumulative_distance / total_distance,
            'end_position': (cumulative_distance + segment_distance) / total_distance
        })
        
        cumulative_distance += segment_distance
        
        # Add transfer segment (except after last hole)
        if i < len(sequence) - 1:
            next_hole = sequence[i + 1]
            next_line = hole_lines.get(next_hole)
            
            if isinstance(next_line, LineString):
                # Transfer from end of current hole to start of next
                start_point = line.coords[-1]
                end_point = next_line.coords[0]
                transfer_line = LineString([start_point, end_point])
            else:
                # Fallback to clubhouse
                start_point = line.coords[-1]
                transfer_line = LineString([start_point, clubhouse_coords])
        else:
            # Final transfer back to clubhouse
            start_point = line.coords[-1]
            transfer_line = LineString([start_point, clubhouse_coords])
        
        # Calculate transfer distance
        transfer_distance = transfer_line.length * 111139  # Convert to meters
        if transfer_distance == 0:
            transfer_distance = 100  # Fallback
        
        # Transfers typically need fewer nodes
        transfer_nodes = max(1, int(transfer_distance * spatial_params.optimal_node_density * 0.5))
        
        segments.append({
            'type': 'transfer',
            'hole_number': hole_num,
            'geometry': transfer_line,
            'distance_m': transfer_distance,
            'nodes_count': transfer_nodes,
            'sequence_index': i,
            'start_distance': cumulative_distance,
            'end_distance': cumulative_distance + transfer_distance,
            'start_position': cumulative_distance / total_distance,
            'end_position': (cumulative_distance + transfer_distance) / total_distance
        })
        
        cumulative_distance += transfer_distance
    
    return segments


def generate_speed_based_nodes(
    segments: List[Dict],
    spatial_params: SpatialParameters,
    golfer_minutes: int,
    bev_cart_minutes: int
) -> List[CourseNode]:
    """
    Generate optimal course nodes using true LCM speed-based positioning.
    
    Both entities follow the same path but at different speeds. We generate nodes
    at positions where they can meet based on the true LCM calculation.
    
    Args:
        segments: List of hole and transfer segments for the shared path
        spatial_params: Spatial parameters including LCM meeting points
        golfer_minutes: Total minutes for golfer to complete the course
        bev_cart_minutes: Total minutes for bev cart to complete the course
        
    Returns:
        List of CourseNode objects with optimal LCM-based positioning
    """
    nodes = []
    
    # Calculate LCM and optimal node spacing
    time_lcm = _lcm(golfer_minutes, bev_cart_minutes)
    time_gcd = math.gcd(golfer_minutes, bev_cart_minutes)
    practical_nodes = time_lcm // time_gcd
    
    total_distance = sum(seg['distance_m'] for seg in segments)
    
    # Generate nodes at evenly spaced intervals along the shared path
    for node_idx in range(practical_nodes + 1):  # +1 to include end point
        # Calculate position along the entire course (0.0 to 1.0)
        if practical_nodes == 0:
            course_progress = 0.0
        else:
            course_progress = node_idx / practical_nodes
        
        # Find which segment this position falls in
        target_distance = course_progress * total_distance
        current_distance = 0.0
        
        for segment in segments:
            segment_start = current_distance
            segment_end = current_distance + segment['distance_m']
            
            if target_distance <= segment_end or segment == segments[-1]:
                # This is the target segment
                if segment['distance_m'] > 0:
                    segment_progress = (target_distance - segment_start) / segment['distance_m']
                else:
                    segment_progress = 0.0
                
                # Clamp to [0, 1]
                segment_progress = max(0.0, min(1.0, segment_progress))
                
                # Get coordinates
                lon, lat = interpolate_along_linestring(segment['geometry'], segment_progress)
                
                # Determine node type
                if segment['type'] == 'hole':
                    if segment_progress < 0.1:
                        node_type = 'tee'
                    elif segment_progress > 0.9:
                        node_type = 'green'
                    else:
                        node_type = 'fairway'
                else:
                    node_type = 'transfer'
                
                # Determine which entities use this node
                entity_types = []
                
                # Check if golfer would be at this position at any integer minute
                golfer_pos_at_time = (node_idx * time_gcd) % golfer_minutes / golfer_minutes
                if abs(golfer_pos_at_time - course_progress) < 0.01:
                    entity_types.append('golfer')
                
                # Check if bev cart would be at this position at any integer minute  
                bev_cart_pos_at_time = (node_idx * time_gcd) % bev_cart_minutes / bev_cart_minutes
                if abs(bev_cart_pos_at_time - course_progress) < 0.01:
                    entity_types.append('bev_cart')
                
                # Default to both if no specific assignment
                if not entity_types:
                    entity_types = ['golfer', 'bev_cart']
                
                # Check if this is a designated meeting point
                is_meeting_point = len(entity_types) > 1
                for meeting_pos in spatial_params.meeting_point_positions:
                    if abs(course_progress - meeting_pos) < 0.02:  # 2% tolerance
                        is_meeting_point = True
                        entity_types = ['golfer', 'bev_cart']
                        break
                
                node = CourseNode(
                    longitude=lon,
                    latitude=lat,
                    hole_number=segment['hole_number'],
                    node_type=node_type,
                    entity_types=entity_types,
                    sequence_position=course_progress,
                    distance_from_start=target_distance
                )
                
                nodes.append(node)
                break
            
            current_distance += segment['distance_m']
    
    return nodes


def analyze_spatial_coverage(nodes: List[CourseNode]) -> Dict:
    """
    Analyze the spatial coverage and distribution of generated nodes.
    
    Args:
        nodes: List of generated CourseNode objects
        
    Returns:
        Dictionary with analysis results
    """
    if not nodes:
        return {}
    
    # Group nodes by hole
    nodes_by_hole = {}
    for node in nodes:
        hole = node.hole_number
        if hole not in nodes_by_hole:
            nodes_by_hole[hole] = []
        nodes_by_hole[hole].append(node)
    
    # Calculate statistics
    total_distance = max(node.distance_from_start for node in nodes) if nodes else 0
    meeting_points = [node for node in nodes if len(node.entity_types) > 1]
    
    hole_coverage = {}
    for hole_num, hole_nodes in nodes_by_hole.items():
        distances = [n.distance_from_start for n in hole_nodes]
        hole_coverage[hole_num] = {
            'node_count': len(hole_nodes),
            'start_distance': min(distances),
            'end_distance': max(distances),
            'hole_length': max(distances) - min(distances)
        }
    
    # Calculate node density
    if len(nodes) > 1:
        distances = [node.distance_from_start for node in nodes]
        distances.sort()
        intervals = [distances[i+1] - distances[i] for i in range(len(distances)-1)]
        avg_interval = sum(intervals) / len(intervals) if intervals else 0
    else:
        avg_interval = 0
    
    return {
        'total_nodes': len(nodes),
        'total_distance_m': total_distance,
        'meeting_points_count': len(meeting_points),
        'nodes_by_hole': hole_coverage,
        'avg_distance_between_nodes': avg_interval,
        'node_density_per_km': 1000 / avg_interval if avg_interval > 0 else 0
    }


def build_course_model(
    course_dir: str,
    config_file: Optional[str] = None,
    output_dir: Optional[str] = None
) -> Dict:
    """
    Build complete course model with optimal spatial node distribution.
    
    Args:
        course_dir: Path to course directory
        config_file: Optional path to simulation config file
        output_dir: Optional output directory for generated files
        
    Returns:
        Dictionary containing complete course model
    """
    init_logging()
    import logging
    logger = logging.getLogger(__name__)
    logger.info("Building optimal course nodes using LCM spatial logic")
    
    # Load configuration
    if config_file:
        # Load from specific file
        with open(config_file, 'r') as f:
            config_data = json.load(f)
        from golfsim.config.models import SimulationConfig
        sim_config = SimulationConfig.from_dict(config_data)
    else:
        # Load using the loader function which expects course directory
        sim_config = load_simulation_config(course_dir)
    
    logger.info(f"Course: {sim_config.course_name}")
    logger.info(f"Golfer 18-hole time: {sim_config.golfer_18_holes_minutes} minutes")
    logger.info(f"Bev cart 18-hole time: {sim_config.bev_cart_18_holes_minutes} minutes")
    
    # Load hole geometry
    hole_lines = load_hole_geometry(course_dir)
    logger.info(f"Loaded {len(hole_lines)} holes: {sorted(hole_lines.keys())}")
    
    if not hole_lines:
        raise ValueError("No valid hole geometry found in course data")
    
    # Get clubhouse coordinates
    clubhouse_coords = sim_config.clubhouse  # (lon, lat)
    
    # Calculate optimal spatial parameters using LCM logic
    spatial_params = calculate_optimal_spatial_parameters(
        golfer_18_holes_minutes=sim_config.golfer_18_holes_minutes,
        bev_cart_18_holes_minutes=sim_config.bev_cart_18_holes_minutes,
        hole_lines=hole_lines
    )
    
    logger.info(f"Golfer total distance: {spatial_params.golfer_total_distance:.0f}m")
    logger.info(f"Bev cart total distance: {spatial_params.bev_cart_total_distance:.0f}m")
    logger.info(f"Optimal node density: {spatial_params.optimal_node_density:.4f} nodes/m")
    logger.info(f"Meeting points: {len(spatial_params.meeting_point_positions)}")
    
    # Build segments for the shared path (both entities use same route)
    shared_segments = build_shared_path_segments(
        hole_lines=hole_lines,
        clubhouse_coords=clubhouse_coords,
        spatial_params=spatial_params
    )
    
    # Generate optimal nodes for the shared path with speed-based positioning
    optimal_nodes = generate_speed_based_nodes(
        segments=shared_segments,
        spatial_params=spatial_params,
        golfer_minutes=sim_config.golfer_18_holes_minutes,
        bev_cart_minutes=sim_config.bev_cart_18_holes_minutes
    )
    
    logger.info(f"Generated {len(optimal_nodes)} optimal nodes using true LCM logic")
    
    # Analyze coverage
    analysis = analyze_spatial_coverage(optimal_nodes)
    
    # Separate nodes by entity type for compatibility
    golfer_only_nodes = [node for node in optimal_nodes if 'golfer' in node.entity_types and 'bev_cart' not in node.entity_types]
    bev_cart_only_nodes = [node for node in optimal_nodes if 'bev_cart' in node.entity_types and 'golfer' not in node.entity_types]
    meeting_nodes = [node for node in optimal_nodes if len(node.entity_types) > 1]
    
    # Build complete model
    course_model = {
        'metadata': {
            'course_name': sim_config.course_name,
            'generated_at': str(Path.cwd()),
            'total_holes': len(hole_lines),
            'clubhouse_coords': clubhouse_coords
        },
        'spatial_parameters': {
            'golfer_total_distance': spatial_params.golfer_total_distance,
            'bev_cart_total_distance': spatial_params.bev_cart_total_distance,
            'golfer_speed_ratio': spatial_params.golfer_speed_ratio,
            'bev_cart_speed_ratio': spatial_params.bev_cart_speed_ratio,
            'optimal_node_density': spatial_params.optimal_node_density,
            'meeting_point_positions': spatial_params.meeting_point_positions,
            'golfer_nodes_per_hole': spatial_params.golfer_nodes_per_hole,
            'bev_cart_nodes_per_hole': spatial_params.bev_cart_nodes_per_hole
        },
        'optimal_nodes': [node.to_dict() for node in optimal_nodes],
        'golfer_specific_nodes': [node.to_dict() for node in golfer_only_nodes],
        'bev_cart_specific_nodes': [node.to_dict() for node in bev_cart_only_nodes],
        'meeting_point_nodes': [node.to_dict() for node in meeting_nodes],
        'analysis': analysis
    }
    
    # Save to file if output directory specified
    if output_dir:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        model_file = output_path / "optimal_course_nodes.json"
        with open(model_file, 'w') as f:
            json.dump(course_model, f, indent=2)
        logger.info(f"Saved course model to {model_file}")
        
        # Save node files organized by purpose
        optimal_file = output_path / "optimal_nodes.json"
        meeting_points_file = output_path / "meeting_points.json"
        
        with open(optimal_file, 'w') as f:
            json.dump([node.to_dict() for node in all_unique_nodes], f, indent=2)
        
        with open(meeting_points_file, 'w') as f:
            meeting_nodes = [node for node in all_unique_nodes if len(node.entity_types) > 1]
            json.dump([node.to_dict() for node in meeting_nodes], f, indent=2)
        
        logger.info(f"Saved optimal nodes to {optimal_file}")
        logger.info(f"Saved meeting points to {meeting_points_file}")
    
    return course_model


def merge_meeting_points(golfer_nodes: List[CourseNode], bev_cart_nodes: List[CourseNode], 
                        spatial_params: SpatialParameters) -> List[CourseNode]:
    """
    Merge golfer and beverage cart nodes, combining nodes at meeting points.
    
    Args:
        golfer_nodes: List of golfer-specific nodes
        bev_cart_nodes: List of beverage cart-specific nodes
        spatial_params: Spatial parameters containing meeting point positions
        
    Returns:
        List of unique nodes with merged meeting points
    """
    all_nodes = []
    tolerance = 0.02  # 2% tolerance for position matching
    
    # Add all golfer nodes first
    for node in golfer_nodes:
        all_nodes.append(node)
    
    # Add beverage cart nodes, merging with golfer nodes at meeting points
    for bev_node in bev_cart_nodes:
        merged = False
        
        # Check if this beverage cart node should be merged with a golfer node
        for i, existing_node in enumerate(all_nodes):
            # Check if positions are close enough to be considered the same location
            if (abs(existing_node.sequence_position - bev_node.sequence_position) < tolerance and
                existing_node.hole_number == bev_node.hole_number):
                
                # Merge entity types
                merged_entity_types = list(set(existing_node.entity_types + ['bev_cart']))
                
                # Create merged node with combined entity types
                merged_node = CourseNode(
                    longitude=(existing_node.longitude + bev_node.longitude) / 2,  # Average position
                    latitude=(existing_node.latitude + bev_node.latitude) / 2,
                    hole_number=existing_node.hole_number,
                    node_type=existing_node.node_type,
                    entity_types=merged_entity_types,
                    sequence_position=existing_node.sequence_position,
                    distance_from_start=existing_node.distance_from_start
                )
                
                all_nodes[i] = merged_node
                merged = True
                break
        
        # If not merged, add as separate node
        if not merged:
            all_nodes.append(bev_node)
    
    # Sort by sequence position for consistent ordering
    all_nodes.sort(key=lambda n: n.sequence_position)
    return all_nodes


def main():
    """Main entry point for the script."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Build optimal course nodes using LCM logic")
    parser.add_argument("--course-dir", default="courses/pinetree_country_club",
                       help="Path to course directory")
    parser.add_argument("--config", help="Path to simulation config file")
    parser.add_argument("--output-dir", help="Output directory for generated files")
    parser.add_argument("--analyze-only", action="store_true",
                       help="Only analyze existing configuration without generating nodes")
    
    args = parser.parse_args()
    
    try:
        if args.analyze_only:
            # Just load config and show spatial analysis
            if args.config:
                # Load from specific file
                with open(args.config, 'r') as f:
                    config_data = json.load(f)
                from golfsim.config.models import SimulationConfig
                sim_config = SimulationConfig.from_dict(config_data)
            else:
                # Load using the loader function which expects course directory
                sim_config = load_simulation_config(args.course_dir)
            
            # Load hole geometry for accurate distance calculations
            hole_lines = load_hole_geometry(args.course_dir)
            
            spatial_params = calculate_optimal_spatial_parameters(
                golfer_18_holes_minutes=sim_config.golfer_18_holes_minutes,
                bev_cart_18_holes_minutes=sim_config.bev_cart_18_holes_minutes,
                hole_lines=hole_lines
            )
            
            print("=== Spatial Analysis ===")
            print(f"Course: {sim_config.course_name}")
            print(f"Golfer total distance: {spatial_params.golfer_total_distance:.0f}m")
            print(f"Bev cart total distance: {spatial_params.bev_cart_total_distance:.0f}m")
            print(f"Golfer speed: {spatial_params.golfer_speed_ratio:.2f} m/s")
            print(f"Bev cart speed: {spatial_params.bev_cart_speed_ratio:.2f} m/s")
            print(f"Optimal node density: {spatial_params.optimal_node_density:.4f} nodes/m")
            print(f"Meeting points: {len(spatial_params.meeting_point_positions)}")
            print(f"Golfer nodes per hole: {spatial_params.golfer_nodes_per_hole}")
            print(f"Bev cart nodes per hole: {spatial_params.bev_cart_nodes_per_hole}")
            print(f"Meeting positions: {[f'{pos:.2f}' for pos in spatial_params.meeting_point_positions]}")
        else:
            # Build full course model
            course_model = build_course_model(
                course_dir=args.course_dir,
                config_file=args.config,
                output_dir=args.output_dir
            )
            
            print("=== Course Model Built Successfully ===")
            print(f"Optimal nodes: {len(course_model['optimal_nodes'])}")
            print(f"Meeting points: {len(course_model['meeting_point_nodes'])}")
            print(f"Node density: {course_model['spatial_parameters']['optimal_node_density']:.4f} nodes/m")
            print(f"Golfer distance: {course_model['spatial_parameters']['golfer_total_distance']:.0f}m")
            print(f"Bev cart distance: {course_model['spatial_parameters']['bev_cart_total_distance']:.0f}m")
            
            if args.output_dir:
                print(f"Files saved to: {args.output_dir}")
        
    except Exception as e:
        print(f"Error: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
