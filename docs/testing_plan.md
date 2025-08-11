## Simulation Testing Plan

This outline is concise, Windows PowerShell friendly, and only references scripts that exist in the repo. All commands assume the repository root as the working directory.

### Quick checklist
- [x] 1. Beverage cart only (GPS monotonic 09:00–17:00)
- [x] 2. 1 Golfer group only, no bev-cart or delivery
- [x] 3. Bev cart + 1 group (order-on-pass; revenue > 0 in most runs)
- [x] 4. Bev cart + 4 groups (15-min intervals; revenue scales with more groups)
- [x] 5. Bev cart + many groups (throughput scales)
- [ ] 6. Single runner, single group (at least one processed order; no failures)
- [ ] 7. Incremental groups 1→2→4→8 (monotonic trends)
- [ ] 8. Threshold search until failures (reports threshold N)
- [ ] 9. Scenario from tee_times_config.json (plausible aggregates)
- [ ] 10. GPS synchronization (config cadence; timestamps align)
- [ ] 11. Two beverage carts (duplicate of Phase 1, two independent carts)
- [ ] 12. 1 Golfer + 1 Beverage cart GPS (LCM cadence alignment; correct counts)
 - [x] 11. Two beverage carts (duplicate of Phase 1, two independent carts)
 - [x] 12. 1 Golfer + 1 Beverage cart GPS (LCM cadence alignment; correct counts)

### Prerequisites
- Activate environment:
  ```powershell
  conda activate my_gemini_env
  ```
- Course data present under `courses/pinetree_country_club/` (`geojson/`, `pkl/`, `config/`).
- For GPS rules and enabling, see `docs/GPS_COORDINATE_TRACKING_UPDATE.md`.

### PowerShell usage rules
- One short command per line; no piping, redirection, or command chaining.
- Scripts are non-interactive and exit with 0 on success.

### Global invariants
- More golfers → more orders (expectation across runs).
- With fixed capacity, higher load → longer queue/total times (on average).
- Orders placed across holes ~ uniform over many runs.
- Timestamps are non-decreasing; prep_start → prep_complete → delivery_start → delivery_complete.

---

## 1. Beverage cart only
Verify beverage cart GPS generation and time alignment (no golfers).

- Invariants
  - Coordinates span 09:00–17:00 (relative to 07:00 start at t=0)
  - Timestamps strictly non-decreasing with consistent cadence (fixed 60s sampling)
  - `current_hole` is always in [1, 18]
- Tests
  - Generate GPS via service; assert first/last timestamps fall in window
  - Assert timestamp deltas are positive and consistent within tolerance; assert all `current_hole` valid
- Notes
  - Ensure service window bounds come from the same config used by the sim
  - Cadence is 60s and endpoints are inclusive. For 09:00–17:00 (8h = 480 minutes), expect 481 data rows (CSV will show 1 header + 481 rows)
  - The cart loops the course multiple times within the window; row count is determined by sampling interval, not loop count
  - Artifacts per run: PNG (`bev_cart_route.png`), GeoJSON (`bev_cart_route.geojson`), CSV (`bev_cart_coordinates.csv`), and `stats.md`
  - Runs are saved under `outputs/{YYYYMMDD_HHMMSS}_phase_01/sim_01..sim_05`, plus a root `summary.md`
  - How to run (PowerShell):
    ```powershell
    conda activate my_gemini_env
    python scripts/sim/phase_01_beverage_cart_only/run_bev_cart_phase1.py
    ```

## 2. 1 Golfer group only, no bev-cart or delivery
Verify golfer simulation mechanics in isolation (no beverage cart or delivery system).

- Invariants
  - Golfer group moves through holes 1-18 in sequence
  - GPS coordinates are generated for golfer movement with consistent cadence
  - Simulation completes successfully without errors
  - No orders are placed or processed (orders_processed == 0, orders_failed == 0)
- Tests
  - Run single golfer group simulation with delivery system disabled
  - Assert golfer progresses through all holes in expected timeframe
  - Verify GPS timestamps are non-decreasing and follow configured cadence
  - Confirm no beverage cart or delivery activity occurs
