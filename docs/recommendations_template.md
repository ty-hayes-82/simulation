## GM Recommendations — <Course> — <Date>

### Executive Summary
- Staffing recommendations by demand level and scenario.
- Hole restriction policy for 1-runner days.
- Peak window plan and sensitivity highlights.

### Staffing Curve (meets targets)
Targets: on_time_rate ≥ 95%, failed_rate ≤ 5%, p90 ≤ 40 min.

| Scenario | Orders | Minimal Runners | On-Time (mean) | Failed (mean) | p90 (mean) |
|---|---:|---:|---:|---:|---:|
| typical_weekday | 18 | 1 | 0.96 | 0.03 | 37.2 |
| busy_weekend | 36 | 2 | 0.95 | 0.04 | 39.8 |

Fill from: `outputs/experiments/<exp-name>/staffing_summary.csv` and `experiment_summary.md`.

### 1-Runner Day Policy (Hole Restrictions)
For each Scenario × Orders, restrict the top <N> slowest holes by avg service time:

- Scenario: <scenario>, Orders: <orders>
  - See: `outputs/experiments/<exp-name>/<scenario>/orders_<NNN>/hole_policy_1_runner.md`
  - Proposed restricted holes: <hole_12>, <hole_5>, <hole_8>

### Peak Window Plan
- Identify 60–90 min windows with clustered SLA misses using `order_timing_logs.csv`.
- Actions:
  - Add temporary 2nd runner during the peak window (stagger shift).
  - Time‑gate restricted holes to off‑peak.
  - Boost prep capacity if queue wait avg > 15 min.

### Sensitivity Highlights
- Runner speed: <summary from sensitivity_summary.md>
- Prep time: <summary from sensitivity_summary.md>

### Decision Rules
- Add 2nd runner when: <rule chosen>
- Restrict top 3 slowest holes when: expected orders ≥ <X> and only 1 runner.
- Re‑enable restricted holes outside peak if queue wait avg < 10 min.


