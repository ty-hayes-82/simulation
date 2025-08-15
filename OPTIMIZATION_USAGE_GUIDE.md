# Comprehensive Golf Simulation Optimization Guide

This guide explains how to run the comprehensive optimization tests you requested for the golf simulation system.

## Quick Start

**To run everything with your exact specifications:**

```bash
conda activate my_gemini_env
python run_comprehensive_golf_optimization.py
```

This will test:
- ✅ **Scenario**: `typical_weekday` only
- ✅ **Total orders**: 5, 10, 15, 20, 25, 30, 35, 40
- ✅ **Beverage carts**: 1, 2, 3, 4, 5
- ✅ **Delivery options**: Full course, blocking up to hole 3, blocking up to hole 6
- ✅ **All output files**: Including coordinate files for visualization

## What Gets Created

The optimization creates a timestamped directory in `outputs/` with this structure:

```
outputs/comprehensive_optimization_20250101_120000/
├── comprehensive_optimization_summary.md       # Overall summary
├── 5orders_1bevcarts/                         # Configurations by total orders + carts
│   ├── bev_cart_only/                         # Beverage cart simulations
│   │   ├── sim_01/, sim_02/, sim_03/          # Individual runs
│   │   │   ├── coordinates.csv                # GPS coordinates ✅
│   │   │   ├── bev_cart_route.png            # Route visualization
│   │   │   ├── events.csv                    # Timeline events
│   │   │   └── bev_cart_metrics_*.md         # Performance metrics
│   │   └── summary.md                        # Summary for this config
│   └── bev_with_golfers/                     # Cart + golfer interactions
│       ├── sim_01/, sim_02/, sim_03/
│       │   ├── coordinates.csv               # GPS coordinates ✅
│       │   ├── sales.json                    # Sales data
│       │   └── bev_cart_metrics_*.md         # Performance metrics
│       └── summary.md
├── 5orders_delivery_full_course/              # Delivery scenarios
│   ├── run_01/, run_02/, run_03/
│   │   ├── coordinates.csv                   # GPS coordinates ✅  
│   │   ├── events.csv                        # Timeline events
│   │   ├── results.json                      # Detailed results
│   │   └── delivery_runner_metrics_*.md      # Performance metrics
│   ├── blocking_scenario.json                # Scenario metadata
│   └── summary.md
├── 5orders_delivery_block_to_hole3/           # Blocking up to hole 3
├── 5orders_delivery_block_to_hole6/           # Blocking up to hole 6
├── 10orders_1bevcarts/                        # Next configuration...
└── ...                                       # All combinations
```

## Key Features

### 1. Coordinate Files ✅
Every simulation generates `coordinates.csv` files containing GPS tracking data:
- **Beverage carts**: GPS track of cart movement
- **Golfer groups**: GPS tracks of golfer movements  
- **Delivery runners**: GPS tracks of runner routes

### 2. Delivery Blocking Scenarios ✅
Three delivery restriction scenarios are tested:
- **Full course**: Orders allowed on any hole (1-18)
- **Block to hole 3**: Orders only allowed on holes 4-18
- **Block to hole 6**: Orders only allowed on holes 7-18

### 3. Total Orders Configuration ✅
The system automatically modifies the simulation config to test different order volumes:
- Backs up original `simulation_config.json`
- Tests each total order value (5, 10, 15, 20, 25, 30, 35, 40)
- Restores original config when complete

### 4. Multiple Beverage Cart Configurations ✅
Tests 1-5 beverage carts operating simultaneously with proper coordination.

## Manual Usage

If you want more control, you can use the underlying scripts directly:

### Comprehensive Optimization Script

```bash
python scripts/sim/run_comprehensive_optimization.py \
    --total-orders-range "5,10,15,20" \
    --bev-carts-range "1,2,3" \
    --log-level INFO
```

### Individual Delivery Simulations with Blocking

```bash
# Full course delivery (no blocking)
python scripts/sim/run_unified_simulation_with_blocking.py \
    --mode delivery-runner \
    --tee-scenario typical_weekday \
    --block-up-to-hole 0 \
    --num-runs 5

# Block orders up to hole 3
python scripts/sim/run_unified_simulation_with_blocking.py \
    --mode delivery-runner \
    --tee-scenario typical_weekday \
    --block-up-to-hole 3 \
    --num-runs 5

# Block orders up to hole 6  
python scripts/sim/run_unified_simulation_with_blocking.py \
    --mode delivery-runner \
    --tee-scenario typical_weekday \
    --block-up-to-hole 6 \
    --num-runs 5
```

### Individual Beverage Cart Simulations

```bash
# Multiple beverage carts
python scripts/sim/run_unified_simulation.py \
    --mode bev-carts \
    --num-carts 3 \
    --tee-scenario typical_weekday \
    --num-runs 5

# Beverage cart with golfer interactions
python scripts/sim/run_unified_simulation.py \
    --mode bev-with-golfers \
    --tee-scenario typical_weekday \
    --num-runs 5
```

## Output Analysis

### Key Files to Check

1. **`coordinates.csv`** - GPS tracking data for visualization
2. **`events.csv`** - Timeline of all simulation events
3. **`*_metrics_*.md`** - Performance analysis and KPIs
4. **`summary.md`** - High-level results for each configuration
5. **`comprehensive_optimization_summary.md`** - Overall test summary

### Typical Analysis Workflow

1. **Start with the comprehensive summary** to get an overview
2. **Compare configurations** by looking at summary.md files
3. **Drill into specific runs** using the individual sim_XX directories
4. **Visualize routes** using the coordinates.csv files
5. **Analyze performance** using the metrics files

## Troubleshooting

### If the script fails:
1. **Check conda environment**: `conda activate my_gemini_env`
2. **Check working directory**: Run from the simulation project root
3. **Check dependencies**: Ensure all required packages are installed
4. **Check disk space**: Large coordinate files require significant storage

### If simulations are slow:
- Reduce `--num-runs` from 3 to 1 for faster testing
- Use `--skip-bev-carts` or `--skip-delivery` to test subsets
- Use `--log-level WARNING` to reduce output

### If coordinate files are missing:
- Check that `track_coordinates=True` in the simulation services
- Verify no errors in the simulation logs
- Ensure sufficient disk space for CSV files

## Estimated Runtime

For the full optimization (40 total order values × 5 bev cart configs × 3 delivery scenarios):
- **Conservative estimate**: 2-4 hours
- **Depends on**: System performance, coordinate tracking, visualization generation
- **Storage needed**: 5-10 GB for all coordinate files and outputs

## Next Steps

After running the optimization:

1. **Review the comprehensive summary** for overall patterns
2. **Identify optimal configurations** based on your KPIs
3. **Deep-dive into specific scenarios** that look promising
4. **Use coordinate files** to create custom visualizations
5. **Run focused tests** on the best-performing configurations

Happy optimizing! 🏌️⛳