- Notes
  - Use golfer-only simulation mode to isolate movement mechanics
  - Verify hole progression timing aligns with configured play duration
  - GPS generation should match same cadence rules as other entities

## 3. Beverage cart + 1 group (order-on-pass)
Validate that probabilistic orders are generated when the cart passes the group’s hole.

- Invariants
  - **Positive mean revenue**: With `pass_order_probability ≈ 0.4`, mean revenue across 5 runs > 0
  - **Pass events observed**: `pass_intervals_per_group[1]` has at least one entry across the 5 runs
- Tests
  - Execute the Phase 3 runner; compute mean revenue over 5 runs and assert `> 0`
  - Inspect `result.json` in each `sim_XX` for `pass_intervals_per_group[1]` length > 0 in at least one run
- Notes
  - Seeds are fixed to run index for stability
  - Intervals are measured between passes, not absolute timestamps
  - Artifacts per run: `coordinates.csv` (combined `golfer_1` + `bev_cart_1`), `bev_cart_route.png`, `sales.json`, `result.json`, `stats.md`
  - How to run (PowerShell):
    ```powershell
    conda activate my_gemini_env
    python scripts/sim/phase_03_bev_cart_plus_one_group/run_bev_cart_phase3.py
    ```

## 4. Bev cart + 4 groups (15-minute intervals)
Validate that beverage cart can handle multiple groups with 15-minute intervals and revenue scales appropriately.

- Invariants
  - **Revenue increases with more groups**: Mean revenue with 4 groups should be ≥ mean revenue with 1 group
  - **Multiple group handling**: All 4 groups receive beverage cart passes during their rounds
  - **No interference**: Groups don't negatively impact each other's service
- Tests
  - Execute the Phase 4 runner; compute mean revenue over 5 runs and compare to Phase 3
  - Verify each group gets at least one pass opportunity in most runs
  - Assert total crossings increase proportionally with group count
- Notes
  - Groups are spaced 15 minutes apart with random start time between 09:00-10:00
  - Should see more total passes/sales opportunities than single group scenario
  - Track group-specific metrics to ensure balanced service
  - How to run (PowerShell):
    ```powershell
    conda activate my_gemini_env
    python scripts/sim/phase_04_bev_cart_plus_four_groups/run_bev_cart_phase4.py
    ```

## 5. Bev cart + many groups (throughput scales)
Run beverage cart simulations using all scenarios from tee_times_config.json. Each scenario generates groups based on hourly_golfers distribution.

- Invariants
  - Revenue increases with more groups across scenarios
  - Each scenario completes successfully with plausible aggregates
  - Groups are distributed according to scenario hourly_golfers
- Tests
  - Run all scenarios from tee_times_config.json
  - Verify revenue correlates with group count across scenarios
  - Assert each scenario generates expected number of groups
- Notes
  - Uses actual tee time distributions from realistic scenarios
  - Each run generates random tee times within specified hours
  - Supports filtering to specific scenarios if needed
- How to run (PowerShell):
  ```powershell
  conda activate my_gemini_env
  python scripts/sim/phase_05_bev_cart_plus_many_groups/run_bev_cart_phase5.py
  ```
- How to run specific scenarios:
  ```powershell
  conda activate my_gemini_env
  python scripts/sim/phase_05_bev_cart_plus_many_groups/run_bev_cart_phase5.py --scenarios typical_weekday busy_weekend
  ```

## 6. Single runner, single group
At least one order is processed successfully with no failures under typical parameters.

- Invariants
  - `orders_processed ≥ 1`, `orders_failed == 0` (with high order probability)
  - Activity log contains `delivery_complete`
- Tests
  - Run multi-golfer sim with 1 group, high probability; assert aggregates as above
