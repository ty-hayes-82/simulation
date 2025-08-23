### Interactive controls and reload strategy for my-map-animation

Goals
- Add top-of-map controls so a user can select: 1) Number of Runners, 2) Number of Orders.
- When a selection is applied, reload both: a) the animated map coordinates and metrics, b) the heatmap view.
- Keep selections shared across views and deep-linkable.

Recommended free UI stack
- Mantine for controls (NumberInput, Slider, Select, Button) — MIT and fast to integrate.
- Optional: Material React Table or React Data Table Component for a summary list of available simulations.

High-level UX
- A compact TopBar overlay that appears on all routes (`/animation`, `/heatmap`).
  - Controls: Number of runners (selectable set from available simulations), Number of orders (numeric or range), Apply and Reset buttons.
  - Read-only badges show the chosen simulation id, scenario label, and quick stats.
- Apply updates the selected simulation across the app.
- URL adds `?sim=<id>` so links/bookmarks restore selections.

Data contract and manifest
- We will extend `/public/coordinates/manifest.json` to include metadata the UI needs to filter and to build URLs for dependent files.

Proposed manifest schema
```json
{
  "simulations": [
    {
      "id": "20250823_135657_delivery_runner_1_runners_typical_weekday_1_groups_run_01_coordinates",
      "name": "Delivery Runners Only | 1 Runner | Typical Weekday 1 Groups | RUN_01 | GPS Coordinates",
      "filename": "20250823_135657_delivery_runner_1_runners_typical_weekday_1_groups_run_01_coordinates.csv",
      "heatmapFilename": "20250823_135657_delivery_runner_1_runners_typical_weekday_1_groups_run_01_coordinates_delivery_heatmap.png",
      "metricsFilename": "20250823_135657_delivery_runner_1_runners_typical_weekday_1_groups_run_01_coordinates_metrics.json",
      "holeDeliveryGeojson": "hole_delivery_times_20250823_135657_delivery_runner_1_runners_typical_weekday_1_groups_run_01.geojson",
      "meta": {
        "runners": 1,
        "bevCarts": 0,
        "golfers": 0,
        "scenario": "typical_weekday_1_groups",
        "orders": 87,
        "lastModified": "2025-08-23T13:56:57Z"
      }
    }
  ],
  "defaultSimulation": "20250823_135657_delivery_runner_1_runners_typical_weekday_1_groups_run_01_coordinates"
}
```

Notes
- `orders` should come from per-run metrics if available (see Backend updates below).
- If a per-simulation hole-delivery GeoJSON exists, reference it; otherwise omit and the frontend will fall back to the global `/hole_delivery_times.geojson`.

Backend (Python) updates — `my-map-animation/run_map_app.py`
1) Enrich manifest
- Parse runner count already extracted by `_parse_simulation_folder_name` and include as `meta.runners`.
- Look for metrics JSON in each run folder (patterns like `delivery_runner_metrics*.json` or `*_metrics.json`).
  - If found, parse to get an order count (prefer keys like `totalOrders` or `orderCount`). Store in `meta.orders`.
- For each simulation:
  - Keep `filename` (CSV) as today.
  - If a heatmap image exists in the same directory (`delivery_heatmap.png` or `heatmap.png`), copy it to `/public/coordinates/<id>_<orig>.png` and set `heatmapFilename` accordingly.
  - If a metrics JSON exists, copy it to `/public/coordinates/<id>_metrics.json` and set `metricsFilename`.
  - Optionally, if a per-run `hole_delivery_times.geojson` exists, copy to `/public/coordinates/hole_delivery_times_<id>.geojson` and set `holeDeliveryGeojson`.

2) Copy logic additions
- Extend `copy_heatmaps_to_coordinates_dirs` to also discover and register corresponding `metrics` files.
- Add helper to read metrics and extract a robust `orders` value, tolerating different keys:
  - Try `totalOrders`, then `orderCount`, then sum arrays if present (e.g., `orders` list length), else omit.

3) Keep `defaultSimulation` selection logic the same, but prefer newest non-Local as today.

