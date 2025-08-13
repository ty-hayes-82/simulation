# Scripts Archive

This directory contains archived/deprecated scripts that are no longer actively maintained but are kept for historical reference.

## Archive Policy

Files in this directory:
- Are **read-only** and should not be modified
- Are **excluded from CI/test runs** 
- May contain outdated code patterns or dependencies
- Are retained for historical reference only

## Usage

**DO NOT** use scripts from this archive directory. Instead, use the current active scripts organized in the main scripts/ subdirectories:

- `scripts/sim/` - Simulation entrypoints
- `scripts/routing/` - Routing and network utilities
- `scripts/viz/` - Visualization tools
- `scripts/analysis/` - Analysis and reporting

## Migration History

Scripts are moved to this archive when they are:
- Superseded by newer, better implementations
- Duplicates of functionality available elsewhere
- No longer compatible with current system architecture
- Replaced by library functions in the `golfsim/` package

## If You Need Archived Functionality

If you need functionality from an archived script:

1. **First check** if equivalent functionality exists in the current active scripts
2. **Check the `golfsim/` library modules** for the functionality you need
3. **If neither exists**, consider whether the archived script should be restored and updated rather than used as-is

## Current Archive Status

The following scripts were superseded by the unified runner or exist as older variants. They are retained for reference only and should not be used:

- `scripts/sim/run_bev_cart_dynamic.py` (use `scripts/sim/run_unified_simulation.py --mode bev-carts` or `--mode bev-with-golfers`)
- `scripts/sim/run_delivery_dynamic.py` (use `scripts/sim/run_unified_simulation.py --mode delivery-runner`)
- `scripts/sim/run_single_golfer.py` (use `scripts/sim/run_single_golfer_simulation.py` or unified runner)
- `scripts/sim/run_reference_crossings.py` (experimental; functionality integrated elsewhere)
- `scripts/sim/build_holes_loop_segments.py` (replaced by `scripts/routing/extract_course_data.py` outputs)
- `scripts/sim/build_optimal_course_nodes.py` (prototype LCM node builder; not used by production flows)
- `scripts/sim/generate_lcm_course_nodes.py` (prototype LCM node generator; not used by production flows)
- `scripts/sim/validate_optimal_nodes.py` (tied to LCM prototypes)

---

*Last updated: 2025*
