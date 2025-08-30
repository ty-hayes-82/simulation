#!/usr/bin/env python3
"""
Convert shapefile to GeoJSON format.

This script converts the shapefile in the holes_geofenced_updated directory
to a GeoJSON file for use in web applications and other geospatial tools.
"""

import geopandas as gpd
import os
import sys
from pathlib import Path
import json


def convert_shapefile_to_geojson(shapefile_dir, output_path=None, output_name=None):
    """
    Convert shapefile to GeoJSON format.
    
    Args:
        shapefile_dir (str): Directory containing the shapefile components
        output_path (str, optional): Output directory for the GeoJSON file
        output_name (str, optional): Name for the output GeoJSON file
    
    Returns:
        str: Path to the created GeoJSON file
    """
    
    # Find the .shp file in the directory
    shapefile_dir = Path(shapefile_dir)
    shp_files = list(shapefile_dir.glob("*.shp"))
    
    if not shp_files:
        raise FileNotFoundError(f"No .shp file found in {shapefile_dir}")
    
    if len(shp_files) > 1:
        print(f"Warning: Multiple .shp files found. Using: {shp_files[0]}")
    
    shapefile_path = shp_files[0]
    print(f"Reading shapefile: {shapefile_path}")
    
    try:
        # Read the shapefile
        gdf = gpd.read_file(shapefile_path)
        
        # Print some info about the data
        print(f"Loaded {len(gdf)} features")
        print(f"CRS: {gdf.crs}")
        print(f"Columns: {list(gdf.columns)}")
        print(f"Geometry types: {gdf.geometry.geom_type.unique()}")
        
        # Set output path and name
        if output_path is None:
            output_path = shapefile_dir.parent
        else:
            output_path = Path(output_path)
        
        if output_name is None:
            output_name = f"{shapefile_path.stem}.geojson"
        
        output_file = output_path / output_name
        
        # Ensure output directory exists
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Convert to GeoJSON and save
        print(f"Converting to GeoJSON: {output_file}")
        gdf.to_file(output_file, driver='GeoJSON')
        
        # Verify the output file was created and is valid
        if output_file.exists():
            file_size = output_file.stat().st_size
            print(f"Successfully created GeoJSON file: {output_file}")
            print(f"File size: {file_size} bytes")
            
            # Try to load it back to verify it's valid JSON
            try:
                with open(output_file, 'r') as f:
                    json.load(f)
                print("GeoJSON file is valid JSON")
            except json.JSONDecodeError as e:
                print(f"Warning: Created file may not be valid JSON: {e}")
        else:
            print("Error: Output file was not created")
            
        return str(output_file)
        
    except Exception as e:
        print(f"Error converting shapefile: {e}")
        raise


def main():
    """Main function to handle command line usage."""
    
    # Default paths
    default_shapefile_dir = "courses/pinetree_country_club/holes_geofenced_updated"
    default_output_dir = "courses/pinetree_country_club/geojson/generated"
    default_output_name = "holes_geofenced_updated.geojson"
    
    # Parse command line arguments if provided
    if len(sys.argv) > 1:
        shapefile_dir = sys.argv[1]
    else:
        shapefile_dir = default_shapefile_dir
    
    if len(sys.argv) > 2:
        output_dir = sys.argv[2]
    else:
        output_dir = default_output_dir
        
    if len(sys.argv) > 3:
        output_name = sys.argv[3]
    else:
        output_name = default_output_name
    
    print("Shapefile to GeoJSON Converter")
    print("=" * 40)
    print(f"Input shapefile directory: {shapefile_dir}")
    print(f"Output directory: {output_dir}")
    print(f"Output filename: {output_name}")
    print()
    
    try:
        # Check if input directory exists
        if not os.path.exists(shapefile_dir):
            print(f"Error: Input directory does not exist: {shapefile_dir}")
            return 1
        
        # Convert the shapefile
        output_file = convert_shapefile_to_geojson(
            shapefile_dir=shapefile_dir,
            output_path=output_dir,
            output_name=output_name
        )
        
        print(f"\nConversion completed successfully!")
        print(f"GeoJSON file created: {output_file}")
        return 0
        
    except Exception as e:
        print(f"\nError during conversion: {e}")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
