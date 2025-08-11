#!/usr/bin/env python3
"""
Analyze proximity between beverage cart and golfer positions from GPS coordinates.
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from math import radians, cos, sin, asin, sqrt
from pathlib import Path
import seaborn as sns

def haversine_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the great circle distance between two points 
    on the earth (specified in decimal degrees) using Haversine formula.
    Returns distance in meters.
    """
    # Convert decimal degrees to radians
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    
    # Haversine formula
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    
    # Radius of earth in meters
    r = 6371000
    return c * r

def analyze_proximity(csv_file):
    """Analyze proximity between beverage cart and golfer by finding closest points across all data."""
    print(f"Loading data from: {csv_file}")
    
    # Load the data
    df = pd.read_csv(csv_file)
    print(f"Loaded {len(df)} GPS points")
    print(f"Unique entities: {df['id'].unique()}")
    
    # Separate golfer and beverage cart data
    golfer_data = df[df['type'] == 'hole'].copy()
    bevcart_data = df[df['type'] == 'bevcart'].copy()
    
    print(f"Golfer points: {len(golfer_data)}")
    print(f"Beverage cart points: {len(bevcart_data)}")
    
    # Calculate distance from each golfer point to each beverage cart point
    print("Calculating distances between all golfer and beverage cart points...")
    
    min_distance = float('inf')
    closest_pair = None
    all_distances = []
    
    total_comparisons = len(golfer_data) * len(bevcart_data)
    print(f"Total comparisons to make: {total_comparisons:,}")
    
    for i, golfer_row in golfer_data.iterrows():
        for j, bevcart_row in bevcart_data.iterrows():
            distance = haversine_distance(
                golfer_row['latitude'], golfer_row['longitude'],
                bevcart_row['latitude'], bevcart_row['longitude']
            )
            
            all_distances.append({
                'golfer_timestamp': golfer_row['timestamp'],
                'bevcart_timestamp': bevcart_row['timestamp'],
                'distance_meters': distance,
                'golfer_hole': golfer_row['hole'],
                'bevcart_hole': bevcart_row['hole'],
                'golfer_lat': golfer_row['latitude'],
                'golfer_lon': golfer_row['longitude'],
                'bevcart_lat': bevcart_row['latitude'],
                'bevcart_lon': bevcart_row['longitude']
            })
            
            if distance < min_distance:
                min_distance = distance
                closest_pair = {
                    'distance_meters': distance,
                    'golfer_timestamp': golfer_row['timestamp'],
                    'bevcart_timestamp': bevcart_row['timestamp'],
                    'golfer_hole': golfer_row['hole'],
                    'bevcart_hole': bevcart_row['hole'],
                    'golfer_lat': golfer_row['latitude'],
                    'golfer_lon': golfer_row['longitude'],
                    'bevcart_lat': bevcart_row['latitude'],
                    'bevcart_lon': bevcart_row['longitude']
                }
    
    # Convert to DataFrame for analysis
    all_distances_df = pd.DataFrame(all_distances)
    distances_only = [d['distance_meters'] for d in all_distances]
    
    # Statistics
    max_distance = max(distances_only)
    avg_distance = np.mean(distances_only)
    median_distance = np.median(distances_only)
    
    print("\n=== CLOSEST POINT ANALYSIS RESULTS ===")
    print(f"Absolute minimum distance: {min_distance:.2f} meters")
    print(f"Maximum distance: {max_distance:.2f} meters")
    print(f"Average distance: {avg_distance:.2f} meters")
    print(f"Median distance: {median_distance:.2f} meters")
    
    print(f"\nClosest approach details:")
    print(f"  Distance: {closest_pair['distance_meters']:.2f} meters")
    print(f"  Golfer timestamp: {closest_pair['golfer_timestamp']} seconds ({closest_pair['golfer_timestamp']//60:.0f}:{closest_pair['golfer_timestamp']%60:02.0f})")
    print(f"  Beverage cart timestamp: {closest_pair['bevcart_timestamp']} seconds ({closest_pair['bevcart_timestamp']//60:.0f}:{closest_pair['bevcart_timestamp']%60:02.0f})")
    print(f"  Golfer was on hole: {closest_pair['golfer_hole']}")
    print(f"  Beverage cart was serving hole: {closest_pair['bevcart_hole']}")
    print(f"  Golfer position: ({closest_pair['golfer_lat']:.6f}, {closest_pair['golfer_lon']:.6f})")
    print(f"  Beverage cart position: ({closest_pair['bevcart_lat']:.6f}, {closest_pair['bevcart_lon']:.6f})")
    
    # Find distances under certain thresholds
    very_close = [d for d in distances_only if d < 50]  # Under 50 meters
    close = [d for d in distances_only if d < 100]      # Under 100 meters
    quite_close = [d for d in distances_only if d < 200]  # Under 200 meters
    
    print(f"\nProximity thresholds across all point pairs:")
    print(f"  Pairs within 50m: {len(very_close):,} ({len(very_close)/len(distances_only)*100:.2f}%)")
    print(f"  Pairs within 100m: {len(close):,} ({len(close)/len(distances_only)*100:.2f}%)")
    print(f"  Pairs within 200m: {len(quite_close):,} ({len(quite_close)/len(distances_only)*100:.2f}%)")
    
    return all_distances_df, distances_only, closest_pair

