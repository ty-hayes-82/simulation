#!/usr/bin/env python3
"""
Test script to validate routing integration across all components.

This comprehensive testing script ensures that the optimal routing integration
works correctly across all components of the golf delivery simulation system.
"""

import sys
import json
import pickle
import argparse
import networkx as nx
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import numpy as np
import pytest

# Ensure repository root is on sys.path for absolute imports like `utils` and `golfsim`
# scripts/routing/test_routing_integration.py → parents[2] is repo root
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from golfsim.logging import init_logging, get_logger
from utils.cli import add_log_level_argument, add_course_dir_argument

logger = get_logger(__name__)

from golfsim.routing.optimal_routing import find_optimal_route, calculate_path_metrics, validate_route_quality
from golfsim.routing.networks import shortest_path_on_cartpaths, nearest_node
from golfsim.simulation.engine import enhanced_delivery_routing, load_travel_times_data


def load_test_data() -> Dict:
    """Load test data for routing integration tests."""
    course_dir = Path("courses/pinetree_country_club")
    
    # Load cart graph
    cart_graph_path = course_dir / "pkl" / "cart_graph.pkl"
    if not cart_graph_path.exists():
        raise FileNotFoundError(f"Cart graph not found: {cart_graph_path}")
    
    with open(cart_graph_path, 'rb') as f:
        cart_graph = pickle.load(f)
    
    # Load configuration
    config_path = course_dir / "config" / "simulation_config.json"
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    clubhouse_coords = (config["clubhouse"]["longitude"], config["clubhouse"]["latitude"])
    
    # Load travel times data
    travel_times = load_travel_times_data(str(course_dir))
    
    # Generate test coordinates
    test_coordinates = []
    if travel_times and "holes" in travel_times:
        # Handle different travel times data formats
        holes_data = travel_times["holes"]
        if isinstance(holes_data, list):
            for hole_data in holes_data:
                if isinstance(hole_data, dict) and "tee_coords" in hole_data:
                    test_coordinates.append({
                        "name": f"hole_{hole_data['hole']}",
                        "coords": hole_data["tee_coords"]
                    })
        elif isinstance(holes_data, dict):
            for hole_num, hole_data in holes_data.items():
                if isinstance(hole_data, dict) and "tee_coords" in hole_data:
                    test_coordinates.append({
                        "name": f"hole_{hole_num}",
                        "coords": hole_data["tee_coords"]
                    })
    
    # Add some random test points within network bounds
    if cart_graph.number_of_nodes() > 0:
        nodes = list(cart_graph.nodes())
        # Use simple indexing instead of np.random.choice for compatibility
        num_samples = min(10, len(nodes))
        indices = np.random.choice(len(nodes), num_samples, replace=False)
        for i, idx in enumerate(indices):
            node = nodes[idx]
            node_data = cart_graph.nodes[node]
            test_coordinates.append({
                "name": f"random_node_{i}",
                "coords": (node_data['x'], node_data['y'])
            })
    
    return {
        "cart_graph": cart_graph,
        "clubhouse_coords": clubhouse_coords,
        "travel_times": travel_times,
        "test_coordinates": test_coordinates,
        "config": config
    }


# Provide pytest fixture for tests below
@pytest.fixture(scope="module")
def test_data() -> Dict:
    return load_test_data()


def test_routing_consistency(test_data: Dict) -> Dict:
    """Test that all routing components produce consistent results."""
    logger.info("Testing networks.py consistency...")
    
    cart_graph = test_data["cart_graph"]
    clubhouse_coords = test_data["clubhouse_coords"]
    test_coordinates = test_data["test_coordinates"]
    
    results = {
        "total_tests": 0,
        "passed": 0,
        "failed": 0,
        "details": []
    }
    
    for test_point in test_coordinates[:5]:  # Test first 5 points
        test_name = test_point["name"]
        target_coords = test_point["coords"]
        
        try:
            # Test optimal routing directly
            optimal_result = find_optimal_route(cart_graph, clubhouse_coords, target_coords, 6.0)
            
            # Test networks.py routing (should use optimal routing internally)
            networks_result = shortest_path_on_cartpaths(cart_graph, clubhouse_coords, target_coords, 6.0)
            
            results["total_tests"] += 1
            
            if optimal_result["success"]:
                # Compare results
                distance_diff = abs(optimal_result["metrics"]["length_m"] - networks_result["length_m"])
                time_diff = abs(optimal_result["metrics"]["time_s"] - networks_result["time_s"])
                
                # Allow small differences due to rounding
                if distance_diff < 1.0 and time_diff < 1.0:
                    results["passed"] += 1
                    status = "PASSED"
                else:
                    results["failed"] += 1
                    status = "FAILED"
                
                results["details"].append({
                    "test": test_name,
                    "status": status,
                    "optimal_distance": optimal_result["metrics"]["length_m"],
                    "networks_distance": networks_result["length_m"],
                    "distance_diff": distance_diff,
                    "optimal_time": optimal_result["metrics"]["time_s"],
                    "networks_time": networks_result["time_s"],
                    "time_diff": time_diff
                })
                
                logger.info(f"   {status} {test_name}: Distance diff {distance_diff:.1f}m, Time diff {time_diff:.1f}s")
            else:
                results["failed"] += 1
                results["details"].append({
                    "test": test_name,
                    "status": "FAILED",
                    "error": optimal_result["error"]
                })
                logger.error(f"   FAILED {test_name}: {optimal_result['error']}")
                
        except Exception as e:
            results["failed"] += 1
            results["details"].append({
                "test": test_name,
                "status": "FAILED",
                "error": str(e)
            })
            logger.error(f"   FAILED {test_name}: {e}")
    
    return results


