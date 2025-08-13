# Production Runbook: Golf Course Simulation

This guide provides the complete workflow for setting up golf courses and running simulations using the refactored `golfsim.tools` package.

## Prerequisites

### Environment Setup
```bash
# Activate your conda environment
conda activate my_gemini_env

# Install the project in development mode
pip install -e .
```

### Project Rules (Windows PowerShell)
- ✅ Use one command per line (no piping with `|` or chaining with `;`, `&&`)
- ✅ Keep commands short to avoid PSReadLine rendering issues  
- ✅ All scripts are non-interactive and exit with proper codes
- ✅ Use `golfsim.logging.init_logging()` for consistent logging

---

## Step 1: Course Data Setup

### 🚀 **Recommended: Automated Setup**

```bash
# Generate all required course data files
python scripts/prep/generate_course_data.py --course-dir courses/pinetree_country_club
```

**What this does:**
- ✅ Validates all required course files exist
- ✅ Auto-generates missing `lcm_course_nodes.geojson` (720 optimal nodes)
- ✅ Auto-generates missing `holes_geofenced.geojson`
- ✅ Handles graceful fallbacks if `geopandas` or other dependencies are missing
- ✅ Works without manual intervention

### 🔍 **Validation Options**

```bash
# Check what files are missing (validation only)
python scripts/prep/generate_course_data.py --validate-only --course-dir courses/pinetree_country_club

# Quick status check (one-liner)
python -c "from golfsim.tools import CourseDataGenerator; print('Ready:', CourseDataGenerator('courses/pinetree_country_club').validate_course_data()['all_files_ready'])"
```

### 🎯 **Specialized Generation**

```bash
# Generate only LCM course nodes
python scripts/prep/generate_lcm_nodes.py --course-dir courses/pinetree_country_club
```

### 🗺️ **Legacy: Full OSM Extraction** 
*(Only needed when starting completely from scratch)*

```bash
# Basic extraction
python scripts/routing/extract_course_data.py --course "Pinetree Country Club" --clubhouse-lat 34.0379 --clubhouse-lon -84.5928 --output-dir courses/pinetree_country_club

# With street data for delivery shortcuts
python scripts/routing/extract_course_data.py --course "Pinetree Country Club" --clubhouse-lat 34.0379 --clubhouse-lon -84.5928 --include-streets --street-buffer 750 --course-buffer 100 --output-dir courses/pinetree_country_club
```

### 📁 **Generated Assets**

After setup, your course directory will contain:

```
courses/pinetree_country_club/
├── geojson/
│   ├── course_polygon.geojson    # Course boundary
│   ├── holes.geojson            # Individual hole geometries  
│   ├── tees.geojson             # Tee locations
│   ├── greens.geojson           # Green locations
│   └── generated/
│       ├── lcm_course_nodes.geojson      # 720 optimal sync nodes
│       └── holes_geofenced.geojson       # Auto-generated hole boundaries
├── pkl/
│   ├── cart_graph.pkl           # Cart path network
│   ├── street_graph.pkl         # (Optional) Street network
│   └── combined_routing_graph.pkl # (Optional) Combined network
└── config/
    ├── simulation_config.json   # Course configuration
    └── tee_times_config.json    # Tee time scenarios
```

---

## Step 2: Run Simulations

### Primary CLI: `run_unified_simulation.py`

- **Standard scenario (delivery runner)**
```bash
python scripts\sim\run_unified_simulation.py --mode delivery-runner --tee-scenario typical_weekday --num-runs 1
```

- **Alternatives**
  - **Different scenario**
  ```bash
  python scripts\sim\run_unified_simulation.py --mode delivery-runner --tee-scenario typical_weekend --num-runs 1
  ```
  - **Beverage carts instead (2 carts)**
  ```bash
  python scripts\sim\run_unified_simulation.py --mode bev-carts --tee-scenario typical_weekday --num-runs 1 --num-carts 2
  ```
  - **Golfers only**
  ```bash
  python scripts\sim\run_unified_simulation.py --mode golfers-only --tee-scenario typical_weekday --num-runs 1
  ```
  - **Additional runners**: Not yet exposed via CLI (single-runner queue only). Run separate processes or use matrix orchestration for workload studies.

### Tee Time Scenarios

