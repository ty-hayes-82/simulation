#!/usr/bin/env python3
"""
Unified Course Data Generator Script

This script provides a command-line interface to the golfsim.tools.CourseDataGenerator
for generating all required course data files.
"""

import argparse
import sys
from pathlib import Path

# Add project root to path for imports
project_root = Path(__file__).resolve().parents[2]
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from golfsim.tools import CourseDataGenerator
from golfsim.logging import init_logging, get_logger

logger = get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description="Generate all required course data files using unified tools"
    )
    parser.add_argument(
        "--course-dir",
        default="courses/pinetree_country_club",
        help="Course directory path"
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Only validate existing files, don't generate missing ones"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Logging level"
    )
    parser.add_argument(
        "--force-regenerate",
        action="store_true",
        help="Force regeneration of all files even if they exist"
    )
    
    args = parser.parse_args()
    init_logging(args.log_level)
    
    logger.info(f"Course data generator starting for: {args.course_dir}")
    
    # Initialize course data generator
    cdg = CourseDataGenerator(args.course_dir)
    
    if args.validate_only:
        # Just validate existing files
        logger.info("Validation mode - checking existing files only")
        status = cdg.validate_course_data()
        
        print("\n=== Course Data Validation Results ===")
        print(f"Course directory: {status['course_dir']}")
        print(f"Holes count: {status['holes_count']}")
        print(f"Nodes count: {status['nodes_count']}")
        print(f"All files ready: {status['all_files_ready']}")
        
        if status['missing_files']:
            print(f"Missing files: {', '.join(status['missing_files'])}")
            print("\nRun without --validate-only to auto-generate missing files.")
            return 1
        else:
            print("✅ All required files are present!")
            return 0
    
    else:
        # Ensure all required files exist
        logger.info("Ensuring all required course data files exist...")
        
        if args.force_regenerate:
            logger.warning("Force regeneration not yet implemented")
        
        results = cdg.ensure_all_required_files()
        
        print("\n=== Course Data Generation Results ===")
        for filename, success in results.items():
            status_icon = "✅" if success else "❌"
            print(f"{status_icon} {filename}")
        
        # Final validation
        final_status = cdg.validate_course_data()
        
        print(f"\nFinal status:")
        print(f"  All files ready: {final_status['all_files_ready']}")
        print(f"  Holes: {final_status['holes_count']}")
        print(f"  Nodes: {final_status['nodes_count']}")
        
        if final_status['missing_files']:
            print(f"  Still missing: {', '.join(final_status['missing_files'])}")
            return 1
        
        print("🎉 Course data generation complete!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
