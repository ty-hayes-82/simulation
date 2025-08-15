# Delivery Runner Optimization Guide

## Overview

The `run_batch_optimization_runners.py` script systematically finds the optimal number of delivery runners needed to achieve specific performance targets (like 95% or 99% on-time delivery rates) across different scenarios and configurations.

## Key Features

- **Automated optimization**: Tests runner counts from 1 to a maximum (default 10) until targets are met
- **Multiple targets**: Supports 95% and 99% on-time rates, plus custom metrics
- **Comprehensive testing**: Tests across scenarios, delivery probabilities, and prevention variants
- **Early stopping**: Stops testing more runners once targets are consistently achieved
- **Detailed tracking**: Records all simulation runs and optimization results

## Quick Start

### Basic Usage (95% and 99% targets)
```bash
conda activate my_gemini_env
python scripts/sim/run_batch_optimization_runners.py --target-95 --target-99
```

### Custom Delivery Probabilities
```bash
python scripts/sim/run_batch_optimization_runners.py --target-95 --delivery-order-probs "0.15,0.25,0.35"
```

### Specific Scenarios Only
```bash
python scripts/sim/run_batch_optimization_runners.py --target-99 --tee-scenarios "busy_weekend,typical_weekday"
```

### Custom Maximum Runners
```bash
python scripts/sim/run_batch_optimization_runners.py --target-95 --max-runners 8
```

## Command Line Options

### Core Options
- `--course-dir`: Course directory (default: `courses/pinetree_country_club`)
- `--output-dir`: Where to store results (default: auto-generated timestamp directory)
- `--log-level`: Logging level (default: `INFO`)

### Optimization Targets
- `--target-95`: Optimize for 95% on-time delivery rate
- `--target-99`: Optimize for 99% on-time delivery rate
- `--custom-targets`: Custom targets in format `name:metric:threshold:comparison,...`

Example custom targets:
```bash
--custom-targets "low_queue:queue_depth_avg:2.0:<=,fast_cycle:delivery_cycle_time_p50:900:<="`
```

### Test Parameters
- `--tee-scenarios`: Scenarios to test (default: `all`)
- `--delivery-order-probs`: Delivery probabilities to test (default: `0.2,0.3`)
- `--front-preventions`: Prevention variants (default: `none,1-3,1-6`)
- `--max-runners`: Maximum runners to test (default: `10`)
- `--runs-per-config`: Simulation runs per configuration (default: `5`)

### Runner Configuration
- `--runner-speed-mps`: Runner speed in m/s (default: `2.68`)
- `--prep-time-min`: Food preparation time in minutes (default: `10`)
- `--seed-base`: Base seed for reproducibility (default: `12345`)

## Output Files

The script generates several output files in a timestamped directory:

### 1. `optimization_results.csv`
**Summary of optimal runner counts for each scenario/target combination**

Key columns:
- `scenario`: Tee time scenario
- `prevention_variant`: Front hole prevention setting
- `delivery_prob`: Order probability per 9 holes
- `target_name`: Performance target being optimized
- `optimal_runners`: Minimum runners needed (or null if not achieved)
- `achieved_metric`: Actual performance achieved
- `optimization_status`: "achieved" or "not_achieved"

### 2. `optimization_detailed.csv`
**All individual simulation runs with full metrics**

Includes detailed performance metrics for every simulation run:
- Runner utilization percentages
- Queue depth and wait times
- Delivery cycle times
- Success/failure rates
- Revenue and capacity metrics

### 3. `optimization_summary.md`
**Human-readable markdown summary**

Organized by scenario with tables showing optimal runner counts for each target.

## Interpretation Guide

### Success Criteria
- **Optimal runners found**: The script found a runner count that achieves the target in ≥80% of test runs
- **Not achieved**: No runner count up to the maximum tested could consistently meet the target

### Key Metrics to Monitor
- **On-time rate**: Percentage of deliveries within SLA (30 minutes)
- **Queue depth**: Average number of orders waiting for pickup
- **Utilization rates**: How busy runners are (driving, waiting, etc.)
- **Cycle time**: Total time from order to delivery

### Prevention Variants
- **none**: No restrictions on ordering
- **front1_3**: Prevent ordering on holes 1-3 (lower front-9 probability)
- **front1_6**: Prevent ordering on holes 1-6 (lower front-9 probability)

## Example Workflows

### 1. Find Minimum Runners for Weekend Rush
```bash
python scripts/sim/run_batch_optimization_runners.py \
  --target-95 \
  --tee-scenarios "busy_weekend" \
  --delivery-order-probs "0.3,0.4" \
  --max-runners 12
```

### 2. Test Conservative vs Aggressive Scenarios
```bash
python scripts/sim/run_batch_optimization_runners.py \
  --target-95 --target-99 \
  --delivery-order-probs "0.2,0.35" \
  --front-preventions "none,1-6" \
  --runs-per-config 8
```

### 3. Quick Feasibility Check
```bash
python scripts/sim/run_batch_optimization_runners.py \
  --target-95 \
  --max-runners 6 \
  --runs-per-config 3 \
  --tee-scenarios "typical_weekday"
```

## Performance Tuning

### Faster Results
- Reduce `--runs-per-config` to 3 for quick estimates
- Limit `--max-runners` to reasonable range (e.g., 6-8)
- Test specific scenarios instead of "all"

### More Robust Results
- Increase `--runs-per-config` to 8-10 for stable averages
- Test wider range of delivery probabilities
- Include all prevention variants

## Integration with Other Scripts

### Follow-up Analysis
After optimization, use results to run targeted simulations:

```bash
# Use optimal runner count from optimization results
python scripts/sim/run_unified_simulation.py \
  --mode optimize-runners \
  --tee-scenario busy_weekend \
  --max-runners 4 \
  --output-dir outputs/opt_validation
```

### Batch Experiments
Use optimization results to inform batch experiment parameters:

```bash
python scripts/sim/run_batch_experiments.py \
  --modes runner \
  --runner-counts "3,4,5" \
  --delivery-order-probs "0.25,0.30" \
  --runs-per-combo 10
```

## Troubleshooting

### Common Issues

1. **No optimal runners found**: Target may be too aggressive; try lower thresholds or more runners
2. **Long runtime**: Reduce test parameters or increase optimization thresholds
3. **Inconsistent results**: Increase `runs-per-config` for more stable averages

### Memory Usage
The script is designed to be memory-efficient:
- No coordinate tracking or visualization generation
- Minimal event logging
- Efficient CSV writing

### Windows PowerShell Compatibility
The script follows project rules for Windows PowerShell:
- No piping or command chaining
- Clean, single-line commands
- Non-interactive operation
