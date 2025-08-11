# Golfer-Beverage Cart Visibility Tracking

## Overview

The visibility tracking system adds time-based color coding to golfer GPS points based on how long it has been since they last saw a beverage cart. This helps identify areas where golfers may be frustrated due to lack of beverage service visibility.

## Features

### Color-Coded Status
Golfer GPS points are automatically color-coded based on time since last cart sighting:

- **🟢 Green**: Recently saw cart (< 20 minutes)
- **🟡 Yellow**: Moderate time since last sighting (20-40 minutes)  
- **🟠 Orange**: Long time since last sighting (40-60 minutes)
- **🔴 Red**: Very long time since last sighting (> 60 minutes)

### Pulsing/Glow Flag
When golfers reach the red status (> 60 minutes without seeing a cart), an optional `pulsing` flag is added to enable visual emphasis in visualization tools.

## Implementation

### Core Components

1. **VisibilityTrackingService** (`golfsim/simulation/visibility_tracking.py`)
   - Main service class for tracking visibility across entire simulation
   - Configurable thresholds for status transitions
   - Haversine distance calculation for proximity detection

2. **Enhanced CSV Export** (`golfsim/io/results.py`)
   - New `write_coordinates_csv_with_visibility()` function
   - Backwards compatible with existing CSV format
   - Automatic visibility processing when both golfers and carts are present

3. **Integration with Phase Simulations**
   - Phase 3: Beverage cart + single golfer group 
   - Phase 12: Combined golfer and beverage cart tracking
   - Other phases remain unchanged (single entity type)

### CSV Output Format

The enhanced CSV includes additional columns for golfer points:

```csv
id,latitude,longitude,timestamp,type,hole,visibility_status,time_since_last_sighting_min,pulsing
test_golfer_1,35.7796,78.6382,9000,golfer,1,green,5.0,false
test_golfer_1,35.7800,78.6386,9060,golfer,1,yellow,25.5,false
test_golfer_1,35.7804,78.6390,9120,golfer,2,red,65.2,true
```

### Configuration

Visibility thresholds can be customized:

```python
from golfsim.simulation.visibility_tracking import create_visibility_service

service = create_visibility_service(
    proximity_threshold_m=100.0,      # Distance for "seeing" cart
    green_to_yellow_min=20.0,         # Green → Yellow transition
    yellow_to_orange_min=40.0,        # Yellow → Orange transition  
    orange_to_red_min=60.0,           # Orange → Red transition
    red_pulsing_enabled=True          # Enable pulsing for red status
)
```

## Usage

### Automatic Integration

The visibility tracking is automatically enabled for simulations that include both golfers and beverage carts:

- **Phase 3**: `run_bev_cart_phase3.py` - Single golfer group + beverage cart
- **Phase 12**: `run_phase12_golfer_and_bev.py` - Golfer + beverage cart

### Manual Usage

```python
from golfsim.io.results import write_coordinates_csv_with_visibility

# Enhanced CSV with visibility tracking
write_coordinates_csv_with_visibility(
    {"golfer_1": golfer_points, "bev_cart_1": cart_points},
    "output/coordinates.csv", 
    enable_visibility_tracking=True,
    visibility_thresholds={
        "proximity_threshold_m": 150.0,  # Custom threshold
        "green_to_yellow_min": 15.0,     # Custom timing
    }
)

# Standard CSV (no visibility tracking)
write_coordinates_csv_with_visibility(
    points_by_id,
    "output/coordinates.csv",
    enable_visibility_tracking=False
)
```

### Testing

Run the test script to see the feature in action:

```bash
conda activate my_gemini_env
python scripts/test/test_visibility_tracking.py
```

This creates a demo scenario with:
- Single golfer playing 18 holes over 4 hours
- Beverage cart encountering golfer 3 times
- Complete visibility status progression through all color states

## Technical Details

### Proximity Detection

- Uses Haversine distance calculation for GPS accuracy
- Default proximity threshold: 100 meters
- Timestamps must match exactly between golfer and cart points for detection

### Performance

- Minimal overhead when visibility tracking is disabled
- Efficient timestamp-based indexing for large coordinate datasets  
- Only processes golfer points when both golfers and carts are present

### Backwards Compatibility

- All existing CSV exports continue to work unchanged
- New visibility columns only appear when tracking is enabled
- Existing visualization and analysis tools work with enhanced CSVs

## Example Output

Sample visibility progression for a golfer:

```
Time 30min: GREEN (last sighting: 5.0min ago)
Time 60min: YELLOW (last sighting: 25.5min ago)  
Time 90min: ORANGE (last sighting: 45.2min ago)
Time 120min: RED (last sighting: 65.8min ago) [PULSING]
```

## Future Enhancements

Potential extensions to the visibility tracking system:

1. **Multi-cart tracking**: Track which specific cart was last seen
2. **Heat mapping**: Generate spatial heat maps of poor visibility areas
3. **Alert thresholds**: Configurable alerts when golfers reach red status
4. **Historical analysis**: Track visibility trends across multiple rounds
5. **Cart dispatching**: Use visibility data to optimize cart routing

## Integration Notes

- Works seamlessly with existing phase simulation infrastructure
- Compatible with all current visualization tools
- No changes required to core simulation timing or logic
- Visibility processing happens only during CSV export phase
