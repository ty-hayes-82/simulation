## Purpose

Organize and copy simulation outputs from `output/` into `my-map-animation/public/coordinates/` so the app can:
- Select a course
- Select number of runners
- Select order counts
- Play the correct animation and show its metrics

This document defines the file selection, naming, destination layout, and the `manifest.json` format the app reads.

## What the app expects

- Data root: `public/coordinates/`
- Manifest: `public/coordinates/manifest.json`
- Per-simulation assets referenced by the manifest:
  - `filename` (CSV): tracker coordinates for the animation
  - `metricsFilename` (JSON): aggregate metrics for panels and matrices
  - `holeDeliveryGeojson` (GEOJSON, optional): per-hole delivery timing points

Minimal manifest entry (one per sim option shown in the UI):

```json
{
  "id": "pinetree_country_club__orders_30__runners_2__back",
  "name": "Pinetree CC — 30 orders — 2 runners — back",
  "filename": "pinetree_country_club__orders_30__runners_2__back.csv",
  "metricsFilename": "pinetree_country_club__orders_30__runners_2__back.metrics.json",
  "holeDeliveryGeojson": "pinetree_country_club__orders_30__runners_2__back.hole_delivery.geojson",
  "variantKey": "back",
  "meta": { "runners": 2, "orders": 30 },
  "courseId": "pinetree_country_club",
  "courseName": "Pinetree Country Club"
}
```

Top-level manifest shape:

```json
{
  "courses": [
    { "id": "pinetree_country_club", "name": "Pinetree Country Club" },
    { "id": "keswick_hall", "name": "Keswick Hall" }
  ],
  "simulations": [ /* entries like above */ ]
}
```

Allowed `variantKey` values (the UI uses these):
- `none`, `front`, `mid`, `back`, `front_mid`, `front_back`, `mid_back`, `front_mid_back`

## Source → Destination mapping

Source layout (example):

```
output/<course>/<TIMESTAMP>/second_pass/
  orders_030/
    runners_2/
      back/
        run_01/
          coordinates.csv
          simulation_metrics.json
          hole_delivery_times.geojson
```

Destination layout (public assets):

```
my-map-animation/public/coordinates/
  manifest.json
  pinetree_country_club__orders_30__runners_2__back.csv
  pinetree_country_club__orders_30__runners_2__back.metrics.json
  pinetree_country_club__orders_30__runners_2__back.hole_delivery.geojson
```

## Selection rules

1. For each course under `output/` (e.g., `pinetree_country_club`, `keswick_hall`):
   - Find all timestamp subfolders matching the simulation pattern, e.g., `20250828_082152_real_tee_sheet`.
   - Select the latest timestamp only (lexicographical max is sufficient for the current naming; otherwise use folder last-modified time).
   - Prefer `second_pass/` over `first_pass/` if both exist.

2. Within the selected pass folder:
   - Iterate `orders_XXX/` directories; parse `orders = int(XXX)`.
   - Inside each, iterate `runners_Y/`; parse `runners = int(Y)`.
   - Inside each `runners_Y`, iterate variant folders present (e.g., `none`, `front`, `mid`, `back`, `front_mid`, `front_back`, `mid_back`).
   - For each variant, choose a single `run_XX/` to represent that (orders, runners, variant) combo. Recommendation: pick `run_01/` for determinism. If you maintain a “best-of” policy, select the run identified by your `@aggregate.json` if such a field exists; otherwise fall back to `run_01/`.

3. Required files to copy from the chosen run:
   - `coordinates.csv` → animation path data (required)
   - `simulation_metrics.json` → metrics panels (required)
   - `hole_delivery_times.geojson` → used by the heatmap view (optional but recommended)

## Naming conventions (destination)

Build a base name per simulation combination:

```
<courseId>__orders_<orders>__runners_<runners>__<variantKey>
```

Then write files as:
- CSV: `<base>.csv`
- Metrics JSON: `<base>.metrics.json`
- Hole delivery GEOJSON: `<base>.hole_delivery.geojson`

Notes:
- `courseId` should match the folder name in `output/` and in any existing `public/<courseId>/` geometry (e.g., `pinetree_country_club`).
- `variantKey` should be exactly one of the allowed values listed above.

## Manifest authoring

