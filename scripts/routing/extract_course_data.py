"""
Step 1: Extract and Save OpenStreetMap Data for Golf Course Simulation

This script extracts all necessary data from OpenStreetMap for a golf course
and saves it to files that can be used by the simulation script. This includes
golf course features (holes, tees, greens), cart paths, and optionally nearby
roads that can be used for delivery shortcuts.

Usage:
    Basic extraction (includes automatic geofenced hole generation):
        python scripts/extract_course_data.py --course "Pinetree Country Club" --clubhouse-lat 34.0379 --clubhouse-lon -84.5928
    
    With street data for delivery shortcuts:
        python scripts/extract_course_data.py --course "Pinetree Country Club" --clubhouse-lat 34.0379 --clubhouse-lon -84.5928 --include-streets --street-buffer 750 --course-buffer 100
    
    Skip automatic geofencing:
        python scripts/extract_course_data.py --course "Pinetree Country Club" --clubhouse-lat 34.0379 --clubhouse-lon -84.5928 --skip-geofencing
    
    Custom geofencing parameters:
        python scripts/extract_course_data.py --course "Pinetree Country Club" --clubhouse-lat 34.0379 --clubhouse-lon -84.5928 --geofence-step 15.0 --geofence-smooth 2.0

Features:
    - Golf course polygon, holes, tees, greens from OpenStreetMap
    - Cart path network for on-course navigation
    - Automatic geofenced hole polygon generation using Voronoi tessellation
    - Optional street network extraction for delivery shortcuts
    - Combined routing network that connects cart paths to nearby roads
    - Configurable buffer distance for street extraction
    - Configurable geofencing parameters (step size, smoothing, point density)
"""
import argparse
import os
import sys
import json
import pickle
import geopandas as gpd
from shapely.geometry import mapping
import networkx as nx
from pathlib import Path

# Add the project root to Python path to enable imports
sys.path.append(str(Path(__file__).parent.parent.parent))

from scripts.course_prep.geofence_holes import split_course_into_holes

from golfsim.data.osm_ingest import load_course, build_cartpath_graph, _get_streets_near_course
from golfsim.preprocess.course_model import build_traditional_route
from golfsim.logging import init_logging, get_logger
from utils.cli import add_log_level_argument

logger = get_logger(__name__)


def save_course_data(data, output_dir):
    """Save course data to files"""
    geojson_dir = os.path.join(output_dir, "geojson")
    os.makedirs(geojson_dir, exist_ok=True)
    
    # Save course polygon as GeoJSON
    if data["course_poly"]:
        course_gdf = gpd.GeoDataFrame(
            [{"name": "course_polygon"}], 
            geometry=[data["course_poly"]], 
            crs="EPSG:4326"
        )
        course_gdf.to_file(os.path.join(geojson_dir, "course_polygon.geojson"), driver="GeoJSON")
        logger.info(f"Saved course polygon to {geojson_dir}/course_polygon.geojson")
    
    # Save holes data
    if len(data["holes"]) > 0:
        data["holes"].to_file(os.path.join(geojson_dir, "holes.geojson"), driver="GeoJSON")
        logger.info(f"Saved {len(data['holes'])} holes to {geojson_dir}/holes.geojson")
    
    # Save tees data
    if len(data["tees"]) > 0:
        data["tees"].to_file(os.path.join(geojson_dir, "tees.geojson"), driver="GeoJSON")
        print(f"✓ Saved {len(data['tees'])} tees to {geojson_dir}/tees.geojson")
    
    # Save greens data
    if len(data["greens"]) > 0:
        data["greens"].to_file(os.path.join(geojson_dir, "greens.geojson"), driver="GeoJSON")
        print(f"✓ Saved {len(data['greens'])} greens to {geojson_dir}/greens.geojson")