def test_travel_times_accuracy(test_data: Dict) -> Dict:
    """Test travel times accuracy and efficiency data."""
    logger.info("Testing travel times accuracy...")
    
    travel_times = test_data["travel_times"]
    cart_graph = test_data["cart_graph"]
    clubhouse_coords = test_data["clubhouse_coords"]
    
    results = {
        "total_holes": 0,
        "with_efficiency": 0,
        "without_efficiency": 0,
        "accuracy_tests": []
    }
    
    if not travel_times or "holes" not in travel_times:
        logger.info("   No travel times data available")
        return results
    
    holes_data = travel_times["holes"]
    holes_to_process = []
    
    if isinstance(holes_data, list):
        holes_to_process = holes_data
    elif isinstance(holes_data, dict):
        holes_to_process = list(holes_data.values())
    
    for hole_data in holes_to_process:
        if not isinstance(hole_data, dict):
            continue
            
        results["total_holes"] += 1
        hole_num = hole_data.get("hole", "unknown")
        
        if "travel_times" in hole_data and "golf_cart" in hole_data["travel_times"]:
            cart_data = hole_data["travel_times"]["golf_cart"]
            
            if "efficiency" in cart_data:
                results["with_efficiency"] += 1
                
                # Test accuracy by recalculating route
                tee_coords = hole_data.get("tee_coords")
                if tee_coords:
                    try:
                        fresh_result = find_optimal_route(cart_graph, clubhouse_coords, tee_coords, 6.0)
                        
                        if fresh_result["success"]:
                            stored_distance = cart_data["distance_m"]
                            fresh_distance = fresh_result["metrics"]["length_m"]
                            distance_diff = abs(stored_distance - fresh_distance)
                            
                            # Allow 5% difference for acceptable accuracy
                            accuracy_threshold = stored_distance * 0.05
                            is_accurate = distance_diff <= accuracy_threshold
                            
                            results["accuracy_tests"].append({
                                "hole": hole_num,
                                "stored_distance": stored_distance,
                                "fresh_distance": fresh_distance,
                                "difference": distance_diff,
                                "accurate": is_accurate
                            })
                            
                            status = "✅" if is_accurate else "⚠️"
                            logger.info(f"   {status} Hole {hole_num}: {distance_diff:.1f}m difference ({distance_diff/stored_distance*100:.1f}%)")
                    except Exception as e:
                        logger.error(f"   Hole {hole_num}: Error recalculating - {e}")
            else:
                results["without_efficiency"] += 1
                logger.info(f"    Hole {hole_num}: Missing efficiency data")
    
    return results


def test_simulation_routing(test_data: Dict) -> Dict:
    """Test simulation routing integration."""
    logger.info("Testing simulation routing...")
    
    cart_graph = test_data["cart_graph"]
    clubhouse_coords = test_data["clubhouse_coords"]
    test_coordinates = test_data["test_coordinates"]
    
    results = {
        "total_tests": 0,
        "passed": 0,
        "failed": 0,
        "details": []
    }
    
    for test_point in test_coordinates[:3]:  # Test first 3 points
        test_name = test_point["name"]
        target_coords = test_point["coords"]
        
        try:
            # Test enhanced delivery routing
            enhanced_result = enhanced_delivery_routing(cart_graph, clubhouse_coords, target_coords, 6.0)
            
            # Test optimal routing directly for comparison
            optimal_result = find_optimal_route(cart_graph, clubhouse_coords, target_coords, 6.0)
            
            results["total_tests"] += 1
            
            if optimal_result["success"]:
                # Compare results
                distance_diff = abs(optimal_result["metrics"]["length_m"] - enhanced_result["length_m"])
                
                if distance_diff < 1.0:  # Allow small rounding differences
                    results["passed"] += 1
                    status = "PASSED"
                    logger.info(f"   {test_name}: Enhanced routing consistent with optimal")
                else:
                    results["failed"] += 1
                    status = "FAILED"
                    logger.info(f"   {test_name}: Distance difference {distance_diff:.1f}m")
                
                results["details"].append({
                    "test": test_name,
                    "status": status,
                    "enhanced_distance": enhanced_result["length_m"],
                    "optimal_distance": optimal_result["metrics"]["length_m"],
                    "difference": distance_diff,
                    "efficiency": enhanced_result.get("efficiency", "N/A")
                })
            else:
                results["failed"] += 1
                logger.error(f"   {test_name}: Optimal routing failed - {optimal_result['error']}")
                
        except Exception as e:
            results["failed"] += 1
            results["details"].append({
                "test": test_name,
                "status": "FAILED",
                "error": str(e)
            })
            logger.info(f"   {test_name}: Exception - {e}")
    
    return results


