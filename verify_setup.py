#!/usr/bin/env python3
"""
Setup verification script for the golf delivery simulation project.
This script checks that all required dependencies are installed and working.
"""

import sys
import importlib

def check_import(module_name, package_name=None):
    """Check if a module can be imported successfully."""
    try:
        importlib.import_module(module_name)
        print(f"✓ {package_name or module_name}")
        return True
    except ImportError as e:
        print(f"✗ {package_name or module_name}: {e}")
        return False

def main():
    print("Verifying golf delivery simulation setup...")
    print("=" * 50)
    
    # Core dependencies
    print("\nCore Dependencies:")
    core_deps = [
        ("osmnx", "OSMnx"),
        ("geopandas", "GeoPandas"),
        ("networkx", "NetworkX"),
        ("shapely", "Shapely"),
        ("simpy", "SimPy"),
        ("pandas", "Pandas"),
        ("numpy", "NumPy"),
        ("folium", "Folium"),
        ("rtree", "Rtree"),
        ("matplotlib", "Matplotlib"),
    ]
    
    core_success = all(check_import(module, name) for module, name in core_deps)
    
    # Development dependencies
    print("\nDevelopment Dependencies:")
    dev_deps = [
        ("ruff", "Ruff"),
        ("black", "Black"),
        ("mypy", "MyPy"),
        ("pytest", "Pytest"),
        ("pytest_cov", "Pytest-cov"),
    ]
    
    dev_success = all(check_import(module, name) for module, name in dev_deps)
    
    # Project package
    print("\nProject Package:")
    project_success = check_import("golfsim", "GolfSim Package")
    
    # Summary
    print("\n" + "=" * 50)
    if core_success and dev_success and project_success:
        print("🎉 All dependencies installed successfully!")
        print("Your virtual environment is ready to use.")
    else:
        print("⚠️  Some dependencies are missing.")
        print("Please check the installation and try again.")
        sys.exit(1)

if __name__ == "__main__":
    main()
