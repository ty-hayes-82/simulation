## GM‑Friendly Simulation Reporting and Log Strategy

### Objective
Give a general manager a fast, intuitive way to see order flow and bottlenecks from each simulation run, while still enabling ops to drill into orders, runners, and queues.

### Deliverables (GM‑friendly first, ops drill‑down second)
- **Executive one‑pager per run (PDF/PNG)**: KPIs, bottlenecks, recommendations
- **Interactive run report (single self‑contained HTML)**: Overview, Orders, Queues, Runners, Map
- **Unified logs (CSV/Parquet)**: `orders_events`, `runner_states`, `queue_levels`
- **Scenario comparison index (HTML)**: Compare runs across orders‑levels and runner counts

### High‑level approach
- **Standardize logs** into three tidy time‑series: orders, runners, queues
- **Generate a one‑pager** “GM Summary” focused on KPIs and bottlenecks
- **Produce an interactive HTML report** with tabs (Overview, Queues, Orders, Runners, Map)
- **Add a scenario index page** to compare runs side‑by‑side (e.g., `orders_030` vs `orders_040`, `runners_2`)
- **Keep filenames and structure** consistent inside each run directory for quick retrieval and sharing

### Data sources to leverage (existing outputs)
- **`results.json`**: order‑ and runner‑level events and outcomes
- **`simulation_metrics.json`**: top‑level KPIs
- **`delivery_runner_metrics_run_01.json`**: runner utilization/performance
- **`coordinates.csv`**: runner trace for mapping/heatmaps
- **`@aggregate.json`**: scenario‑level summary (if present)

## Standardized log schema (export per run)

#### Orders log `orders_events.csv`
- **Columns**: `ts, order_id, event, queue, runner_id, hole, prep_sla_s, delivered_sla_s`
- **Events**: `created, queued, assigned, picked_up, delivered, cancelled`

```csv
ts,order_id,event,queue,runner_id,hole,prep_sla_s,delivered_sla_s
2025-08-31T08:30:12,ORD-001,created,front_9,,1,600,900
2025-08-31T08:31:03,ORD-001,queued,front_9,,1,600,900
2025-08-31T08:32:17,ORD-001,assigned,front_9,RUN-1,1,600,900
2025-08-31T08:33:05,ORD-001,picked_up,front_9,RUN-1,1,600,900
2025-08-31T08:39:44,ORD-001,delivered,front_9,RUN-1,5,600,900
```

#### Runner log `runner_states.csv`
- **Columns**: `ts, runner_id, state, hole, order_id, lat, lon, speed_mps`
- **States**: `idle, enroute_pickup, picking_up, enroute_delivery, delivering, break`

```csv
ts,runner_id,state,hole,order_id,lat,lon,speed_mps
2025-08-31T08:30:00,RUN-1,idle,pro_shop,,34.0241,-84.6093,
2025-08-31T08:32:17,RUN-1,enroute_pickup,1,ORD-001,34.0245,-84.6090,6.2
2025-08-31T08:33:05,RUN-1,picking_up,1,ORD-001,34.0246,-84.6089,
2025-08-31T08:33:40,RUN-1,enroute_delivery,5,ORD-001,34.0254,-84.6072,7.1
2025-08-31T08:39:44,RUN-1,delivering,5,ORD-001,34.0260,-84.6065,
```

#### Queue log `queue_levels.csv`
- **Columns**: `ts, queue, length, max_wait_s, arrivals, assignments, abandons`

```csv
ts,queue,length,max_wait_s,arrivals,assignments,abandons
2025-08-31T08:30:00,front_9,2,180,1,0,0
2025-08-31T08:35:00,front_9,7,540,6,1,0
2025-08-31T08:45:00,front_9,11,900,5,2,0
```

## GM Summary one‑pager (PDF/PNG)

#### Content
- **KPIs with traffic‑light colors**
  - Service level: % delivered within X minutes (e.g., 10/12/15)
  - Delivery times: median, p90, p95
  - Max queue length and sustained backlog windows
  - Runner utilization: average, p95, idle time
- **Bottleneck callouts**
  - When, where, how bad (e.g., “Back 9 queue > 8 for 42 min between 8:30–9:12”)
- **Recommendations**
  - Example: “+1 runner on Back 9 between 8:30–10:00 reduces p95 by ~5.2 min”
