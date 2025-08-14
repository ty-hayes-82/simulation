#!/usr/bin/env python3
"""
GPS Coordinate Processor and Map App Runner

This script scans for simulation directories and loads coordinate files 
for map visualization with hierarchical selection.
"""

import os
import glob
import shutil
import subprocess
import sys
import json
from pathlib import Path
from typing import List, Tuple, Dict
from datetime import datetime

# Configuration
PUBLIC_DIR = "public"
COORDINATES_DIR = "coordinates"
LOCAL_CSV_FILE = "public/coordinates.csv"

# Determine outputs directory dynamically, with env override
# Falls back to ../outputs relative to this script
DEFAULT_OUTPUTS_DIR = str((Path(__file__).resolve().parent / ".." / "outputs").resolve())
SIM_BASE_DIR = os.environ.get("SIM_BASE_DIR", DEFAULT_OUTPUTS_DIR)

def _humanize(name: str) -> str:
    name = name.replace('-', ' ').replace('_', ' ').strip()
    parts = [p for p in name.split(' ') if p]
    return ' '.join(w.capitalize() for w in parts) if parts else name


def find_all_simulations() -> Dict[str, List[Tuple[str, str, str]]]:
    """
    Recursively scan for all coordinate CSV files under the outputs directory.

    Returns:
        Dict with simulation_group as key and list of (sim_id, display_name, full_path) as value
    """
    simulations: Dict[str, List[Tuple[str, str, str]]] = {}

    # Add local file if it exists
    if os.path.exists(LOCAL_CSV_FILE):
        simulations.setdefault("Local", []).append(("coordinates", "GPS Coordinates", LOCAL_CSV_FILE))
        print(f"Found local simulation file: {LOCAL_CSV_FILE}")

    base_dir = SIM_BASE_DIR
    if not os.path.exists(base_dir):
        print(f"Outputs directory not found: {base_dir}")
        return simulations

    # Walk the outputs directory and collect any coordinates CSVs
    valid_filenames = {"coordinates.csv", "bev_cart_coordinates.csv"}

    for root, dirs, files in os.walk(base_dir):
        csv_files = [f for f in files if f in valid_filenames]
        if not csv_files:
            continue

        for file_name in csv_files:
            full_path = os.path.join(root, file_name)
            rel_path = os.path.relpath(full_path, base_dir)
            parts = rel_path.split(os.sep)

            # Determine group as everything up to the leaf folder (excluding sim/run folder and filename)
            # Example: scenario_quiet_day/bev_with_golfers/sim_01/coordinates.csv ->
            #   group_parts = [scenario_quiet_day, bev_with_golfers]
            group_parts = parts[:-2] if len(parts) >= 2 else parts[:-1]
            group_name = ' - '.join(_humanize(p) for p in group_parts) if group_parts else 'Simulations'

            # Simulation folder name (sim_01, run_01, etc.)
            sim_folder = parts[-2] if len(parts) >= 2 else os.path.splitext(parts[-1])[0]

            # Friendly type from filename
            if file_name == 'coordinates.csv':
                friendly_type = 'Coordinates'
            elif file_name == 'bev_cart_coordinates.csv':
                friendly_type = 'Beverage Cart Coordinates'
            else:
                friendly_type = os.path.splitext(file_name)[0].replace('_', ' ').title()

            # Display name and id
            display_name = f"{sim_folder.upper()} ({friendly_type})"
            # Unique ID derived from relative path (without extension)
            sim_id = rel_path.replace(os.sep, '_').replace('.csv', '')

            simulations.setdefault(group_name, []).append((sim_id, display_name, full_path))

    # Sort groups and simulations for consistent UI ordering
    sorted_simulations: Dict[str, List[Tuple[str, str, str]]] = {}
    for group in sorted(simulations.keys()):
        sorted_simulations[group] = sorted(simulations[group], key=lambda x: x[0])

    # Logging summary
    for group_name, sims in sorted_simulations.items():
        print(f"Found {len(sims)} simulations in {group_name}")

    return sorted_simulations



