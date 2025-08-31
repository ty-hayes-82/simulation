# Golf Delivery Simulation Reporting

This directory contains scripts to generate GM-friendly reports and standardized logs from simulation runs.

## Quick Start

### Option 1: Integrated workflow (recommended)
```bash
# Reports generated automatically during simulation
python scripts/optimization/optimize_staffing_policy_two_pass.py \
  --course-dir courses/pinetree_country_club \
  --tee-scenario real_tee_sheet \
  --orders-levels 30 40 \
  --runner-range 2 \
  --concurrency 10 \
  --auto-report
```

### Option 2: Alternative integrated wrapper
```bash
python scripts/report/run_and_report.py \
  --course-dir courses/pinetree_country_club \
  --tee-scenario real_tee_sheet \
  --orders-levels 30 40 \
  --runner-range 2 \
  --concurrency 10
```

### Option 3: Generate reports for existing runs
```bash
# For all runs in a scenario
python scripts/report/auto_report.py --scenario-dir "output/pinetree_country_club/20250831_083006_real_tee_sheet/first_pass"

# For a single run
python scripts/report/build_report.py --run-dir "output/.../run_01" --emit-csv --html
```

## Generated Artifacts

### Per Run (`run_XX/report/`)
- **`report.html`** - Interactive tabbed report with KPIs, charts, and download links
- **`kpis.json`** - Standardized metrics for programmatic access
- **`orders_events.csv`** - Order lifecycle events (created → queued → assigned → delivered)
- **`runner_states.csv`** - Runner position and state over time with speed
- **`queue_levels.csv`** - Queue length and wait times over time

### Per Scenario
- **`index.html`** - Comparison matrix of all runs by orders level and runner count

## What the GM Sees

### Scenario Index
- Grid layout: orders_030/040 × runners_2 × variants (front, back, front_back, etc.)
- Each card shows: Total Orders, On-Time %, P95 Delivery, Utilization
- Color-coded by performance (green = good, yellow = fair, red = poor)
- Click "View Report" to drill into individual runs

### Individual Run Report (Tabbed)
- **Overview**: KPI cards + bar chart of key metrics
- **Orders**: Timeline of order processing (placeholder for future Gantt chart)
- **Queues**: Queue length over time (placeholder for actual data visualization)
- **Runners**: Runner utilization and activity (placeholder for swimlane chart)
- **Download**: Links to standardized CSV files

## File Structure

```
output/pinetree_country_club/20250831_083006_real_tee_sheet/first_pass/
├── index.html                    # Scenario comparison
├── orders_030/
│   └── runners_2/
│       ├── front_back/
│       │   ├── run_01/
│       │   │   ├── results.json           # Original simulation output
│       │   │   ├── simulation_metrics.json
│       │   │   ├── coordinates.csv
│       │   │   └── report/                # Generated reports
│       │   │       ├── report.html        # Interactive report
│       │   │       ├── kpis.json         # Standardized KPIs
│       │   │       ├── orders_events.csv # Order lifecycle
│       │   │       ├── runner_states.csv # Runner positions/states
│       │   │       └── queue_levels.csv  # Queue time series
│       │   ├── run_02/
│       │   └── ...
│       ├── front/
│       ├── back/
│       └── ...
└── orders_040/
    └── ...
```

## Scripts

- **`build_report.py`** - Core report generator for a single run
- **`build_index.py`** - Scenario comparison index generator  
- **`auto_report.py`** - Batch process all runs in a scenario
- **`run_and_report.py`** - Run simulation + auto-generate reports

## Data Schema

### orders_events.csv
```csv
ts,order_id,event,queue,runner_id,hole,prep_sla_s,delivered_sla_s
15101,001,created,front_9,,4,,,
15102,001,queued,front_9,,4,,,
15105,001,assigned,front_9,,4,,
15106,001,picked_up,front_9,,4,,
16190,001,delivered,front_9,,5,,,
```

### runner_states.csv  
```csv
ts,runner_id,state,hole,order_id,lat,lon,speed_mps
14400.0,runner_1,idle,clubhouse,,34.0379,-84.5928,
15705.0,runner_1,idle,5,,34.03796,-84.59271,0.008
15723.0,runner_1,moving,5,,34.03833,-84.59237,2.891
```

### queue_levels.csv
```csv
ts,queue,length,max_wait_s,arrivals,assignments,abandons
15060,front_9,1,60,1,,
15120,front_9,0,60,0,,
15540,front_9,1,60,1,,
```

### kpis.json
```json
{
  "totalOrders": 30,
  "successfulDeliveries": 30,
  "onTimePct": 90.0,
  "delivery_minutes_median": 18.25,
  "delivery_minutes_p95": 31.565,
  "runnerUtilizationPct": 19.28
}
```

## Future Enhancements

1. **Real chart data** - Load actual CSV data into Plotly charts instead of placeholders
2. **PDF export** - Add WeasyPrint or Chromium-based PDF generation for GM summaries
3. **Bottleneck detection** - Automated identification of queue buildups and utilization spikes
4. **Recommendations engine** - Suggest staffing changes based on detected patterns
5. **Real-time data** - Parse detailed event logs if available from simulation internals