def create_visualizations(proximity_df, distances, closest_pair):
    """Create visualizations of the proximity analysis."""
    
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(15, 12))
    
    # 1. Distance histogram (all point-to-point distances)
    ax1.hist(distances, bins=50, alpha=0.7, color='skyblue', edgecolor='black')
    ax1.set_xlabel('Distance (meters)')
    ax1.set_ylabel('Frequency')
    ax1.set_title('Distribution of All Point-to-Point Distances')
    ax1.axvline(x=np.mean(distances), color='red', linestyle='--', label=f'Mean: {np.mean(distances):.1f}m')
    ax1.axvline(x=np.median(distances), color='green', linestyle='--', label=f'Median: {np.median(distances):.1f}m')
    ax1.axvline(x=min(distances), color='purple', linestyle='-', linewidth=2, label=f'Minimum: {min(distances):.1f}m')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # 2. Zoomed histogram for close distances
    close_distances = [d for d in distances if d < 500]  # Focus on closer distances
    ax2.hist(close_distances, bins=30, alpha=0.7, color='lightcoral', edgecolor='black')
    ax2.set_xlabel('Distance (meters)')
    ax2.set_ylabel('Frequency')
    ax2.set_title('Distribution of Distances < 500m (Zoomed View)')
    ax2.axvline(x=min(distances), color='purple', linestyle='-', linewidth=2, label=f'Absolute minimum: {min(distances):.1f}m')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    # 3. Hole-by-hole minimum distances
    hole_distances = proximity_df.groupby('golfer_hole')['distance_meters'].agg(['mean', 'min', 'max']).reset_index()
    
    x_pos = range(len(hole_distances))
    ax3.bar(x_pos, hole_distances['mean'], alpha=0.7, label='Average distance', color='lightblue')
    ax3.scatter(x_pos, hole_distances['min'], color='red', s=50, label='Minimum distance', zorder=5)
    ax3.set_xlabel('Golfer Hole Number')
    ax3.set_ylabel('Distance (meters)')
    ax3.set_title('Average and Minimum Distance by Golfer Hole')
    ax3.set_xticks(x_pos)
    ax3.set_xticklabels(hole_distances['golfer_hole'])
    ax3.legend()
    ax3.grid(True, alpha=0.3)
    
    # 4. Spatial plot showing the closest point pair
    # Load original data to plot all points
    csv_file = "outputs/20250810_132314_phase_03/sim_03/coordinates.csv"
    df = pd.read_csv(csv_file)
    golfer_data = df[df['type'] == 'hole']
    bevcart_data = df[df['type'] == 'bevcart']
    
    # Plot all points with transparency
    ax4.scatter(golfer_data['longitude'], golfer_data['latitude'], 
               c='lightblue', alpha=0.3, s=10, label='All golfer positions')
    ax4.scatter(bevcart_data['longitude'], bevcart_data['latitude'], 
               c='lightcoral', alpha=0.3, s=10, label='All beverage cart positions')
    
    # Highlight the closest pair
    ax4.scatter(closest_pair['golfer_lon'], closest_pair['golfer_lat'], 
               c='blue', s=100, label=f'Closest golfer point\n(Hole {closest_pair["golfer_hole"]})', zorder=5)
    ax4.scatter(closest_pair['bevcart_lon'], closest_pair['bevcart_lat'], 
               c='red', s=100, label=f'Closest beverage cart point\n(Serving hole {closest_pair["bevcart_hole"]})', zorder=5)
    
    # Draw line between closest points
    ax4.plot([closest_pair['golfer_lon'], closest_pair['bevcart_lon']], 
            [closest_pair['golfer_lat'], closest_pair['bevcart_lat']], 
            'purple', linewidth=3, label=f'Closest distance: {closest_pair["distance_meters"]:.1f}m', zorder=4)
    
    ax4.set_xlabel('Longitude')
    ax4.set_ylabel('Latitude')
    ax4.set_title('All GPS Points with Closest Pair Highlighted')
    ax4.legend()
    ax4.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('proximity_analysis.png', dpi=300, bbox_inches='tight')
    plt.show()
    
    return fig

