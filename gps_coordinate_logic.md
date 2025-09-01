## Runner–Golfer Coordinates Snapping & Delivery Meeting Logic

This document describes the implementation that ensures delivery runners meet golfers exactly at the golfers’ GPS point at the nearest-minute to the delivery, flags those moments in both streams, and saves a filtered CSV for quick inspection.

### Goals
- Always meet the golfer at the golfer’s minute-aligned GPS point (nearest to the delivery time).
- Snap the runner’s outbound endpoint to exactly that golfer coordinate and timestamp.
- Turn the golfer marker green at that exact moment if delivered within SLA.
- Persist delivery flags and order IDs to the unified coordinates CSV.
- Emit a filtered coordinates_delivery_points.csv containing only delivery meeting points.

### CSV Interface Changes
- Added new columns to the unified coordinates CSV:
  - `order_id`: string, order identifier for the delivery point.
  - `is_delivery_event`: boolean, marks the coordinate as the delivery meeting point.

These fields are normalized and passed through by the writer so downstream consumers can inspect delivery events without breaking existing flows.

Affected code:
- `golfsim/io/results.py`
  - `normalize_coordinate_entry()`: preserves `order_id`, `is_delivery_event` when present.
  - `write_unified_coordinates_csv()`: includes the new columns in `fieldnames`.

### Runner Coordinate Generation (Meeting Logic)
File: `golfsim/postprocessing/coordinates.py`

Function: `generate_runner_coordinates_from_events()`

Key behaviors:
- Build `order_id -> group_id` mapping from events for accurate group alignment.
- Determine the meeting point by selecting the golfer’s nearest-minute GPS coordinate for the order’s group at/near the delivered timestamp.
- Compute the shortest path from the clubhouse to the meeting node and back using `nearest_node()` and `networkx.shortest_path()`.
- If departure time is unknown, back-calculate it from routed path length and runner speed.
- Use internal `_nodes_to_points()` to time-scale per-segment traversal so the final outbound point timestamp equals the meeting timestamp.
- SNAP: Overwrite the last outbound runner point’s `latitude`/`longitude` to match the golfer’s meeting coordinate exactly, and set:
  - `is_delivery_event = True`
  - `order_id = <order_id>`
- Start the return path at the same meeting timestamp; estimate its end from path length and speed.

Fallbacks:
- If delivery stats or group mapping are missing, fall back to global nearest golfer coordinate.
- If cart graph nodes cannot be resolved, skip pathing for that order.

### Golfer Annotation and Color Update
File: `golfsim/simulation/orchestration.py`

- After generating `runner_points`, iterate delivery-flagged runner points and locate the corresponding golfer point (same group, same meeting timestamp).
- Set golfer flags on that point:
  - `is_delivery_event = True`
  - `order_id = <order_id>`
- SLA coloring at the exact meeting minute:
  - If `(meeting_ts - placed_ts) <= SLA_seconds`, set golfer `fill_color` and `border_color` to green (`#00b894`).
- SNAP safeguard: Re-write the runner’s flagged point `latitude`/`longitude` to the golfer’s coordinates (extra defense against drift), ensuring visual overlap in the animation.

### Filtered CSV for Delivery Points
File: `golfsim/simulation/orchestration.py`

- Alongside the standard `coordinates.csv`, we write `coordinates_delivery_points.csv` that includes only coordinates with `is_delivery_event == True` (both golfer and runner streams). This is useful for debugging and validating exact meeting behavior.

### Verification Checklist
- Unified CSV schema contains `order_id` and `is_delivery_event` columns.
- For each delivery, there exist exactly two flagged rows in the filtered CSV:
  - One golfer row (type `golfer`, green if under SLA) at the meeting timestamp.
  - One runner row (type `runner`) at the identical timestamp and identical lat/lon.
- In the main CSV, grep for `#00b894` confirms SLA-met golfer points are green at the flagged moment.

### Edge Cases & Notes
- If the cart graph or meeting node resolution fails, no runner points are added for that order.
- When group IDs are absent on events, the meeting point falls back to global nearest golfer minute.
- Time scaling avoids minute rounding—exact time scaling is used so the final outbound point equals the meeting timestamp; return starts at the same timestamp.

### Files and Functions Touched
- `golfsim/io/results.py`
  - `normalize_coordinate_entry()`
  - `write_unified_coordinates_csv()`
- `golfsim/postprocessing/coordinates.py`
  - `generate_runner_coordinates_from_events()` and helpers
- `golfsim/simulation/orchestration.py`
  - Delivery flag/green annotation and filtered CSV write

### Performance Considerations
- The snapping and scaling operate per order path; impact is minimal compared to pathfinding.
- Writing a second filtered CSV is negligible relative to the main CSV.

### Backward Compatibility
- Existing consumers that ignore unknown columns remain unaffected.
- The default color logic for non-delivery moments is unchanged; only the exact delivery minute is forced green when SLA is met.

### Future Enhancements
- Multi-runner meeting collisions resolution/visualization.
- Explicit tolerance thresholds for snapping when course data is noisy.
- Optional interpolation for sub-minute golfer telemetry (if available) to increase accuracy.


