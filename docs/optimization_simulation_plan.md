## Simulation-Optimization Development Plan

- **Owner**:
- **Repo**: `golf-delivery-sim`
- **Scope**: Single runner (delivery staff), dynamic open/closed delivery zones by hole/cluster, optimize revenue and reduce delivery/total order time.
- **Principles**: Keep current sim working; all new work is additive behind flags/config; progress measured by data and tests at each phase. Prefer thin CLIs in `scripts/` that delegate to library APIs in `golfsim/` (typed configs, structured logging, unified results I/O).

### Progress Tracker (high level)
- [ ] Phase 0 — Objectives & Guardrails
- [ ] Phase 1 — Travel-Time Ground Truth
- [ ] Phase 2 — Simulator Instrumentation Baseline
- [ ] Phase 3 — Demand & Patience Models
- [ ] Phase 4 — Policy Hooks (Gating + ETA Cap) and Routing Heuristic
- [ ] Phase 5 — Optimization Wrapper (Multi-objective)
- [ ] Phase 6 — Pareto Frontier & Robustness
- [ ] Phase 7 — Offline Backtest (Historical/Scripted Days)
- [ ] Phase 8 — Shadow Mode Pilot
- [ ] Phase 9 — Limited Production (1 Course)
- [ ] Phase 10 — Scale & Continuous Improvement

## KPI & Definitions (confirm before Phase 1)
- [ ] Define SLA (e.g., 15 min) and whether mean or p95 drives decisions
- [ ] Define profit model: revenue/order, cost/order (variable), runner cost/hour, late penalty ($/min > SLA), cancel penalty ($/order)
- [ ] Define acceptance: total order time = order_created→handoff; delivery time = depart_clubhouse→handoff
- [ ] Confirm fairness guardrails (e.g., max consecutive minutes a hole may be blocked)
- [ ] Logging schema approved: `order_created`, `order_accepted|rejected`, `route_planned`, `depart`, `arrive`, `handoff`, `cancel`

## Phase 0 — Objectives & Guardrails
Build
- [ ] Write KPI/penalty spec in `docs/` and add to course config (read-only by sim)
- [ ] Add config flags in typed config to keep new logic off by default (e.g., `SimulationConfig.opt.enable_policy=false`)
- [ ] Unit tests for metric calculations (zero orders, mass cancel, long routes)

Exit (all must be true)
- [ ] Written KPI/penalty spec reviewed
- [ ] Metric unit tests pass

Artifacts
- [ ] `docs/kpi_guardrails.md`
- [ ] `courses/<course>/config/simulation_config.json` updated (non-breaking)
 - [ ] `golfsim/config/models.py` and `golfsim/config/loaders.py` updated as needed (typed validation)

## Phase 1 — Travel-Time Ground Truth
Build
- [ ] Precompute clubhouse↔hole and hole↔hole shortest-path matrix from existing cart-path graph (`pkl/cart_graph.pkl`)
- [ ] Persist matrix to `courses/<course>/pkl/travel_time_matrix.pkl`
- [ ] Add variability model (e.g., slowdown zones, stochastic factor)

Implementation notes (post-refactor)
- Prefer library utilities in `golfsim/routing/` for graph loading and shortest paths
- CLI entrypoint: `scripts/routing/compute_travel_times.py` (renamed from `calculate_travel_times.py`)

Validation Data
- [ ] Collect ≥50 timed legs (GPS/sim) across near/mid/far holes

Exit (all must be true)
- [ ] 95% of simulated legs within ±15% of measured times
- [ ] Triangle inequality violations <1% and investigated

Artifacts
- [ ] `courses/<course>/pkl/travel_time_matrix.pkl`
- [ ] `docs/travel_time_validation.md`

## Phase 2 — Simulator Instrumentation Baseline
Build
- [ ] Add event logging hooks via `golfsim/logging.init_logging(...)` without changing control flow
- [ ] Baseline policy: all holes open; one-runner min-added-latency insertion routing
- [ ] Seed control and reproducibility toggles

Exit (all must be true)
- [ ] 10 simulated “days” yield stable metrics (bootstrap 95% CI width <10% of mean for profit and mean ETA)
- [ ] Same seed ⇒ identical event sequence

Artifacts
- [ ] Structured results per run saved via `golfsim/io/results.SimulationResult` (JSON + CSV helpers) under `outputs/`
- [ ] `docs/sim_instrumentation.md`

Entry points (post-refactor)
- Library: `golfsim/simulation/services.py` (`SingleRunnerDeliveryService`, `simulate_golfer_orders`)
- CLI: `scripts/sim/run_single_golfer.py` (renamed from `run_simulation.py`)

## Phase 3 — Demand & Patience Models
Build
- [ ] Arrival curves λ_i(t) by hole/time (Poisson or empirical); tee-sheet modulation if available
- [ ] Basket size and gross margin distributions
- [ ] Patience/cancel vs promised ETA (logit or piecewise); service time distribution at handoff

Exit (all must be true)
- [ ] Back-cast (if history): simulated cancel rate within ±20% relative; hourly volume R² ≥ 0.8
- [ ] If no history: parameter sweep shows realistic tipping (cancel jumps when ETA > SLA+5)

Artifacts
- [ ] `docs/demand_patience_model.md`
- [ ] Serialized priors in `courses/<course>/pkl/`

## Phase 4 — Policy Hooks and Routing Heuristic
Policy family (parameters the optimizer will tune)
- Queue-aware dynamic radius: `{R_min, R_max, q_low, q_high}`
- ETA acceptance cap: `T_max`
- Optional: hole clusters (near/mid/far) toggles

