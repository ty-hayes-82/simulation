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
import re
from pathlib import Path
from typing import List, Tuple, Dict, Optional
from datetime import datetime

# --- Start of new path configuration ---
# Make paths robust to script's location and execution directory
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = (SCRIPT_DIR / "..").resolve()

# Configuration - Copy to my-map-animation/public only
PUBLIC_DIRS = [str(SCRIPT_DIR / "public")]
COORDINATES_DIR = "coordinates"
LOCAL_CSV_FILE = str(SCRIPT_DIR / "public" / "coordinates.csv")

# Determine outputs directory dynamically, with env override
# Falls back to ../outputs relative to this script
DEFAULT_OUTPUTS_DIR = str(PROJECT_ROOT / "outputs")
SIM_BASE_DIR = os.environ.get("SIM_BASE_DIR", DEFAULT_OUTPUTS_DIR)
# --- End of new path configuration ---

def _humanize(name: str) -> str:
    name = name.replace('-', ' ').replace('_', ' ').strip()
    parts = [p for p in name.split(' ') if p]
    return ' '.join(w.capitalize() for w in parts) if parts else name


def _parse_simulation_folder_name(folder_name: str) -> Dict[str, str]:
    """
    Parse simulation folder names to extract meaningful information.
    
    Expected format: YYYYMMDD_HHMMSS_Xbevcarts_Yrunners_Zgolfers_[scenario]
    
    Returns:
        Dict with parsed components
    """
    result = {
        'date': '',
        'time': '',
        'bev_carts': '0',
        'runners': '0', 
        'golfers': '0',
        'scenario': '',
        'original': folder_name
    }
    
    # Handle timestamp prefix (YYYYMMDD_HHMMSS_)
    if '_' in folder_name:
        parts = folder_name.split('_')
        
        # Check if first part looks like a date (8 digits)
        if len(parts) > 0 and len(parts[0]) == 8 and parts[0].isdigit():
            result['date'] = parts[0]
            
            # Check if second part looks like time (6 digits)
            if len(parts) > 1 and len(parts[1]) == 6 and parts[1].isdigit():
                result['time'] = parts[1]
                
                # Parse the configuration part
                config_parts = parts[2:]
                config_str = '_'.join(config_parts)
                
                # Extract bev carts (handle both "bevcarts" and "bev_carts")
                bev_match = re.search(r'(\d+)bev_?carts?', config_str, re.IGNORECASE)
                if bev_match:
                    result['bev_carts'] = bev_match.group(1)
                
                # Extract runners
                runner_match = re.search(r'(\d+)runners?', config_str, re.IGNORECASE)
                if runner_match:
                    result['runners'] = runner_match.group(1)
                
                # Extract golfers
                golfer_match = re.search(r'(\d+)golfers?', config_str, re.IGNORECASE)
                if golfer_match:
                    result['golfers'] = golfer_match.group(1)
                
                # Look for scenario after the last numeric component
                # Skip parts that match numeric patterns (like "sim_01", "run_01")
                scenario_parts = []
                for part in config_parts:
                    # Skip if it's a numeric component or sim/run folder
                    if not (re.match(r'^\d+[a-zA-Z]+$', part) or 
                           re.match(r'^(sim|run)_\d+$', part, re.IGNORECASE)):
                        scenario_parts.append(part)
                
                if scenario_parts:
                    result['scenario'] = '_'.join(scenario_parts)
    
    return result


def _format_simulation_name(parsed: Dict[str, str]) -> str:
    """
    Format parsed simulation data into a readable name.
    """
    components = []
    
    # Add configuration summary
    config_parts = []
    if parsed['bev_carts'] != '0':
        config_parts.append(f"{parsed['bev_carts']} Cart{'s' if parsed['bev_carts'] != '1' else ''}")
    if parsed['runners'] != '0':
        config_parts.append(f"{parsed['runners']} Runner{'s' if parsed['runners'] != '1' else ''}")
    if parsed['golfers'] != '0':
        config_parts.append(f"{parsed['golfers']} Golfer{'s' if parsed['golfers'] != '1' else ''}")
    
    if config_parts:
        components.append(' + '.join(config_parts))
    
    # Add scenario if available
    if parsed['scenario']:
        scenario_name = _humanize(parsed['scenario'])
        components.append(scenario_name)
    
    # Add date/time if available
    if parsed['date'] and parsed['time']:
        try:
            date_obj = datetime.strptime(f"{parsed['date']}_{parsed['time']}", "%Y%m%d_%H%M%S")
            components.append(date_obj.strftime("%b %d, %H:%M"))
        except ValueError:
            pass
    
    return ' | '.join(components) if components else parsed['original']


