### Executive Summary: F&B Delivery Optimization at Keswick Hall

**To:** General Manager, Keswick Hall
**From:** Operations Analysis
**Date:** October 26, 2023
**Subject:** Staffing & Delivery Zone Recommendations to Meet Service Targets

### Summary

Our analysis shows that we can meet our on-time delivery goals (`≥90%`) by strategically adjusting staffing and delivery zones based on daily order volume. At low volumes, one runner is sufficient. As demand surpasses 5 orders per hour, we must either add a second runner or restrict delivery to core holes to prevent service delays. For peak periods, a combination of increased staff and restricted delivery zones is the most efficient way to guarantee performance without overstaffing.

### Optimized Staffing Plan

| Orders per Hour (Approx.) | Baseline Runners (Full Course) | Recommended Runners (Optimized) | Recommended Strategy |
| :--- | :--- | :--- | :--- |
| **< 5** (1-25 Daily) | 1 | **1** | None (Full Course) |
| **5–8** (26-40 Daily) | 2 | **2** | None (Full Course) |
| **8–10** (41-50 Daily) | 3 | **2** | Block `front_back` (Holes 1-3 & 10-12) |
| **> 10** (50+ Daily) | 3+ | **3** | Block `front_back` (Holes 1-3 & 10-12) |

### Quick Guide for On-Course Operations

*   **Standard Day (< 8 Orders/Hr):** Staff two runners to provide timely, full-course coverage. This maintains an average delivery time under 30 minutes.
*   **Busy Day (8–10 Orders/Hr):** Instead of adding a third runner, maintain two runners and enable the `front_back` blocking strategy. This focuses service on holes 4-9, keeping delivery times low and utilization high.
*   **Peak Demand (> 10 Orders/Hr):** Add a third runner *and* keep the `front_back` blocking strategy active to prevent system failure and ensure over 90% of orders arrive on time.

### Confidence in Recommendations

*   **Low Volume:** High confidence in our ability to meet targets with current staffing.
*   **Medium Volume:** Medium confidence; the optimal trade-off between adding staff and blocking zones can vary with pace of play.
*   **High Volume:** High confidence that the recommended hybrid strategy is necessary to avoid significant service degradation.

_Source: Gemini_
