#!/usr/bin/env python3
"""Test script to verify CSV aggregation works correctly."""

import sys
from pathlib import Path
sys.path.append('.')

from scripts.sim.run_scenarios_batch import _aggregate_run_stats_to_csv

# Test the aggregation function
test_dir = Path('outputs/scenario_typical_weekday/delivery_runner_1r_total10_none')
if test_dir.exists():
    print(f"Testing CSV aggregation on: {test_dir}")
    _aggregate_run_stats_to_csv(test_dir, 'typical_weekday', 'delivery_runner_1r_total10_none')
    print("CSV aggregation completed")
    
    # Check if the CSV was created and has content
    csv_file = test_dir / "aggregated_stats.csv"
    if csv_file.exists():
        print(f"CSV file created: {csv_file}")
        with open(csv_file, 'r') as f:
            lines = f.readlines()
            print(f"CSV has {len(lines)} lines")
            if len(lines) > 1:
                print(f"Header: {lines[0].strip()}")
                print(f"Sample row: {lines[1].strip()}")
    else:
        print("CSV file was not created")
else:
    print(f"Test directory does not exist: {test_dir}")
