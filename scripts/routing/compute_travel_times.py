#!/usr/bin/env python3
"""
Compute approximate travel times from clubhouse to each hole using cart path network.

Outputs two files in the course directory:
- travel_times.json (rich per-hole metrics)
- travel_times_simple.json (minimal per-hole summary)

This is a thin CLI that delegates routing to library functions and uses shared utils.
"""

from __future__ import annotations

import argparse
import json
import math
import pickle
from pathlib import Path
from typing import Any, Dict, List, Tuple

import networkx as nx

from golfsim.config.loaders import load_simulation_config
from golfsim.logging import get_logger, init_logging
from golfsim.routing.networks import shortest_path_on_cartpaths
from utils import setup_encoding, add_log_level_argument, add_course_dir_argument, write_json


logger = get_logger(__name__)


def _load_hole_lines(course_dir: Path) -> List[Dict[str, Any]]:
    holes_path = course_dir / "geojson" / "holes.geojson"
    if not holes_path.exists():
        raise FileNotFoundError(f"Holes geojson not found: {holes_path}")
    with holes_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("features", [])


def _hole_line_endpoints(feature: Dict[str, Any]) -> Tuple[Tuple[float, float], Tuple[float, float]]:
    coords = feature.get("geometry", {}).get("coordinates", [])
    if not coords:
        return (0.0, 0.0), (0.0, 0.0)
    start = tuple(coords[0])  # (lon, lat)
    end = tuple(coords[-1])
    return start, end


def _compute_distance_time(
    G: nx.Graph, start_lonlat: Tuple[float, float], end_lonlat: Tuple[float, float], speed_mps: float
) -> Tuple[float, float]:
    try:
        result = shortest_path_on_cartpaths(G, start_lonlat, end_lonlat, speed_mps=speed_mps)
        return float(result["length_m"]), float(result["time_s"]) / 60.0
    except Exception:
        # Fallback: straight-line with routing factor
        dx = (end_lonlat[0] - start_lonlat[0]) * 111_139
        dy = (end_lonlat[1] - start_lonlat[1]) * 111_139
        distance_m = math.hypot(dx, dy) * 1.4
        time_min = (distance_m / max(speed_mps, 0.1)) / 60.0
        return distance_m, time_min


