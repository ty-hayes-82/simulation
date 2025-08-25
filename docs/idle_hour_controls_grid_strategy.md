### Goal
Run the same controls-grid simulation for `Idle Hour` as for `Pinetree`, without overriding existing files.

### Safe-run rules
- **Use Idle Hour course**: `--course-dir courses/idle_hour_country_club`.
- **Keep existing outputs**: add `--keep-old-outputs` (prevents cleanup of prior timestamped runs).
- **Isolate new outputs**: optionally set `--output-root outputs_idle_hour` so results land in a separate folder.
- **Use the same scenario**: `--tee-scenario real_tee_sheet` (matches `tee_times_config_real.json`).
- **Minimize artifacts**: keep `--minimal-outputs` and `--coordinates-only-for-first-run` if you only need coordinates/metrics.

### Recommended command
```bash
python scripts/optimization/run_controls_grid.py \
  --course-dir courses/idle_hour_country_club \
  --tee-scenario real_tee_sheet \
  --runners 1 2 3 \
  --orders 10 20 30 40 \
  --runs-per 10 \
  --run-blocking-variants \
  --minimal-outputs \
  --coordinates-only-for-first-run \
  --keep-old-outputs \
  --output-root outputs_idle_hour
```

### Windows PowerShell (one-liner)
```powershell
python scripts/optimization/run_controls_grid.py --course-dir courses/idle_hour_country_club --tee-scenario real_tee_sheet --runners 1 2 3 --orders 10 20 30 40 --runs-per 10 --run-blocking-variants --minimal-outputs --coordinates-only-for-first-run --keep-old-outputs --output-root outputs_idle_hour
```

### What this does
- Writes results under `outputs_idle_hour/<timestamp>_delivery_runner_<R>_runners_real_tee_sheet/...`.
- Each run uses a unique timestamp, so even without `--keep-old-outputs` you wouldn’t overwrite; the flag additionally prevents cleanup of older runs.
- The script automatically updates the map animation cache at the end if available; otherwise you can run it manually later.

### Tips
- To do a quick smoke test first, reduce load: `--orders 10 --runs-per 1`.
- If you’re in a specific Conda env, ensure it’s activated before running the command.