- Notes
  - Choose a tee time firmly within the service window to avoid edge effects
  - Use deterministic seed if needed to ensure at least one order arrives
  - How to run a basic single-order runner sim (PowerShell):
    ```powershell
    conda activate my_gemini_env
    python scripts/sim/run_single_golfer_simulation.py --course-dir courses/pinetree_country_club --hole 9 --prep-time 10 --runner-speed 6.0 --save-coordinates
    ```
  - When validating Phase 2, also re-run Phase 1 to ensure it still passes
    - Run tests sequentially:
      ```powershell
      conda activate my_gemini_env
      pytest -q tests/phase_01_beverage_cart_only
      pytest -q -k phase2
      ```

## 7. Incremental groups 1→2→4→8 (monotonic trends)
System behavior should reflect increased load.

- Invariants
  - `orders_processed` is non-decreasing with more groups
  - Average total order time is non-decreasing (holding capacity fixed)
- Tests
  - Run sizes [1, 2, 4, 8]; assert monotonicity on processed and avg time
- Notes
  - Keep service capacity and policy fixed; only vary group count
  - Aggregate repeated runs per size if needed for stability

## 8. Threshold search until failures
Find smallest N where any orders fail (due to service window or queueing).

- Invariants
  - There exists a finite threshold N where failures begin, given fixed capacity
- Tests
  - Increase groups until failures > 0 (within an upper bound); assert threshold found
- Notes
  - Fix runner speed, prep time, and probabilities; sweep group count only
  - Use a reasonable upper bound to keep test runtime contained

## 9. Scenario from tee_times_config.json
Build groups from scenario and validate aggregates.

- Invariants
  - Simulation completes successfully with structured aggregates
  - Processed+failed orders roughly scales with number of generated groups
- Tests
  - Load scenario, build groups per config; run; assert `success` and aggregates present
- Notes
  - Pick the first available scenario by name; skip if config is empty
  - Record the scenario name in test output for traceability

## 10. GPS synchronization
Generated GPS streams should be time-aligned and sane.

- Invariants
  - Beverage cart coordinates follow a consistent cadence derived from config/LCM
  - Golfer GPS uses the same consistent cadence; runner GPS timestamps are non-decreasing (per-node increments)
- Tests
  - Verify positive, consistent cadence for bev cart and golfer streams; verify runner timestamps are non-decreasing
- Notes
  - Enable coordinate tracking on the single-golfer simulation for this check
  - Allow runner deltas to vary; only require non-decreasing timestamps

## 11. Two beverage carts (Phase 1 x2)
Mirror Phase 1 but generate outputs for two independent beverage carts.

- Invariants
  - Each cart independently produces a 60s cadence stream from 09:00–17:00
  - Each run folder contains artifacts for Cart A and Cart B
  - Counts per cart are ~481 points (inclusive endpoints)
- Tests
  - Execute phase 11 runner; verify 5 sims created
  - For each sim, ensure artifacts for Cart A and Cart B (PNG, GeoJSON, CSV) and `stats.md`
  - Verify point counts ~481 for each cart (60s cadence inclusive) and timestamps within 09:00–17:00
- How to run (PowerShell):
  ```powershell
  conda activate my_gemini_env
  python scripts/sim/phase_11_two_beverage_carts/run_bev_cart_phase11.py
  ```

## 12. Golfer + Beverage cart GPS (LCM alignment)
Simulate one golfer group (round start at 07:00, 12+2 cadence) and one beverage cart (09:00–17:00).

- Invariants
  - Golfer: exactly 252 minutes worth of points at 60s cadence (12 play + 2 transfer × 18, includes 18→clubhouse transfer)
  - Beverage cart: 09:00–17:00 inclusive, 60s cadence, ~481 points
  - Both streams are 60s cadence; timestamps are non-decreasing and aligned to minute boundaries
- Notes
  - Golfer path uses minute-level segments; cart uses course service window
- Tests
  - Execute phase 12 runner; verify combined artifacts exist in `sim_01`
  - Assert both streams are 60s cadence (strict +60s deltas) and non-decreasing
  - Assert bev-cart timestamps in 09:00–17:00; golfer start aligned to a valid tee-time hour from config
- How to run (PowerShell):
  ```powershell
  conda activate my_gemini_env
  python scripts/sim/phase_12_golfer_and_bev_cart/run_phase12_golfer_and_bev.py
  ```