def save_cart_paths(graph, output_dir):
    """Save cart path graph as GeoJSON and pickle"""
    geojson_dir = os.path.join(output_dir, "geojson")
    pkl_dir = os.path.join(output_dir, "pkl")
    os.makedirs(geojson_dir, exist_ok=True)
    os.makedirs(pkl_dir, exist_ok=True)
    
    if graph.number_of_edges() > 0:
        # Save as GeoJSON for visualization
        features = []
        for u, v, data in graph.edges(data=True):
            u_node = graph.nodes[u]
            v_node = graph.nodes[v]
            geometry = {
                "type": "LineString",
                "coordinates": [[u_node['x'], u_node['y']], [v_node['x'], v_node['y']]]
            }
            properties = {
                "length": data.get('length', 0),
                "highway": data.get('highway', 'unknown')
            }
            # Add golf-related tags if present
            if 'golf' in data:
                properties['golf'] = data['golf']
            if 'golf_cart' in data:
                properties['golf_cart'] = data['golf_cart']
            
            feature = {
                "type": "Feature",
                "geometry": geometry,
                "properties": properties
            }
            features.append(feature)
        
        geojson = {
            "type": "FeatureCollection",
            "features": features
        }
        
        with open(os.path.join(geojson_dir, "cart_paths.geojson"), 'w') as f:
            json.dump(geojson, f, indent=2)
        print(f"✓ Saved cart paths GeoJSON to {geojson_dir}/cart_paths.geojson")
        
        # Save graph as pickle for simulation use
        with open(os.path.join(pkl_dir, "cart_graph.pkl"), 'wb') as f:
            pickle.dump(graph, f)
        print(f"✓ Saved cart graph pickle to {pkl_dir}/cart_graph.pkl")
        
        return True
    else:
        print("⚠ No cart paths found!")
        return False


def save_route_data(route_data, output_dir, save_hole_lines=True):
    """Save golf route data"""
    geojson_dir = os.path.join(output_dir, "geojson")
    pkl_dir = os.path.join(output_dir, "pkl")
    os.makedirs(geojson_dir, exist_ok=True)
    os.makedirs(pkl_dir, exist_ok=True)
    
    # Save hole lines as GeoJSON (optional, since holes.geojson contains this info)
    if save_hole_lines and route_data["hole_lines"]:
        hole_features = []
        for hole_num, line in route_data["hole_lines"].items():
            feature = {
                "type": "Feature",
                "geometry": mapping(line),
                "properties": {"hole": hole_num}
            }
            hole_features.append(feature)
        
        hole_geojson = {
            "type": "FeatureCollection",
            "features": hole_features
        }
        
        with open(os.path.join(geojson_dir, "hole_lines.geojson"), 'w') as f:
            json.dump(hole_geojson, f, indent=2)
        print(f"✓ Saved hole lines to {geojson_dir}/hole_lines.geojson")
    elif not save_hole_lines:
        print("⊘ Skipped saving hole lines (using holes.geojson instead)")
    
    # Save full route as pickle
    with open(os.path.join(pkl_dir, "golf_route.pkl"), 'wb') as f:
        pickle.dump(route_data["route"], f)
    print(f"✓ Saved golf route pickle to {pkl_dir}/golf_route.pkl")
    
    # Save route summary
    route_summary = {
        "total_holes": len(route_data["hole_lines"]),
        "route_length_coords": len(list(route_data["route"].coords)),
        "bbox": list(route_data["route"].bounds)
    }
    
    with open(os.path.join(output_dir, "route_summary.json"), 'w') as f:
        json.dump(route_summary, f, indent=2)
    print(f"✓ Saved route summary to {output_dir}/route_summary.json")


def save_streets_data(streets_gdf, output_dir):
    """Save streets data to a GeoJSON file."""
    if streets_gdf is not None and not streets_gdf.empty:
        geojson_dir = os.path.join(output_dir, "geojson")
        pkl_dir = os.path.join(output_dir, "pkl")
        os.makedirs(geojson_dir, exist_ok=True)
        os.makedirs(pkl_dir, exist_ok=True)
        
        streets_path = os.path.join(geojson_dir, "streets.geojson")
        streets_gdf.to_file(streets_path, driver="GeoJSON")
        print(f"✓ Saved {len(streets_gdf)} streets to {streets_path}")
        
        # Build a street network graph for routing
        street_graph = build_street_graph(streets_gdf)
        if street_graph.number_of_edges() > 0:
            with open(os.path.join(pkl_dir, "street_graph.pkl"), 'wb') as f:
                pickle.dump(street_graph, f)
            print(f"✓ Saved street graph pickle to {pkl_dir}/street_graph.pkl")
        
        return True
    else:
        print("⊘ No streets data to save.")
        return False