Frontend integration
New files
- `src/context/SimulationContext.tsx`: React context (or Zustand) holding `selectedSimId`, `filters` (`runners`, `orders`), manifest, and helper `selectBestMatch`.
- `src/components/TopBarControls.tsx`: The overlay UI with Mantine controls; reads manifest distinct runner counts and order ranges.
- `src/lib/manifest.ts`: Loader and types for the manifest; caches result and exposes utility selectors.

Wiring changes
- `src/App.tsx`
  - Wrap routes with `SimulationProvider`.
  - Render `<TopBarControls />` once so it appears on all views.
  - Sync `selectedSimId` with URL query `?sim=` on load and on change.

- `src/views/AnimationView.tsx`
  - Replace hardcoded `coordinates.csv` with dynamic path:
    - `csvPath = /coordinates/${selectedSim.filename}`
  - Load metrics from per-sim file when present:
    - Try `/coordinates/${selectedSim.metricsFilename}`, else fall back to `/coordinates/simulation_metrics.json`.
  - On `selectedSimId` change: re-fetch CSV and metrics, reset animation timing.

- `src/views/HeatmapView.tsx`
  - Load per-sim hole delivery GeoJSON when available:
    - Try `/coordinates/${selectedSim.holeDeliveryGeojson}`; fallback to `/hole_delivery_times.geojson` then `/hole_delivery_times_debug.geojson`.
  - Load the same per-sim metrics used by Animation view for consistent panels.

Selection logic
- Filters: `runners` (exact match) and `orders` (closest by absolute difference).
- `selectBestMatch(filters, manifest)` returns the `id` of the best simulation.
- If no candidate matches `runners`, choose closest `runners` value, then minimize order distance.
- Persist to URL and localStorage for resilience.

Minimal types
```ts
export type SimulationMeta = {
  runners?: number;
  bevCarts?: number;
  golfers?: number;
  scenario?: string;
  orders?: number;
  lastModified?: string;
};

export type SimulationEntry = {
  id: string;
  name: string;
  filename: string;               // CSV
  heatmapFilename?: string;       // PNG (optional)
  metricsFilename?: string;       // JSON (optional)
  holeDeliveryGeojson?: string;   // GEOJSON (optional)
  meta?: SimulationMeta;
};

export type SimulationManifest = {
  simulations: SimulationEntry[];
  defaultSimulation?: string;
};
```

Folder and file structure
```
my-map-animation/
  public/
    coordinates/
      manifest.json
      <simId>.csv
      <simId>_delivery_heatmap.png          (if exists)
      <simId>_metrics.json                  (if exists)
      hole_delivery_times_<simId>.geojson   (if exists)
    hole_delivery_times.geojson             (global fallback)
    hole_delivery_times_debug.geojson       (debug fallback)
```

Implementation steps (concise)
1) Backend
- Extend `run_map_app.py` to discover per-run metrics and write enriched `manifest.json` as above.
- Copy per-run metrics and (optional) per-run hole-delivery GeoJSON alongside CSVs.

2) Frontend
- Add `SimulationContext`, `TopBarControls`, and `manifest` loader.
- Update `App.tsx` to include the provider and top bar; sync `?sim=`.
- Update `AnimationView.tsx` and `HeatmapView.tsx` to use `selectedSim` resources.

3) UI library
- Install Mantine (or use native inputs if you prefer zero deps initially). Mantine install example:
```bash
npm i @mantine/core @mantine/hooks @emotion/react
```

Testing checklist
- With multiple output runs copied, controls list the distinct `runners` values.
- Enter an `orders` value; Apply selects the closest available simulation; both views reload.
- URL `?sim=` loads the same selection on hard refresh and when navigating between views.
- If a sim lacks per-sim metrics or hole GeoJSON, panels and layers gracefully fall back.

Future enhancements
- Add a data table of simulations (sortable by orders, runners, scenario) using Material React Table or RDT.
- Add additional filters (scenario, golfers, carts) and pinned favorites.
- Support side-by-side compare (split view) of two simulations.



### How to generate and publish simulations for the controls

Use these commands to produce the exact coordinate CSVs, heatmaps, and metrics the app expects. After generating runs, publish them to `my-map-animation/public/coordinates` so the UI (and future TopBar controls) can discover them via `manifest.json`.

