# Golf Delivery Simulation - Complete Usage Guide

This comprehensive guide covers all simulation scripts in the system, from single simulations to large-scale batch optimizations.

## 📋 Table of Contents

1. [Quick Start](#quick-start)
2. [Single Simulations](#single-simulations)
3. [Batch Experiments](#batch-experiments)
4. [Optimization Scripts](#optimization-scripts)
5. [Unified Simulation Runner](#unified-simulation-runner)
6. [Analysis and Visualization](#analysis-and-visualization)
7. [Troubleshooting](#troubleshooting)

---

## 🚀 Quick Start

### Environment Setup
```bash
# Activate conda environment
conda activate my_gemini_env

# Verify setup
python verify_setup.py
```

### Basic Test Run
```bash
# Quick test with rainy day scenario (4 golfers)
python scripts/sim/run_scenarios_batch.py \
  --course-dir courses/pinetree_country_club \
  --scenario testing_rainy_day \
  --runs-per-scenario 3 \
  --runner-speed 6.0
```

---

## 🎯 Single Simulations

### 1. Single Golfer Delivery (`run_single_golfer.py`)

**Purpose**: Test delivery to one golfer at a specific hole.

```bash
# Basic single delivery
python scripts/sim/run_single_golfer.py \
  --course-dir courses/pinetree_country_club \
  --hole 9 \
  --prep-time 10 \
  --runner-speed 6.0

# With GPS tracking and custom output
python scripts/sim/run_single_golfer.py \
  --course-dir courses/pinetree_country_club \
  --hole 14 \
  --prep-time 15 \
  --runner-speed 2.68 \
  --save-coordinates \
  --output-dir outputs/hole14_test
```

**Key Parameters:**
- `--hole`: Delivery hole (1-18)
- `--prep-time`: Kitchen prep time in minutes
- `--runner-speed`: Runner speed in m/s
- `--save-coordinates`: Enable GPS tracking

### 2. Single Golfer Simulation (`run_single_golfer_simulation.py`)

**Purpose**: More detailed single simulation with full metrics.

```bash
# Detailed single simulation
python scripts/sim/run_single_golfer_simulation.py \
  --course-dir courses/pinetree_country_club \
  --hole 7 \
  --tee-time "09:15" \
  --runner-speed 3.0 \
  --prep-time 12

# Multiple holes
python scripts/sim/run_single_golfer_simulation.py \
  --course-dir courses/pinetree_country_club \
  --holes "5,12,16" \
  --tee-time "08:30" \
  --output-dir outputs/multi_hole_test
```

### 3. Two Golfer Simulation (`run_two_golfer_simulation.py`)

**Purpose**: Test simultaneous delivery to two golfer groups.

```bash
# Two groups with different tee times
python scripts/sim/run_two_golfer_simulation.py \
  --course-dir courses/pinetree_country_club \
  --holes1 "6,13" \
  --holes2 "8,15" \
  --tee-time1 "08:00" \
  --tee-time2 "08:15" \
  --runner-speed 2.68
```

---

## 🔄 Batch Experiments

### 1. Comprehensive Batch Runner (`run_batch_experiments.py`)

**Purpose**: Large-scale parameter sweeps across scenarios and configurations.

#### Basic Batch Run (Both Beverage Carts and Delivery Runners)
```bash
python scripts/sim/run_batch_experiments.py \
  --course-dir courses/pinetree_country_club \
  --runs-per-combo 5 \
  --modes "bevcart,runner"
```

#### Beverage Cart Only Experiments
```bash
# Test different cart counts and order probabilities
python scripts/sim/run_batch_experiments.py \
  --modes "bevcart" \
  --bev-cart-counts "1,2,3" \
  --bev-order-probs "0.3,0.4,0.5" \
  --bev-price-usd 15.0 \
  --runs-per-combo 10 \
  --tee-scenarios "busy_weekend,typical_weekday"
```

#### Delivery Runner Experiments
```bash
# Test runner counts with prevention strategies
python scripts/sim/run_batch_experiments.py \
  --modes "runner" \
  --runner-counts "1-5" \
  --delivery-order-probs "0.2,0.3,0.4" \
  --front-preventions "none,1-3,1-6" \
  --runs-per-combo 8 \
  --runner-speed-mps 2.68 \
  --prep-time-min 10
```

#### Custom Scenario Testing
```bash
# Focus on specific scenarios
python scripts/sim/run_batch_experiments.py \
  --tee-scenarios "busy_weekend" \
  --modes "runner" \
  --runner-counts "2,3,4" \
  --delivery-order-probs "0.25,0.35" \
  --runs-per-combo 15 \
  --output-dir outputs/weekend_optimization
```

**Key Parameters:**
- `--modes`: "bevcart", "runner", or both
- `--runs-per-combo`: Repetitions per parameter combination
- `--tee-scenarios`: Specific scenarios or "all"
- `--output-dir`: Custom output location

**Generated Files:**
- `batch_stats.csv`: Summary metrics per run
- `batch_events.csv`: Event log for all simulations
- `batch_metrics.csv`: Detailed metrics
- `batch_summary_*.csv`: Aggregated results by mode

### 2. Scenario Batch Runner (`run_scenarios_batch.py`)

**Purpose**: Multiple runs of same scenario with different configurations.

```bash
# Multiple runs of rainy day scenario
python scripts/sim/run_scenarios_batch.py \
  --course-dir courses/pinetree_country_club \
  --scenario testing_rainy_day \
  --runs-per-scenario 10 \
  --runner-speed 6.0 \
  --prep-time 10

# Speed comparison study
python scripts/sim/run_scenarios_batch.py \
  --scenario typical_weekday \
  --runs-per-scenario 8 \
  --runner-speed 2.0 \
  --speed-comparison

# Custom groups and holes
python scripts/sim/run_scenarios_batch.py \
  --scenario busy_weekend \
  --groups 3 \
  --holes "4,8,12,16" \
  --runs-per-scenario 5
```

---

## 🎯 Optimization Scripts

### 1. Runner Count Optimization (`run_batch_optimization_runners.py`)

**Purpose**: Find minimum runners needed for target on-time rates.

#### Basic Optimization (95% and 99% targets)
```bash
python scripts/sim/run_batch_optimization_runners.py \
  --target-95 \
  --target-99 \
  --max-runners 8 \
  --runs-per-config 5
```

#### Scenario-Specific Optimization
```bash
# Optimize for weekend rush
python scripts/sim/run_batch_optimization_runners.py \
  --target-95 \
  --tee-scenarios "busy_weekend" \
  --delivery-order-probs "0.3,0.4" \
  --max-runners 10 \
  --runs-per-config 8 \
  --front-preventions "none,1-6"
```

#### Custom Target Optimization
```bash
# Optimize for low queue depth and fast cycle times
python scripts/sim/run_batch_optimization_runners.py \
  --custom-targets "low_queue:queue_depth_avg:2.0:<=,fast_cycle:delivery_cycle_time_p50:900:<=,high_throughput:orders_per_runner_hour:8.0:>=" \
  --max-runners 6 \
  --runs-per-config 10
```

#### Conservative vs Aggressive Testing
```bash
# Test different prevention strategies
python scripts/sim/run_batch_optimization_runners.py \
  --target-95 \
  --delivery-order-probs "0.2,0.35" \
  --front-preventions "none,1-3,1-6" \
  --max-runners 8 \
  --output-dir outputs/prevention_optimization
```

**Key Features:**
- **Early stopping**: Stops when targets are consistently achieved
- **Success validation**: Requires 80% success rate across runs
- **Multiple targets**: Can optimize for different metrics simultaneously
- **Comprehensive tracking**: Records all tested configurations

**Generated Files:**
- `optimization_results.csv`: Optimal runner counts summary
- `optimization_detailed.csv`: All simulation runs with metrics
- `optimization_summary.md`: Human-readable results by scenario

---

## 🎛️ Unified Simulation Runner

### Unified Matrix Runner (`run_unified_matrix.py`)

**Purpose**: Systematic testing across multiple parameter dimensions.

```bash
# Full parameter matrix
python scripts/sim/run_unified_matrix.py \
  --course-dir courses/pinetree_country_club \
  --scenarios "busy_weekend,typical_weekday" \
  --runner-counts "1,2,3,4" \
  --delivery-probs "0.2,0.3" \
  --prevention-modes "none,front1_5" \
  --runs-per-combo 5
```

### Unified Simulation (`run_unified_simulation.py`)

**Purpose**: Flexible simulation runner with multiple modes.

#### Mode: optimize-runners
```bash
# Find optimal runners for scenario
python scripts/sim/run_unified_simulation.py \
  --mode optimize-runners \
  --tee-scenario busy_weekend \
  --max-runners 6 \
  --target-on-time-rate 0.95 \
  --output-dir outputs/weekend_optimization
```

#### Mode: bev-with-golfers  
```bash
# Beverage cart with golfer interactions
python scripts/sim/run_unified_simulation.py \
  --mode bev-with-golfers \
  --tee-scenario typical_weekday \
  --num-bev-carts 2 \
  --bev-order-prob 0.4 \
  --runs 8
```

#### Mode: delivery-stress-test
```bash
# High-load delivery testing
python scripts/sim/run_unified_simulation.py \
  --mode delivery-stress-test \
  --tee-scenario busy_weekend \
  --delivery-prob 0.4 \
  --num-runners 3 \
  --runs 10
```

---

## 📊 Analysis and Visualization

### 1. Beverage Cart Analysis
```bash
# Analyze bev cart performance
python scripts/analysis/analyze_bev_cart_metrics.py \
  --input-dir outputs/bevcart_batch_20240815_143022 \
  --output-dir outputs/bevcart_analysis

# Compare multiple bev cart experiments
python scripts/analysis/analyze_bev_cart_metrics.py \
  --input-dir outputs/bevcart_comparison \
  --compare-scenarios \
  --generate-plots
```

### 2. Delivery Runner Analysis
```bash
# Analyze runner performance
python scripts/analysis/analyze_delivery_runner_metrics.py \
  --input-dir outputs/runner_optimization_20240815_150133 \
  --output-dir outputs/runner_analysis

# Runner utilization analysis
python scripts/analysis/analyze_delivery_runner_metrics.py \
  --input-dir outputs/optimization_results \
  --focus-utilization \
  --breakdown-by-scenario
```

### 3. Batch Metrics Aggregation
```bash
# Aggregate batch experiment results
python scripts/analysis/aggregate_batch_metrics.py \
  --batch-dir outputs/batch_20240815_162045 \
  --output-file outputs/aggregated_analysis.md

# Compare multiple batches
python scripts/analysis/aggregate_batch_metrics.py \
  --batch-dirs "outputs/batch1,outputs/batch2,outputs/batch3" \
  --comparative-analysis \
  --output-file outputs/multi_batch_comparison.md
```

### 4. Visualization
```bash
# Render delivery route visualization
python scripts/viz/render_single_delivery_png.py \
  --simulation-file outputs/single_sim/simulation_results.json \
  --output-file outputs/delivery_route_vis.png

# View cart network
python scripts/viz/view_cart_network.py \
  --course-dir courses/pinetree_country_club \
  --show-holes \
  --show-paths
```

---

## 🔬 Advanced Use Cases

### 1. Performance Benchmarking
```bash
# Compare different runner speeds
python scripts/sim/run_batch_experiments.py \
  --modes "runner" \
  --runner-counts "3" \
  --delivery-order-probs "0.3" \
  --tee-scenarios "busy_weekend" \
  --runs-per-combo 15 \
  --output-dir outputs/speed_benchmark

# Test with different speeds by modifying simulation_config.json
# Then run multiple batches and compare
```

### 2. Capacity Planning
```bash
# Find break-even points for additional runners
python scripts/sim/run_batch_optimization_runners.py \
  --custom-targets "break_even:second_runner_break_even_orders:20:<=,capacity:capacity_15min_window:12:>=" \
  --delivery-order-probs "0.2,0.25,0.3,0.35,0.4" \
  --max-runners 5 \
  --output-dir outputs/capacity_planning
```

### 3. Prevention Strategy Analysis
```bash
# Compare all prevention strategies
python scripts/sim/run_batch_experiments.py \
  --modes "runner" \
  --runner-counts "2,3,4" \
  --delivery-order-probs "0.3" \
  --front-preventions "none,1-3,1-5,1-6" \
  --runs-per-combo 12 \
  --tee-scenarios "busy_weekend,typical_weekday" \
  --output-dir outputs/prevention_analysis
```

### 4. Revenue Optimization
```bash
# Optimize beverage cart placement and pricing
python scripts/sim/run_batch_experiments.py \
  --modes "bevcart" \
  --bev-cart-counts "1,2,3" \
  --bev-order-probs "0.3,0.4,0.5,0.6" \
  --bev-price-usd "10,12,15,18" \
  --runs-per-combo 10 \
  --output-dir outputs/revenue_optimization
```

---

## ⚙️ Configuration Examples

### 1. High-Performance Testing
```bash
# Fast testing configuration
python scripts/sim/run_batch_optimization_runners.py \
  --target-95 \
  --max-runners 6 \
  --runs-per-config 3 \
  --tee-scenarios "testing_rainy_day" \
  --delivery-order-probs "0.25"
```

### 2. Production Validation
```bash
# Comprehensive validation testing
python scripts/sim/run_batch_experiments.py \
  --modes "runner" \
  --runner-counts "1-8" \
  --delivery-order-probs "0.15,0.2,0.25,0.3,0.35" \
  --front-preventions "none,1-3,1-6" \
  --runs-per-combo 20 \
  --tee-scenarios "all" \
  --output-dir outputs/production_validation
```

### 3. Stress Testing
```bash
# Maximum load testing
python scripts/sim/run_unified_simulation.py \
  --mode delivery-stress-test \
  --tee-scenario busy_weekend \
  --delivery-prob 0.5 \
  --num-runners 2 \
  --runs 25 \
  --output-dir outputs/stress_test
```

---

## 🔧 Troubleshooting

### Common Issues

1. **Long Runtime**
   ```bash
   # Reduce parameters for faster testing
   --runs-per-combo 3 --max-runners 5 --tee-scenarios "testing_rainy_day"
   ```

2. **Memory Issues**
   ```bash
   # Reduce batch size and disable coordinate tracking
   --runs-per-combo 5 --no-coordinates
   ```

3. **No Optimal Solution Found**
   ```bash
   # Increase maximum runners or reduce target threshold
   --max-runners 12 --custom-targets "relaxed_target:on_time_rate:0.90:>="
   ```

### Performance Optimization

**Fast Testing:**
- Use `testing_rainy_day` scenario (4 golfers only)
- Reduce `--runs-per-config` to 3
- Limit `--max-runners` to 6
- Test single scenarios instead of "all"

**Robust Results:**
- Increase `--runs-per-config` to 8-10
- Test wider parameter ranges
- Include all scenarios and prevention variants
- Use higher runner counts (up to 10)

### Windows PowerShell Compatibility

All scripts follow Windows PowerShell best practices:
- No piping or command chaining
- Clean, single-line commands
- Non-interactive operation
- Proper error handling

---

## 📝 Output File Reference

### Batch Experiments Output
```
outputs/batch_YYYYMMDD_HHMMSS/
├── batch_stats.csv              # Summary metrics per run
├── batch_events.csv             # Event log for all runs
├── batch_metrics.csv            # Detailed metrics per run
├── batch_summary_bevcart.csv    # Beverage cart summaries
├── batch_summary_runner.csv     # Runner summaries
├── aggregated_metrics_report.md # Analysis report
└── events_by_run/               # Per-run event files
    ├── batch_scenario_run01.csv
    └── ...
```

### Optimization Output
```
outputs/optimization_YYYYMMDD_HHMMSS/
├── optimization_results.csv    # Optimal runner counts
├── optimization_detailed.csv   # All simulation runs
└── optimization_summary.md     # Readable summary
```

### Single Simulation Output
```
outputs/single_sim/
├── delivery_simulation.png     # Route visualization
├── golfer_coordinates.csv      # GPS tracking
├── runner_coordinates.csv      # Runner tracking
├── simulation_results.json     # Raw results
└── simulation_stats.md         # Analysis
```

---

This guide covers all major simulation scripts and use cases. Start with simple single simulations, then progress to batch experiments and optimization based on your specific needs.