def build_street_graph(streets_gdf):
    """Build a NetworkX graph from street GeoDataFrame"""
    G = nx.Graph()
    G.graph["crs"] = "EPSG:4326"
    
    for idx, row in streets_gdf.iterrows():
        geom = row.geometry
        if geom and hasattr(geom, 'coords'):
            coords = list(geom.coords)
            # Extract street metadata
            edge_data = {
                'highway': row.get('highway', 'unknown'),
                'name': row.get('name', 'unnamed'),
                'maxspeed': row.get('maxspeed', None),
                'surface': row.get('surface', None)
            }
            _add_linestring_to_graph_with_data(G, coords, edge_data)
    
    return G


def _add_linestring_to_graph_with_data(G, coords, edge_data):
    """Add a linestring to the graph with metadata (copied from osm_ingest.py)"""
    last = None
    for lon, lat in coords:
        node = (round(lon, 7), round(lat, 7))
        if node not in G:
            G.add_node(node, x=lon, y=lat)
        if last is not None:
            # Calculate distance in meters
            from math import radians, cos, sin, asin, sqrt
            
            # Haversine formula for accurate distance
            lat1, lon1 = radians(G.nodes[last]["y"]), radians(G.nodes[last]["x"])
            lat2, lon2 = radians(lat), radians(lon)
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
            c = 2 * asin(sqrt(a))
            length = 6371000 * c  # Earth radius in meters
            
            # Combine length with edge data
            edge_attrs = {"length": length}
            edge_attrs.update(edge_data)
            G.add_edge(last, node, **edge_attrs)
        last = node


def save_combined_routing_network(cart_graph, street_graph, output_dir):
    """Combine cart paths and nearby streets into a unified routing network"""
    pkl_dir = os.path.join(output_dir, "pkl")
    os.makedirs(pkl_dir, exist_ok=True)
    
    # Create combined graph
    combined_graph = nx.Graph()
    combined_graph.graph["crs"] = "EPSG:4326"
    
    # Add cart paths
    if cart_graph.number_of_edges() > 0:
        for u, v, data in cart_graph.edges(data=True):
            # Mark as cart path
            edge_data = data.copy()
            edge_data['network_type'] = 'cart_path'
            combined_graph.add_edge(u, v, **edge_data)
        
        # Add cart path nodes
        for node, data in cart_graph.nodes(data=True):
            combined_graph.add_node(node, **data)
    
    # Add street network  
    if street_graph.number_of_edges() > 0:
        for u, v, data in street_graph.edges(data=True):
            # Mark as street and apply speed penalty for delivery vehicles
            edge_data = data.copy()
            edge_data['network_type'] = 'street'
            # Add delivery penalty - streets are slower for golf cart deliveries
            edge_data['delivery_weight'] = edge_data.get('length', 0) * 1.5  # 50% penalty
            combined_graph.add_edge(u, v, **edge_data)
        
        # Add street nodes
        for node, data in street_graph.nodes(data=True):
            if node not in combined_graph:
                combined_graph.add_node(node, **data)
    
    # Connect cart paths to nearby streets for inter-network routing
    if cart_graph.number_of_edges() > 0 and street_graph.number_of_edges() > 0:
        _connect_cart_paths_to_streets(combined_graph, cart_graph, street_graph)
    
    # Save combined network
    with open(os.path.join(pkl_dir, "combined_routing_graph.pkl"), 'wb') as f:
        pickle.dump(combined_graph, f)
    
    print(f"✓ Saved combined routing network: {combined_graph.number_of_nodes()} nodes, {combined_graph.number_of_edges()} edges")
    return combined_graph


