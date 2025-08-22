# Speed Configuration Refactoring Plan

## Overview

This plan eliminates legacy "minutes per hole" pacing logic and standardizes on the **one node per minute** model driven by `golfer_18_holes_minutes` configuration. All golfer and beverage cart movement will be based on traversing nodes from `holes_connected.geojson` at a rate of one node per minute.

## Current State Analysis

### Legacy Concepts to Remove
- `minutes_per_hole` and `minutes_between_holes` parameters in synchronized timing
- `bev_cart_18_holes_minutes` (deprecated but still present)
- `calculate_synchronized_timing()` with separate hole/transfer timing
- Manual hole sequence building in beverage cart service
- Speed derivation from total minutes in crossings module

### Core Truth: Node-Per-Minute Model
- `golfer_18_holes_minutes` defines total round duration
- `holes_connected.geojson` contains exactly `golfer_18_holes_minutes` nodes (240 by default)
- Both golfers and beverage carts traverse these nodes at 1 node per minute
- Golfers go forward (idx 0→239), beverage carts go reverse (idx 239→0)
- `time_quantum_s = 60` (one minute per node)

## Refactoring Plan

### Phase 1: Configuration Consolidation

**Files to modify:**
- `golfsim/config/models.py`
- `courses/pinetree_country_club/config/simulation_config.json`

**Changes:**
1. Add unified `speeds` configuration block:
   ```json
   {
     "speeds": {
       "runner_mps": 6.0,
       "time_quantum_s": 60,
       "golfer_total_minutes": 240
     }
   }
   ```

2. Update `SimulationConfig` to include `SpeedSettings` dataclass:
   ```python
   @dataclass
   class SpeedSettings:
       runner_mps: float = 6.0
       time_quantum_s: int = 60
       golfer_total_minutes: int = 240
   ```

3. Map legacy keys with deprecation warnings:
   - `delivery_runner_speed_mps` → `speeds.runner_mps`
   - `golfer_18_holes_minutes` → `speeds.golfer_total_minutes`

### Phase 2: Core Simulation Engine Cleanup

**Files to modify:**
- `golfsim/simulation/engine.py`

**Changes:**
1. **Remove `calculate_synchronized_timing()`** - Replace with simple node-per-minute logic:
   ```python
   def get_node_timing(golfer_total_minutes: int, time_quantum_s: int = 60) -> Dict[str, int]:
       return {
           "time_quantum_s": time_quantum_s,
           "golfer_total_minutes": golfer_total_minutes,
           "total_duration_s": golfer_total_minutes * time_quantum_s
       }
   ```

2. **Simplify `simulate_beverage_cart_gps()`**:
   - Remove `synchronized_timing` parameter
   - Remove `total_bev_cart_minutes` parameter
   - Use `golfer_total_minutes` directly from config
   - Always use reverse node traversal (239→0)

3. **Update `run_unified_delivery_simulation()`**:
   - Use `config.speeds.golfer_total_minutes` instead of `total_golfer_minutes` parameter
   - Use `config.speeds.time_quantum_s` consistently

### Phase 3: Beverage Cart Service Refactoring

**Files to modify:**
- `golfsim/simulation/beverage_cart_service.py`

**Changes:**
1. **Remove deprecated fields**:
   - Remove `bev_cart_18_holes_minutes`
   - Remove `_build_hole_sequence()` method

2. **Simplify coordinate generation**:
   ```python
   def _generate_coordinates(self) -> None:
       # Load golfer nodes and reverse for bev cart
       loop_points, loop_holes = self._load_or_build_loop_points()
       if not loop_points:
           return
           
       # Reverse for bev cart (18→1 direction)
       bev_points = list(reversed(loop_points))
       bev_holes = list(reversed(loop_holes)) if loop_holes else None
       
       # Generate one point per minute from service start to end
       for minute_offset in range(0, (self.service_end_s - self.service_start_s) // 60):
           node_idx = minute_offset % len(bev_points)
           timestamp = self.service_start_s + (minute_offset * 60)
           # ... append coordinate
   ```

### Phase 4: Phase Simulations Cleanup

**Files to modify:**
- `golfsim/simulation/phase_simulations.py`

**Changes:**
1. **Remove synchronized timing calls**:
   - Remove all `calculate_synchronized_timing()` calls
   - Remove `_run_synchronized_simulation()` functions
   - Remove `sync_timing` and `sync_calc` parameters

2. **Simplify GPS generation**:
   - Use direct node-per-minute traversal
   - Remove complex offset calculations
   - Use service hours from config directly

3. **Update all phase simulation functions**:
   - `_run_standard_simulation()` → simplified to use node-per-minute only
   - Remove `_run_synchronized_simulation()` variants
   - Update `_generate_beverage_cart_gps_from_nodes()` to use simple reverse traversal

