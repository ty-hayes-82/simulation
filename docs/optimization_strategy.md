## GM‑Oriented Optimization Strategy (No Code Changes)

This strategy outlines how to use existing configuration and CLI flags to optimize delivery runner operations without modifying source code. It focuses on staffing, reliability, and guest experience, using outputs already produced by the system.

### Objectives
- **Service reliability**: On‑time rate vs SLA, failed rate, p90 cycle time.
- **Labor efficiency**: Orders per runner‑hour; utilization balance (driving vs idle).
- **Revenue protection**: Revenue per ordering group; total revenue vs staffing cost.
- **Guest experience by zone**: Per‑hole service time outliers; avoid chronically slow zones when understaffed.
- **Operational stability**: Queue waits; peak window load; sensitivity to prep time and speed.

### Key questions to answer
- **Staffing curve**: For each demand level (total orders), what is the minimal number of runners meeting SLA and failed‑rate targets?
- **Break‑even**: At what order volume does the 2nd runner pay for itself?
- **Peak windows**: During which 60–90 minute windows do SLA breaches cluster? Do short, temporary adds (floater shifts) help?
- **Hole restrictions**:
  - If running with 1 runner (slow day), which holes produce the most SLA breaches or p90 times? Should we disable them or time‑gate them?
  - For busy days, which additional holes (if any) should be restricted or allowed only outside peak?
- **Prep and speed sensitivity**: How do +5 min prep or −1 m/s speed shifts change staffing requirements?
- **Open/close ramp**: Does a startup ramp reduce early SLA misses when the queue spikes at open?

### KPIs and targets (recommended)
- **On‑time rate**: ≥ 95% within SLA.
- **Failed rate**: ≤ 5%.
- **Delivery cycle time (p90)**: ≤ 40 min (align with your SLA).
- **Orders per runner‑hour**: maximize subject to above; use as tiebreaker across equal SLA solutions.
- **Queue wait avg**: ≤ 10–15 min during peaks.
- **Utilization**: Driving 35–60% for solo runner; idle not persistently > 60%.

### Inputs you can vary today (no code changes)
- **`--num-runners`**: staffing level.
- **`delivery_total_orders`** in `courses/<course>/config/simulation_config.json`: demand level.
- **`--tee-scenario`**: e.g., `typical_weekday`, `busy_weekend`, `quiet_day`.
- **`--runner-speed`** (m/s): sensitivity.
- **`--prep-time`** (minutes): kitchen sensitivity.
- **`--num-runs`**: repetitions per scenario.
- Optional JSON: **`delivery_opening_ramp_minutes`**, **`sla_minutes`**, **`service_hours_duration`**, **`random_seed`**.

### What each run produces
- `outputs/.../run_*/delivery_runner_metrics_run_*.json|.md`: GM‑ready metrics (orders per runner‑hour, on‑time rate, p90, failed rate, queue wait, utilization, distance per delivery, zone service times).
- `outputs/.../run_*/simulation_metrics.json`: broader summary.
- `my-map-animation/public/hole_delivery_times.geojson` (via `scripts/sim/run_new.py` with `--export-geojson`): per‑hole service times for mapping.
- `coordinates.csv` and heatmaps for spatial context.

### Experiment design
- **Scenarios (demand × schedule)**:
  - Slow day: `--tee-scenario quiet_day` or `typical_weekday`; vary `delivery_total_orders` (e.g., 6/10/14/18).
  - Busy day: `--tee-scenario busy_weekend`; vary `delivery_total_orders` (e.g., 20/28/36/44/52).
- **Staffing sweep**: For each demand level, test `--num-runners` from 1 up to the smallest value meeting targets (typically 1–4).
- **Sensitivity sweeps (optional)**: `--prep-time` {8, 12, 15}, `--runner-speed` {5.0, 6.0, 7.0} m/s.
- **Repetition**: `--num-runs 5` with fixed `random_seed` to reduce variance.

### PowerShell command templates

Set `delivery_total_orders` in `courses/pinetree_country_club/config/simulation_config.json` and run sweeps.

Slow day sweep:

```powershell
$orders = @(6,10,14,18)
$runners = 1..3
foreach ($o in $orders) {
  (Get-Content courses/pinetree_country_club/config/simulation_config.json -Raw) `
    | ConvertFrom-Json | ForEach-Object { $_.delivery_total_orders = $o; $_ } `
    | ConvertTo-Json -Depth 6 | Set-Content courses/pinetree_country_club/config/simulation_config.json
  foreach ($r in $runners) {
    python scripts/sim/run_new.py --course-dir courses/pinetree_country_club --tee-scenario typical_weekday --num-runners $r --num-runs 5 --runner-speed 6.0 --prep-time 10 --log-level INFO
  }
}
```

Busy day sweep:

