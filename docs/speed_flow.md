# Simplified Speed Configuration

This document describes the unified speed configuration system that uses the **node-per-minute** model for all simulation timing.

## Core Concept: Node-Per-Minute Model

All golfer and beverage cart movement is based on traversing nodes from `holes_connected.geojson` at a rate of **one node per minute**.

- **Golfers**: Move forward through nodes (index 0→239) at one node per minute
- **Beverage carts**: Move in reverse through nodes (index 239→0) at one node per minute  
- **Time quantum**: 60 seconds per node (configurable)
- **Total duration**: Determined by `golfer_total_minutes` (default: 240 minutes)

## Configuration

### Unified Speeds Block

The new configuration uses a single `speeds` section in `simulation_config.json`:
    
    ```json
    {
      "speeds": {
    "runner_mps": 6.0,
    "time_quantum_s": 60,
    "golfer_total_minutes": 240
      }
    }
    ```
    
### Legacy Key Support

For backward compatibility, legacy keys are still supported with deprecation warnings:
- `delivery_runner_speed_mps` → `speeds.runner_mps`
- `golfer_18_holes_minutes` → `speeds.golfer_total_minutes`

## CLI Flags

- `--runner-speed <m/s>`: Override runner speed in meters per second
- `--golfer-total-minutes <minutes>`: Override total minutes for golfer round
- All other timing is derived from the node-per-minute model

## How It Works

### Golfers
1. Load nodes from `holes_connected.geojson`
2. Traverse nodes sequentially (0→239) at one node per minute
3. Total round time = `golfer_total_minutes` × `time_quantum_s`

### Beverage Carts  
1. Load same nodes from `holes_connected.geojson`
2. Traverse nodes in reverse (239→0) at one node per minute
3. Service during configured hours using cycling node traversal

### Delivery Runners
1. Use `runner_mps` for route calculations via cart graph
2. Node-based prediction for optimal delivery locations
3. GPS coordinate generation based on actual travel times

## Benefits

- **Simplicity**: Single source of truth for all pacing
- **Consistency**: All movement based on same node sequence
- **Predictability**: One node per minute eliminates complex timing calculations
- **Maintainability**: Easy to understand and modify

## Migration Notes

This system replaces the previous complex synchronized timing approach with a much simpler node-based model. All legacy timing functions have been removed and replaced with straightforward node traversal logic.
