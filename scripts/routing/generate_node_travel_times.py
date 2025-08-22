#!/usr/bin/env python3
"""
Pre-compute travel times from the clubhouse to all course nodes.

This script loads the cart path network graph and the list of connected nodes
(representing the golfer's path) and calculates the shortest travel time and
distance from the clubhouse to every single node on the course.

The output is a JSON file that maps each node index to its travel details,
which can be used by the simulation for highly accurate delivery time calculations.
"""

from __future__ import annotations
import argparse
import json
import pickle
from pathlib import Path
import sys

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from golfsim.routing.optimal_routing import find_optimal_route
from golfsim.logging import init_logging, get_logger

logger = get_logger(__name__)

def main():
    """Main script execution."""
    parser = argparse.ArgumentParser(description="Pre-compute travel times from clubhouse to all course nodes.")
    parser.add_argument("--course-dir", type=Path, default=Path("courses/pinetree_country_club"), help="Path to the course directory.")
    parser.add_argument("--output-file", type=Path, help="Output JSON file path. Defaults to [course_dir]/node_travel_times.json")
    parser.add_argument("--speed", type=float, default=2.68, help="Runner speed in meters per second for travel time calculation.")
    args = parser.parse_args()

    init_logging()

    # Set default output path if not provided
    if args.output_file is None:
        args.output_file = args.course_dir / "node_travel_times.json"

    # --- 1. Load required files ---
    try:
        # Load cart graph
        cart_graph_path = args.course_dir / "pkl" / "cart_graph.pkl"
        with cart_graph_path.open("rb") as f:
            graph = pickle.load(f)
        logger.info("Loaded cart graph from: %s", cart_graph_path)

        # Load clubhouse coordinates from simulation config
        config_path = args.course_dir / "config" / "simulation_config.json"
        with config_path.open("r") as f:
            config = json.load(f)
        clubhouse_coords = (config["clubhouse"]["longitude"], config["clubhouse"]["latitude"])
        logger.info("Loaded clubhouse coordinates: %s", clubhouse_coords)

        # Load connected nodes (golfer path)
        nodes_path = args.course_dir / "geojson" / "generated" / "holes_connected.geojson"
        with nodes_path.open("r") as f:
            nodes_geojson = json.load(f)
        
        # Extract point coordinates from GeoJSON features
        node_coords = [
            feature["geometry"]["coordinates"]
            for feature in nodes_geojson["features"]
            if feature["geometry"]["type"] == "Point"
        ]
        logger.info("Loaded %d nodes from: %s", len(node_coords), nodes_path)

    except FileNotFoundError as e:
        logger.error("Error loading required file: %s", e)
        sys.exit(1)
    except (KeyError, IndexError) as e:
        logger.error("Error parsing required file data: %s", e)
        sys.exit(1)


    # --- 2. Calculate travel times for each node ---
    travel_times_data = []
    failed_nodes = 0

    for i, node_coord in enumerate(node_coords):
        route_result = find_optimal_route(
            graph=graph,
            start_coords=clubhouse_coords,
            end_coords=tuple(node_coord),
            speed_mps=args.speed,
        )

        if route_result["success"]:
            travel_times_data.append({
                "node_index": i,
                "lon": node_coord[0],
                "lat": node_coord[1],
                "distance_m": route_result["metrics"]["length_m"],
                "time_s": route_result["metrics"]["time_s"],
            })
            if (i + 1) % 50 == 0:
                 logger.info("Calculated travel time for node %d/%d", i + 1, len(node_coords))
        else:
            failed_nodes += 1
            logger.warning("Failed to find route to node %d at %s. Error: %s", i, node_coord, route_result.get("error"))

    logger.info("Successfully calculated travel times for %d nodes.", len(travel_times_data))
    if failed_nodes > 0:
        logger.warning("%d nodes could not be reached from the clubhouse.", failed_nodes)

    # --- 3. Save the output file ---
    output_data = {
        "course_name": config.get("course_name", args.course_dir.name),
        "runner_speed_mps": args.speed,
        "clubhouse_coords": clubhouse_coords,
        "node_count": len(travel_times_data),
        "travel_times": travel_times_data,
    }

    try:
        with args.output_file.open("w") as f:
            json.dump(output_data, f, indent=2)
        logger.info("Successfully wrote node travel times to: %s", args.output_file)
    except IOError as e:
        logger.error("Error writing output file: %s", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