1. Build `courses` by discovering course folders under `output/`. Use human-friendly names if you have them (otherwise title-case the id).
2. Add a `simulations` entry per (courseId, orders, runners, variantKey) you copied.
3. Each entry must include:
   - `id`: a unique string; recommend using the base name
   - `name`: a readable label (used in tooltips and internal logs)
   - `filename`: CSV filename placed under `/coordinates`
   - `metricsFilename`: JSON filename placed under `/coordinates`
   - `holeDeliveryGeojson`: GEOJSON filename placed under `/coordinates` (if copied)
   - `variantKey`, `meta.runners`, `meta.orders`, `courseId`, `courseName`

The UI will:
- Populate the course dropdown from `courses`
- Determine selectable runner and order counts from the distinct values in `simulations`
- Choose the best match for the current filters (course → variant → runners → nearest orders)

## Handling multiple timestamps

- Only include entries from the latest timestamp per course.
- If older assets already exist in `public/coordinates/`, you may delete them or regenerate `manifest.json` without entries pointing to them.

## Optional automation outline

You can script the above in Python or PowerShell. Pseudocode outline:

```python
from pathlib import Path
import json, re, shutil

OUTPUT = Path('output')
DEST = Path('my-map-animation/public/coordinates')

def latest_timestamp_dir(course_dir: Path) -> Path | None:
    candidates = [d for d in course_dir.iterdir() if d.is_dir()]
    return max(candidates) if candidates else None  # relies on sortable naming

def scan_course(course_id: str, course_name: str):
    course_dir = OUTPUT / course_id
    ts = latest_timestamp_dir(course_dir)
    if not ts: return []
    root = (ts / 'second_pass') if (ts / 'second_pass').exists() else (ts / 'first_pass')
    sims = []
    for orders_dir in sorted(root.glob('orders_*')):
        m = re.search(r'orders_(\d+)', orders_dir.name)
        if not m: continue
        orders = int(m.group(1))
        for runners_dir in sorted(orders_dir.glob('runners_*')):
            m2 = re.search(r'runners_(\d+)', runners_dir.name)
            if not m2: continue
            runners = int(m2.group(1))
            for variant_dir in sorted(runners_dir.iterdir()):
                if not variant_dir.is_dir(): continue
                variant = variant_dir.name
                run = (variant_dir / 'run_01')
                if not run.exists():
                    continue
                base = f"{course_id}__orders_{orders}__runners_{runners}__{variant}"
                csv_src = run / 'coordinates.csv'
                met_src = run / 'simulation_metrics.json'
                geo_src = run / 'hole_delivery_times.geojson'
                csv_dst = DEST / f"{base}.csv"
                met_dst = DEST / f"{base}.metrics.json"
                geo_dst = DEST / f"{base}.hole_delivery.geojson"
                if csv_src.exists(): shutil.copy2(csv_src, csv_dst)
                if met_src.exists(): shutil.copy2(met_src, met_dst)
                if geo_src.exists(): shutil.copy2(geo_src, geo_dst)
                sims.append({
                    'id': base,
                    'name': f"{course_name} — {orders} orders — {runners} runners — {variant}",
                    'filename': csv_dst.name,
                    'metricsFilename': met_dst.name,
                    'holeDeliveryGeojson': geo_dst.name if geo_src.exists() else None,
                    'variantKey': variant,
                    'meta': { 'runners': runners, 'orders': orders },
                    'courseId': course_id,
                    'courseName': course_name,
                })
    return sims

courses = [('pinetree_country_club','Pinetree Country Club'), ('keswick_hall','Keswick Hall')]
all_sims = []
for cid, cname in courses:
    all_sims += scan_course(cid, cname)

manifest = {
    'courses': [ { 'id': cid, 'name': cname } for cid, cname in courses ],
    'simulations': all_sims,
}
DEST.mkdir(parents=True, exist_ok=True)
with open(DEST / 'manifest.json', 'w', encoding='utf-8') as f:
    json.dump(manifest, f, indent=2)
```

## Verification checklist

- `public/coordinates/manifest.json` exists and lists the intended courses and sims
- CSV and JSON files referenced by the manifest are present under `public/coordinates/`
- Files are unique per (course, orders, runners, variant)
- App loads and the course dropdown, runner/order selectors show expected options
- Selecting different combos updates the animation and metrics without 404s


