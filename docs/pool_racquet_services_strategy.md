## Pool & Racquet Services — Simulation Strategy

### Goals
- Add Pool and Racquet (tennis/pickle) amenities as first-class order sources in simulations.
- Allow optimizing runner staffing when delivery, pool, and racquet orders occur individually or together.
- Keep backward compatibility with existing delivery-only simulations and tooling.

---

## 1) Data requirements

### 1.1 Geofences (polygons)
- **Where**: `courses/<course>/geojson/generated/holes_geofenced_updated.geojson`
- **Required features**:
  - Pool polygon with `"hole": "members_pool"` (or `"pool"` if you prefer a shorter id; keep consistent).
  - Court polygons with `"hole": "court_1"`, `"court_2"`, `"court_3"` (extendable list).
- **CRS**: EPSG:4326 (lon, lat).
- **Validation**:
  - Polygons must be valid (no self-intersections) and non-empty.
  - Names must be unique per course and stable across runs.

### 1.2 Routing connectivity
- **Where**: `courses/<course>/geojson/generated/holes_connected*.geojson`
- Add amenity-adjacent routing nodes and connections so runners can reach the amenities:
  - Provide an access path node (e.g., `"node_id": "alt_access"`) connected to the main cart path nearest the Pool/Courts.
  - Optional named points (e.g., `"node_id": "court_1"`) if you want exact drop-off anchors.
- **Fallback**: If a named amenity node is missing, find the nearest existing graph node to the amenity polygon centroid.
- **Validation**: Ensure NetworkX shortest path exists between clubhouse and each amenity polygon/anchor.

### 1.3 Amenity identifiers
- Use string ids for amenities to avoid colliding with numeric hole ids:
  - Pool: `members_pool`
  - Courts: `court_1`, `court_2`, `court_3`
- Keep these ids consistent across GeoJSON, config, and code.

---

## 2) Simulation config schema additions

### 2.1 High-level approach
Introduce a `services` object that holds configuration for each service stream. Preserve existing top-level delivery fields for backward compatibility; map or default them into `services.delivery`.

### 2.2 Proposed schema (backward compatible)
```json
{
  "course_name": "Keswick Hall",
  "clubhouse": { "latitude": 38.017149, "longitude": -78.365977 },

  // Existing delivery fields remain supported (legacy)
  "delivery_total_orders": 30,
  "delivery_hourly_distribution": { "11:00": 0.14, "12:00": 0.24 },
  "delivery_service_hours": { "open_time": "11:00", "close_time": "18:00" },
  "delivery_avg_order_usd": 30.0,

  // New multi-service block
  "services": {
    "delivery": {
      "enabled": true,
      "total_orders": 30,
      "avg_order_usd": 30.0,
      "service_hours": { "open_time": "11:00", "close_time": "18:00" },
      "hourly_distribution": { "11:00": 0.14, "12:00": 0.24, "13:00": 0.19, "14:00": 0.10, "15:00": 0.12, "16:00": 0.13, "17:00": 0.08 },
      "failure_minutes": 60,
      "queue_policy": "fifo"
    },
    "pool": {
      "enabled": false,
      "total_orders": 20,
      "avg_order_usd": 22.0,
      "service_hours": { "open_time": "11:00", "close_time": "19:00" },
      "hourly_distribution": { "11:00": 0.10, "12:00": 0.20, "13:00": 0.20, "14:00": 0.15, "15:00": 0.15, "16:00": 0.12, "17:00": 0.08 },
      "failure_minutes": 45,
      "queue_policy": "fifo",
      "amenity_targets": ["members_pool"],
      "start_anchor": { "type": "node_id", "value": "alt_access" }
    },
    "racquet": {
      "enabled": false,
      "total_orders": 15,
      "avg_order_usd": 18.0,
      "service_hours": { "open_time": "10:00", "close_time": "20:00" },
      "hourly_distribution": { "10:00": 0.10, "11:00": 0.15, "12:00": 0.15, "13:00": 0.15, "14:00": 0.10, "15:00": 0.10, "16:00": 0.10, "17:00": 0.10, "18:00": 0.05 },
      "failure_minutes": 45,
      "queue_policy": "fifo",
      "amenity_targets": ["court_1", "court_2", "court_3"],
      "start_anchor": { "type": "node_id", "value": "alt_access" }
    }
  }
}
```

