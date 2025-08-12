## Refactoring and code cleanup plan

This document outlines targeted refactors to improve clarity, consistency, and maintainability while preserving behavior. Changes are grouped by priority and reference concrete modules and scripts in this repo.

### Objectives

- Reduce duplication and dead code
- Normalize data schemas (coordinates, timestamps, holes)
- Separate orchestration (scripts) from core logic
- Make configuration-driven behavior explicit and testable
- Keep public interfaces small and typed

### Principles

- Incremental, test-backed edits in small PRs
- Preserve external CLI behavior while improving internals
- Centralize I/O and time formatting logic
- Prefer composition over deep inheritance or complex single files

### Priority P0: Safety and duplication cleanup (small, high-impact)

- **Deduplicate functions in `golfsim/io/phase_reporting.py`**
  - Remove repeated definitions of `save_phase5_output_files` and `write_phase5_stats_file` (duplicated blocks near the end of file).
  - Ensure all imports reference existing modules (e.g., use `golfsim.viz.matplotlib_viz.render_beverage_cart_plot` instead of non-existent `visualization.plotting`).

- **Normalize timestamp field names**
  - Use `timestamp` for seconds since 7AM consistently across coordinate records. Avoid mixing `timestamp` and `timestamp_s`.
  - Provide adapter utilities to convert legacy data to the normalized schema.

- **Remove hardcoded course path in reporting**
  - In `golfsim/io/phase_reporting.py`, avoid hardcoding `courses/pinetree_country_club` when rendering plots. Accept `course_dir` or infer from simulation results.

- **Stabilize imports and module boundaries**
  - Confirm `golfsim.analysis.metrics_integration` is committed and used as the single integration entrypoint.
  - In scripts, avoid importing demo/experimental code from `golfsim/simulation.engine` unless necessary.

### Priority P1: Structure, naming, and shared utilities

- **Extract time and formatting utilities**
  - Create `golfsim/utils/time.py` with:
    - `seconds_since_7am(hhmm: str) -> int`
    - `format_time_from_baseline(seconds: int) -> str` (centralize existing implementations)
    - `parse_hhmm(hhmm: str) -> tuple[int, int]`
  - Replace ad-hoc helpers in `scripts/sim/run_unified_simulation.py` and services with these utilities.

- **Define typed schemas for coordinates and sales**
  - Add `golfsim/types.py` or `golfsim/io/schemas.py` with `TypedDict`/dataclasses:
    - `Coordinate`: `entity_id`, `latitude`, `longitude`, `timestamp`, `type`, `current_hole?`
    - `SaleRecord`: `timestamp`, `price`, `group_id`, `hole_num`
  - Update `golfsim/io/results.py` writers to validate/normalize input via these types.

- **Split large service module**
  - Move `BeverageCartService` to `golfsim/simulation/bev_cart_service.py` and `SingleRunnerDeliveryService` to `golfsim/simulation/delivery_service.py`.
  - Leave thin re-exports in `golfsim/simulation/services.py` for backward compatibility.

- **Scenario and groups generation**
  - Introduce `golfsim/simulation/scenarios.py` with functions to:
    - Build groups from `tee_times_config.json`
    - Build interval-based groups
  - Replace `_build_groups_from_scenario` and `_build_groups_interval` in `scripts/sim/run_unified_simulation.py` with library calls.

- **Visualization cohesion**
  - Ensure all visualization calls route through `golfsim/viz/matplotlib_viz.py` or `folium_viz.py`.
  - Remove legacy references to `..visualization.plotting` in `golfsim/io/phase_reporting.py`.

### Priority P2: API polish and de-duplication

- **Unify coordinate generation for beverage carts**
  - Ensure a single path for generating beverage cart GPS (either via `BeverageCartService` or a pure function). Remove parallel DIY logic in scripts.

- **Consolidate pass/crossings serialization**
  - Provide a serializer in `golfsim/simulation/pass_detection.py` or `io/` layer and reuse everywhere (`serialize_crossings_summary`).

- **Reduce mode branching in runner script**
  - Extract each mode (`bev-carts`, `bev-with-golfers`, `golfers-only`, `delivery-runner`) into separate functions in a module `golfsim/cli/unified_modes.py`.
  - Keep `scripts/sim/run_unified_simulation.py` as a thin CLI wrapper.

- **Parameter normalization**
  - Standardize naming: `order_prob` vs `order_probability_per_9_holes` (choose one public name; adapt internally).
  - Adopt consistent units in parameter names (`*_s`, `*_min`, `*_mps`).

### Priority P3: Experimental code isolation and performance

- **Isolate experimental engine code**
  - Move advanced/experimental functions from `golfsim/simulation/engine.py` into `golfsim/simulation/experimental/` or mark clearly as experimental.
  - Provide a stable, minimal surface for production flows.

- **Performance guardrails**
  - Avoid DataFrame creation in hot paths (e.g., `predict_golfer_position_at_delivery`) unless necessary.
  - Cache course-derived artifacts (hole lines, cart graph) behind loader utilities.

### Naming and data consistency decisions

- Timestamps: `timestamp` (seconds since 7AM) in all coordinate-like records.
- Coordinates: `latitude` and `longitude` keys only; avoid `lon`/`lat`.
- Hole indices: use `current_hole` for moving entities; `hole_num` in event/sales records.
- Entity type: use `type` values from the set `{golfer, bev_cart, delivery-runner}`.

### Concrete edit checklist (first passes)

- `golfsim/io/phase_reporting.py`
  - Remove duplicated `save_phase5_output_files` and `write_phase5_stats_file` blocks at the bottom.
  - Replace any `..visualization.plotting` imports with `golfsim.viz.matplotlib_viz` equivalents.
  - Accept `course_dir` parameter in visualization helpers to avoid hardcoded paths.

- `scripts/sim/run_unified_simulation.py`
  - Replace private helpers for time parsing and scenario group building with `golfsim.utils.time` and `golfsim.simulation.scenarios`.
  - Normalize `timestamp` usage and adapt legacy writes via a small adapter function.

- `golfsim/simulation/services.py`
  - Split into `bev_cart_service.py` and `delivery_service.py`; keep re-exports in `services.py`.
  - Ensure shared helpers (e.g., Haversine, resampling) move into a `golfsim/utils/geo.py` where appropriate.

- `golfsim/analysis/bev_cart_metrics.py`
  - Accept normalized schemas and provide a small adapter for legacy keys (`hole` vs `current_hole`).

### Testing and validation

- Add unit tests for:
  - Time utilities (`seconds_since_7am`, `format_time_from_baseline`)
  - Scenario builders (interval and config-based)
  - Coordinate schema adapters
  - Phase reporting deduped functions

- Update integration tests to assert normalized CSV column names and timestamp semantics.

### Rollout plan

1. Land P0: phase reporting dedupe, hardcoded paths removal, import fixes.
2. Introduce `utils.time`, `simulation.scenarios`, and types module; migrate scripts incrementally.
3. Split services; keep re-exports to avoid breaking imports; adjust tests.
4. Normalize coordinate schemas and update writers; provide adapters for old data.
5. Extract unified CLI mode implementations to library; keep script as thin wrapper.
6. Optionally isolate experimental engine code.

### Developer ergonomics and PowerShell stability

- Keep CLI entrypoints short and non-interactive; one command per line.
- Ensure logging is initialized by `golfsim.logging.init_logging()` in all scripts.
- Avoid long single-line commands or chained invocations in docs and examples.
