#!/usr/bin/env python3
"""
LCM Course Nodes Generator (Unified Wrapper)

This script provides a modern command-line interface to generate LCM-optimized
course nodes using the sophisticated algorithm.
"""

import argparse
import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from golfsim.tools.node_generator import generate_lcm_course_nodes
from golfsim.logging import init_logging, get_logger

logger = get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Generate LCM-optimized course nodes for perfect golfer/cart synchronization"
    )
    parser.add_argument(
        "--course-dir",
        default="courses/pinetree_country_club",
        help="Course directory path"
    )
    parser.add_argument(
        "--output-path",
        help="Custom output path (defaults to course-dir/geojson/generated/lcm_course_nodes.geojson)"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level"
    )
    
    args = parser.parse_args()
    init_logging(args.log_level)
    
    logger.info(f"LCM course node generator starting for: {args.course_dir}")
    
    try:
        # Generate LCM nodes
        node_count = generate_lcm_course_nodes(
            course_dir=args.course_dir,
            output_path=args.output_path
        )
        
        output_file = args.output_path or f"{args.course_dir}/geojson/generated/lcm_course_nodes.geojson"
        
        print(f"\n🎉 LCM Course Node Generation Complete!")
        print(f"✅ Generated {node_count} optimal nodes")
        print(f"📁 Saved to: {output_file}")
        print(f"🔄 Uses sophisticated LCM synchronization logic")
        
        return 0
        
    except Exception as e:
        logger.error(f"Failed to generate LCM course nodes: {e}")
        print(f"\n❌ Generation failed: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
