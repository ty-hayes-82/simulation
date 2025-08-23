#!/usr/bin/env python3
"""
A utility to select and view simulation animation results from experiments.

This script scans the `outputs/experiments` directory for simulation results,
presents an interactive, multi-level menu for the user to navigate and choose one,
and then copies the necessary files to the animation viewer directory before
launching the viewer.

Usage:
  python scripts/optimization/view_simulation_result.py
"""

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

def find_simulation_results(experiments_root: Path) -> List[Path]:
    """Find all coordinates.csv files in the experiments directory."""
    print(f"Searching for simulation results in {experiments_root}...")
    results = sorted(list(experiments_root.rglob("coordinates.csv")))
    print(f"Found {len(results)} simulation results.")
    return results

def build_results_tree(results: List[Path], experiments_root: Path) -> Dict[str, Any]:
    """Build a nested dictionary tree from the list of result paths."""
    tree: Dict[str, Any] = {}
    for path in results:
        # Get path parts relative to the experiments root, excluding the filename
        parts = path.relative_to(experiments_root).parts[:-1]
        node = tree
        for part in parts:
            node = node.setdefault(part, {})
        # Use a special key to store the full path at the leaf node
        node['__path__'] = path
    return tree

def navigate_menu(tree: Dict[str, Any]) -> Optional[Path]:
    """Display an interactive menu to navigate the results tree."""
    path_stack: List[str] = []
    current_node = tree

    while True:
        # Get subdirectories from the current node
        options = sorted([key for key in current_node if key != '__path__'])
        
        print("\n" + "="*40)
        current_path_str = "/".join(path_stack) if path_stack else "Top Level"
        print(f"Current Location: {current_path_str}")
        print("="*40)
        
        for i, option in enumerate(options):
            print(f"  {i+1:2d}) {option}/")

        # Menu options start after the directory listings
        menu_offset = len(options)
        selection_option = -1
        
        # Check if the current path is a selectable result
        if '__path__' in current_node:
            selection_option = menu_offset + 1
            print(f"  {selection_option:2d}) ✨ Select this result ({current_node['__path__'].name})")
            menu_offset += 1

        back_option = menu_offset + 1
        exit_option = menu_offset + 2
        print(f"  {back_option:2d}) .. (Back)")
        print(f"  {exit_option:2d}) [Exit]")

        try:
            choice_str = input(f"\nEnter your choice: ")
            if not choice_str:
                continue
            choice = int(choice_str)

            if 1 <= choice <= len(options):
                # Navigate into a subdirectory
                chosen_dir = options[choice - 1]
                path_stack.append(chosen_dir)
                current_node = current_node[chosen_dir]
            elif choice == selection_option:
                # Select the current result
                return current_node['__path__']
            elif choice == back_option:
                # Go back up
                if path_stack:
                    path_stack.pop()
                    # Re-navigate from the root to rebuild the current node
                    current_node = tree
                    for part in path_stack:
                        current_node = current_node[part]
                else:
                    print("Already at the top level.")
            elif choice == exit_option:
                print("Exiting.")
                return None
            else:
                print("Invalid choice. Please try again.")

        except ValueError:
            print("Invalid input. Please enter a number.")
        except (KeyboardInterrupt, EOFError):
            print("\nSelection cancelled.")
            return None

def prepare_animation_files(selected_path: Path, animation_dir: Path, project_root: Path):
    """Copy selected simulation files to the animation directory."""
    print(f"\nPreparing animation for: {'/'.join(selected_path.parts[2:])}")
    
    # 1. Copy the coordinates file
    target_coords_path = animation_dir / "public" / "coordinates.csv"
    print(f"  - Copying coordinates to {target_coords_path}")
    shutil.copy(selected_path, target_coords_path)

    # 2. Find and copy the corresponding simulation config as config.json
    source_config_path = None
    # Start search from the parent of the runXX directory
    search_dir = selected_path.parents[1]
    
    # Walk up until we find the course_copy_* directory
    while search_dir != search_dir.parent:
        course_copy_dirs = [d for d in search_dir.iterdir() if d.is_dir() and d.name.startswith('course_copy')]
        if course_copy_dirs:
            config_path = course_copy_dirs[0] / "config" / "simulation_config.json"
            if config_path.exists():
                source_config_path = config_path
                break
        search_dir = search_dir.parent

    # If no experiment-specific config was found, fall back to the default Pinetree config
    if not source_config_path:
        print("  - No experiment-specific config found. Falling back to default course config.")
        fallback_config_path = project_root / "courses" / "pinetree_country_club" / "config" / "simulation_config.json"
        if fallback_config_path.exists():
            source_config_path = fallback_config_path

    target_config_path = animation_dir / "public" / "config.json"
    if source_config_path:
        print(f"  - Found simulation config at {source_config_path}")
        print(f"  - Copying config to {target_config_path}")
        shutil.copy(source_config_path, target_config_path)
    else:
        print("  - Warning: Could not find ANY simulation_config.json. Animation may use stale settings or fail.")

def launch_animation_viewer(animation_dir: Path):
    """Launch the npm start process for the animation viewer."""
    print("\nLaunching animation viewer...")
    print("Press Ctrl+C in the new terminal to stop the viewer.")
    
    # Use 'npm.cmd' on Windows
    npm_cmd = "npm.cmd" if sys.platform == "win32" else "npm"
    
    try:
        subprocess.run([npm_cmd, "start"], cwd=animation_dir, check=True)
    except FileNotFoundError:
        print("\nError: `npm` command not found.")
        print("Please ensure Node.js and npm are installed and in your PATH.")
    except subprocess.CalledProcessError as e:
        print(f"\nError launching animation viewer: {e}")
    except KeyboardInterrupt:
        print("\nAnimation viewer process interrupted.")

def main():
    """Main function to run the script."""
    project_root = Path(__file__).resolve().parents[2]
    experiments_root = project_root / "outputs" / "experiments"
    animation_dir = project_root / "my-map-animation"

    if not experiments_root.exists():
        print(f"Error: Experiments directory not found at {experiments_root}")
        return
        
    if not animation_dir.exists():
        print(f"Error: Animation directory not found at {animation_dir}")
        return

    results = find_simulation_results(experiments_root)
    if not results:
        return
        
    results_tree = build_results_tree(results, experiments_root)
    
    selected_result_path = navigate_menu(results_tree)
    
    if selected_result_path:
        prepare_animation_files(selected_result_path, animation_dir, project_root)
        launch_animation_viewer(animation_dir)

if __name__ == "__main__":
    main()
