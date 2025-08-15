#!/usr/bin/env python3
"""
Generate delivery time heatmap for golf course simulation results.

This script creates a heatmap visualization showing order placement locations
on the golf course, color-coded by average delivery times.

Usage:
    python scripts/viz/generate_delivery_heatmap.py --results-file path/to/results.json
    python scripts/viz/generate_delivery_heatmap.py --output-dir path/to/outputs/run_01
"""

import argparse
import json
import sys
from pathlib import Path

# Add project root to Python path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from golfsim.viz.heatmap_viz import create_course_heatmap, create_delivery_statistics_summary
from golfsim.logging import init_logging, get_logger

logger = get_logger(__name__)


def find_simulation_results(search_dir: Path) -> Path:
    """Find simulation results.json file in the given directory.
    
    Args:
        search_dir: Directory to search for results file
        
    Returns:
        Path to results.json file
        
    Raises:
        FileNotFoundError: If no results file is found
    """
    # Look for results.json directly
    results_file = search_dir / "results.json"
    if results_file.exists():
        return results_file
    
    # Look for results.json in subdirectories (run_01, run_02, etc.)
    for subdir in search_dir.glob("run_*"):
        if subdir.is_dir():
            results_file = subdir / "results.json"
            if results_file.exists():
                logger.info("Found results file: %s", results_file)
                return results_file
    
    raise FileNotFoundError(f"No results.json file found in {search_dir}")


def load_simulation_results(results_file: Path) -> dict:
    """Load simulation results from JSON file.
    
    Args:
        results_file: Path to results.json file
        
    Returns:
        Simulation results dictionary
    """
    try:
        with open(results_file, 'r', encoding='utf-8') as f:
            results = json.load(f)
        
        logger.info("Loaded simulation results: %d orders", len(results.get('orders', [])))
        return results
        
    except Exception as e:
        logger.error("Failed to load results file %s: %s", results_file, e)
        raise


def main():
    """Main function to generate delivery heatmap."""
    parser = argparse.ArgumentParser(
        description="Generate delivery time heatmap for golf simulation results",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Generate heatmap from specific results file
    python scripts/viz/generate_delivery_heatmap.py --results-file outputs/run_01/results.json
    
    # Generate heatmap from output directory (auto-finds results.json)
    python scripts/viz/generate_delivery_heatmap.py --output-dir outputs/20250815_070011_0bevcarts_1runners_0golfers_typical_weekday/run_02
    
    # Custom output path and title
    python scripts/viz/generate_delivery_heatmap.py --results-file results.json --output heatmap.png --title "Weekday Delivery Times"
        """
    )
    
    # Input options (mutually exclusive)
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        '--results-file', 
        type=Path,
        help='Path to simulation results.json file'
    )
    input_group.add_argument(
        '--output-dir',
        type=Path, 
        help='Path to simulation output directory (will auto-find results.json)'
    )
    
    # Output options
    parser.add_argument(
        '--output', '-o',
        type=Path,
        help='Output heatmap image path (default: heatmap.png in same directory as results)'
    )
    parser.add_argument(
        '--course-dir',
        type=Path,
        default=Path('courses/pinetree_country_club'),
        help='Path to course directory with geojson data (default: courses/pinetree_country_club)'
    )
    parser.add_argument(
        '--title',
        type=str,
        default='Golf Course Order Delivery Time Heatmap',
        help='Title for the heatmap plot'
    )
    parser.add_argument(
        '--resolution',
        type=int,
        default=100,
        help='Heatmap grid resolution (default: 100)'
    )
    parser.add_argument(
        '--colormap',
        type=str,
        default='RdYlGn_r',
        help='Matplotlib colormap name (default: RdYlGn_r)'
    )
    parser.add_argument(
        '--summary',
        action='store_true',
        help='Also generate a text summary of delivery statistics'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Enable verbose logging'
    )
    
    args = parser.parse_args()
    
    # Initialize logging
    log_level = 'DEBUG' if args.verbose else 'INFO'
    init_logging(level=log_level)
    
    try:
        # Find and load results file
        if args.results_file:
            results_file = args.results_file
            if not results_file.exists():
                logger.error("Results file not found: %s", results_file)
                return 1
        else:
            results_file = find_simulation_results(args.output_dir)
        
        results = load_simulation_results(results_file)
        
        # Determine output path
        if args.output:
            output_path = args.output
        else:
            output_path = results_file.parent / "delivery_heatmap.png"
        
        # Validate course directory
        if not args.course_dir.exists():
            logger.error("Course directory not found: %s", args.course_dir)
            return 1
        
        # Generate heatmap
        logger.info("Generating delivery heatmap...")
        saved_path = create_course_heatmap(
            results=results,
            course_dir=args.course_dir,
            save_path=output_path,
            title=args.title,
            grid_resolution=args.resolution,
            colormap=args.colormap
        )
        
        print(f"✓ Heatmap saved to: {saved_path}")
        
        # Generate summary if requested
        if args.summary:
            summary_path = output_path.with_suffix('.txt')
            from golfsim.viz.heatmap_viz import load_geofenced_holes
            hole_polygons = load_geofenced_holes(args.course_dir)
            
            summary_text = create_delivery_statistics_summary(
                results=results,
                hole_polygons=hole_polygons,
                save_path=summary_path
            )
            
            print(f"✓ Summary saved to: {summary_path}")
            print("\nDelivery Statistics Preview:")
            print("-" * 40)
            print(summary_text[:500] + "..." if len(summary_text) > 500 else summary_text)
        
        # Show order count and basic stats
        orders = results.get('orders', [])
        if orders:
            import numpy as np
            from golfsim.viz.heatmap_viz import extract_order_data
            
            order_data = extract_order_data(results)
            if order_data:
                delivery_times = [o['delivery_time_min'] for o in order_data]
                avg_time = np.mean(delivery_times)
                print(f"\n📊 Processed {len(order_data)} orders with avg delivery time: {avg_time:.1f} minutes")
            else:
                print(f"\n⚠️  Found {len(orders)} orders but no delivery time data")
        else:
            print("\n⚠️  No orders found in simulation results")
        
        return 0
        
    except Exception as e:
        logger.error("Failed to generate heatmap: %s", e)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