def main() -> int:
    setup_encoding()

    parser = argparse.ArgumentParser(
        description="Compute travel times from clubhouse to each hole using cart paths",
    )
    add_course_dir_argument(parser)
    parser.add_argument(
        "--cart-speed-mph",
        type=float,
        default=10.0,
        help="Cart speed in mph (default: 10)",
    )
    add_log_level_argument(parser)
    args = parser.parse_args()

    init_logging(args.log_level)

    course_dir = Path(args.course_dir)

    # Load config for clubhouse
    sim_cfg = load_simulation_config(course_dir)
    clubhouse = tuple(sim_cfg.clubhouse)  # (lon, lat)

    # Load cart graph
    graph_path = course_dir / "pkl" / "cart_graph.pkl"
    if not graph_path.exists():
        logger.error("Cart graph not found: %s", graph_path)
        return 1
    with graph_path.open("rb") as f:
        G: nx.Graph = pickle.load(f)

    # Speed
    speed_mps = float(args.cart_speed_mph) * 0.44704

    # Holes
    features = _load_hole_lines(course_dir)

    holes_rich: List[Dict[str, Any]] = []
    holes_simple: List[Dict[str, Any]] = []

    for feat in features:
        props = feat.get("properties", {})
        try:
            hole_num = int(props.get("ref") or props.get("hole"))
        except Exception:
            continue
        par = str(props.get("par", ""))
        tee_lonlat, target_lonlat = _hole_line_endpoints(feat)

        # Compute metrics to tee (clubhouse -> tee)
        dist_to_tee_m, time_to_tee_min = _compute_distance_time(G, clubhouse, tee_lonlat, speed_mps)
        # Compute metrics to target (clubhouse -> near green)
        dist_to_target_m, time_to_target_min = _compute_distance_time(G, clubhouse, target_lonlat, speed_mps)

        holes_rich.append(
            {
                "hole": hole_num,
                "par": par,
                "travel_times": {
                    "golf_cart": {
                        "to_tee": {"distance_m": dist_to_tee_m, "time_min": time_to_tee_min},
                        "to_target": {"distance_m": dist_to_target_m, "time_min": time_to_target_min},
                    }
                },
            }
        )

        holes_simple.append(
            {
                "hole": hole_num,
                "par": par,
                "distance_m": dist_to_tee_m,
                "travel_time_min": time_to_tee_min,
            }
        )

    # Sort by hole number
    holes_rich.sort(key=lambda h: h["hole"])
    holes_simple.sort(key=lambda h: h["hole"])

    # Write outputs
    rich_out = {
        "course_name": course_dir.name.replace("_", " ").title(),
        "clubhouse_coords": list(clubhouse),
        "cart_speed_mph": float(args.cart_speed_mph),
        "holes": holes_rich,
        "calculation_params": {
            "speeds_mph": {"golf_cart": float(args.cart_speed_mph)},
        },
    }

    simple_out = {
        "course_name": course_dir.name.replace("_", " ").title(),
        "cart_speed_mph": float(args.cart_speed_mph),
        "holes": holes_simple,
    }

    write_json(course_dir / "travel_times.json", rich_out)
    write_json(course_dir / "travel_times_simple.json", simple_out)
    logger.info("Saved travel times to %s and %s", course_dir / "travel_times.json", course_dir / "travel_times_simple.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
#!/usr/bin/env python3
"""
Script to calculate estimated travel times to each hole for delivery based on cart paths.

This script:
1. Loads cart paths GeoJSON data
2. Loads holes and tees GeoJSON data 
3. Builds a cart path network graph
4. Calculates shortest paths from clubhouse to each hole
5. Estimates travel times based on realistic cart/runner speeds
6. Saves the travel time estimates to a JSON file

Usage:
    python scripts/calculate_travel_times.py [course_directory]
"""

import json
import pickle
import argparse
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import geopandas as gpd
import networkx as nx
import numpy as np
from shapely.geometry import Point

# Add project root to path to import modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from golfsim.data.osm_ingest import build_cartpath_graph
from golfsim.routing.networks import shortest_path_on_cartpaths, nearest_node


def load_course_data(data_dir: Path) -> Dict:
    """Load all necessary course data files."""
    print(f"Loading course data from {data_dir}...")
    
    # Define paths for different data types
    config_dir = data_dir / "config"
    geojson_dir = data_dir / "geojson"
    
    # Load simulation config for clubhouse location
    config_path = config_dir / "simulation_config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"Missing simulation config: {config_path}")
    
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    clubhouse_coords = (config["clubhouse"]["longitude"], config["clubhouse"]["latitude"])
    print(f"Clubhouse location: {clubhouse_coords}")
    
    # Load holes data
    holes_path = geojson_dir / "holes.geojson"
    if not holes_path.exists():
        raise FileNotFoundError(f"Missing holes data: {holes_path}")
    
    holes_gdf = gpd.read_file(holes_path).to_crs(4326)
    print(f"Loaded {len(holes_gdf)} holes")
    
    # Load tees data (optional)
    tees_path = geojson_dir / "tees.geojson"
    tees_gdf = None
    if tees_path.exists():
        tees_gdf = gpd.read_file(tees_path).to_crs(4326)
        print(f"Loaded {len(tees_gdf)} tees")
    
    # Load greens data (optional)
    greens_path = geojson_dir / "greens.geojson"
    greens_gdf = None
    if greens_path.exists():
        greens_gdf = gpd.read_file(greens_path).to_crs(4326)
        print(f"Loaded {len(greens_gdf)} greens")
    
    # Load course polygon
    course_poly_path = geojson_dir / "course_polygon.geojson"
    if not course_poly_path.exists():
        raise FileNotFoundError(f"Missing course polygon: {course_poly_path}")
    
    course_poly_gdf = gpd.read_file(course_poly_path).to_crs(4326)
    course_polygon = course_poly_gdf.geometry.iloc[0]
    print(f"Loaded course polygon")
    
    return {
        "config": config,
        "clubhouse_coords": clubhouse_coords,
        "holes": holes_gdf,
        "tees": tees_gdf,
        "greens": greens_gdf,
        "course_polygon": course_polygon
    }


def build_cart_graph(data_dir: Path, course_polygon) -> nx.Graph:
    """Build cart path network graph."""
    print("Building cart path network graph...")
    
    # Define paths for different data types
    geojson_dir = data_dir / "geojson"
    pkl_dir = data_dir / "pkl"
    
    # Check if enhanced graph exists first
    enhanced_graph_path = pkl_dir / "cart_graph.pkl"
    if enhanced_graph_path.exists():
        print(f"Loading enhanced cart graph from {enhanced_graph_path}")
        with open(enhanced_graph_path, 'rb') as f:
            return pickle.load(f)
    
    # Check if pre-built graph exists
    cart_graph_path = pkl_dir / "cart_graph.pkl"
    if cart_graph_path.exists():
        print(f"Loading existing cart graph from {cart_graph_path}")
        with open(cart_graph_path, 'rb') as f:
            return pickle.load(f)
    
    # Build from cart paths GeoJSON
    cart_paths_path = geojson_dir / "cart_paths.geojson"
    if not cart_paths_path.exists():
        raise FileNotFoundError(f"Missing cart paths data: {cart_paths_path}")
    
    graph = build_cartpath_graph(
        course_poly=course_polygon,
        cartpath_geojson=str(cart_paths_path),
        broaden=False
    )
    
    print(f"Built cart graph with {graph.number_of_nodes()} nodes and {graph.number_of_edges()} edges")
    return graph


def get_hole_coordinates(holes_gdf: gpd.GeoDataFrame, tees_gdf: Optional[gpd.GeoDataFrame] = None) -> Dict[str, Dict]:
    """Extract tee box coordinates for each hole (first geopoint for each hole)."""
    hole_coords = {}
    
    for idx, hole in holes_gdf.iterrows():
        hole_ref = hole.get('ref', str(idx + 1))
        
        # Get hole line geometry
        hole_geom = hole.geometry
        
        # For LineString holes, use start as tee box
        if hole_geom.geom_type == "LineString":
            coords = list(hole_geom.coords)
            tee_coords = coords[0]  # (longitude, latitude) - first geopoint
        else:
            # For other geometries, use centroid
            centroid = hole_geom.centroid
            tee_coords = (centroid.x, centroid.y)
        
        hole_coords[hole_ref] = {
            "hole_number": hole_ref,
            "par": hole.get('par', 'Unknown'),
            "handicap": hole.get('handicap', 'Unknown'),
            "tee_coords": tee_coords,
            "hole_line": list(hole_geom.coords) if hole_geom.geom_type == "LineString" else [tee_coords]
        }
    
    # Sort by hole number for consistent ordering
    sorted_holes = {}
    for hole_num in sorted(hole_coords.keys(), key=lambda x: int(x) if x.isdigit() else 999):
        sorted_holes[hole_num] = hole_coords[hole_num]
    
    return sorted_holes


def calculate_travel_times(graph: nx.Graph, clubhouse_coords: Tuple[float, float], 
                         hole_coords: Dict[str, Dict], speeds: Dict[str, float]) -> Dict:
    """
    UPDATED: Calculate travel times using optimal routing logic.
    """
    from golfsim.routing.optimal_routing import find_optimal_route
    
    print("Calculating travel times to tee boxes using optimal routing...")
    
    travel_times = {
        "clubhouse_coords": clubhouse_coords,
        "calculation_params": {
            "speeds_mps": speeds,
            "speeds_kmh": {k: v * 3.6 for k, v in speeds.items()},
            "speeds_mph": {k: v * 2.237 for k, v in speeds.items()}
        },
        "holes": {}
    }
    
    for hole_num, hole_info in hole_coords.items():
        print(f"  Calculating for hole {hole_num}...")
        
        tee_coords = hole_info["tee_coords"]
        
        hole_travel_times = {
            "hole_number": hole_num,
            "par": hole_info["par"],
            "handicap": hole_info["handicap"],
            "tee_coords": tee_coords,
            "travel_times": {}
        }
        
        # Calculate travel times using optimal routing
        for method, speed_mps in speeds.items():
            route_result = find_optimal_route(graph, clubhouse_coords, tee_coords, speed_mps)
            
            if route_result["success"]:
                hole_travel_times["travel_times"][method] = {
                    "distance_m": route_result["metrics"]["length_m"],
                    "time_s": route_result["metrics"]["time_s"],
                    "time_min": route_result["metrics"]["time_min"],
                    "efficiency": route_result["efficiency"],
                    "path_nodes": route_result["path"]
                }
            else:
                print(f"     Error calculating {method} for hole {hole_num}: {route_result['error']}")
                hole_travel_times["travel_times"][method] = {
                    "error": route_result["error"]
                }
        
        travel_times["holes"][hole_num] = hole_travel_times
    
    return travel_times


def analyze_routing_efficiency(travel_times: Dict) -> None:
    """
    Analyze and report routing efficiency statistics.
    """
    print("\n📊 Routing Efficiency Analysis:")
    
    efficiencies = []
    distances = []
    times = []
    
    for hole_num, hole_data in travel_times["holes"].items():
        if "golf_cart" in hole_data["travel_times"]:
            cart_data = hole_data["travel_times"]["golf_cart"]
            if "efficiency" in cart_data:
                efficiencies.append(cart_data["efficiency"])
                distances.append(cart_data["distance_m"])
                times.append(cart_data["time_min"])
    
    if efficiencies:
        print(f"   • Average efficiency: {np.mean(efficiencies):.1%}")
        print(f"   • Efficiency range: {min(efficiencies):.1%} - {max(efficiencies):.1%}")
        print(f"   • Distance range: {min(distances):.0f}m - {max(distances):.0f}m")
        print(f"   • Time range: {min(times):.1f} - {max(times):.1f} minutes")
        
        # Identify potential optimization opportunities
        inefficient_holes = [
            (hole_num, eff) for hole_num, eff in 
            zip(travel_times["holes"].keys(), efficiencies) 
            if eff < 60.0
        ]
        
        if inefficient_holes:
            print(f"    Holes with <60% efficiency: {inefficient_holes}")
        else:
            print(f"   All routes have ≥60% efficiency")


def create_simplified_output(travel_times: Dict) -> Dict:
    """Create simplified output with just hole number, distance, and travel time."""
    print("Creating simplified output...")
    
    simplified = {
        "course_name": "",
        "clubhouse_coords": travel_times["clubhouse_coords"],
        "cart_speed_mph": travel_times["calculation_params"]["speeds_mph"]["golf_cart"],
        "holes": []
    }
    
    # Extract simplified data for each hole
    for hole_num in sorted(travel_times["holes"].keys(), key=lambda x: int(x) if x.isdigit() else 999):
        hole_data = travel_times["holes"][hole_num]
        
        if "golf_cart" in hole_data["travel_times"]:
            cart_data = hole_data["travel_times"]["golf_cart"]
            
            if "error" not in cart_data:
                simplified["holes"].append({
                    "hole": int(hole_num) if hole_num.isdigit() else hole_num,
                    "par": hole_data["par"],
                    "distance_m": round(cart_data["distance_m"], 1),
                    "travel_time_min": round(cart_data["time_min"], 2)
                })
            else:
                simplified["holes"].append({
                    "hole": int(hole_num) if hole_num.isdigit() else hole_num,
                    "par": hole_data["par"],
                    "distance_m": "error",
                    "travel_time_min": "error"
                })
    
    return simplified


def main():
    """Main function to calculate and save travel times."""
    parser = argparse.ArgumentParser(description="Calculate travel times to each hole for delivery")
    parser.add_argument("course_dir", nargs="?", default="courses/pinetree_country_club",
                       help="Course directory containing GeoJSON files")
    parser.add_argument("--output", "-o", help="Output file path (default: <course_dir>/travel_times.json)")
    parser.add_argument("--cart-speed", type=float, default=6.0,
                       help="Golf cart speed in m/s (default: 6.0)")
    
    args = parser.parse_args()
    
    # Setup paths
    course_dir = Path(args.course_dir)
    if not course_dir.exists():
        print(f"Course directory not found: {course_dir}")
        sys.exit(1)
    
    output_path = Path(args.output) if args.output else course_dir / "travel_times.json"
    
    print(f" Calculating travel times for {course_dir}")
    print()
    
    try:
        # Load course data
        course_data = load_course_data(course_dir)
        
        # Load delivery speed from config or use command line argument
        config_speed_mph = course_data["config"].get("delivery_runner_speed_mph", None)
        if config_speed_mph and args.cart_speed == 6.0:  # Use config if no custom speed provided
            delivery_speed_mps = config_speed_mph * 0.44704  # Convert mph to m/s
            print(f"📊 Using delivery speed from config: {config_speed_mph} mph ({delivery_speed_mps:.2f} m/s)")
        else:
            delivery_speed_mps = args.cart_speed
            if args.cart_speed != 6.0:
                print(f"📊 Using custom delivery speed: {args.cart_speed} m/s ({args.cart_speed * 2.237:.1f} mph)")
            else:
                print(f"📊 Using default delivery speed: {args.cart_speed} m/s")
        
        # Define delivery method speeds (meters per second)
        speeds = {
            "golf_cart": delivery_speed_mps,
        }
        
        print(f"📊 Delivery speeds: {speeds} m/s")
        
        # Build cart path graph
        cart_graph = build_cart_graph(course_dir, course_data["course_polygon"])
        
        if cart_graph.number_of_edges() == 0:
            print("No cart paths found in graph. Cannot calculate travel times.")
            sys.exit(1)
        
        # Get hole coordinates
        hole_coords = get_hole_coordinates(course_data["holes"], course_data["tees"])
        print(f"Found coordinates for {len(hole_coords)} holes")
        
        # Calculate travel times
        travel_times = calculate_travel_times(
            cart_graph, 
            course_data["clubhouse_coords"], 
            hole_coords, 
            speeds
        )
        
        # Analyze routing efficiency
        analyze_routing_efficiency(travel_times)
        
        # Create simplified output
        simplified_output = create_simplified_output(travel_times)
        simplified_output["course_name"] = course_data["config"].get("course_name", "Unknown")
        
        # Save results
        with open(output_path, 'w') as f:
            json.dump(simplified_output, f, indent=2)
        
        print(f"Travel times calculated and saved to {output_path}")
        
        # Print summary
        print("\n📊 Summary:")
        print(f"   Course: {simplified_output['course_name']}")
        print(f"   Holes: {len(simplified_output['holes'])}")
        print(f"   Cart path network: {cart_graph.number_of_nodes()} nodes, {cart_graph.number_of_edges()} edges")
        print(f"   Cart speed: {simplified_output['cart_speed_mph']:.1f} mph")
        
        # Calculate simple statistics
        distances = [h["distance_m"] for h in simplified_output["holes"] if h["distance_m"] != "error"]
        times = [h["travel_time_min"] for h in simplified_output["holes"] if h["travel_time_min"] != "error"]
        
        if distances and times:
            print(f"   Distance range: {min(distances):.0f}-{max(distances):.0f}m (avg: {sum(distances)/len(distances):.0f}m)")
            print(f"   Time range: {min(times):.1f}-{max(times):.1f}min (avg: {sum(times)/len(times):.1f}min)")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