Build
- [ ] Implement policy hooks in `golfsim/simulation/services.SingleRunnerDeliveryService` using `SimulationConfig.opt.*` toggles
- [ ] Acceptance rule: accept iff predicted ETA ≤ T_max and within open radius
- [ ] One-runner routing: minimum added latency insertion after each accept
- [ ] Comprehensive unit tests for monotonic behavior (e.g., higher queue ⇒ smaller open set)

Exit (all must be true)
- [ ] With fixed seed, parameter changes monotonically affect accepted sets and ETAs
- [ ] When queue ≥ q_high ⇒ only near holes open; when ≤ q_low ⇒ full radius opens

Artifacts
- [ ] `docs/policy_hooks.md`

## Phase 5 — Optimization Wrapper (Multi-objective)
Build
- [ ] Library wrapper `simulate(policy, seed) -> metrics` with replication aggregation (K=8–10) implemented in `golfsim/simulation/services.py`
- [ ] Multi-objective search (e.g., Optuna NSGA-II): maximize profit, minimize mean delay (p95 as constraint)
- [ ] Early stopping for dominated candidates; common random numbers for noise control

Exit (all must be true)
- [ ] Optimizer finds policies that beat baseline by ≥ +10% profit or −15% mean ETA on synthetic demand
- [ ] Ranking of top-5 policies stable across replications (Kendall τ ≥ 0.6)

Artifacts
- [ ] `outputs/optimization_trials.db` (or CSV)
- [ ] `docs/optimizer_setup.md`

Entry points (post-refactor)
- CLI: `scripts/sim/run_scenarios_batch.py` (renamed from `run_configurable_simulations.py`)

## Phase 6 — Pareto Frontier & Robustness
Build
- [ ] Run 300–500 trials; extract non-dominated set; plot frontier
- [ ] Stress tests: demand ±30%, service-time +20%, path closures, weather slowdown

Exit (all must be true)
- [ ] At least one Balanced policy with ≥95% SLA hit-rate and ≥5% profit gain vs baseline across all stress tests
- [ ] Report with 3 canonical policies: Speed / Balanced / Revenue

Artifacts
- [ ] `outputs/pareto_frontier.png`
- [ ] `docs/robustness_report.md`

## Phase 7 — Offline Backtest (Historical/Scripted Days)
Build
- [ ] Feed historical tee sheets + timestamps (if available) to simulate shadow accept/reject
- [ ] Compare per-hole block rates, completion, lateness vs historical ops

Exit (all must be true)
- [ ] Balanced policy improves profit ≥5% and reduces p95 ETA ≥10% on ≥75% of test days
- [ ] Fairness guardrail met: no hole blocked >X consecutive minutes more than Y times/day

Artifacts
- [ ] `docs/offline_backtest.md`

## Phase 8 — Shadow Mode Pilot
Build
- [ ] Run live with suggestions only; operators retain control
- [ ] Dashboard: live queue, runner position, predicted vs actual ETA error, suggested open zones

Exit (all must be true)
- [ ] ETA prediction MAPE ≤ 12% across ≥200 live orders
- [ ] When operators follow suggestions (≥50 cases), mean ETA improves ≥10% vs non-adherence

Artifacts
- [ ] `docs/shadow_mode_findings.md`

## Phase 9 — Limited Production (1 Course)
Build
- [ ] Enable auto-gating with manual override and guardrails (max ETA, max queue)
- [ ] Daily report: profit, completion, mean/p95 ETA, block rate by hole, lost-demand estimate

Exit (all must be true)
- [ ] Over 2 weeks: profit/hour +8–12% and p95 ETA −10–15% vs pre-pilot baseline; cancel rate not worse by >1 pp
- [ ] Override usage <10% of orders; no safety/ops incidents

Artifacts
- [ ] `outputs/daily_reports/*.parquet`
- [ ] `docs/pilot_report.md`

## Phase 10 — Scale & Continuous Improvement
Build
- [ ] Monthly re-optimization; add dynamic delivery fee by zone/time
- [ ] Two-runner extension; predictive gating using tee-sheet/weather 30–60 min ahead

Exit (all must be true)
- [ ] With dynamic fees: maintain SLA while recapturing ≥50% of far-zone profit lost to gating
- [ ] Two-runner sim demonstrates staffing break-even curve with diminishing returns

Artifacts
- [ ] `docs/scaling_playbook.md`

## Global Engineering Standards (use throughout)
- [ ] Version everything: policy params, seeds, code hash, travel-time matrix version
- [ ] Export every sim run via `golfsim/io/results.py` with a `run_id` (JSON + CSV); Parquet/SQLite optional for analytics
- [ ] Common random numbers for A/B comparisons; report 95% CIs
- [ ] Non-breaking edits only; keep new logic behind config flags

## Tactical Rules (ship early while optimizing)
- [ ] ETA cap: block if predicted ETA > T_max
- [ ] Queue-aware radius: if queue ≥ q_high ⇒ only accept within R_min
- [ ] Position-aware gating: temporarily block holes opposite the runner beyond R_min
- [ ] Time-of-day tightening during peak waves

## Decisions Needed Before Phase 5
- [ ] Optimize profit or gross revenue?
- [ ] SLA focus: mean or p95 (and target values)?
- [ ] Cancel and late-minute penalties ($)?
- [ ] Max acceptable consecutive block time per hole (fairness)?
- [ ] Allow dynamic fees by zone/time?

---

This plan is additive and test-driven at each phase to avoid regressions and preserve the current working simulation. All new features should default to off and be toggled via typed configuration (`golfsim/config/models.SimulationConfig`). Prefer using library APIs over scripts; CLIs under `scripts/` are thin wrappers aligned with the refactored layout and names.