def copy_all_coordinate_files(all_simulations: Dict[str, List[Tuple[str, str, str]]]) -> bool:
    """
    Copy all coordinate files to the public/coordinates directory and create a hierarchical manifest.
    
    Args:
        all_simulations: Dict with simulation groups and their files
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Create coordinates directory
        coordinates_dir = os.path.join(PUBLIC_DIR, COORDINATES_DIR)
        
        # Fully clear out existing coordinate directory first (including manifest and any stale files)
        if os.path.exists(coordinates_dir):
            try:
                print("Cleaning coordinates directory...")
                shutil.rmtree(coordinates_dir)
            except Exception as e:
                print(f"Error clearing coordinates directory: {e}")
                return False
        
        os.makedirs(coordinates_dir, exist_ok=True)
        
        # Create hierarchical manifest for the React app
        manifest = {
            "simulationGroups": {},
            "defaultGroup": None,
            "defaultSimulation": None
        }
        
        copied_count = 0
        total_size = 0
        
        for group_name, file_options in all_simulations.items():
            group_simulations = []
            
            for scenario_id, display_name, source_path in file_options:
                # Create target filename
                target_filename = f"{scenario_id}.csv"
                target_path = os.path.join(coordinates_dir, target_filename)
                
                # Copy the file
                shutil.copy2(source_path, target_path)
                
                # Verify the copy
                if os.path.exists(target_path):
                    source_size = os.path.getsize(source_path)
                    target_size = os.path.getsize(target_path)
                    
                    if source_size == target_size:
                        copied_count += 1
                        total_size += source_size
                        
                        # Add to group simulations
                        file_info = get_file_info(source_path)
                        group_simulations.append({
                            "id": scenario_id,
                            "name": display_name,
                            "filename": target_filename,
                            "description": file_info
                        })
                        
                        print(f"✅ {display_name} ({source_size//1024:,} KB)")
                    else:
                        print(f"❌ Failed to verify copy for {display_name}")
                        return False
                else:
                    print(f"❌ Failed to copy {display_name}")
                    return False
            
            # Add group to manifest
            if group_simulations:
                manifest["simulationGroups"][group_name] = group_simulations
        
        # Set defaults (prefer non-Local group if available)
        if manifest["simulationGroups"]:
            available_groups = list(manifest["simulationGroups"].keys())
            
            # Prefer first non-Local group if available, otherwise use first group
            default_group = available_groups[0]
            if len(available_groups) > 1 and "Local" in available_groups:
                non_local_groups = [g for g in available_groups if g != "Local"]
                if non_local_groups:
                    default_group = non_local_groups[0]
            
            manifest["defaultGroup"] = default_group
            if manifest["simulationGroups"][default_group]:
                manifest["defaultSimulation"] = manifest["simulationGroups"][default_group][0]["id"]
                print(f"Set default group: {default_group}, default simulation: {manifest['defaultSimulation']}")
        
        # Write manifest file
        manifest_path = os.path.join(coordinates_dir, "manifest.json")
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)
        
        print(f"\n✅ Successfully copied {copied_count} simulations ({total_size//1024:,} KB total)")
        print(f"📋 Created manifest: {manifest_path}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error copying files: {e}")
        return False

def get_file_info(file_path: str) -> str:
    """Get information about the coordinate file."""
    try:
        with open(file_path, 'r') as f:
            lines = f.readlines()
            if len(lines) > 1:
                # Count data rows (excluding header)
                data_rows = len(lines) - 1
                return f"{data_rows:,} coordinate points"
            else:
                return "Empty file"
    except Exception as e:
        return f"Error reading file: {e}"

def run_react_app() -> bool:
    """
    Start the React development server.
    
    Returns:
        True if app started successfully, False otherwise
    """
    try:
        print("\n🚀 Starting React map animation app...")
        print("📍 The app will open in your default browser")
        print("🔄 Use Ctrl+C to stop the server when done")
        print("-" * 60)
        
        # Start the React app
        result = subprocess.run(
            ["npm", "start"],
            cwd=os.getcwd(),
            shell=True
        )
        
        return result.returncode == 0
        
    except KeyboardInterrupt:
        print("\n⏹️  App stopped by user")
        return True
    except Exception as e:
        print(f"❌ Error starting React app: {e}")
        print("💡 Make sure you have Node.js and npm installed")
        print("💡 Try running 'npm install' first if this is a fresh setup")
        return False

def main():
    """Main function."""
    print("🔍 Scanning for simulation coordinate files...")
    
    try:
        # Find all simulations
        all_simulations = find_all_simulations()
        
        total_sims = sum(len(sims) for sims in all_simulations.values())
        print(f"\n📋 Found {total_sims} simulations across {len(all_simulations)} groups:")
        
        for group_name, sims in all_simulations.items():
            print(f"  📁 {group_name}: {len(sims)} simulations")
            for scenario_id, display_name, file_path in sims:
                file_info = get_file_info(file_path)
                print(f"    • {display_name} - {file_info}")
        
        print(f"\n📂 Copying simulations to React app...")
        
        # Copy coordinate files
        if not copy_all_coordinate_files(all_simulations):
            print("❌ Failed to copy coordinate files")
            sys.exit(1)
        
        print("✅ Simulation is ready!")
        print(f"💡 You can start the app manually with: npm start")
        print(f"🎮 The golfer coordinates will be displayed on the map")
            
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
