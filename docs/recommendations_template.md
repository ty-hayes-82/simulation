## GM Recommendations — <Course> — <Date>

### Executive Summary
- Staffing recommendations by demand level and scenario.
- Hole restriction policy for 1-runner days.
- Peak window plan and sensitivity highlights.

### Staffing Curve (meets targets)
Targets: on_time_rate ≥ 95%, failed_rate ≤ 5%, p90 ≤ 40 min.

<table style="border-collapse: collapse; width: 100%;">
  <thead>
    <tr>
      <th style="border: 1px solid #ccc; text-align: left; padding: 6px;">Scenario</th>
      <th style="border: 1px solid #ccc; text-align: right; padding: 6px;">Orders</th>
      <th style="border: 1px solid #ccc; text-align: right; padding: 6px;">Minimal Runners</th>
      <th style="border: 1px solid #ccc; text-align: right; padding: 6px;">On-Time %</th>
      <th style="border: 1px solid #ccc; text-align: right; padding: 6px;">Failed (mean)</th>
      <th style="border: 1px solid #ccc; text-align: right; padding: 6px;">p90 (mean)</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td style="border: 1px solid #eee; padding: 6px;">typical_weekday</td>
      <td style="border: 1px solid #eee; text-align: right; padding: 6px;">18</td>
      <td style="border: 1px solid #eee; text-align: right; padding: 6px;">1</td>
      <td style="border: 1px solid #eee; text-align: right; padding: 6px;">0.96</td>
      <td style="border: 1px solid #eee; text-align: right; padding: 6px;">0.03</td>
      <td style="border: 1px solid #eee; text-align: right; padding: 6px;">37.2</td>
    </tr>
    <tr>
      <td style="border: 1px solid #eee; padding: 6px;">busy_weekend</td>
      <td style="border: 1px solid #eee; text-align: right; padding: 6px;">36</td>
      <td style="border: 1px solid #eee; text-align: right; padding: 6px;">2</td>
      <td style="border: 1px solid #eee; text-align: right; padding: 6px;">0.95</td>
      <td style="border: 1px solid #eee; text-align: right; padding: 6px;">0.04</td>
      <td style="border: 1px solid #eee; text-align: right; padding: 6px;">39.8</td>
    </tr>
  </tbody>
  
</table>

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


