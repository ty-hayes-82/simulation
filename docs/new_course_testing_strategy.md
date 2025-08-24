## Strategy: Test README flows with a new golf club without overwriting anything

This guide walks you through setting up and testing all README flows on a brand-new course directory in a fully non-destructive way. You will:
- create an isolated course copy
- generate geofenced holes and the simplified holes-connected network
- precompute travel times
- run delivery-runner simulations into a unique outputs folder
- preview in the React map app

All steps write only to the new course folder or timestamped outputs, leaving existing data untouched.

### 0) Environment isolation
- Use Poetry shell (recommended) or a venv so that any optional packages you install don’t affect other projects.
```
poetry install
poetry shell
```

### 1) Create a new course workspace (non-destructive)
Pick a unique course key. Example here uses `new_club_name`.
```
$root = (Resolve-Path .).Path
$src  = Join-Path $root "courses/pinetree_country_club"
$dst  = Join-Path $root "courses/new_club_name"

if (-not (Test-Path $dst)) {
  Copy-Item $src $dst -Recurse -Force
}

# Ensure config exists and remains editable only under new_club_name
Get-ChildItem $dst
```

Why copy? Scripts read from `--course-dir`, and this keeps your original Pinetree assets intact while giving you a safe sandbox.

### 2) Configure clubhouse and timing in the new course
Edit only the new course’s `simulation_config.json`:
```
courses/new_club_name/config/simulation_config.json
```
- Set `clubhouse.latitude` and `clubhouse.longitude` to the new club.
- Optionally adjust:
  - `golfer_18_holes_minutes` (round duration)
  - `delivery_runner_speed_mps`, `delivery_prep_time_sec`
  - `network_params` (e.g., `max_connection_distance_m`)

Copy or tailor tee scenarios (optional):
```
courses/new_club_name/config/tee_times_config.json
```

The config loader looks in `courses/<club>/config/` first, so no global files are modified.

### 3) Extract base course data (safe outputs)
Run the extractor with `--output-dir courses/new_club_name`. This writes only under that path.
```
python scripts/routing/extract_course_data.py \
  --course "New Club Name" \
  --clubhouse-lat <LAT> \
  --clubhouse-lon <LON> \
  --include-streets \
  --street-buffer 750 \
  --course-buffer 100 \
  --output-dir courses/new_club_name
```

What gets written (non-destructive, scoped under new course):
- `courses/new_club_name/geojson/{course_polygon,holes,tees,greens}.geojson`
- `courses/new_club_name/geojson/generated/holes_geofenced.geojson`
- `courses/new_club_name/geojson/generated/holes_connected.geojson`
- `courses/new_club_name/pkl/{cart_graph.pkl,golf_route.pkl,street_graph.pkl?}`
- `courses/new_club_name/config/simulation_config.json` (created/merged)

Notes:
- Geofencing and holes-connected are produced automatically. Nothing in other course folders is touched.

### 4) Build simplified holes-connected cart network (optional, still scoped)
If you want the simplified network from the README’s "holes_connected" section:
```
python scripts/routing/build_cart_network_from_holes_connected.py courses/new_club_name --save-png outputs/cart_network.png
```
This writes `courses/new_club_name/pkl/cart_graph.pkl` and, if provided, a PNG under `courses/new_club_name/outputs/` (relative save path resolves inside the course dir).

### 5) Pre-compute node travel times for the new course (scoped file)
```
python scripts/routing/generate_node_travel_times.py --course-dir courses/new_club_name --speed 6.0
```
Writes `courses/new_club_name/node_travel_times.json`.

### 6) Run delivery-runner simulations into a unique outputs folder
Use the unified runner. Avoid global cleanup by passing `--keep-old-outputs` and a custom `--output-dir`:
```
python scripts/sim/run_new.py \
  --course-dir courses/new_club_name \
  --num-runners 1 \
  --tee-scenario typical_weekend \
  --runner-speed 6.0 \
  --num-runs 1 \
  --keep-old-outputs \
  --output-dir outputs/NEW_CLUB_test_$(Get-Date -Format yyyyMMdd_HHmmss)
```
All artifacts go under your timestamped `outputs/NEW_CLUB_test_*` directory. Existing outputs remain.

Tips:
- Add `--minimal-outputs` to skip heavy artifacts if you only need the coordinates and summary.
- Add `--no-heatmap` if you want to speed things up further.

### 7) Preview in the React map app without copying over public
Point the loader at your timestamped outputs; it copies only the discovered coordinates into the app’s public folder and generates a manifest. Your raw outputs are untouched.
```
python scripts/viz/load_animations.py --source-dir outputs/NEW_CLUB_test_YYYYMMDD_HHMMSS --start-app
```

If you want a read-only preview, skip `--start-app` and open the copied files under `my-map-animation/public/coordinates/` in version control to verify diffs before starting the app.

### 8) Safety checklist (no overrides)
- Use a dedicated `--course-dir` like `courses/new_club_name` for every command.
- Never run generators against `courses/pinetree_country_club` when testing new clubs.
- Always specify `--output-dir` for simulations; the runner creates timestamped subfolders and can keep old outputs with `--keep-old-outputs`.
- The extractor merges defaults into `simulation_config.json` only when keys are missing; it will not erase your edits.

### 9) Quick rollback
- To discard the test: delete the `courses/new_club_name/` folder and the specific `outputs/NEW_CLUB_test_*` folder.
- Original course data remains intact.

### 10) Troubleshooting (new club)
- Missing `tee_times_config.json`: copy from `courses/pinetree_country_club/config/` and adjust scenarios.
- No cart paths found: re-run extractor with `--broaden`, or provide a custom cart path GeoJSON.
- Runner coordinates missing: confirm `holes_connected.geojson`, `pkl/cart_graph.pkl`, and clubhouse tuple handling in config.

This workflow mirrors the README functionality while guaranteeing isolation for new-club experimentation.


