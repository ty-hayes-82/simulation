# Course Setup Scripts: Idle Hour Country Club (Lexington, KY)

**Course**: Idle Hour Country Club  
**Coordinates**: 38.027532, -84.469878

## Step 1 — Extract course data from OpenStreetMap
```powershell
python scripts/routing/extract_course_data.py --course "Idle Hour Country Club" --clubhouse-lat 38.027532 --clubhouse-lon -84.469878 --include-streets --street-buffer 750 --course-buffer 100 --include-sports-pitch --pitch-radius-yards 200 --include-water --water-radius-yards 200 --output-dir courses/idle_hour_country_club
```

**Outputs**: `pkl/cart_graph.pkl`, `pkl/golf_route.pkl`, `pkl/street_graph.pkl`, `geojson/` files, `geojson/generated/holes_geofenced.geojson`, `geojson/sports_pitches.geojson`, `geojson/pools_water.geojson`

## Step 2 — Generate holes connected path
```powershell
python scripts/course_prep/geofence_holes.py --boundary courses/idle_hour_country_club/geojson/course_polygon.geojson --holes courses/idle_hour_country_club/geojson/holes.geojson --generated_dir generated
```

**Outputs**: `geojson/generated/holes_connected.geojson`

## Step 3 — Build simplified cart network
```powershell
python scripts/routing/build_cart_network_from_holes_connected.py courses/idle_hour_country_club --save-png outputs/cart_network.png --shortcuts "138-173,225-189,13-191,14-223,101-69,102-206,23-55" --clubhouse-routes "115-114,1-2,116-117,239-238"
```

**Shortcuts**: 
- 138-173, 225-189, 13-191, 14-223, 101-69, 102-206, 23-55

**Clubhouse starting routes**:
- 115-114 (Holes 9 to 1)
- 1-2 (Holes 1 to 9) 
- 116-117 (Holes 10-18)
- 239-238 (Holes 18-10)

**Outputs**: Updated `pkl/cart_graph.pkl`, `outputs/cart_network.png`

## Step 4 — Compute travel times
```powershell
python scripts/routing/generate_node_travel_times.py --course-dir courses/idle_hour_country_club --speed 2.68
```

**Outputs**: `node_travel_times.json`

## Step 5 — Verify the build
```powershell
python scripts/routing/verify_cart_graph.py courses/idle_hour_country_club
```

**Outputs**: Console validation logs

## Test simulation
```powershell
python scripts/sim/run_unified_simulation.py --mode golfers-only --course-dir courses/idle_hour_country_club --groups-count 12 --first-tee 08:00 --groups-interval-min 12 --num-runs 1 --open-viewer
```

**Outputs**: `outputs/<scenario>/run_*/coordinates.csv`
