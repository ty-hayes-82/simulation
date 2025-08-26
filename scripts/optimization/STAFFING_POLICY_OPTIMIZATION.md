## Optimization Wrappers

This folder contains small CLI wrappers to recommend delivery runner staffing and blocking policies using the existing simulation engine.

### Scripts

- `optimize_runners.py`: Given a single orders level (e.g., 36) and an optional list of blocked holes, sweeps runner counts, aggregates multiple runs with confidence intervals, and prints the recommended number of runners.
- `optimize_staffing_policy.py`: For multiple order levels (e.g., 20/30/40), evaluates several blocked-hole variants and runner counts, then recommends the minimal runners and policy per orders level.

Both wrappers call `scripts/sim/run_new.py` under the hood and parse per-run metrics (`delivery_runner_metrics_run_XX.json` when present; fallback to `simulation_metrics.json`).

---

### Prerequisites

- Course directory prepared (cart graph, holes, config). See project `README.md` and `COURSE_SETUP_README.md`.
- Python environment activated; run from the repository root.

---

### Confidence and Targets

- On-time rate uses a Wilson score lower bound (95%) aggregated across runs.
- A configuration “meets targets” when all are true:
  - on_time_wilson_lo ≥ `--target-on-time`
  - failed_mean ≤ `--max-failed-rate`
  - p90_mean ≤ `--max-p90` (ignored if not available)
- Increase `--runs-per` for tighter intervals and higher certainty.

---

### Quick start

#### Recommend runners for one orders level

Windows PowerShell example (use `^` for line breaks):

```bash
python scripts/optimization/optimize_runners.py ^
  --course-dir courses/pinetree_country_club ^
  --tee-scenario real_tee_sheet ^
  --orders 36 ^
  --runner-range 1-3 ^
  --runs-per 8 ^
  --block-holes 1 2 3 ^
  --target-on-time 0.90 ^
  --max-failed-rate 0.05 ^
  --max-p90 40
```

Output: JSON with the recommended `num_runners` and per-`runners` aggregates. Exit code 0 if recommended, 2 otherwise.

#### Recommend policy and runners for multiple orders levels

```bash
python scripts/optimization/optimize_staffing_policy.py ^
  --course-dir courses/pinetree_country_club ^
  --tee-scenario real_tee_sheet ^
  --orders-levels 20 30 40 ^
  --runner-range 1-3 ^
  --runs-per 8 ^
  --target-on-time 0.90 ^
  --max-failed-rate 0.05 ^
  --max-p90 40
```

Printed lines include human-readable recommendations, for example:

```
Orders 20: You can use 1 runner(s) if you block holes 1–6 & 10–12; otherwise you need 2 runner(s).
```

Final JSON summarizes chosen variant/runner per orders and includes per-variant metrics.

---

### Parameters (shared or analogous)

- `--course-dir`: Course folder (`courses/<club>`). Relative to repo root if not absolute.
- `--tee-scenario`: Tee sheet scenario (e.g., `real_tee_sheet`, `idle_hour`).
- `--runner-range`: Range like `1-3` or a single number `2`.
- `--runs-per`: Number of runs per combination to average over.
- `--runner-speed`, `--prep-time`: Optional overrides.
- `--log-level`: Logging for the underlying runner.
- `--output-root`: Root for outputs; timestamped subfolders are created.

Specific:

- `optimize_runners.py`:
  - `--orders`: Total orders to simulate
  - `--block-holes`: Explicit list (e.g., `--block-holes 1 2 3`) applied to all runs

- `optimize_staffing_policy.py`:
  - `--orders-levels`: Multiple total orders values
  - `--variants`: Subset of built-in variants to test (defaults to all)
    - Built-ins: `none`, `front` (1–3), `mid` (4–6), `back` (10–12), `front_mid` (1–6), `front_back` (1–3 & 10–12), `mid_back` (4–6 & 10–12), `front_mid_back` (1–6 & 10–12)

Targets (both scripts):

- `--target-on-time` (default 0.90)
- `--max-failed-rate` (default 0.05)
- `--max-p90` minutes (default 40)

---

### Output structure

Each combination writes to a timestamped directory under `--output-root`:

- `optimize_runners.py`: `outputs/runner_opt/<stamp>_opt_<scenario>_orders_XXX/runners_N/run_*/...`
- `optimize_staffing_policy.py`: `outputs/policy_opt/<stamp>_<scenario>/orders_XXX/<variant>/runners_N/run_*/...`

Core per-run files include `simulation_metrics.json` and (if enabled by the engine) `delivery_runner_metrics_run_XX.json`.

The scripts aggregate these per-run files to compute means and Wilson CIs, and then print/return a final JSON summary.

---

### Interpreting results

- Prefer the smallest `num_runners` whose Wilson lower bound for on-time meets the target and whose failure/p90 are within limits.
- If a blocking policy allows fewer runners for the same orders level, the script will recommend it. Otherwise, it will recommend the minimal runners without blocking.
- Increase `--runs-per` if results are borderline; check `on_time_wilson_lo` vs. `--target-on-time`.

---

### Tips

- Use smaller `--runner-range` during exploration to save time.
- To test a subset of policies in `optimize_staffing_policy.py`, use `--variants none front_mid_back`.
- You can run multiple commands in parallel to fill out the grid faster if your machine allows it.


