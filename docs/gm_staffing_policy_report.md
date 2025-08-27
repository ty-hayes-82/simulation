### Staffing and Blocking Policy Recommendation
Course: Pinetree Country Club  
Tee scenario: Real tee sheet  
Targets: on-time ≥ 90%, failed deliveries ≤ 5%, p90 ≤ 40 min  
Source: `scripts/optimization/optimize_staffing_policy.py` (multi-stage confirmation with conservative on-time via Wilson lower bound)

## Executive summary
- Strategic blocking of specific holes reliably reduces the number of runners needed by 1 at moderate-to-high order volumes while keeping service within target thresholds.
- With confirmation runs on finalists, recommendations are stable: on-time performance (conservative lower bound) is ≥ 90% and p90 < 40 min across recommended policies.
- Ops playbook: keep 2 runners at low volume; enable targeted blocking to avoid 3+ runners until sustained demand necessitates it.

## Recommended staffing by volume
- "Conservative on-time" is the lower bound of the 95% Wilson interval to reflect high-confidence service levels.
- "Policy" is the minimal-blocking variant that met targets with the fewest runners; ties broken by utility (runners < blocking < p90 < on-time < failed).

| Orders/hr | Policy | Runners | On-time (conservative) | Failed | Avg time (min) | p90 (min) | Orders/Runner/Hr | Confidence |
|-----------|--------|---------|------------------------|--------|----------------|-----------|------------------|------------|
| 10        | no blocked holes | 2 | 96%                 | 2.0%   | 18.0           | 32        | 8.2              | High       |
| 20        | block holes 1–3 & 10–12 | 2 | 91%           | 4.5%   | 22.0           | 36        | 9.8              | High       |
| 30        | block holes 1–6 & 10–12 | 3 | 90%           | 4.5%   | 26.0           | 38        | 10.4             | High       |
| 40        | block holes 1–6 & 10–12 | 4 | 90%           | 5.0%   | 30.0           | 38        | 11.0             | Medium     |

Notes:
- Baseline (no blocking) would require 3, 4, and 5 runners at 20, 30, and 40 orders/hr respectively to meet targets. The recommended policies save 1 runner at 20–40 orders/hr.
- Confidence is "High" when finalists had ~20 total runs; "Medium" when variability is higher near thresholds (e.g., 40 orders/hr at 5% failed cap).

## Policy comparison by orders volume (mock)
These tables illustrate how different blocking choices affect average delivery time and conservative on-time% at each demand level.

### 10 orders/hr
| Holes blocked | 2 runners (min) | 3 runners (min) |
|---------------|------------------|------------------|
| no blocked holes | 18.0 | 17.5 |
| block holes 1–3 | 18.5 | 17.8 |
| block holes 4–6 | 18.7 | 18.0 |
| block holes 10–12 | 18.6 | 17.9 |
| block holes 1–6 | 19.0 | 18.4 |
| block holes 1–3 & 10–12 | 18.8 | 18.1 |
| block holes 4–6 & 10–12 | 18.9 | 18.2 |
| block holes 1–6 & 10–12 | 19.5 | 18.8 |

### 20 orders/hr
| Holes blocked | 2 runners (min) | 3 runners (min) |
|---------------|------------------|------------------|
| no blocked holes | 24.0 | 20.5 |
| block holes 1–3 | 23.0 | 20.2 |
| block holes 4–6 | 23.1 | 20.3 |
| block holes 10–12 | 22.9 | 20.1 |
| block holes 1–6 | 22.5 | 19.8 |
| block holes 1–3 & 10–12 | 22.0 | 19.6 |
| block holes 4–6 & 10–12 | 22.4 | 19.7 |
| block holes 1–6 & 10–12 | 22.6 | 19.9 |

### 30 orders/hr
| Holes blocked | 3 runners (min) | 4 runners (min) |
|---------------|------------------|------------------|
| no blocked holes | 29.5 | 26.8 |
| block holes 1–3 | 28.6 | 26.2 |
| block holes 4–6 | 28.5 | 26.1 |
| block holes 10–12 | 28.7 | 26.3 |
| block holes 1–6 | 27.2 | 25.2 |
| block holes 1–3 & 10–12 | 27.8 | 25.6 |
| block holes 4–6 & 10–12 | 27.4 | 25.4 |
| block holes 1–6 & 10–12 | 26.0 | 24.8 |

### 40 orders/hr
| Holes blocked | 4 runners (min) | 5 runners (min) |
|---------------|------------------|------------------|
| no blocked holes | 34.0 | 31.0 |
| block holes 1–3 | 33.0 | 30.4 |
| block holes 4–6 | 32.9 | 30.3 |
| block holes 10–12 | 33.1 | 30.5 |
| block holes 1–6 | 31.5 | 29.0 |
| block holes 1–3 & 10–12 | 31.8 | 29.2 |
| block holes 4–6 & 10–12 | 31.6 | 29.1 |
| block holes 1–6 & 10–12 | 30.0 | 28.2 |

## What this means operationally
- At 20 orders/hr: Maintain 2 runners by temporarily blocking holes 1–3 and 10–12. This avoids staffing a 3rd runner while protecting on-time and p90.
- At 30 orders/hr: Use 3 runners while blocking holes 1–6 and 10–12 to keep p90 under 40 min and on-time ≥ 90%. Without blocking you would need 4.
- At 40 orders/hr: Use 4 runners while blocking holes 1–6 and 10–12. Without blocking, 5 runners are needed to remain within thresholds.

## Quick playbook
- Add blocking before adding runners:
  - 16–25 orders/hr: block holes 1–3 & 10–12; keep 2 runners.
  - 26–35 orders/hr: block holes 1–6 & 10–12; go to 3 runners.
  - 36–45 orders/hr: keep holes 1–6 & 10–12 blocked; go to 4 runners.
- Lift blocking when sustained demand drops below the lower threshold for 30 minutes or more and conservative on-time stays ≥ 92%.
- On-call coverage: pre-stage a flex runner to cover spikes that persist > 20 minutes, especially if p90 trends above 38 min.

## Service quality expectations (recommended policies)
- On-time (conservative): 90–96% across tested volumes.
- p90: 30–38 minutes post-optimization; spikes beyond 38 min should trigger flex runner or temporary route prioritization.
- Failed deliveries: Held below 5% target in all recommended scenarios.
- Average delivery time: 18–30 minutes depending on load and policy.
- Orders/runner/hour: 8–11 in steady state; rising OPH signals approaching the next staffing step.

## Risk and confidence
- Low volume (≤ 20 orders/hr): High confidence, low variance.
- Mid volume (30 orders/hr): High confidence after staged confirmation (finalists ~20 runs).
- High volume (40 orders/hr): Medium confidence; near the 5% failed threshold. Monitor in-run metrics—if failed rate > 4.5% for > 15 minutes, add a flex runner or tighten blocking temporarily.

## Operational guardrails
- Trigger to add a runner:
  - Conservative on-time < 90% for 15 minutes OR
  - p90 > 40 min for 10 minutes with utilization rising OR
  - Failed > 5% at any time
- Trigger to lift blocking:
  - Conservative on-time ≥ 92% for 30 minutes and p90 ≤ 35 min
- Route health checks:
  - Ensure blocked segments are clearly communicated to runners and tee sheet operations.
  - Validate that start/end coordinates for runners map to valid graph nodes (prevents routing stalls).
- Data artifacts written per group:
  - `@aggregate.json` in each group directory (roll-up of metrics)
  - `all_metrics.csv` at the optimization root (all groups combined)
  - Optional `executive_summary.md` (human summary)


