## Runner–Golfer Coordinates Snapping & Delivery Meeting Logic

This document describes the implementation that ensures delivery runners meet golfers exactly at the golfers’ GPS point at the nearest-minute to the delivery, flags those moments in both streams, and saves a filtered CSV for quick inspection.

### Goals
- Always meet the golfer at the golfer’s minute-aligned GPS point (nearest to the delivery time).
- Snap the runner’s outbound endpoint to exactly that golfer coordinate and timestamp.
- Turn the golfer marker green at that exact moment if delivered within SLA.
- Persist delivery flags and order IDs to the unified coordinates CSV.
- Emit a filtered coordinates_delivery_points.csv containing only delivery meeting points.

### Final Strategy: Shortest-Path Runner Pathing

- Runners always travel via the cart graph’s shortest path, not the golfer’s path.
- The authoritative routing network is `cart_graph.pkl` (loaded NetworkX graph). Never travel off this graph.
- Edge cost is distance-based: use edge attribute (e.g., `length_m`) when present; otherwise compute from node coordinates (`x`,`y`).
- Meeting target is the golfer’s nearest-minute GPS point to the delivery-complete time.
- Meeting node is resolved with `nearest_node(cart_graph, lon, lat)` using the golfer’s meeting coordinate.
- Outbound path uses `networkx.shortest_path(clubhouse_node, meeting_node, weight=distance)` where `distance` is the edge length (meters).
- Return path uses `networkx.shortest_path(meeting_node, clubhouse_node, weight=distance)` (reversal is used only if it is also the shortest).
- Timing is derived from graph edge lengths and `runner_speed_mps`:
  - `start_ts = meeting_ts - travel_out_s`, `return_end_ts = meeting_ts + travel_back_s`.
  - No minute rounding for traversal; only the meeting is minute-aligned.
- Coordinate synthesis uses `_nodes_to_points(nodes, start_ts, end_ts, ...)` to time-scale segments so the last outbound point lands exactly on `meeting_ts`.
- SNAP: overwrite the final outbound runner point’s lat/lon to the golfer’s meeting coordinate; set `is_delivery_event=True` and `order_id`.
- Annotate the matching golfer point at `meeting_ts` with the same flags and apply SLA-green (`#00b894`) when within threshold.
- Persist both streams to the unified CSV, and also write a filtered `coordinates_delivery_points.csv` containing only `is_delivery_event == True` rows.
- No geometry smoothing or straight-line interpolation that cuts across the map; emitted runner points must lie strictly on nodes/edges of `cart_graph.pkl`.

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
- Compute the shortest path from the clubhouse to the meeting node and back using `nearest_node()` and weighted `networkx.shortest_path()` over `cart_graph.pkl`.
- If departure time is unknown, back-calculate it from routed path length and runner speed.
- Use internal `_nodes_to_points()` to time-scale per-segment traversal so the final outbound point timestamp equals the meeting timestamp.
- SNAP: Overwrite the last outbound runner point’s `latitude`/`longitude` to match the golfer’s meeting coordinate exactly, and set:
  - `is_delivery_event = True`
  - `order_id = <order_id>`
- Start the return path at the same meeting timestamp; estimate its end from path length and speed.

- Return route uses a fresh `networkx.shortest_path(meeting_node, clubhouse_node)` computation (do not assume reverse of outbound unless it is also shortest).
- Do not follow the golfer’s node sequence; always route the runner on the graph’s shortest path between endpoints.
- Never deviate from the shortest path defined by `cart_graph.pkl`. If no path exists, skip generating runner points for that order (no off-graph fallback).

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

- Runner route is the shortest path in both directions; optionally verify by recomputing with `networkx.shortest_path` against the same endpoints.
  - Validate that emitted runner node sequence equals the recomputed shortest path (weighted) between the same endpoints.
  - Confirm all runner coordinates are graph node coordinates (or lie along graph edges if edge-interpolated).

### Edge Cases & Notes
- If the cart graph or meeting node resolution fails, no runner points are added for that order.
- When group IDs are absent on events, the meeting point falls back to global nearest golfer minute.
- Time scaling avoids minute rounding—exact time scaling is used so the final outbound point equals the meeting timestamp; return starts at the same timestamp.

- If the shortest return path differs from the outbound reverse, prefer the newly computed shortest return path.
 - No off-graph fallback: if weighted shortest path cannot be found in `cart_graph.pkl`, do not synthesize runner points for that order.

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


