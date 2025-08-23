## Simulation Output Cross-Check Checklist

Use this checklist after each run to validate that generated data, derived metrics, and exported files are internally consistent and animation-ready.

### 1) Run metadata and structure
- **Output folders exist**: `outputs/<timestamp>_<mode>/run_01/`
- **Core files present**: `results.json`, `simulation_metrics.json`, `order_logs.csv`, `events.csv`, `runner_action_log.csv`, `coordinates.csv`
- **Optional visuals present**: `delivery_heatmap.png` (if enabled)
- **Public copies synced**: `my-map-animation/public/coordinates.csv`, `my-map-animation/public/simulation_metrics.json`, `my-map-animation/public/hole_delivery_times.geojson`

### 2) Order volume integrity
- **Requested vs generated**: `simulation_metrics.json.deliveryMetrics.totalOrders` equals requested `--delivery-total-orders` (or config `delivery_total_orders`).
- **orders vs orders_all**: In `results.json`, `len(orders)` equals requested total and matches `simulation_metrics.json.deliveryMetrics.totalOrders`.
- **Failed orders count**: `simulation_metrics.json.deliveryMetrics.failedDeliveries` equals `len(results.json.failed_orders)`.

### 3) Service hours conformance
- **Orders within hours**: All `results.json.orders[*].order_time_s` fall within service window: `[service_open_s, service_close_s]`.
- **Events within hours**: In `events.csv`, `timestamp_s` for `order_placed`, `delivery_start`, `order_delivered` occur within service hours (or are explicitly post-processed after close if expected).

### 4) Golfer tracks consistency
- **Monotonic timestamps**: For each `golfer_group_*` in `coordinates.csv`, timestamps ascend per group.
- **Hole progression**: `hole` increases 1→18 across the round; no reversion except course-specific transitions.
- **Temporal alignment**: First golfer point timestamp aligns with group `tee_time_s` in `results.json.metadata`/scenario.

### 5) Runner coordinates integrity
- **Presence**: `coordinates.csv` contains `runner_*` rows when there are orders.
- **Cadence**: Runner timestamps advance in 60s steps; avoid duplicate timestamps for the same `id`.
- **Trips alignment**: For each delivered order, runner points exist covering `delivery_start`→`order_delivered`→`returned` windows (`runner_action_log.csv`).

### 6) Events ↔ Orders ↔ Coordinates linkage
- **Orders to events**: Every `results.json.orders[*].order_id` appears in `events.csv` as `order_placed` and corresponding lifecycle events.
- **Events to runner segments**: `runner_action_log.csv` contains contiguous segments partitioning service window; delivery and return segments align with events timing.
- **Runner to golfer proximity**: At `order_delivered` time, nearest golfer point timestamp is within ≤60s and is spatially close (sanity spot-check N=3).

### 7) Metrics sanity
- **Average order time**: `simulation_metrics.json.deliveryMetrics.avgOrderTime` equals mean of `delivery_stats.total_completion_time_s/60` from `results.json`.
- **On-time percentage**: Matches SLA rule applied to the same set as above.
- **Counts match**: `successfulDeliveries` equals `len(results.json.delivery_stats)`.

### 8) Heatmap and GeoJSON validity
- **GeoJSON export**: `my-map-animation/public/hole_delivery_times.geojson` exists and parses (valid JSON).
- **Heatmap present**: `delivery_heatmap.png` exists when `no_heatmap` is false; visually shows activity in expected holes.

### 9) Animation readiness (React)
- **Public files updated**: `public/coordinates.csv` and `public/simulation_metrics.json` are recent (mtime ≥ run completion time).
- **Schema compliance**: `coordinates.csv` columns: `id,latitude,longitude,timestamp,type,hole,visibility_status,time_since_last_sighting_min,pulsing,total_orders,total_revenue,avg_per_order,revenue_per_hour,avg_order_time_min`.
- **Entity IDs**: Stable IDs (`runner_1`, `golfer_group_1`, etc.); types are `runner` or `golfer`.
- **Timeline anchor**: Presence of `timeline` row extending end of animation window.

### 10) Quick automated checks (suggested)
```bash
# 1) Count orders
jq '.deliveryMetrics.totalOrders' outputs/*/run_*/simulation_metrics.json

# 2) Ensure orders are within service hours
python - << 'PY'
import json, glob
for p in glob.glob('outputs/*/run_*/results.json'):
    r=json.load(open(p))
    srv_open=r.get('metadata',{}).get('service_open_s',None)
    srv_close=r.get('metadata',{}).get('service_close_s',None)
    if srv_open is None or srv_close is None:
        continue
    bad=[o for o in r.get('orders',[]) if not (srv_open <= int(o.get('order_time_s',0)) <= srv_close)]
    print(p, 'OK' if not bad else f'BAD:{len(bad)}')
PY

# 3) Validate coordinates schema (header)
head -1 outputs/*/run_*/coordinates.csv | rg 'id,latitude,longitude,timestamp,type,hole'

# 4) Check monotonicity per entity (sample)
python - << 'PY'
import csv, glob
for p in glob.glob('outputs/*/run_*/coordinates.csv'):
    by={}
    with open(p,newline='') as f:
        for row in csv.DictReader(f):
            by.setdefault(row['id'],[]).append(int(row['timestamp']))
    issues=[eid for eid,ts in by.items() if ts!=sorted(ts)]
    print(p,'OK' if not issues else f'Non-monotonic:{issues[:3]}')
PY
```

### 11) Common issues and fixes
- **Zero orders generated**: Ensure `--groups-count > 0` or scenario produces groups; verify `--delivery-total-orders` is set.
- **Orders outside service hours**: Confirm hourly distribution generation uses service window and that overrides are respected.
- **Static animation**: Check golfer `hole` progression in `coordinates.csv`; ensure runner has non-duplicate, 60s cadence timestamps.
- **Missing public files**: Confirm `sync_run_outputs_to_public()` ran; check `my-map-animation/public/` for updated files.