- **Small visuals**
  - Queue‑over‑time sparkline (front/back)
  - Runner utilization gauges
  - Delivery‑time distribution strip

#### Output
- `report/summary.pdf` and `report/summary.png`

## Interactive HTML report (single file, per run)

#### Tabs
- **Overview**: KPIs, bottleneck annotations, mini‑charts
- **Orders**: interactive timeline of order lifecycles (Gantt; color by queue), searchable table
- **Queues**: line charts of length and max wait over time, shaded “red zones”
- **Runners**: per‑runner timelines and utilization, idle vs active, handoffs
- **Map**: path heatmap from `coordinates.csv`, delivery hotspots by hole
- **Download**: links to exported CSVs and `kpis.json`

#### Tech
- Static Plotly/Altair embedded in a single HTML for zero‑dependency viewing

## Scenario comparison index (HTML)
- **Matrix cards** by `orders_level` × `runner_count`
- **Each card**: top KPIs + sparkline + “Open run report” link
- **Quick sort/filter** by Service level, p95 delivery, Max queue

## File structure (within each run folder)

```
.../run_01/
  report/
    summary.pdf
    report.html
    orders_events.csv
    runner_states.csv
    queue_levels.csv
    kpis.json
    bottlenecks.json
```

At scenario level:

```
.../first_pass/
  index.html  (scenario comparison across runs)
```

## Bottleneck detection rules (simple, explainable)
- **Queue‑based**: queue length > threshold (e.g., 6) sustained > N minutes (e.g., 10)
- **Service‑based**: p95 delivery > SLA target (e.g., 15 min) within any 30‑min window
- **Utilization‑based**: runner utilization > 85% for > 30 min with concurrent backlog
- **Output** intervals with start/end, severity score, and suggested remedy

## KPIs export example `kpis.json`

```json
{
  "course": "pinetree_country_club",
  "tee_scenario": "real_tee_sheet",
  "orders_level": 30,
  "runner_count": 2,
  "run_id": "run_01",
  "orders_total": 126,
  "pct_delivered_within_12_min": 82.4,
  "delivery_minutes_median": 9.3,
  "delivery_minutes_p95": 18.1,
  "max_queue_len_front": 11,
  "max_queue_len_back": 9,
  "runner_utilization_avg": 0.78,
  "runner_idle_minutes_per_hr": 13.2
}
```

## Workflow to generate

#### Option 1: Integrated (recommended) - Reports generated automatically

```bash
python scripts/optimization/optimize_staffing_policy_two_pass.py \
  --course-dir courses/pinetree_country_club \
  --tee-scenario real_tee_sheet \
  --orders-levels 30 40 \
  --runner-range 2 \
  --concurrency 10 \
  --auto-report
```

#### Option 2: Manual post-processing

```bash
# 1) Run simulation without auto-report
python scripts/optimization/optimize_staffing_policy_two_pass.py \
  --course-dir courses/pinetree_country_club \
  --tee-scenario real_tee_sheet \
  --orders-levels 30 40 \
  --runner-range 2 \
  --concurrency 10

# 2) Generate reports for all runs in scenario
python scripts/report/auto_report.py \
  --scenario-dir output/pinetree_country_club/<scenario>/...
```

#### Option 3: Single run reports

```bash
python scripts/report/build_report.py \
  --run-dir output/pinetree_country_club/<scenario>/.../run_01 \
  --emit-csv --html
```

## Implementation notes
- Minimal post‑processor reads existing outputs (`results.json`, `simulation_metrics.json`, `delivery_runner_metrics_run_01.json`, `coordinates.csv`)
- Writes standardized CSVs and `kpis.json`, then renders `summary.pdf` and `report.html`
- Prefer self‑contained HTML (bundled data) for easy sharing

## Why this works for a GM
- **One page** to grasp performance and bottlenecks (save/print/share)
- **Simple color cues** and plain‑English recommendations
- **Interactive deep dives** only when needed, without installing anything

---

### Appendix: Data source mapping
- `results.json` → `orders_events.csv` and `runner_states.csv`
- `simulation_metrics.json` → `kpis.json`
- `delivery_runner_metrics_run_01.json` → runner utilization in HTML/PDF
- `coordinates.csv` → map heatmap layer in HTML


