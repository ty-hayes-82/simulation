### Comprehensive Simulation Matrix Runner

This guide explains how to run the comprehensive delivery-runner simulation matrix using `scripts/sim/run_comprehensive_matrix.py`.

#### What it runs
- **Tee scenario**: `typical_weekday`
- **Delivery orders**: 20, 30
- **Runners**: 1, 2
- **Blocking variants**: `none`, `0-3`, `0-6` (currently logged only; real blocking not yet implemented)

Total: 1 × 2 × 2 × 3 = 12 combinations.

---

### Prerequisites
- Windows PowerShell
- A conda environment with the project requirements installed
- Non-interactive console usage per project rules (short, single-purpose commands)

If you haven't yet, install dependencies:
```powershell
conda create -n my_gemini_env python=3.11 -y
conda activate my_gemini_env
pip install -r requirements.txt
```

---

### Quick start
1) Activate the environment:
```powershell
conda activate my_gemini_env
```

2) Dry run (prints the 12 combinations; does not execute simulations):
```powershell
python scripts/sim/run_comprehensive_matrix.py --dry-run
```

3) Execute the full matrix with 1 run per combination (faster validation):
```powershell
python scripts/sim/run_comprehensive_matrix.py --num-runs 1
```

4) Execute with 3 runs per combination (default; longer):
```powershell
python scripts/sim/run_comprehensive_matrix.py
```

Optional flags:
- `--course-dir courses/pinetree_country_club`
- `--output-dir outputs\comprehensive_matrix_YYYYMMDD_HHMMSS`
- `--log-level INFO`
- `--random-seed 42`

Notes:
- The runner internally invokes the unified simulation via `-m scripts.sim.run_unified_simulation` to avoid import issues.
- Visualizations are disabled for speed; metrics and heatmaps are still generated per run.

---

### Output
The runner creates a timestamped directory under `outputs/`, e.g.:
```
outputs/
  comprehensive_matrix_20250816_201358/
    sim_01_20orders_1runners_blocknone/
      run_01/
        results.json
        events.csv
        delivery_heatmap.png
        delivery_runner_metrics_run_01.json
        delivery_runner_metrics_run_01.md
      summary.md
    ...sim_02 ... sim_12 ...
    comprehensive_summary.md  (created at the end)
```

`comprehensive_summary.md` includes a table of all combinations with their success/failure status and links to subfolders.

---

### Current limitations
- **Blocking variants (`0-3`, `0-6`) are placeholders**: They are logged but currently run without actual hole blocking. If you need real blocking, see `scripts/sim/run_scenarios_batch.py` for an approach and open a task to add support to the unified runner.

---

### Troubleshooting
- **Import errors when the unified script is called directly**: The matrix runner already uses `python -m scripts.sim.run_unified_simulation` to prevent this. If you call the unified script yourself, prefer the `-m` module form from the project root.

- **FileNotFoundError writing `comprehensive_summary.md`**: Ensure the `outputs/<timestamped-dir>/` folder exists. The runner creates it at start; if the folder was removed externally during execution, re-run the matrix.

- **Timeouts**: Each combination has a 30-minute timeout. If a combination times out (e.g., heavy scenarios), re-run with `--num-runs 1` to validate quickly, then scale up.

- **PSReadLine/PowerShell hangs**: Avoid long chained commands and piping. Run one command per line, as shown above.

---

### Example: end-to-end session
```powershell
conda activate my_gemini_env
python scripts\sim\run_comprehensive_matrix.py --dry-run
python scripts\sim\run_comprehensive_matrix.py --num-runs 1
```

When complete, open the summary:
```powershell
code outputs\comprehensive_matrix_YYYYMMDD_HHMMSS\comprehensive_summary.md
```

---

### Where to look for metrics
- Per-run metrics: `sim_XX/run_YY/delivery_runner_metrics_run_YY.json|.md`
- Heatmap: `sim_XX/run_YY/delivery_heatmap.png`
- Events: `sim_XX/run_YY/events.csv`
- Combined summary: `comprehensive_summary.md`

---

### Next steps
- If you need real blocking behavior, implement `block-up-to-hole` support in the unified runner or integrate the separate blocking script pattern used by `scripts/sim/run_scenarios_batch.py`.


