## Optimization Reference Guide

This guide summarizes what you can optimize in the golf delivery simulation, typical constraints to enforce, and example commands for running optimizations in a Windows PowerShell friendly way.

### High-priority levers and sequence

- **Focus first** (largest impact on SLA, lowest risk):
  - Reduce `--prep-time` (kitchen latency drives queueing)
  - Increase `--runner-speed` (m/s) (direct travel-time reduction)
  - Adjust `--num-runners` (stepwise capacity)
  - Improve staging/location (e.g., on-course hub) to cut travel
  - Use SLA-priority queueing over FIFO

- **Next tier** (after SLA is stable):
  - Demand shaping (prevent early holes 1–3/1–6, smooth peaks)
  - Align service window and shift staggering to demand
  - Enhanced routing/network refinements

- **Business levers** (after operational stability):
  - Pricing/promotions (avg order value vs demand vs SLA)
  - Profit optimization (runners, demand, price) under SLA and labor cost

### Core invariants

- Orders must be placed within the delivery service window (default 11:00–18:00). Delivered + failed should equal orders placed.
- SLA compliance is measured by on-time rate: share of deliveries with total_completion_time ≤ SLA minutes.

### Levers to tune

- **Demand levers**
  - `order_prob_9` (overall demand per group per nine)
  - Time-of-day shaping; front/back-nine split
  - Prevent early holes (e.g., prevent_front_upto_hole = 1–3, 1–6)
  - Group size distribution; tee-time density (scenario choice)
- **Supply levers**
  - `num_runners`, `runner_speed_mps`, `prep_time_min`
  - Service window start/end; shift staggering / breaks
  - Staging location (clubhouse vs on-course hub); routing mode (enhanced/simple)
- **Dispatch/policy levers**
  - Queue policy (FIFO, SLA-priority, shortest-travel-time-first)
  - Batching (multiple orders per trip), cancellation cutoff, `sla_minutes`
  - Assignment strategy (nearest-runner vs round-robin), zone restrictions
- **Pricing/revenue levers**
  - `revenue_per_order` (avg order value), dynamic pricing by hour/zone
  - Promotions/discounts, delivery fee, minimum order value
- **Operational levers**
  - Kitchen staffing (prep time distribution), terrain/weather speed scaling
  - Deadhead minimization rules, clubhouse-to-hole distance model

### Objectives (optimize one or combine with constraints)

- **Minimize runners**: smallest `num_runners` s.t. on_time_rate ≥ target
- **Maximize capacity**: largest `order_prob_9` s.t. on_time_rate ≥ target with fixed `num_runners`
- **Maximize total revenue**: maximize `successful_orders × revenue_per_order` under SLA constraints
- **Maximize profit**: maximize `total_revenue − (runner_wage_per_hour × num_runners × service_hours) − (variable_cost_per_order × successful_orders)` under SLA constraints
- **Minimize delivery times**: minimize p50/p90 cycle time (and/or dispatch delay, travel time)
- **Minimize failed rate**; **maximize orders per runner-hour**; **minimize distance per delivery**

### Common constraints

- **Service quality**: on_time_rate ≥ 0.90/0.95/0.99, failed_rate ≤ 5%
- **Budget**: num_runners ≤ limit; total labor cost ≤ budget
- **Operational**: service window fixed; zone/hole specific SLAs

### Generic optimization mode (suggested CLI shape)

Add a generic optimizer mode to `scripts/sim/run_unified_simulation.py` that accepts levers, constraints, and a chosen objective.

- **Flags**
  - `--mode optimize-generic`
  - `--objective {runners_min,capacity,revenue,profit,p90_time,failed_rate}`
  - `--constraint 'on_time_rate>=0.95'` (repeatable)
  - `--lever 'order_prob_9=0.05:0.70:0.05'` (repeatable)
  - `--lever 'num_runners=1:10:1'`
  - `--fixed 'prep_time=8'` `--fixed 'runner_speed=2.9'` (repeatable)
  - `--search {grid,random,binary}` `--random-samples 200`
  - `--runner-wage 25` `--variable-cost 5` (for profit objective)
- **Evaluation**
  - For each candidate configuration, run N replicates, aggregate metrics, verify constraints, score objective.
- **Outputs**
  - `best.json` with best config + metrics
  - `frontier.csv` for Pareto sets (when applicable)
  - `summary.md` human-readable report

### Example commands (PowerShell, one per line)

- **Capacity with 1 runner (max demand within SLA)**

```
& C:\Main\GIT\simulation\.venv\Scripts\python.exe C:\Main\GIT\simulation\scripts\sim\run_unified_simulation.py --mode optimize-generic --course-dir courses\pinetree_country_club --tee-scenario typical_weekday --objective capacity --constraint on_time_rate>=0.90 --lever order_prob_9=0.05:0.80:0.05 --fixed num_runners=1 --num-runs 8 --search binary
```

- **Revenue at fixed SLA (choose promos and staffing)**

```
& C:\Main\GIT\simulation\.venv\Scripts\python.exe C:\Main\GIT\simulation\scripts\sim\run_unified_simulation.py --mode optimize-generic --course-dir courses\pinetree_country_club --tee-scenario busy_weekday --objective revenue --constraint on_time_rate>=0.95 --lever order_prob_9=0.10:0.70:0.05 --lever num_runners=1:8:1 --fixed prep_time=8 --fixed runner_speed=2.9 --num-runs 6 --search grid
```

- **Profit with wages and variable costs (SLA enforced)**

```
& C:\Main\GIT\simulation\.venv\Scripts\python.exe C:\Main\GIT\simulation\scripts\sim\run_unified_simulation.py --mode optimize-generic --course-dir courses\pinetree_country_club --tee-scenario busy_weekend --objective profit --constraint on_time_rate>=0.90 --lever order_prob_9=0.10:0.70:0.05 --lever num_runners=1:10:1 --fixed avg_order_usd=25 --runner-wage 25 --variable-cost 5 --num-runs 6 --search random --random-samples 150
```

### Tips

- Use binary search for 1D monotonic levers (capacity via `order_prob_9`).
- For 2–3 levers, grid or random search are fine; keep `--num-runs` to 6–10 replicates for stability.
- Always enforce the service window rule so placed = delivered + failed.
- Inspect `optimization_summary.json`, `summary.md`, and per-run `results.json` for deeper diagnostics.