def main():
    """Main analysis function."""
    csv_file = "outputs/20250810_132314_phase_03/sim_03/coordinates.csv"
    
    if not Path(csv_file).exists():
        print(f"Error: File {csv_file} not found!")
        return
    
    # Analyze proximity
    proximity_df, distances, closest_pair = analyze_proximity(csv_file)
    
    # Create visualizations
    fig = create_visualizations(proximity_df, distances, closest_pair)
    
    # Save detailed results (sample of closest distances to avoid huge file)
    closest_1000 = proximity_df.nsmallest(1000, 'distance_meters')
    closest_1000.to_csv('proximity_analysis_closest_1000.csv', index=False)
    print(f"\nTop 1000 closest point pairs saved to: proximity_analysis_closest_1000.csv")
    print(f"Visualization saved to: proximity_analysis.png")
    
    # Additional analysis - find all very close point pairs
    very_close_pairs = proximity_df[proximity_df['distance_meters'] < 100].copy()
    if len(very_close_pairs) > 0:
        print(f"\n=== VERY CLOSE POINT PAIRS (< 100m) ===")
        print(f"Total point pairs within 100m: {len(very_close_pairs):,}")
        
        print("\nTop 10 closest point pairs:")
        for i, (_, pair) in enumerate(very_close_pairs.nsmallest(10, 'distance_meters').iterrows(), 1):
            golfer_time = f"{pair['golfer_timestamp']//60:.0f}:{pair['golfer_timestamp']%60:02.0f}"
            bevcart_time = f"{pair['bevcart_timestamp']//60:.0f}:{pair['bevcart_timestamp']%60:02.0f}"
            print(f"  {i:2}. {pair['distance_meters']:.1f}m - "
                  f"Golfer @{golfer_time} hole {pair['golfer_hole']}, "
                  f"Cart @{bevcart_time} serving hole {pair['bevcart_hole']}")
    
    print(f"\n=== SUMMARY ===")
    print(f"Total point pairs analyzed: {len(distances):,}")
    print(f"Closest distance found: {min(distances):.2f} meters")
    print(f"This represents the absolute closest the golfer and beverage cart ever got to each other during the simulation.")

if __name__ == "__main__":
    main()