### Phase 5: Metrics and Analysis Cleanup

**Files to modify:**
- `golfsim/analysis/bev_cart_metrics.py`
- `golfsim/analysis/metrics_integration.py`

**Changes:**
1. **Remove pace-related metrics**:
   - Remove `minutes_per_hole_per_cart` calculations
   - Remove `holes_covered_per_hour` complex calculations
   - Simplify to use total service time and node count

2. **Update coverage calculations**:
   ```python
   def _calculate_holes_covered(coordinates: List[Dict[str, Any]]) -> int:
       # Count unique holes visited (from hole labels in coordinates)
       holes = {coord.get("current_hole") or coord.get("hole") for coord in coordinates}
       return len([h for h in holes if h is not None])
   ```

### Phase 6: Pass Detection and Sales Cleanup

**Files to modify:**
- `golfsim/simulation/bev_cart_pass.py`
- `golfsim/simulation/pass_detection.py`

**Changes:**
1. **Remove legacy timing parameters**:
   - Remove `minutes_between_holes` and `minutes_per_hole` from sales simulation
   - Use node-based timing only

2. **Simplify pass detection**:
   - Use direct node index comparison instead of complex timing calculations
   - Base proximity detection on node positions only

### Phase 7: CLI and Documentation Updates

**Files to modify:**
- `scripts/sim/run_new.py`
- `docs/speed_flow.md`

**Changes:**
1. **Update CLI flags**:
   - Keep `--runner-speed` for runner m/s
   - Add `--golfer-total-minutes` to override config
   - Remove any legacy timing flags

2. **Update documentation**:
   - Replace current speed flow documentation with simplified node-per-minute model
   - Document the single source of truth: `golfer_18_holes_minutes` → node count → pacing

## Implementation Status ✅ COMPLETED

### ✅ Step 1: Core Configuration 
1. ✅ Updated `SimulationConfig` with `SpeedSettings`
2. ✅ Added deprecation warnings for legacy keys
3. ✅ Updated config loading to use new structure

### ✅ Step 2: Engine Simplification 
1. ✅ Removed `calculate_synchronized_timing()`
2. ✅ Simplified `simulate_beverage_cart_gps()`
3. ✅ Updated all engine functions to use node-per-minute directly

### ✅ Step 3: Service Refactoring 
1. ✅ Refactored `BeverageCartService`
2. ✅ Updated coordinate generation logic
3. ✅ Removed complex hole sequence building

### ✅ Step 4: Phase Simulation Cleanup 
1. ✅ Removed synchronized simulation variants
2. ✅ Simplified all phase simulation functions
3. ✅ Updated GPS generation to use simple node traversal

### ✅ Step 5: Metrics and Analysis 
1. ✅ Updated metrics calculations
2. ✅ Removed pace-related complexity
3. ✅ Simplified coverage and efficiency calculations

### ✅ Step 6: Pass Detection Cleanup 
1. ✅ Simplified pass detection logic
2. ✅ Removed legacy timing parameters
3. ✅ Updated to use node-based proximity only

### ✅ Step 7: CLI and Documentation 
1. ✅ Updated CLI flags (added --golfer-total-minutes)
2. ✅ Updated documentation (simplified speed_flow.md)
3. ✅ All refactoring phases completed successfully

## Validation Criteria

### Before Refactoring
- [ ] Document current behavior of all affected simulations
- [ ] Create regression tests for key metrics
- [ ] Backup current configuration files

### After Each Phase
- [ ] All existing tests pass
- [ ] No deprecation warnings in test runs
- [ ] Output formats remain consistent
- [ ] Performance is maintained or improved

### Final Validation
- [ ] Single source of truth for all pacing: `golfer_18_holes_minutes`
- [ ] No "minutes per hole" logic anywhere in codebase
- [ ] All movement based on `holes_connected.geojson` node traversal
- [ ] Clean, unified configuration interface
- [ ] Updated documentation reflects reality

## Risk Mitigation

1. **Backward Compatibility**: Keep legacy key support with warnings during transition
2. **Incremental Changes**: Each phase should be independently testable
3. **Output Consistency**: Ensure metrics and visualizations remain comparable
4. **Performance**: Node-per-minute should be simpler and faster than complex timing calculations

## Files to Delete/Deprecate

After refactoring:
- Legacy timing calculation functions in `engine.py`
- Complex hole sequence logic in `beverage_cart_service.py`
- Synchronized timing variants in `phase_simulations.py`
- Pace-related metrics in `bev_cart_metrics.py`

## Success Metrics

1. **Code Simplicity**: Reduce lines of code in timing/pacing logic by >50%
2. **Configuration Clarity**: Single config section controls all pacing
3. **Performance**: No regression in simulation speed
4. **Maintainability**: New developers can understand pacing in <5 minutes