Notes:
- `enabled`: Toggle service stream on/off per simulation.
- `total_orders`: Total for the simulation window (distributed by `hourly_distribution`).
- `service_hours`: Use existing parsing helpers (seconds since 7am) per configuration-management rules.
- `hourly_distribution`: Fractions within service_hours; normalize if not summing exactly to 1.0.
- `amenity_targets`: List of amenity ids to route to (randomly assigned per order unless a policy dictates otherwise).
- `start_anchor`:
  - `{ "type": "node_id", "value": "alt_access" }` or `{ "type": "lonlat", "value": [-78.3659, 38.0171] }`.
  - If omitted, default to clubhouse.
- `queue_policy`: initial value `fifo`. Future: `priority` (e.g., preference by service, revenue, SLA).

### 2.3 Backward compatibility
- If `services` is missing, build `services.delivery` from legacy top-level fields:
  - `delivery_total_orders` → `services.delivery.total_orders`
  - `delivery_hourly_distribution` → `services.delivery.hourly_distribution`
  - `delivery_service_hours` → `services.delivery.service_hours`
  - `delivery_avg_order_usd` → `services.delivery.avg_order_usd`
- Default `pool` and `racquet` to `enabled=false`.

---

## 3) Orchestration & order generation

### 3.1 Multi-service order synthesis
- For each `services.<name>` with `enabled=true`:
  1) Validate service hours; clamp hourly distribution to within hours; renormalize if needed.
  2) Compute orders per hour slice: `orders = round(total_orders * share_by_hour)`.
  3) For each order, pick a target amenity:
     - If `amenity_targets` contains multiple items (e.g., courts), pick uniformly or by simple round-robin.
     - Destination coordinate: centroid of the polygon, or a random point inside the polygon for variation.
  4) Map start/end to nodes:
     - Start: `start_anchor` node_id if provided; else nearest node to clubhouse.
     - End: nearest node to destination coordinate (or to named amenity node if present).
  5) Generate route (out-and-back) and timings the same way as delivery.

### 3.2 SLA / failure
- Use per-service `failure_minutes` to mark orders failed if not completed within the window.
- Queueing is shared across services by default (FIFO). Later we can allow service priority.

### 3.3 Metrics tagging
- Tag each order with `service: "delivery" | "pool" | "racquet"` and `amenity_id` when applicable.
- Persist into `results.json` delivery_stats, ensuring downstream aggregators can filter/summarize by service.

---

## 4) Optimizer: alternate script for multi-service

### 4.1 New script
- File: `scripts/optimization/optimize_staffing_policy_multi_service.py` (alternate to `optimize_staffing_policy_two_pass.py`).
- Purpose: Support delivery-only, pool-only, racquet-only, or any combination simultaneously.

### 4.2 CLI (proposed)
- `--services`: one or more of `delivery`, `pool`, `racquet` (default: `delivery`).
- `--service-total-orders` (repeatable): `service=NUM` to override config (e.g., `--service-total-orders pool=40`).
- `--service-hours` (repeatable override): `service=OPEN-CLOSE` (e.g., `--service-hours racquet=10:00-20:00`).
- `--service-hourly-dist` (optional override): `service=JSON` where JSON is a compact `{"11:00":0.2,...}`.
- All existing flags from the original optimizer remain (variants, runner-range, orders-levels, etc.).

Notes:
- `--orders-levels` continues to refer to the overall total order volume for the scenario. Two options:
  1) Treat `--orders-levels` as applying only to `services.delivery` unless overridden per service; OR
  2) If any `--service-total-orders` is passed, use those explicitly and ignore `--orders-levels` for that service.
- Start with (1) for simplicity; (2) as an incremental enhancement.

### 4.3 Execution model
- For each candidate (variant × runners × orders-level), run N simulations where all enabled services contribute orders per their configs/overrides.
- Runners are shared across services. The shared FIFO queue means the optimizer will capture contention effects.

### 4.4 Aggregation & reporting
- Extend aggregate to produce both combined and per-service metrics:
  - Combined (existing): on_time_rate, failed_rate, p90, avg, orders_per_runner_hour, etc.
  - Per-service: counts, success/failure, avg cycle time, revenue.