```powershell
$orders = @(20,28,36,44,52)
$runners = 1..4
foreach ($o in $orders) {
  (Get-Content courses/pinetree_country_club/config/simulation_config.json -Raw) `
    | ConvertFrom-Json | ForEach-Object { $_.delivery_total_orders = $o; $_ } `
    | ConvertTo-Json -Depth 6 | Set-Content courses/pinetree_country_club/config/simulation_config.json
  foreach ($r in $runners) {
    python scripts/sim/run_new.py --course-dir courses/pinetree_country_club --tee-scenario busy_weekend --num-runners $r --num-runs 5 --runner-speed 6.0 --prep-time 10 --log-level INFO
  }
}
```

Speed/prep sensitivity (example at 28 orders):

```powershell
$prep = @(8,12,15); $speed = @(5.0,6.0,7.0)
# set orders once
(Get-Content courses/pinetree_country_club/config/simulation_config.json -Raw) `
 | ConvertFrom-Json | % { $_.delivery_total_orders = 28; $_ } `
 | ConvertTo-Json -Depth 6 | Set-Content courses/pinetree_country_club/config/simulation_config.json
foreach ($p in $prep) { foreach ($s in $speed) {
  python scripts/sim/run_new.py --course-dir courses/pinetree_country_club --tee-scenario typical_weekday --num-runners 1 --num-runs 5 --runner-speed $s --prep-time $p --log-level INFO
}}
```

### Determining required runners at each threshold
For each `delivery_total_orders`:
- Pick the smallest `--num-runners` such that across runs:
  - **on_time_rate ≥ 0.95**
  - **failed_rate ≤ 0.05**
  - **delivery_cycle_time_p90 ≤ 40 min** (or your SLA)
- If two staffing levels meet targets, prefer the one with higher orders per runner‑hour and acceptable utilization (not chronically > 60% idle).
- Cross‑check using the built‑in break‑even field `second_runner_break_even_orders`. If observed orders ≥ this value, the 2nd runner likely pays off.

### Hole restriction policy (1 runner)
- Use `zone_service_times` from `delivery_runner_metrics_run_*.json` and the `hole_delivery_times.geojson` to identify outlier holes (high average service time and/or few but very slow deliveries).
- Policy recommendations (operational, no code changes):
  - **Slow day (1 runner)**: Restrict the top 2–4 outlier holes all day, or allow them only outside peak windows (e.g., first/last 90 minutes). Consider `delivery_opening_ramp_minutes` to smooth opening spikes.
  - **Busy day (1 runner)**: Add 1–2 more holes to the restrict list, or move to 2 runners during peak windows.
- Validate by re‑running the same demand with 1 runner and confirming SLA metrics improve when these holes are operationally rejected/time‑gated.

### Peak window management
- Identify 60–90 minute windows with most SLA misses (use `order_timing_logs.csv` and `events.csv`).
- Options (no code changes):
  - Temporarily switch to 2 runners only during that window (staggered coverage).
  - Time‑gate slow holes to off‑peak windows.
  - Increase prep capacity during peaks if queue wait avg > 15 min.

### Dashboard items to compile (manual or spreadsheet)
- **Staffing curve**: Minimal runners vs `delivery_total_orders` for each tee scenario.
- **Break‑even overlay**: Observed orders vs `second_runner_break_even_orders`.
- **SLA/quality**: On‑time rate and p90 per threshold/staffing.
- **Efficiency**: Orders per runner‑hour, utilization mix.
- **Queue**: Avg queue wait during peak windows.
- **Hole policy**: Ranked slow holes and proposed restrictions by day type.

### Practical guardrails
- Keep `random_seed` stable when comparing staffing levels.
- If you change `--runner-speed`, prefer entrypoints that recompute routing as needed; otherwise consider running with travel‑time regeneration modes where applicable.
- If runner coordinates are missing, verify course `pkl` graphs and coordinate formats (see repo debugging notes).

### Example decision rules (operational)
- Add 2nd runner when either:
  - 3 of last 4 runs < 95% on‑time, or
  - p90 > 40 min for two consecutive days, or
  - Orders ≥ model’s break‑even threshold for 3 consecutive weeks.
- Restrict top 3 slowest holes on any day with only 1 runner and expected orders ≥ X (based on your staffing curve).
- Enable restricted holes only during low‑load windows and when queue wait avg < 10 min.

### Repo artifacts to review for each analysis
- Metrics JSON/MD: `outputs/.../run_*/delivery_runner_metrics_run_*.json|.md`
- GeoJSON by hole: `my-map-animation/public/hole_delivery_times.geojson`
- Order timing logs: `outputs/.../run_*/order_timing_logs.csv`
- Viewer: `my-map-animation/run_map_app.bat` or `my-map-animation/run_map_app.py`


