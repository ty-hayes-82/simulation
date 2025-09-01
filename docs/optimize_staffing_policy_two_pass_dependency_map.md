@optimize_staffing_policy_two_pass.py

## Purpose
- Outline the behavior of `scripts/optimization/optimize_staffing_policy_two_pass.py` and recursively map all Python modules it references.
- Provide a complete list of actively used files vs. discovered-but-not-used files from this traversal.
- Identify Python files that create or copy artifacts (GeoJSON/CSV/PNG/JSON), and where those artifacts are consumed.

## Top-level Entry
- File: `scripts/optimization/optimize_staffing_policy_two_pass.py`
- Key responsibilities:
  - Two-pass optimization: first-pass minimal runs across all combinations; second-pass full runs for winners.
  - Invokes `scripts/sim/run_new.py` to execute simulations.
  - Aggregates results via helpers from `scripts/optimization/optimize_staffing_policy.py`.
  - Publishes results to `my-map-animation/public` and `my-map-setup/public` (coordinates, metrics, optional heatmaps and hole delivery GeoJSON).

### Direct Python Dependencies (static imports / direct inline imports)
- From `scripts/optimization/optimize_staffing_policy.py`:
  - `BLOCKING_VARIANTS`, `BlockingVariant`
  - `aggregate_runs`, `build_feature_collection`, `choose_best_variant`, `parse_range`, `utility_score`
  - `_make_group_context`, `_row_from_context_and_agg`, `_write_group_aggregate_file`, `_write_group_aggregate_heatmap`, `_write_group_delivery_geojson`, `_write_final_csv`
- CLI target invoked for runs: `scripts/sim/run_new.py`
- GeoJSON creation (inline within two-pass script):
  - Imports from `golfsim.viz.heatmap_viz`: `load_geofenced_holes`, `extract_order_data`, `calculate_delivery_time_stats` (for per-run hole_delivery_times.geojson generation when missing)

### Files Created / Copied by two-pass script
- Under optimization root:
  - Per group: `@aggregate.json`, `heatmap.png`, `hole_delivery_times.geojson`
  - CSV: `all_metrics.csv`
- Under `my-map-animation/public` and `my-map-setup/public`:
  - Copies course geojson assets (holes/course/cart_paths/greens/tees/holes_geofenced)
  - Copies simulation coordinate CSVs and per-run metrics into `/public/coordinates/` with `manifest.json`
  - Global/selected `hole_delivery_times.geojson` copied to `/public`

---

## Recursive Dependency Expansion

### 1) scripts/optimization/optimize_staffing_policy.py
- Responsibilities:
  - Core aggregation and selection logic (single/multi-stage). Provides helpers used by two-pass.
  - Generates: `@aggregate.json`, `heatmap.png` via `golfsim.viz.heatmap_viz.create_course_heatmap`, `hole_delivery_times.geojson` via `_write_group_delivery_geojson`, and `all_metrics.csv`.
- Imports:
  - `golfsim.viz.heatmap_viz`: `create_course_heatmap`, `load_geofenced_holes`
  - Standard libs: `argparse`, `json`, `math`, `csv`, `subprocess`, `sys`, `os`, `datetime`, `pathlib.Path`
- Artifact producers:
  - Writes group-level `hole_delivery_times.geojson` using `build_feature_collection()` with geofenced hole polygons.

### 2) scripts/sim/run_new.py
- Responsibilities:
  - Unified simulation CLI; runs delivery-runner scenario via `golfsim.simulation.orchestration.run_delivery_runner_simulation`.
  - Minimal-outputs support; may export per-run `hole_delivery_times.geojson`.
  - Auto-publishes to `my-map-animation/public` unless `--skip-publish`.
- Imports:
  - `golfsim.simulation.orchestration`: `run_delivery_runner_simulation`, `create_simulation_config_from_args`
  - `golfsim.viz.heatmap_viz`: `load_geofenced_holes`, `extract_order_data`, `calculate_delivery_time_stats`
- Artifact producers:
  - Per-run: `run_XX/coordinates.csv`, `simulation_metrics.json`, optional `delivery_heatmap.png` (via orchestrator), optional `hole_delivery_times.geojson` (per-run)
  - Copies to `my-map-animation/public`/`public/coordinates`

