# Course Setup Scripts

## Step 1 — Extract initial course data from OpenStreetMap
For new courses, use the extract script to download and create initial GeoJSON files:
```powershell
python scripts/routing/extract_course_data.py --course "Course Name" --clubhouse-lat LAT --clubhouse-lon LON --include-streets --street-buffer 750 --course-buffer 100 --include-sports-pitch --pitch-radius-yards 200 --include-water --water-radius-yards 200 --output-dir courses/course_name
```

**Outputs**: 
- `geojson/course_polygon.geojson`, `geojson/holes.geojson`, `geojson/tees.geojson`, `geojson/greens.geojson`
- `geojson/cart_paths.geojson`, `geojson/streets.geojson` (if --include-streets)
- `geojson/sports_pitches.geojson` (if --include-sports-pitch), `geojson/pools_water.geojson` (if --include-water)
- `geojson/generated/holes_geofenced.geojson`, `geojson/generated/holes_connected.geojson`
- `pkl/cart_graph.pkl`, `pkl/golf_route.pkl`, `pkl/street_graph.pkl` (if --include-streets)
- `config/simulation_config.json` (course configuration with delivery settings)
- `config/tee_times_config.json` (copied from template with real_tee_sheet scenario)
- `route_summary.json`

**Note**: The script automatically copies the tee times configuration template and creates a complete simulation config with all necessary delivery runner settings (delivery_total_orders, delivery_hourly_distribution, etc.) to ensure simulations work out of the box.

## Step 1 (Alternative) — Refresh existing course data
For existing courses, use the refresh script to update GeoJSON files:
```powershell
python scripts/maintenance/refresh_course_data.py --course-id keswick_hall --radius-km 2.0 --pitch-radius-yards 200 --water-radius-yards 200 --simplify 5
```

This recreates the existing course GeoJSON files with updated OpenStreetMap data (same outputs as Step 1).

## Step 2 — Edit geofences and connections using 3rd party tools
Use a 3rd party GIS website or tool to manually edit the generated files:

1. **Edit geofences**: Update `geojson/generated/holes_geofenced.geojson` and save as `holes_geofenced_updated.geojson`
2. **Edit connections**: Update `geojson/generated/holes_connected.geojson` to add shortcuts and clean up connections, save as `holes_connected_updated.geojson`

**Files to edit**:
- `courses/[course_name]/geojson/generated/holes_geofenced.geojson` → `holes_geofenced_updated.geojson`
- `courses/[course_name]/geojson/generated/holes_connected.geojson` → `holes_connected_updated.geojson`

This is a critical step to ensure accurate geofences and network connectivity.

## Step 3 — Build cart network graph
```powershell
python scripts/routing/build_cart_network_from_holes_connected.py courses/[course_name]
```

**Outputs**: `pkl/cart_graph.pkl` (NetworkX graph built from holes_connected data, replaces the initial cart_graph.pkl)

## Step 4 — Compute travel times
```powershell
python scripts/routing/generate_node_travel_times.py --course-dir courses/[course_name]
```

**Outputs**: `node_travel_times.json` (Pre-computed travel times from the clubhouse to all course nodes, used for accurate delivery time simulation.)