- Prereqs (one-time):
  - Python env activated; Node installed
  - In `my-map-animation/`: `npm install`

- Expected per-run outputs (created automatically by the runner):
  - `outputs/<timestamp>_delivery_runner_<N>_runners_<scenario>[_<groups>]/run_01/coordinates.csv`
  - `outputs/.../run_01/delivery_heatmap.png`
  - `outputs/.../run_01/simulation_metrics.json`
  - `outputs/.../run_01/results.json`

#### A) Single simulation with scripts/sim/run_new.py

- Example: 1 runner, typical weekday, ~87 orders, 1 run
```bash
python scripts/sim/run_new.py \
  --course-dir courses/pinetree_country_club \
  --tee-scenario typical_weekday \
  --num-runners 1 \
  --num-runs 1 \
  --delivery-total-orders 87 \
  --log-level INFO
```

- Variations you can control:
  - Runners: `--num-runners 1|2|3|...`
  - Orders: `--delivery-total-orders <int>`
  - Speed/Prep (optional): `--runner-speed <mps> --prep-time <min>`
  - Output folder (optional): `--output-dir outputs/<your_name>`
  - Per-run hole heatmap PNG and global `hole_delivery_times.geojson` are produced automatically when data is available.

#### B) Batch simulations via optimization scripts

These sweep runner counts and orders and write each combo into its own output directory (the app will discover all of them):

- Staffing grid across runners and orders
```bash
python scripts/optimization/run_staffing_experiments.py \
  --base-course-dir courses/pinetree_country_club \
  --tee-scenarios typical_weekday \
  --order-levels 20 28 36 44 \
  --runner-range 1-3 \
  --runs-per 3 \
  --runner-speed 6.0 \
  --prep-time 10 \
  --exp-name staffing_weekday
```

- Sensitivity sweep (fixed runners/orders, vary speed/prep)
```bash
python scripts/optimization/run_sensitivity_experiments.py \
  --base-course-dir courses/pinetree_country_club \
  --tee-scenario typical_weekday \
  --orders 28 \
  --num-runners 1 \
  --speeds 5.5 6.0 6.5 \
  --preps 8 12 15 \
  --runs-per 3 \
  --exp-name sens_weekday_28
```

Both scripts call `scripts/sim/run_new.py` under the hood, so each run writes `coordinates.csv`, `delivery_heatmap.png`, and `simulation_metrics.json` in its `run_XX/` folder.

#### C) Publish runs to the map app and build manifest

Run the publisher to scan `outputs/` (and nested experiments), copy files to the app, and create `public/coordinates/manifest.json`:
```bash
python my-map-animation/run_map_app.py
```

- Optional: set a default selection for the app’s first load
```bash
python my-map-animation/run_map_app.py --default-id <simId>
```

- Optional: point the scanner at a nonstandard outputs root
```bash
# PowerShell
$env:SIM_BASE_DIR = "$PWD\outputs"
python my-map-animation/run_map_app.py
```

What the publisher does today:
- Copies every discovered `coordinates.csv` to `my-map-animation/public/coordinates/<simId>.csv`
- Copies matching heatmaps as `<simId>_delivery_heatmap.png`
- Writes a flattened `manifest.json` with `id`, `name`, and `filename`
- Copies a global `simulation_metrics.json` if present (per-sim metrics enrichment is planned; fallback still works)

#### D) Start the app and view by runners/orders

```bash
cd my-map-animation
npm start
```

- The app loads `public/coordinates/manifest.json`. As you add runs that differ by `--num-runners` and `--delivery-total-orders`, they appear as separate entries. The TopBar controls (from this strategy) will map your selections to the closest available simulation by runners and orders and reload both the animation and heatmap views.

Troubleshooting (quick):
- If a run is missing in the UI, re-run the publisher and check `public/coordinates/manifest.json`.
- If the heatmap is missing, confirm `delivery_heatmap.png` exists next to the run’s `coordinates.csv`.
- If coordinates look wrong, verify clubhouse and hole coordinates are `(lon, lat)` tuples and that the cart graph loads (see simulation-debugging guide).