def _connect_cart_paths_to_streets(combined_graph, cart_graph, street_graph, max_connection_distance_m=100):
    """Connect cart path network to street network at nearby intersection points"""
    connections_made = 0
    
    # Find cart path nodes near course boundary that could connect to streets
    for cart_node in cart_graph.nodes():
        cart_x, cart_y = cart_graph.nodes[cart_node]['x'], cart_graph.nodes[cart_node]['y']
        
        # Find nearest street nodes
        min_dist = float('inf')
        nearest_street_node = None
        
        for street_node in street_graph.nodes():
            street_x, street_y = street_graph.nodes[street_node]['x'], street_graph.nodes[street_node]['y']
            
            # Calculate distance
            from math import radians, cos, sin, asin, sqrt
            lat1, lon1 = radians(cart_y), radians(cart_x)
            lat2, lon2 = radians(street_y), radians(street_x)
            dlat = lat2 - lat1
            dlon = lon2 - lon1
            a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
            c = 2 * asin(sqrt(a))
            distance_m = 6371000 * c
            
            if distance_m < min_dist:
                min_dist = distance_m
                nearest_street_node = street_node
        
        # Connect if close enough
        if nearest_street_node and min_dist <= max_connection_distance_m:
            combined_graph.add_edge(
                cart_node, 
                nearest_street_node,
                length=min_dist,
                network_type='connection',
                delivery_weight=min_dist * 2.0  # Higher penalty for network transitions
            )
            connections_made += 1
    
    print(f"✓ Created {connections_made} cart-path-to-street connections")
    return connections_made


def save_simulation_config(args, output_dir):
    """Create or merge simulation configuration without overwriting existing values unnecessarily."""
    config_dir = os.path.join(output_dir, "config")
    os.makedirs(config_dir, exist_ok=True)
    config_path = os.path.join(config_dir, "simulation_config.json")

    # Template with sensible defaults (matches documented structure)
    default_config = {
        "course_name": args.course,
        "within": args.within,
        "state": args.state,
        "bbox": args.bbox,
        "clubhouse": {
            "latitude": args.clubhouse_lat,
            "longitude": args.clubhouse_lon,
        },
        "extraction_params": {
            "broaden": bool(args.broaden),
            "include_streets": bool(args.include_streets),
            "street_buffer_m": int(args.street_buffer),
            "course_buffer_m": int(args.course_buffer),
            "combined_network": (not args.no_combined_network),
        },
        "network_params": {
            "auto_connect_clubhouse": True,
            "max_connection_distance_m": 500.0,
            "connect_on_network_build": True,
        },
        # Simulation timing and economics defaults (preserved if file exists)
        "golfer_18_holes_hours": 4.25,
        "bev_cart_18_holes_hours": 3.0,
        "delivery_runner_speed_mph": 6.0,
        "delivery_prep_time_sec": 600,
        "bev_cart_avg_order_usd": 12.50,
        "delivery_avg_order_usd": 30.00,
        "bev_cart_order_probability": 0.4,
        "delivery_order_probability_per_9_holes": 0.2,
        "delivery_service_hours": {
            "open_time": "11:00",
            "close_time": "18:00",
            "description": "Delivery service operates 11:00 AM to 6:00 PM",
        },
        "bev_cart_service_hours": {
            "start_time": "09:00",
            "end_time": "17:00",
            "description": "Beverage cart operates 9:00 AM to 5:00 PM",
        },
    }

    def merge_missing(dst, src):
        """Recursively add keys from src into dst only when missing. Returns True if modified."""
        modified = False
        for key, value in src.items():
            if key not in dst:
                dst[key] = value
                modified = True
            else:
                if isinstance(value, dict) and isinstance(dst[key], dict):
                    if merge_missing(dst[key], value):
                        modified = True
        return modified

    if os.path.exists(config_path):
        # Load existing and only fill in missing fields
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {}
        changed = merge_missing(existing, default_config)
        if changed:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(existing, f, indent=2)
            logger.info(f"Updated simulation config with missing defaults at {config_path}")
        else:
            logger.info(f"Simulation config already present and up-to-date at {config_path}")
    else:
        # Create new file from template
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(default_config, f, indent=2)
        logger.info(f"Created simulation config at {config_path}")