### 3) golfsim/simulation/orchestration.py
- Responsibilities:
  - Runs delivery runner simulation core loop; writes `results.json`, metrics JSON, logs, and coordinates CSV.
  - Generates heatmap PNG via `golfsim.viz.heatmap_viz.create_course_heatmap` unless minimal outputs.
  - Writes unified `coordinates.csv` via `golfsim.io.results.write_unified_coordinates_csv`.
  - Copies artifacts to `my-map-animation/public` via `golfsim.io.results.copy_to_public_coordinates` and `sync_run_outputs_to_public` (unless minimal outputs).
- Imports:
  - Config loaders: `golfsim.config.loaders`, `golfsim.config.models`
  - Services and generation: `golfsim.simulation.services`, `golfsim.simulation.delivery_service`, `golfsim.simulation.order_generation`
  - Postprocessing: `golfsim.postprocessing.coordinates`, `golfsim.postprocessing.golfer_colors`
  - IO: `golfsim.io.reporting`, `golfsim.io.results`
  - Viz: `golfsim.viz.heatmap_viz`, `golfsim.viz.matplotlib_viz`
  - Routing helpers: `golfsim.routing.utils.get_hole_for_node`
- Artifact producers:
  - Per run (in `output/.../run_XX/`):
    - `results.json`, `simulation_metrics.json`, `order_logs.csv`, `runner_action_log.csv`, `order_timing_logs.csv`
    - `delivery_heatmap.png` (when enabled)
    - `coordinates.csv`

### 4) golfsim/viz/heatmap_viz.py
- Responsibilities:
  - Builds heatmap PNGs; loads geofenced holes, calculates per-hole delivery time stats.
  - Also supports interactive Folium map HTML.
- Imports:
  - GeoPandas, Matplotlib, Folium, Pandas, NumPy
  - `golfsim.viz.matplotlib_viz.load_course_geospatial_data` for course layers
- Artifact producers:
  - PNG heatmaps to `<group or run>/delivery_heatmap.png`
  - May output interactive HTML heatmap if used (not directly referenced by two-pass)
- Artifact consumers:
  - Reads `courses/<course>/geojson/generated/holes_geofenced.geojson` and fallbacks to `geojson/holes.geojson`

### 5) golfsim/io/results.py
- Responsibilities:
  - Unified coordinates CSV writer, public publishing helpers, and auxiliary CSV writers.
- Artifact producers:
  - `write_unified_coordinates_csv(...)` → `coordinates.csv`
  - Copies `coordinates.csv` and `simulation_metrics.json` to `my-map-animation/public` and `public/coordinates` with `manifest.json`

### 6) sync_simulation_assets.py
- Responsibilities:
  - Scans `output/<course>/<timestamp>_{scenario}/` and writes curated copies to `my-map-animation/public/coordinates`, with an aggregated manifest.
  - Copies representative run’s `coordinates.csv`, aggregated metrics, and group-level `hole_delivery_times.geojson` if present.

---

## Artifact Map (Create/Copy/Consume)

- coordinates.csv
  - Create: `golfsim.io.results.write_unified_coordinates_csv` (called by orchestration)
  - Copy/Publish: `golfsim.io.results.copy_to_public_coordinates`, `golfsim.io.results.sync_run_outputs_to_public`, `scripts/sim/run_new.py`, `sync_simulation_assets.py`, two-pass publisher
  - Consume: Web app `my-map-animation` and `my-map-setup` (via `/public/coordinates/*.csv` + `manifest.json`)

- simulation_metrics.json
  - Create: `golfsim.io.reporting.generate_simulation_metrics_json` (from orchestration)
  - Copy: same as above publishers
  - Consume: map app controls, optimizers selection, reports

- delivery_heatmap.png
  - Create: `golfsim.viz.heatmap_viz.create_course_heatmap` (called by orchestrator and optimize scripts)
  - Consume: reports, visualization

