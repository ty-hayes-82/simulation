#!/usr/bin/env python3
import sys
sys.path.append('.')
from golfsim.viz.heatmap_viz import extract_order_data, calculate_delivery_time_stats
import json

# Load the new 1 mph results
with open('outputs/20250816_143146_0bevcarts_3runners_0golfers_busy_weekend/run_01/results.json') as f:
    results = json.load(f)

# Test the fixed extraction with 1 mph speed
order_data = extract_order_data(results)
hole_stats = calculate_delivery_time_stats(order_data)

print('=== 1 MPH SPEED HEATMAP VALUES ===')
for hole_num in sorted(hole_stats.keys()):
    if hole_num in [14, 18]:
        stats = hole_stats[hole_num]
        print(f'Hole {hole_num}: {stats["avg_time"]:.1f} min (count: {stats["count"]})')

print('\n=== VERIFICATION - ACTUAL DELIVERY STATS ===')
# Get actual delivery times for comparison  
hole18_stats = [s for s in results['delivery_stats'] if s.get('hole_num') == 18]
hole14_stats = [s for s in results['delivery_stats'] if s.get('hole_num') == 14]

if hole18_stats:
    print(f'Hole 18 actual delivery_time_s: {hole18_stats[0]["delivery_time_s"]:.1f}s = {hole18_stats[0]["delivery_time_s"]/60:.2f}min')
if hole14_stats:
    print(f'Hole 14 actual delivery_time_s: {hole14_stats[0]["delivery_time_s"]:.1f}s = {hole14_stats[0]["delivery_time_s"]/60:.2f}min')

print('\n=== COMPARISON ===')
print('6 mph speed (previous test):')
print('  Hole 18: 1.1 min, Hole 14: 2.7 min')
print('')
print('1 mph speed (current test):')
for hole_num in [14, 18]:
    if hole_num in hole_stats:
        print(f'  Hole {hole_num}: {hole_stats[hole_num]["avg_time"]:.1f} min')

print('\n=== SPEED RATIO CHECK ===')
print('Expected: 1 mph should be ~6x slower than 6 mph')
if 18 in hole_stats and 14 in hole_stats:
    print(f'Hole 18: 6.6min / 1.1min = {6.6/1.1:.1f}x slower')
    print(f'Hole 14: 16.2min / 2.7min = {16.2/2.7:.1f}x slower')
