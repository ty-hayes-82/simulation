# Simulation Optimization Strategy

This document outlines strategies for running the simulation optimization grid more efficiently, focusing on reducing file output and speeding up multi-run analyses.

## Key Concepts

When running a batch of simulations (e.g., 10 runs for a single configuration), the primary goals are typically:
1.  **Aggregated Metrics**: To understand the average performance of the configuration.
2.  **Visual Inspection**: To see a representative example of one run on the animated map.

Generating detailed output for every single run in the batch is often unnecessary and time-consuming.

## Optimization Techniques

### 1. Minimizing File Output

The simulation scripts include a `--minimal-outputs` flag. This is the first step to a faster workflow.

**Action**: Add the `--minimal-outputs` flag to your `run_controls_grid.py` command.

**What it does**:
-   Disables the generation of PNG heatmaps and other visualization files.
-   Stops the creation of secondary logs and metrics files that are not essential for the map animation or the final summary.
-   The essential files required by the map application (`coordinates.csv`, `simulation_metrics.json`, `results.json`) are still generated.

### 2. Handling Averaged Metrics

The `run_controls_grid.py` script automatically handles metric averaging.

**How it works**:
-   After completing all runs for a given configuration (e.g., 2 runners, 30 orders), the script finds all the individual `simulation_metrics.json` files.
-   It then calculates the average for key metrics (e.g., on-time percentage, failed deliveries) across all runs.
-   This summary is saved to a file named `@simulation_metrics.json` in the output directory for that configuration. This gives you a stable, aggregated view of performance.

### 3. Reducing Coordinate Generation (Recommended Change)

Currently, even in minimal mode, the system generates a `coordinates.csv` file for every run. This is the most time-intensive part of the simulation. Since you only need one file for visualization, we can optimize this.

The strategy is to introduce a new flag, `--coordinates-only-for-first-run`, that will modify the simulation loop:
-   **Run 1**: Behaves as normal, generating all necessary files (`coordinates.csv`, metrics, etc.).
-   **Runs 2 through 10**: The simulation will still run to calculate metrics, but it will **skip the expensive coordinate generation and file writing step**.

**Benefit**: This significantly speeds up batch runs by focusing only on what's needed from each run: metrics for aggregation and a single coordinate file for visualization.

### 4. How Coordinate Files Are Handled by the Map App

It's useful to know that the map application (`run_map_app.py`) has its own logic for selecting which `coordinates.csv` to display. When it finds multiple runs for the same configuration, it:
1.  Calculates the average metrics across all runs.
2.  Selects the run that is the "most representative" of the average (closest by z-score).
3.  Copies **only that representative run's** `coordinates.csv` to the public folder for display.

By implementing the `--coordinates-only-for-first-run` flag, we are simplifying this process and enforcing that "run 01" is always the representative run, which is a very effective optimization.

## Final Recommended Command Structure

Your final command will look like this, incorporating the new flags:

```bash
python scripts/optimization/run_controls_grid.py \
  --course-dir courses/pinetree_country_club \
  --tee-scenario real_tee_sheet \
  --runners 1 2 3 \
  --orders 10 20 30 40 \
  --runs-per 10 \
  --run-blocking-variants \
  --minimal-outputs \
  --coordinates-only-for-first-run
```


