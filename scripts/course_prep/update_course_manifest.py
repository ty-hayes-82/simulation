#!/usr/bin/env python3
"""
Script to automatically update the course manifest and copy holes_geofenced.geojson files
for the course setup application.
"""

import os
import json
import shutil
from pathlib import Path

def scan_courses_directory(courses_dir):
    """Scan the courses directory and return a list of available courses."""
    courses = []
    
    if not os.path.exists(courses_dir):
        print(f"Courses directory not found: {courses_dir}")
        return courses
    
    for course_dir in os.listdir(courses_dir):
        course_path = os.path.join(courses_dir, course_dir)
        
        # Skip if not a directory
        if not os.path.isdir(course_path):
            continue
            
        # Check if holes_geofenced.geojson exists
        holes_geofenced_path = os.path.join(course_path, "geojson", "generated", "holes_geofenced.geojson")
        
        if os.path.exists(holes_geofenced_path):
            # Convert directory name to display name
            display_name = course_dir.replace('_', ' ').title()
            
            courses.append({
                "id": course_dir,
                "name": display_name,
                "holes_geofenced_path": holes_geofenced_path
            })
            print(f"Found course: {display_name} ({course_dir})")
        else:
            print(f"Skipping {course_dir}: holes_geofenced.geojson not found")
    
    return courses

def update_manifest(manifest_path, courses):
    """Update the manifest.json file with the discovered courses."""
    
    # Load existing manifest or create new one
    manifest = {}
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, 'r') as f:
                manifest = json.load(f)
        except json.JSONDecodeError:
            print(f"Warning: Could not parse existing manifest at {manifest_path}")
            manifest = {}
    
    # Update courses section
    manifest["courses"] = [{"id": course["id"], "name": course["name"]} for course in courses]
    
    # Set default course if we have courses
    if courses:
        manifest["defaultCourse"] = courses[0]["id"]
    
    # Preserve existing simulations section if it exists
    if "simulations" not in manifest:
        manifest["simulations"] = [
            {
                "id": "coordinates",
                "name": "Simulation",
                "filename": "coordinates.csv",
                "description": "Delivery runner simulation (1 runner)"
            }
        ]
        manifest["defaultSimulation"] = "coordinates"
    
    # Write updated manifest
    with open(manifest_path, 'w') as f:
        json.dump(manifest, f, indent=2)
    
    print(f"Updated manifest with {len(courses)} courses")

def copy_holes_geofenced_files(courses, public_dir):
    """Copy holes_geofenced.geojson files to the public directory."""
    
    # Create courses subdirectory in public
    courses_public_dir = os.path.join(public_dir, "courses")
    os.makedirs(courses_public_dir, exist_ok=True)
    
    for course in courses:
        course_id = course["id"]
        source_path = course["holes_geofenced_path"]
        
        # Create course-specific directory
        course_public_dir = os.path.join(courses_public_dir, course_id)
        os.makedirs(course_public_dir, exist_ok=True)
        
        # Copy holes_geofenced.geojson
        dest_path = os.path.join(course_public_dir, "holes_geofenced.geojson")
        shutil.copy2(source_path, dest_path)
        
        print(f"Copied {course['name']} holes to {dest_path}")

def main():
    """Main function to update course manifest and copy files."""
    
    # Get script directory and project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent.parent
    
    courses_dir = project_root / "courses"
    public_dir = project_root / "public"
    manifest_path = public_dir / "manifest.json"
    
    print("Scanning courses directory...")
    courses = scan_courses_directory(str(courses_dir))
    
    if not courses:
        print("No courses found with holes_geofenced.geojson files!")
        return
    
    print(f"\nFound {len(courses)} courses:")
    for course in courses:
        print(f"  - {course['name']} ({course['id']})")
    
    print("\nUpdating manifest.json...")
    update_manifest(str(manifest_path), courses)
    
    print("\nCopying holes_geofenced.geojson files...")
    copy_holes_geofenced_files(courses, str(public_dir))
    
    print("\nCourse setup update complete!")
    print(f"Manifest updated: {manifest_path}")
    print(f"Course files copied to: {public_dir / 'courses'}")

if __name__ == "__main__":
    main()
