## run_unified_simulation.py — Dependency Guide

This document lists the internal modules and companion scripts that `scripts/sim/run_unified_simulation.py` calls or imports. Use it to understand what code paths are exercised by each mode and what external tools may be invoked.

### Primary script
- `scripts/sim/run_unified_simulation.py`

### Internal Python modules (direct imports)
- `golfsim.logging`: `init_logging`, `get_logger`
- `golfsim.performance_logger`: `get_performance_tracker`, `reset_performance_tracking`, `log_performance_summary`, `timed_operation`, `timed_file_io`, `timed_visualization`, `timed_computation`, `timed_simulation`
- `golfsim.config.loaders`: `load_tee_times_config`, `load_simulation_config`
- `golfsim.simulation.services`: `BeverageCartService`, `MultiRunnerDeliveryService`, `DeliveryOrder`
- `golfsim.simulation.phase_simulations`: `generate_golfer_track`
- `golfsim.simulation.crossings`: `compute_crossings_from_files`, `serialize_crossings_summary`
- `golfsim.simulation.pass_detection`: `find_proximity_pass_events`, `compute_group_hole_at_time`
- `golfsim.simulation.bev_cart_pass`: `simulate_beverage_cart_sales`
- `golfsim.simulation.engine`: `run_golf_delivery_simulation`
- `golfsim.io.results`: `write_unified_coordinates_csv`, `save_results_bundle`
- `golfsim.io.phase_reporting`: `save_phase3_output_files`, `write_phase3_summary`
- `golfsim.analysis.metrics_integration`: `generate_and_save_metrics`
- `golfsim.viz.matplotlib_viz`: `render_beverage_cart_plot`, `render_delivery_plot`, `load_course_geospatial_data`, `create_folium_delivery_map`, `clear_course_data_cache`
- `golfsim.viz.heatmap_viz`: `create_course_heatmap`, `create_interactive_course_heatmap`, `load_all_heatmap_data`, `clear_heatmap_caches`
- `utils.simulation_reporting`: `log_simulation_results`, `write_multi_run_summary`, `create_delivery_log`, `handle_simulation_error`

### External/standard libraries used
- `argparse`, `json`, `time`, `datetime`, `pathlib`, `sys`, `typing`, `os`, `subprocess`
- `simpy`, `csv`
- Optional/conditional: `urllib.request`, `socket`, `webbrowser`, `pickle`, `pandas`, `networkx`

### Companion scripts invoked via subprocess
- `scripts/analysis/generate_gemini_executive_summary.py`
  - Called to generate an executive summary for a run/output directory.
- `scripts/viz/export_hole_delivery_geojson.py`
  - Called to export `hole_delivery_times.geojson` for the React viewer.
- `my-map-animation/run_map_app.py`
  - Prepares/refreshes the viewer's `public/coordinates` manifest.
- React dev server (Create React App)
  - Spawns `npm start` inside `my-map-animation/` to serve the viewer (best-effort, non-blocking).

### Data/config file dependencies (read at runtime)
- Course configuration and assets under the selected `--course-dir` (default `courses/pinetree_country_club`):
  - `config/simulation_config.json`
  - `config/tee_times_config.json` (for scenario-driven tee times)
  - `geojson/generated/holes_connected.geojson` (paths/holes for bev cart + golfer tracks)
  - `geojson/generated/holes_geofenced.geojson` and `geojson/generated/lcm_course_nodes.geojson` (when computing crossings in delivery-runner mode with bev-cart)
  - `pkl/cart_graph.pkl` (optional; used for runner path/node visualization/synthesis)
  - `travel_times.json` and `travel_times_simple.json` (may be renamed to `.backup` when `--regenerate-travel-times` is used)

### Mode-to-dependency mapping (high level)
- bev-carts (GPS only)
  - `BeverageCartService`, `write_unified_coordinates_csv`, `render_beverage_cart_plot`, metrics integration
- bev-with-golfers (cart + golfer proximity sales)
  - `compute_crossings_from_files`, `simulate_beverage_cart_sales`, `generate_golfer_track`, plotting, metrics integration
- golfers-only (golfer GPS tracks only)
  - `generate_golfer_track`, `save_phase3_output_files`
- delivery-runner (0..N runners serving orders)
  - `MultiRunnerDeliveryService`, order generation helpers in this script, optional bev-cart inclusion, plotting/heatmap, metrics integration
- single-golfer (parity with dedicated single-golfer flow)
  - `run_golf_delivery_simulation`, `save_results_bundle`, plotting/heatmap, metrics annotation
- optimize-runners (search min runners to meet SLA)
  - Reuses delivery-runner logic + utilization/summary builders in this script

### Outputs that may be produced
- Run folders under `outputs/.../` or a user-specified `--output-dir`, including: `coordinates.csv`, `events.csv`, `results.json`/`result.json`, `sales.json`, PNG/HTML visualizations, metrics markdowns, and summaries.
- Optional: `hole_delivery_times.geojson` in `my-map-animation/public/` (for viewer).

### Notes
- Viewer startup and executive summary generation are best-effort; failures are logged and do not stop the simulation.
- On Windows PowerShell, prefer one command per line without piping/chaining when running this script.