- hole_delivery_times.geojson
  - Create: 
    - Group-level: `scripts/optimization/optimize_staffing_policy.py::_write_group_delivery_geojson`
    - Per-run: `scripts/sim/run_new.py::export_hole_delivery_geojson`
    - Fallback/inline creation inside two-pass script when missing (using heatmap_viz helpers)
  - Copy: two-pass publisher to `/public/coordinates/hole_delivery_times_<id>.geojson` and to global `/public/hole_delivery_times.geojson`
  - Consume: `my-map-animation/src/views/HeatmapView.tsx` (per-sim geojson preferred, fallback to `/hole_delivery_times.geojson`)

- Course GeoJSON assets (inputs to viz and routing)
  - `courses/<course>/geojson/generated/holes_geofenced.geojson` (primary for hole polygons)
  - `courses/<course>/geojson/generated/holes_connected.geojson` (cart routing nodes)
  - Others: `cart_paths.geojson`, `course_polygon.geojson`, `holes.geojson`, `greens.geojson`, `tees.geojson`
  - Copy to app public dirs by two-pass publisher and setup sync scripts

---

## Active vs. Inactive Python Files (from traversal starting at two-pass)

### Actively used (directly or transitively via two-pass)
- scripts/optimization/optimize_staffing_policy_two_pass.py
- scripts/optimization/optimize_staffing_policy.py
- scripts/sim/run_new.py
- golfsim/simulation/orchestration.py
- golfsim/viz/heatmap_viz.py
- golfsim/io/results.py
- sync_simulation_assets.py
- Plus transitive modules referenced by orchestration:
  - golfsim/config/{loaders.py, models.py}
  - golfsim/simulation/{services.py, tracks.py, orders.py, delivery_service.py, beverage_cart_service.py, order_generation.py, visibility_tracking.py}
  - golfsim/postprocessing/{coordinates.py, golfer_colors.py}
  - golfsim/analysis/{metrics_integration.py}
  - golfsim/viz/{matplotlib_viz.py}
  - golfsim/routing/{utils.py}
  - golfsim/io/{reporting.py, running_totals.py}

Note: The exact set used at runtime depends on CLI flags (e.g., minimal outputs skips heatmap/geojson export), but imports indicate potential usage.

### Discovered but not directly used by the two-pass flow
- scripts/sim/run_unified_simulation.py (separate unified runner)
- scripts/optimization/run_controls_grid.py (alternative grid driver)
- scripts/routing/{build_cart_network_from_holes_connected.py, extract_course_data.py}
- scripts/course_prep/geofence_holes.py (geofencing tool)
- convert_shapefile_to_geojson.py (utility)
- Various report scripts in scripts/report/* (used if auto-report is invoked elsewhere)

---

## Other GeoJSON Writers and Asset Producers

- GeoJSON generators (via GeoPandas `to_file`):
  - `convert_shapefile_to_geojson.py`
  - `scripts/routing/extract_course_data.py` (writes `course_polygon.geojson`, `holes.geojson`, `tees.geojson`, `greens.geojson`)
  - `scripts/course_prep/geofence_holes.py` (writes geofenced holes)
- Hole delivery GeoJSON creators/copy:
  - `scripts/optimization/optimize_staffing_policy.py` (group-level)
  - `scripts/sim/run_new.py` (per-run, optional via flags)
  - `my-map-setup/run_map_app.py` and `my-map-animation/run_map_app.py` (copy/ensure global/per-sim files in public dirs)
  - `sync_simulation_assets.py` (copies group-level into `/public/coordinates`)

## How to Extend This Map
- To add another entry point, append a new top-level section mirroring the above pattern: list direct imports, CLI invocations, produced artifacts, then recurse.
- To confirm runtime usage, search for symbol references and subprocess calls, then verify files appear under `output/` after a run.

## Quick Pointers
- Optimize flow always calls `scripts/sim/run_new.py` for runs, with flags:
  - First pass adds: `--minimal-outputs`, `--coordinates-only-for-first-run`, `--skip-publish`
  - Second pass: full outputs (heatmaps, per-run geojson if enabled)
- Per-group `hole_delivery_times.geojson` is generated by aggregation helpers; per-run versions are generated by the runner when export is enabled.
- The two-pass publisher sanitizes and deduplicates `coordinates.csv` and writes per-sim metrics and per-run hole delivery GeoJSON into `my-map-animation/public/coordinates/` with a curated `manifest.json` and course asset syncing.