def _format_simple_simulation_name(parsed: Dict[str, str]) -> str:
    """
    Format parsed simulation data into a simple name without date/time.
    """
    components = []
    
    # Add configuration summary
    config_parts = []
    if parsed['bev_carts'] != '0':
        config_parts.append(f"{parsed['bev_carts']} Cart{'s' if parsed['bev_carts'] != '1' else ''}")
    if parsed['runners'] != '0':
        config_parts.append(f"{parsed['runners']} Runner{'s' if parsed['runners'] != '1' else ''}")
    if parsed['golfers'] != '0':
        config_parts.append(f"{parsed['golfers']} Golfer{'s' if parsed['golfers'] != '1' else ''}")
    
    if config_parts:
        components.append(' + '.join(config_parts))
    
    # Add scenario if available
    if parsed['scenario']:
        scenario_name = _humanize(parsed['scenario'])
        components.append(scenario_name)
    
    return ' | '.join(components) if components else parsed['original']


def _create_group_name(parsed: Dict[str, str]) -> str:
    """
    Create a meaningful group name based on parsed simulation data.
    """
    # Group by scenario if available
    if parsed['scenario']:
        return _humanize(parsed['scenario'])
    
    # Group by configuration type
    if parsed['bev_carts'] != '0' and parsed['runners'] != '0':
        return "Mixed Operations"
    elif parsed['bev_carts'] != '0':
        return "Beverage Cart Only"
    elif parsed['runners'] != '0':
        return "Delivery Runners Only"
    else:
        return "Other Simulations"


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

    # Walk the outputs directory and collect any coordinates CSVs and heatmaps
    valid_filenames = {"coordinates.csv", "bev_cart_coordinates.csv"}
    valid_heatmap_filenames = {"delivery_heatmap.png", "heatmap.png"}

    for root, dirs, files in os.walk(base_dir):
        csv_files = [f for f in files if f in valid_filenames]
        if not csv_files:
            continue

        for file_name in csv_files:
            full_path = os.path.join(root, file_name)
            rel_path = os.path.relpath(full_path, base_dir)
            parts = rel_path.split(os.sep)

            # Parse the simulation folder name to extract meaningful information
            if len(parts) >= 3:
                # The simulation folder is the parent of the run/sim folder
                # Structure: outputs/simulation_folder/run_01/coordinates.csv
                sim_folder_name = parts[-3]
                run_folder = parts[-2]
                parsed = _parse_simulation_folder_name(sim_folder_name)
                
                # Create meaningful group name
                group_name = _create_group_name(parsed)
                
                # Create meaningful simulation name (without date/time to avoid duplication)
                base_sim_name = _format_simple_simulation_name(parsed)
                
                # Add run/sim identifier if available
                if run_folder.startswith(('sim_', 'run_')):
                    run_id = run_folder.upper()
                else:
                    run_id = ""
                
                # Friendly type from filename
                if file_name == 'coordinates.csv':
                    friendly_type = 'GPS Coordinates'
                elif file_name == 'bev_cart_coordinates.csv':
                    friendly_type = 'Beverage Cart GPS'
                else:
                    friendly_type = os.path.splitext(file_name)[0].replace('_', ' ').title()
                
                # Combine components for display name
                display_components = [base_sim_name]
                if run_id:
                    display_components.append(run_id)
                display_components.append(friendly_type)
                display_name = ' | '.join(display_components)
                
            elif len(parts) >= 2:
                # Fallback: direct simulation folder structure
                sim_folder_name = parts[-2]
                parsed = _parse_simulation_folder_name(sim_folder_name)
                
                # Create meaningful group name
                group_name = _create_group_name(parsed)
                
                # Create meaningful simulation name (without date/time to avoid duplication)
                base_sim_name = _format_simple_simulation_name(parsed)
                
                # Friendly type from filename
                if file_name == 'coordinates.csv':
                    friendly_type = 'GPS Coordinates'
                elif file_name == 'bev_cart_coordinates.csv':
                    friendly_type = 'Beverage Cart GPS'
                else:
                    friendly_type = os.path.splitext(file_name)[0].replace('_', ' ').title()
                
                display_name = f"{base_sim_name} | {friendly_type}"
                
            else:
                # Fallback for simple file structure
                group_name = 'Simulations'
                display_name = f"Coordinates ({os.path.splitext(file_name)[0]})"
            
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



