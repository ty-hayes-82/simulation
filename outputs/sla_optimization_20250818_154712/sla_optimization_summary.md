# SLA Optimization Summary

**Generated:** 2025-08-18 16:05:07
**Target SLA:** 95.0%
**Tee Scenario:** busy_weekend
**Runner Count:** 1

## Results by Blocking Scenario

| Scenario | SLA % | Failed % | Avg Wait | Avg Order | P90 Order | Revenue | Status |
|----------|-------|---------|----------|-----------|-----------|---------|--------|
| block_to_hole6 | 55.0% | 16.7% | 22.7 min | 27.8 min | 45.0 min | $23.81 | ✗ Below Target |
| <small><i>Block holes 1-6</i></small> | | | | | | |
| block_holes_1_5_and_10_12 | 52.2% | 8.0% | 25.2 min | 33.4 min | 57.3 min | $25.00 | ✗ Below Target |
| <small><i>Block holes 1-5 AND 10-12</i></small> | | | | | | |
| full_course | 47.8% | 17.9% | 27.2 min | 35.2 min | 58.5 min | $25.00 | ✗ Below Target |
| <small><i>No blocking (full course)</i></small> | | | | | | |
| block_to_hole3 | 47.1% | 46.9% | 23.0 min | 29.9 min | 45.8 min | $17.00 | ✗ Below Target |
| <small><i>Block holes 1-3</i></small> | | | | | | |
| block_holes_0_5 | 36.4% | 26.7% | 27.3 min | 35.8 min | 55.2 min | $22.00 | ✗ Below Target |
| <small><i>Block holes 1-5</i></small> | | | | | | |
| block_holes_10_12 | 10.0% | 41.2% | 35.5 min | 46.4 min | 60.8 min | $20.83 | ✗ Below Target |
| <small><i>Block holes 10-12</i></small> | | | | | | |

## Summary

- **Total scenarios tested:** 6
- **Scenarios meeting 95.0% SLA:** 0
- **Best scenario:** block_to_hole6 (55.0% SLA)

## Recommendations

**No scenarios achieved 95.0% SLA.**
Best achievable: 55.0% with block_to_hole6