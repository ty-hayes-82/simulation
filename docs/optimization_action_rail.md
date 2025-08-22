## Optimization Action Rail — Run → Review → Recommend

This rail guides you through executing the experiments, reviewing results, and issuing GM-ready recommendations without modifying existing source files.

### 1) Run Experiments

1. Create staffing sweep (baseline):
```powershell
python scripts/optimization/run_staffing_experiments.py `
  --base-course-dir courses/pinetree_country_club `
  --tee-scenarios typical_weekday busy_weekend `
  --order-levels 10 14 18 28 36 44 `
  --runner-range 1-4 `
  --runs-per 5 `
  --runner-speed 6.0 `
  --prep-time 10 `
  --target-on-time 0.95 `
  --max-failed-rate 0.05 `
  --max-p90 40 `
  --top-holes 3 `
  --exp-name baseline
```

2. Sweep sensitivity (example typical weekday @ 28 orders):
```powershell
python scripts/optimization/run_sensitivity_experiments.py `
  --base-course-dir courses/pinetree_country_club `
  --tee-scenario typical_weekday `
  --orders 28 `
  --num-runners 1 `
  --speeds 5.0 6.0 7.0 `
  --preps 8 12 15 `
  --runs-per 5 `
  --exp-name sens_weekday_28
```

3. Collect all metrics to a flat CSV for your dashboard:
```powershell
python scripts/optimization/collect_metrics_csv.py `
  --root outputs/experiments/baseline `
  --out outputs/experiments/baseline/metrics_flat.csv
```

### 2) Review Results

- Open `outputs/experiments/<exp-name>/staffing_summary.csv` and filter rows by scenario and orders to identify the minimal `num_runners` where `meets_targets==True`.
- Read `outputs/experiments/<exp-name>/<scenario>/orders_<NNN>/hole_policy_1_runner.md` for recommended holes to restrict when staffing = 1.
- For sensitivity, review `outputs/experiments/<exp-name>/sensitivity_summary.{csv,md}` to understand robustness to speed/prep.
- Optionally open `my-map-animation` and the generated `hole_delivery_times.geojson` from each run to visualize per-hole service times.

Quick checklist:
- Minimal runners per orders level satisfy: on_time_rate ≥ 95%, failed_rate ≤ 5%, p90 ≤ 40 min.
- Second-runner break‑even (`second_runner_break_even_orders_mean`) is ≤ observed orders when recommending to add a runner.
- Hole restriction list focuses on the slowest zones (highest avg minutes) for 1-runner days.

### 3) Provide Recommendations

Use `docs/recommendations_template.md` as a scaffold and fill in:
- Staffing curve table (scenario × orders → minimal runners)
- Policy for 1-runner days (holes restricted/time-gated)
- Peak window plan (temporary 2nd runner or queue mitigation)
- Sensitivity notes (how speed/prep shifts change decisions)

Deliverables:
- `outputs/experiments/<exp-name>/experiment_summary.md`
- `outputs/experiments/<exp-name>/staffing_summary.csv`
- `outputs/experiments/<exp-name>/<scenario>/orders_<NNN>/hole_policy_1_runner.md`
- `docs/recommendations_template.md` (clone to a dated doc for executive review)

Or auto-generate a recommendations draft:
```powershell
python scripts/optimization/generate_recommendations.py `
  --exp-root outputs/experiments/<exp-name> `
  --course "Pinetree Country Club" `
  --out docs/recommendations_<exp-name>.md
```