def main():
    parser = argparse.ArgumentParser(description="Extract OpenStreetMap data for golf course simulation")
    add_log_level_argument(parser)
    parser.add_argument("--course", required=True, help="Course name, e.g., 'Pinetree Country Club'")
    parser.add_argument("--within", default=None, help="Place context to search within, e.g., 'Kennesaw, GA, USA'")
    parser.add_argument("--state", default=None, help="State to search within, e.g., 'Georgia' or 'GA'")
    parser.add_argument("--bbox", default=None, help="Optional bbox 'west,south,east,north'")
    parser.add_argument("--clubhouse-lat", type=float, required=True, help="Clubhouse latitude")
    parser.add_argument("--clubhouse-lon", type=float, required=True, help="Clubhouse longitude")
    parser.add_argument("--broaden", action="store_true", help="Broaden OSM path filter if cart paths are sparse")
    
    # Street extraction options
    parser.add_argument("--include-streets", action="store_true", help="Include nearby roads for delivery shortcuts")
    parser.add_argument("--street-buffer", type=int, default=500, help="Search buffer distance in meters for street extraction (default: 500m)")
    parser.add_argument("--course-buffer", type=int, default=100, help="Filter buffer distance in meters - only keep streets within this distance of course boundary (default: 100m)")
    parser.add_argument("--no-combined-network", action="store_true", help="Skip creating combined cart path + street routing network")
    
    # Geofencing options
    parser.add_argument("--skip-geofencing", action="store_true", help="Skip automatic generation of geofenced hole polygons")
    parser.add_argument("--geofence-step", type=float, default=20.0, help="Densify step in meters along hole centerlines for geofencing (default: 20.0)")
    parser.add_argument("--geofence-smooth", type=float, default=1.0, help="Boundary smoothing distance in meters for geofenced holes (default: 1.0)")
    parser.add_argument("--geofence-max-points", type=int, default=300, help="Maximum seed points per hole for geofencing tessellation (default: 300)")

    parser.add_argument("--output-dir", default="courses/pinetree_country_club", help="Output directory for saved data")
    
    args = parser.parse_args()
    init_logging(args.log_level)
    
    logger.info(f"Extracting data for {args.course}...")
    
    # Parse bbox if provided
    bbox = None
    if args.bbox:
        west, south, east, north = map(float, args.bbox.split(","))
        bbox = (west, south, east, north)
    
    try:
        # Step 1: Load course data from OSM (including cart paths and optionally streets)
        print("\nLoading course data from OpenStreetMap...")
        data = load_course(
            course_name=args.course, 
            within=args.within, 
            bbox=bbox, 
            state=args.state,
            center_lat=args.clubhouse_lat,
            center_lon=args.clubhouse_lon,
            radius_km=10.0,
            include_cart_paths=True,
            broaden=args.broaden,
            include_streets=False  # We'll handle this separately to use custom buffer
        )
        
        # Handle street extraction with custom buffer distance
        if args.include_streets:
            print(f"\nFetching nearby streets (search: {args.street_buffer}m, filter: {args.course_buffer}m)...")
            streets_gdf = _get_streets_near_course(
                data["course_poly"], 
                buffer_dist_m=args.street_buffer,
                course_buffer_m=args.course_buffer
            )
            data["streets"] = streets_gdf
            if len(streets_gdf) > 0:
                print(f"   ✓ Found {len(streets_gdf)} street segments within course geofence")
            else:
                print(f"   ⚠ No streets found within {args.course_buffer}m of course boundary")
        print(f"✓ Found course polygon with {len(data['holes'])} holes, {len(data['tees'])} tees, {len(data['greens'])} greens")
        
        # Step 2: Extract cart path graph (already built in load_course)
        print("\nCart path network loaded...")
        cart_graph = data["cart_graph"]
        print(f"✓ Built cart path graph with {cart_graph.number_of_nodes()} nodes and {cart_graph.number_of_edges()} edges")
        
        # Step 2: Build traditional golf route (skip hole lines since they're in holes.geojson)
        print("\n⛳ Building traditional golf route...")
        route_data = build_traditional_route(data, strict_18=True)
        print(f"✓ Built route with {len(route_data['hole_lines'])} hole segments")
        
        # Step 3: Save all data
        print(f"\n💾 Saving data to {args.output_dir}/...")
        save_course_data(data, args.output_dir)
        
        # Auto-generate geofenced holes if enabled and both boundary and holes were saved
        if not args.skip_geofencing:
            try:
                geojson_dir = os.path.join(args.output_dir, "geojson")
                boundary_path = os.path.join(geojson_dir, "course_polygon.geojson")
                holes_path = os.path.join(geojson_dir, "holes.geojson")
                if os.path.exists(boundary_path) and os.path.exists(holes_path):
                    print("\n⛳ Generating geofenced hole polygons...")
                    generated_dir = os.path.join(geojson_dir, "generated")
                    os.makedirs(generated_dir, exist_ok=True)
                    out_path = os.path.join(generated_dir, "holes_geofenced.geojson")
                    
                    split_course_into_holes(
                        course_polygon_path=boundary_path,
                        hole_lines_path=holes_path,
                        output_path=out_path,
                        step_m=args.geofence_step,
                        smooth_m=args.geofence_smooth,
                        max_points_per_hole=args.geofence_max_points,
                    )
                    print(f"✓ Saved geofenced holes to {out_path}")
                    logger.info(f"Generated geofenced holes with {args.geofence_step}m step, {args.geofence_smooth}m smoothing")
                else:
                    print("⊘ Skipping geofenced holes: boundary or holes GeoJSON not found")
                    logger.warning("Skipping geofenced holes: boundary or holes GeoJSON not found")
            except Exception as ge:
                print(f"⚠ Failed to create geofenced holes automatically: {ge}")
                logger.warning(f"Failed to create geofenced holes automatically: {ge}")
        else:
            print("⊘ Skipping geofenced holes generation (disabled via --skip-geofencing)")
        cart_paths_saved = save_cart_paths(cart_graph, args.output_dir)
        
        # Handle street data if included
        streets_saved = False
        street_graph = None
        if args.include_streets and "streets" in data:
            streets_saved = save_streets_data(data["streets"], args.output_dir)
            if streets_saved:
                street_graph = build_street_graph(data["streets"])
        
        # Create combined routing network
        if not args.no_combined_network and cart_paths_saved:
            print("\nCreating combined routing network...")
            if street_graph and street_graph.number_of_edges() > 0:
                save_combined_routing_network(cart_graph, street_graph, args.output_dir)
            else:
                print("   No street data available for combined network")

        save_route_data(route_data, args.output_dir, save_hole_lines=False)
        save_simulation_config(args, args.output_dir)
        
        print(f"\n✅ Data extraction complete!")
        print(f"All files saved to: {os.path.abspath(args.output_dir)}")
        
        # Check if geofenced holes were generated
        geofenced_path = os.path.join(args.output_dir, "geojson", "generated", "holes_geofenced.geojson")
        if not args.skip_geofencing and os.path.exists(geofenced_path):
            print(f"📐 Geofenced hole polygons: {geofenced_path}")
        elif args.skip_geofencing:
            print("📐 Geofenced holes skipped (use --geofence-* options to customize)")
        
        if not cart_paths_saved:
            print("\n⚠️ WARNING: No cart paths found. You may need to:")
            print("   - Use --broaden flag to include more path types")
            print("   - Provide a custom cart path GeoJSON file")
            print("   - Check if the course area has sufficient OSM data")
        
        print(f"\n🎮 Next step: Run the simulation with:")
        print(f"   python step2_run_simulation.py --data-dir {args.output_dir}")
        
        if args.include_streets and streets_saved:
            print(f"\nStreet data extracted and saved:")
            print(f"   - Street network graph: {args.output_dir}/pkl/street_graph.pkl")
            if not args.no_combined_network:
                print(f"   - Combined routing network: {args.output_dir}/pkl/combined_routing_graph.pkl")
                print(f"   - Use combined network for delivery route optimization with road shortcuts")
        
    except Exception as e:
        print(f"\nError during data extraction: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