- Update `utility_score` (optional) to consider revenue or per-service penalties if desired later. Default behavior can remain unchanged to avoid bias.
- CSV: add columns `services` (comma-separated), and a JSON column `per_service_metrics` containing a compact summary.
- `hole_delivery_times.geojson`: unchanged; still maps to course holes. Consider an amenity_delivery_times.geojson later.

### 4.5 Backward compatibility
- If `--services` is omitted, behavior matches the original optimizer (delivery only).
- If `services.pool.enabled=false` and `services.racquet.enabled=false`, results are identical to delivery-only.

---

## 5) Implementation plan (incremental)

1) Config & loaders
   - Update simulation config models to accept the `services` block.
   - Backfill `services.delivery` from legacy fields if missing.
   - Add validators for `service_hours`, `hourly_distribution`, and `amenity_targets` existence in geofences.

2) Amenity polygon loader
   - Add `load_amenity_polygons(course_dir) -> Dict[str, shapely.geometry.Polygon]` that reads amenity ids from geofence GeoJSON where `hole` is non-numeric.
   - Keep existing hole loader unchanged.

3) Order generation
   - In the chosen runner service, add multi-service order creation with tagging and routing to amenity targets.

4) New optimizer script
   - Copy `optimize_staffing_policy_two_pass.py` → `optimize_staffing_policy_multi_service.py` and add the new flags and service enablement logic.
   - Pass-through overrides to the sim runner; ensure results include `service` tags.

5) Aggregation updates
   - Extend `aggregate_runs()` to compute per-service stats by filtering delivery_stats on `service`.
   - Serialize a compact `per_service_metrics` section for CSV and saved aggregates.

6) Testing
   - Unit: config parsing, service validation, amenity polygon loader.
   - Integration: small runs with pool-only, racquet-only, and combined; confirm metrics sanity.
   - Routing smoke tests: clubhouse ↔ amenity nodes reachable.

7) Docs & examples
   - Add example `simulation_config.json` snippet (above).
   - Add CLI examples (below).

---

## 6) CLI examples

### 6.1 Delivery + Pool together (use config volumes)
```bash
python scripts/optimization/optimize_staffing_policy_multi_service.py \
  --course-dir courses/keswick_hall \
  --tee-scenario real_tee_sheet \
  --orders-levels 30 40 \
  --services delivery pool \
  --runner-range 1-3
```

### 6.2 Pool-only with override volumes/hours
```bash
python scripts/optimization/optimize_staffing_policy_multi_service.py \
  --course-dir courses/keswick_hall \
  --tee-scenario real_tee_sheet \
  --services pool \
  --service-total-orders pool=50 \
  --service-hours pool=11:00-19:00
```

### 6.3 Delivery + Racquet + Pool (explicit totals)
```bash
python scripts/optimization/optimize_staffing_policy_multi_service.py \
  --course-dir courses/keswick_hall \
  --tee-scenario real_tee_sheet \
  --services delivery racquet pool \
  --service-total-orders delivery=30 \
  --service-total-orders racquet=20 \
  --service-total-orders pool=25 \
  --runner-range 1-4
```

---

## 7) Validation & guardrails
- Coordinate validation per configuration-management rules (clubhouse tuples, lon/lat ranges).
- Service hours must be within 07:00–24:00 and `open < close`.
- Hourly distributions must be defined only within service hours; normalize to 1.0.
- Every `amenity_targets` id must exist as a polygon in geofences.
- Ensure graph reachability from start anchor to each amenity.

---

## 8) Backward-compatibility & rollout
- Phase 1: Implement config parsing + multi-service in runner; keep original optimizer.
- Phase 2: Land the new optimizer script; keep the original intact.
- Phase 3: Migrate dashboards to optionally read per-service metrics.
- No changes required for courses that do not enable pool/racquet.

---

## 9) Open questions (future enhancements)
- Priority queues by service or SLA (e.g., hot food at pool > racquet snacks).
- Amenity-specific prep time overrides.
- Separate runner pools for amenities vs course (toggle).
- Amenity-specific map overlays (amenity_delivery_times.geojson).