def test_network_enhancement(test_data: Dict) -> Dict:
    """Test network enhancement validation."""
    logger.info("Testing network enhancement...")
    
    cart_graph = test_data["cart_graph"]
    clubhouse_coords = test_data["clubhouse_coords"]
    
    results = {
        "network_stats": {
            "nodes": cart_graph.number_of_nodes(),
            "edges": cart_graph.number_of_edges(),
            "connected_components": len(list(nx.connected_components(cart_graph)))
        },
        "routing_tests": 0,
        "successful_routes": 0,
        "failed_routes": 0
    }
    
    # Test routing to various points in the network
    test_nodes = list(cart_graph.nodes())[:10]  # Test first 10 nodes
    
    for node in test_nodes:
        try:
            node_data = cart_graph.nodes[node]
            target_coords = (node_data['x'], node_data['y'])
            
            route_result = find_optimal_route(cart_graph, clubhouse_coords, target_coords, 6.0)
            results["routing_tests"] += 1
            
            if route_result["success"]:
                results["successful_routes"] += 1
                
                # Validate route quality
                quality = validate_route_quality(route_result)
                if quality["quality_score"] in ["excellent", "good"]:
                    logger.info(f"   Node {node}: {quality['quality_score']} route ({route_result['efficiency']:.1f}% efficiency)")
                else:
                    logger.info(f"    Node {node}: {quality['quality_score']} route ({route_result['efficiency']:.1f}% efficiency)")
            else:
                results["failed_routes"] += 1
                logger.error(f"   Node {node}: Routing failed - {route_result['error']}")
                
        except Exception as e:
            results["failed_routes"] += 1
            logger.error(f"   Node {node}: Exception - {e}")
    
    return results


def run_comprehensive_test() -> Dict:
    """Run all integration tests and return comprehensive results."""
    logger.info(" GOLF DELIVERY ROUTING INTEGRATION TESTS")
    logger.info("=" * 60)
    
    try:
        # Load test data
        logger.info("Loading test data...")
        test_data = load_test_data()
        logger.info(f"   Cart network: {test_data['cart_graph'].number_of_nodes()} nodes, {test_data['cart_graph'].number_of_edges()} edges")
        logger.info(f"   Clubhouse: {test_data['clubhouse_coords']}")
        logger.info(f"   Test coordinates: {len(test_data['test_coordinates'])} points")
        
        # Run all tests
        all_results = {
            "consistency": test_routing_consistency(test_data),
            "travel_times": test_travel_times_accuracy(test_data),
            "simulation": test_simulation_routing(test_data),
            "network": test_network_enhancement(test_data)
        }
        
        # Generate summary
        logger.info("\n📊 TEST SUMMARY")
        logger.info("=" * 30)
        
        total_tests = 0
        total_passed = 0
        total_failed = 0
        
        for test_name, results in all_results.items():
            if "total_tests" in results:
                total_tests += results.get("total_tests", 0)
                total_passed += results.get("passed", 0)
                total_failed += results.get("failed", 0)
                
                success_rate = (results["passed"] / max(results["total_tests"], 1)) * 100
                logger.info(f"{test_name.capitalize()}: {results['passed']}/{results['total_tests']} passed ({success_rate:.1f}%)")
        
        if total_tests > 0:
            overall_success_rate = (total_passed / total_tests) * 100
            logger.info(f"\nOverall: {total_passed}/{total_tests} passed ({overall_success_rate:.1f}%)")
            
            if overall_success_rate >= 90:
                logger.info("🎉 EXCELLENT: Integration is working very well!")
            elif overall_success_rate >= 75:
                logger.info("GOOD: Integration is working well with minor issues")
            elif overall_success_rate >= 50:
                logger.info(" FAIR: Integration has some issues that should be addressed")
            else:
                logger.info("POOR: Integration has significant issues requiring attention")
        
        # Travel times specific summary
        travel_results = all_results["travel_times"]
        if travel_results["total_holes"] > 0:
            efficiency_coverage = (travel_results["with_efficiency"] / travel_results["total_holes"]) * 100
            logger.info(f"\nTravel Times: {travel_results['with_efficiency']}/{travel_results['total_holes']} holes have efficiency data ({efficiency_coverage:.1f}%)")
        
        return all_results
        
    except Exception as e:
        logger.error(f"CRITICAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}


def main():
    """Main function with argument parsing."""
    parser = argparse.ArgumentParser(description="Test routing integration across all components")
    add_log_level_argument(parser)
    
    args = parser.parse_args()
    init_logging(args.log_level)
    
    results = run_comprehensive_test()
    
    # Exit with appropriate code
    if "error" in results:
        sys.exit(1)
    
    # Check if any tests failed
    failed_any = False
    for test_results in results.values():
        if isinstance(test_results, dict) and test_results.get("failed", 0) > 0:
            failed_any = True
            break
    
    sys.exit(1 if failed_any else 0)

if __name__ == "__main__":
    main()