def copy_all_coordinate_files(all_simulations: Dict[str, List[Tuple[str, str, str]]], preferred_default_id: Optional[str] = None) -> bool:
    """
    Copy all coordinate files to both public directories and create hierarchical manifests.
    
    Args:
        all_simulations: Dict with simulation groups and their files
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Create coordinates directories in both locations
        coordinates_dirs = []
        for public_dir in PUBLIC_DIRS:
            coordinates_dir = os.path.join(public_dir, COORDINATES_DIR)
            coordinates_dirs.append(coordinates_dir)
            
            # Fully clear out existing coordinate directory first (including manifest and any stale files)
            if os.path.exists(coordinates_dir):
                try:
                    print(f"Cleaning coordinates directory: {coordinates_dir}")
                    shutil.rmtree(coordinates_dir)
                except Exception as e:
                    print(f"Error clearing coordinates directory {coordinates_dir}: {e}")
                    return False
            
            os.makedirs(coordinates_dir, exist_ok=True)
        
        # Create flattened manifest for the React app
        manifest = {
            "simulations": [],
            "defaultSimulation": None
        }
        
        copied_count = 0
        total_size = 0
        id_to_mtime: Dict[str, float] = {}
        
        for group_name, file_options in all_simulations.items():
            for scenario_id, display_name, source_path in file_options:
                # Create target filename
                target_filename = f"{scenario_id}.csv"
                
                # Copy the file to all coordinates directories
                all_copies_successful = True
                for coordinates_dir in coordinates_dirs:
                    target_path = os.path.join(coordinates_dir, target_filename)
                    
                    # Copy the file
                    shutil.copy2(source_path, target_path)
                    
                    # Verify the copy
                    if os.path.exists(target_path):
                        source_size = os.path.getsize(source_path)
                        target_size = os.path.getsize(target_path)
                        
                        if source_size != target_size:
                            print(f"❌ Failed to verify copy for {display_name} to {coordinates_dir}")
                            all_copies_successful = False
                            break
                    else:
                        print(f"❌ Failed to copy {display_name} to {coordinates_dir}")
                        all_copies_successful = False
                        break
                
                if all_copies_successful:
                    copied_count += 1
                    total_size += source_size
                    
                    # Add to flattened simulations list (only once)
                    file_info = get_file_info(source_path)
                    manifest["simulations"].append({
                        "id": scenario_id,
                        "name": f"{group_name}: {display_name}",
                        "filename": target_filename,
                        "description": file_info
                    })
                    try:
                        id_to_mtime[scenario_id] = os.path.getmtime(source_path)
                    except Exception:
                        pass
                    
                    print(f"✅ {display_name} ({source_size//1024:,} KB) - copied to all locations")
                else:
                    return False
        
        # Set default simulation
        if manifest["simulations"]:
            # Allow caller to specify a preferred default simulation via param or env var
            env_default_id = os.environ.get("DEFAULT_SIMULATION_ID", "").strip()
            chosen_id = (preferred_default_id or env_default_id or "").strip()

            selected_default = None
            if chosen_id:
                for sim in manifest["simulations"]:
                    if sim["id"] == chosen_id:
                        selected_default = sim
                        break

            # Fallbacks
            if not selected_default:
                # 1) Most recently modified file if available
                if id_to_mtime:
                    try:
                        newest_id = max(id_to_mtime.items(), key=lambda kv: kv[1])[0]
                        selected_default = next((sim for sim in manifest["simulations"] if sim["id"] == newest_id), None)
                    except Exception:
                        selected_default = None
            if not selected_default:
                # 2) Prefer first non-Local simulation if available
                selected_default = next(
                    (sim for sim in manifest["simulations"] if not sim["name"].startswith("Local:")),
                    manifest["simulations"][0]
                )

            manifest["defaultSimulation"] = selected_default["id"]
            print(f"Set default simulation: {selected_default['name']}")
        
        # Write manifest files to all coordinates directories
        for coordinates_dir in coordinates_dirs:
            manifest_path = os.path.join(coordinates_dir, "manifest.json")
            with open(manifest_path, 'w') as f:
                json.dump(manifest, f, indent=2)
            print(f"📋 Created manifest: {manifest_path}")
        
        # Copy simulation_metrics.json if it exists in the my-map-animation public directory
        metrics_source = SCRIPT_DIR / "public" / "simulation_metrics.json"
        if os.path.exists(metrics_source):
            for coordinates_dir in coordinates_dirs:
                metrics_target = os.path.join(coordinates_dir, "simulation_metrics.json")
                try:
                    shutil.copy2(metrics_source, metrics_target)
                    print(f"📋 Copied simulation_metrics.json to {coordinates_dir}")
                except Exception as e:
                    print(f"⚠️  Warning: Could not copy simulation_metrics.json to {coordinates_dir}: {e}")
        
        # Copy heatmap files from simulation outputs
        copy_heatmaps_to_coordinates_dirs(all_simulations, coordinates_dirs)
        
        # Copy hole_delivery_times.geojson if it exists
        copy_hole_delivery_geojson(coordinates_dirs)
        
        print(f"\n✅ Successfully copied {copied_count} simulations ({total_size//1024:,} KB total)")
        
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

def copy_heatmaps_to_coordinates_dirs(all_simulations: Dict[str, List[Tuple[str, str, str]]], coordinates_dirs: List[str]) -> None:
    """Copy heatmap files from simulation outputs to coordinates directories."""
    valid_heatmap_filenames = {"delivery_heatmap.png", "heatmap.png"}
    
    for group_name, file_options in all_simulations.items():
        for scenario_id, display_name, csv_source_path in file_options:
            # Find heatmap files in the same directory as the CSV
            csv_dir = os.path.dirname(csv_source_path)
            
            for filename in os.listdir(csv_dir):
                if filename in valid_heatmap_filenames:
                    heatmap_source = os.path.join(csv_dir, filename)
                    
                    # Copy to all coordinates directories
                    for coordinates_dir in coordinates_dirs:
                        # Create a unique heatmap filename based on scenario_id
                        heatmap_filename = f"{scenario_id}_{filename}"
                        heatmap_target = os.path.join(coordinates_dir, heatmap_filename)
                        
                        try:
                            shutil.copy2(heatmap_source, heatmap_target)
                            print(f"🖼️  Copied {filename} to {coordinates_dir} as {heatmap_filename}")
                        except Exception as e:
                            print(f"⚠️  Warning: Could not copy {filename}: {e}")

def copy_hole_delivery_geojson(coordinates_dirs: List[str]) -> None:
    """Copy hole_delivery_times.geojson to parent public directories."""
    source_file = SCRIPT_DIR / "public" / "hole_delivery_times.geojson"
    
    if os.path.exists(source_file):
        for public_dir in PUBLIC_DIRS:
            target_file = os.path.join(public_dir, "hole_delivery_times.geojson")
            try:
                # Use a temporary file to handle potential file locks
                temp_target = target_file + ".tmp"
                shutil.copy2(source_file, temp_target)
                os.replace(temp_target, target_file)
                print(f"🗺️  Copied hole_delivery_times.geojson to {public_dir}")
            except Exception as e:
                print(f"⚠️  Warning: Could not copy hole_delivery_times.geojson to {public_dir}: {e}")

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
            cwd=str(SCRIPT_DIR),
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
    import argparse
    parser = argparse.ArgumentParser(description="Prepare map app coordinates and manifest")
    parser.add_argument("--default-id", dest="default_id", default=None, help="Preferred default simulation id (manifest id)")
    args = parser.parse_args()

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
        if not copy_all_coordinate_files(all_simulations, preferred_default_id=args.default_id):
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