Use predefined scenarios from `tee_times_config.json`:
```bash
# Use a predefined scenario
--tee-scenario typical_weekday

# Disable scenarios (use manual group settings)
--tee-scenario none
```

---

## Step 3: Orchestration & Analysis

### **Multiple Run Orchestration**

```bash
# Small matrix of different configurations
python scripts/sim/run_unified_matrix.py --course-dir courses/pinetree_country_club --log-level INFO

# Preview commands without executing
python scripts/sim/run_unified_matrix.py --dry-run

# Batch config-driven runs  
python scripts/sim/run_scenarios_batch.py --course-dir courses/pinetree_country_club --scenario testing_rainy_day --runs-per-scenario 5
```

### **Analysis Tools**

```bash
# Simulation results analysis
python scripts/analysis/analyze_simulation_results.py

# Delivery metrics analysis
python scripts/analysis/analyze_delivery_runner_metrics.py

# Beverage cart metrics analysis 
python scripts/analysis/analyze_bev_cart_metrics.py
```

### **Visualization**

```bash
# View cart network
python scripts/viz/view_cart_network.py

# Render delivery visualization
python scripts/viz/render_single_delivery_png.py
```

---

## Advanced Usage

### **Programmatic API**

```python
from golfsim.tools import CourseDataGenerator

# Initialize course data generator
cdg = CourseDataGenerator('courses/pinetree_country_club')

# Validate course data
status = cdg.validate_course_data()
print(f"All files ready: {status['all_files_ready']}")
print(f"Holes: {status['holes_count']}, Nodes: {status['nodes_count']}")

# Auto-generate missing files
results = cdg.ensure_all_required_files()
print(f"Generation results: {results}")

# Generate tracks programmatically
tracks = cdg.generate_tracks()
```

### **Legacy Script Compatibility**

For regression testing, phase-specific wrappers remain available:
```bash
python scripts/sim/phase_01_beverage_cart_only/run_bev_cart_phase1.py
python scripts/sim/phase_02_golfer_only/run_golfer_only_phase2.py
python scripts/sim/phase_11_two_beverage_carts/run_bev_cart_phase11.py
python scripts/sim/phase_12_golfer_and_bev_cart/run_phase12_golfer_and_bev.py
```

---

## Troubleshooting

### **Post-Refactoring Improvements** ✨

- **🔄 Automated data generation**: Missing files are auto-generated with no manual intervention
- **🛡️ Graceful fallbacks**: System works even without optional dependencies like `geopandas`
- **🔧 Self-healing**: Course validation automatically fixes missing files
- **📦 Unified tools**: All data generation available via `golfsim.tools` package
- **⚡ Fewer dependencies**: Fallback implementations reduce external requirements

### **Common Issues & Solutions**

| Issue | Solution |
|-------|----------|
| **Missing course files** | Run `python scripts/prep/generate_course_data.py --course-dir <path>` |
| **Import errors** | Activate environment: `conda activate my_gemini_env` |
| **PowerShell hangs** | Use shorter commands, avoid piping/chaining |
| **Cart path connectivity** | Use `scripts/routing/enhance_cart_network.py` |
| **Dependency issues** | System has graceful fallbacks for optional deps |

### **Quick Health Checks**

```bash
# Validate course data
python scripts/prep/generate_course_data.py --validate-only

# Test routing integration
python scripts/routing/test_routing_integration.py

# Run full regression test
python scripts/test/run_all_phases.py
```

### **Logging Control**

All scripts support `--log-level` for debugging:
```bash
--log-level DEBUG    # Verbose output
--log-level INFO     # Default level  
--log-level WARNING  # Minimal output
```

---

## Migration Notes

### **From Legacy Workflow**

- **Old**: Extract OSM → Generate nodes → Generate geofences → Validate manually
- **New**: Run single validation command → Auto-generates missing files → Ready to simulate

### **Backward Compatibility**

- ✅ Existing courses work unchanged 
- ✅ Legacy scripts available in `scripts/_archive/` 
- ✅ All simulation outputs remain compatible
- ✅ Configuration files unchanged

### **Dependency Changes**

- ✅ Fewer required dependencies (graceful fallbacks)
- ✅ `geopandas` now optional (has fallback implementation)
- ✅ Course setup works even with minimal Python environment


