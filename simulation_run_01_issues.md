<!--
**Fix Status Tracker**

- [x] **Order Count Mismatch:** Fixed and verified.
- [x] **Failed Order Count Discrepancy:** Fixed and verified.
- [x] **Inconsistent On-Time Percentage:** Fixed and verified.
- [x] **Revenue Discrepancy:** Fixed and verified.
- [x] **Runner Utilization Mismatch:** Fixed and verified.

**Instructions:**
1. Run the simulation using the command below to reproduce the issues.
2. For each issue, follow the "Verification and Validation" steps to confirm the discrepancy.
3. Implement the "Fix Strategy" to resolve the issue.
4. After implementing a fix, re-run the simulation and verify that the issue is resolved.
5. Update the status tracker above.
6. Repeat until all issues are resolved and all items are checked.
-->

# Simulation `run_01` Issues

To reproduce this specific simulation run, you can use the following command:

```bash
python scripts/optimization/optimize_staffing_policy_two_pass.py --course-dir courses/pinetree_country_club --tee-scenario real_tee_sheet --orders-levels 30 --runner-range 1 --concurrency 1 --first-pass-runs 1 --second-pass-runs 0 --auto-report --blocking-variant none
```

This document outlines the inconsistencies and discrepancies found in the simulation data for `run_01`.

## 1. Order Count Mismatch

There is a discrepancy in the total number of orders accounted for in the summary files versus the detailed logs.

- **`delivery_runner_metrics_run_01.json`** and **`simulation_metrics.json`** report:
  - **Total Orders**: 30
  - **Successful Deliveries**: 16
  - **Failed Deliveries**: 12
- The sum of successful and failed deliveries is **28**, leaving two orders unaccounted for.

**`results.json`** reveals that orders **`029`** and **`030`** have a `pending` status and were not completed before the simulation ended.

---

### Verification and Validation Strategy

1.  **Inspect `results.json`**: Manually inspect the `orders` section of `results.json` for `run_01` to confirm that orders `029` and `030` have a `status` of `pending`.
2.  **Review Simulation End Time**: Check the simulation's `end_time` against the `order_time` of the pending orders. This will likely confirm that the simulation terminated before these orders could be fulfilled.
3.  **Trace Metric Generation**: Identify the code responsible for generating `delivery_runner_metrics.json` and `simulation_metrics.json`. This is likely in the `golfsim/analysis` or `golfsim/io` modules. Confirm that these scripts do not account for a `pending` status when summarizing order counts.

### Fix Strategy

1.  **Update Metrics Models**: Modify the data models or dictionaries used for metrics to include a `pending_deliveries` count.
2.  **Adjust Calculation Logic**: In the metric generation scripts, adjust the logic to query for `pending` orders and include this count in the final JSON outputs.
3.  **Ensure Consistency**: Ensure that `total_orders` is consistently calculated as the sum of `successful_deliveries`, `failed_deliveries`, and `pending_deliveries`.

---

## 2. Failed Order Count Discrepancy

The number of failed orders is inconsistent between the event log and the final metrics.

- **`simulation_metrics.json`** reports **12 failed** deliveries.
- **`report/orders_events.csv`** implies **14 failed** deliveries (orders delivered to hole `None`).

The discrepancy is due to the `orders_events.csv` file categorizing both `failed` and `pending` orders as being delivered to `None`.

---

### Verification and Validation Strategy

1.  **Examine `orders_events.csv`**: Open `report/orders_events.csv` and filter for orders delivered to hole `None`. Cross-reference the `order_id`s with `results.json` to confirm that this set includes both `failed` and `pending` orders.
2.  **Code Review**: Locate the script that generates `orders_events.csv` (likely in `golfsim/io/reporting.py` or a similar reporting script). Review the logic to see how it handles different order statuses when writing the `delivered_hole` column.

### Fix Strategy

1.  **Differentiate Statuses in Report**: Modify the CSV generation logic to handle different order statuses explicitly.
    - For `pending` orders, the `delivered_hole` could be `PENDING` or an empty string, instead of `None`.
    - Add a `status` column to `orders_events.csv` to make the state of each order explicit.
2.  **Update Downstream dependencies**: If any other process consumes `orders_events.csv`, ensure it is updated to handle the new format.

---

## 3. Inconsistent On-Time Percentage

The on-time delivery rate is calculated differently across the metric files, leading to conflicting values.

- **`delivery_runner_metrics_run_01.json`**: `on_time_rate` = **37.5%**
- **`simulation_metrics.json`**: `onTimePercentage` = **20.0%**

The calculation methods appear to be:
- **37.5%**: `(successful - late) / successful` deliveries (6 / 16).
- **20.0%**: `(successful - late) / total` orders (6 / 30).

The definition of a "late" order and the correct calculation method needs to be clarified.

---

### Verification and Validation Strategy

1.  **Identify Calculation Points**: Find the code that calculates `on_time_rate` and `onTimePercentage`. This will involve searching for these keys in the codebase.
2.  **Confirm Formulas**: Verify that the code implements the formulas exactly as hypothesized above.
3.  **Consult Business Logic**: Determine the correct, authoritative definition of "On-Time Percentage". This should be based on successful deliveries, not total orders, as you cannot be "on-time" for an order that wasn't delivered.

### Fix Strategy

1.  **Standardize Calculation**: Update the calculation for `onTimePercentage` in `simulation_metrics.json` to be based on the number of successful deliveries: `(successful_on_time_deliveries) / successful_deliveries`.
2.  **Unify Field Names**: For consistency, consider renaming `on_time_rate` and `onTimePercentage` to a single, shared name like `on_time_delivery_rate` across all reports.
3.  **Clarify "Late" Definition**: Ensure the logic for determining if an order is "late" is consistent and well-documented in the code.

---

## 4. Revenue Discrepancy

The total revenue reported in the two main summary files does not match.

- **`delivery_runner_metrics_run_01.json`**: `total_revenue` = **480.0**
- **`simulation_metrics.json`**: `revenue` = **540.0**

The source of this discrepancy could not be determined from the available data.

---

### Verification and Validation Strategy

1.  **Trace Revenue Calculation**: Locate the code responsible for calculating `total_revenue` and `revenue`.
2.  **Identify Revenue Sources**: Determine what constitutes revenue. Is it based on all orders placed, or only successfully delivered orders?
3.  **Step-Through Debugging**: If necessary, use a debugger or add logging to trace the revenue calculation for a single simulation run, observing which orders contribute to the total in each report. The discrepancy might be that one includes revenue from failed/pending orders while the other doesn't. `540.0` is likely `30 orders * 18/order`, while `480.0` might be based on another logic.

### Fix Strategy

1.  **Define Revenue Standard**: Establish a clear rule for revenue calculation. Typically, revenue should only be recognized for **successfully completed deliveries**.
2.  **Unify Logic**: Refactor the code to use a single function for calculating revenue that is called by both reporting scripts.
3.  **Apply Consistently**: Ensure the standardized revenue logic is applied wherever revenue is reported.

---

## 5. Runner Utilization and Active Hours Mismatch

The runner utilization percentage and the runner's active hours are calculated differently, leading to inconsistent metrics.

- **`delivery_runner_metrics_run_01.json`** calculates metrics based on **7.15 active runner hours**.
- **`simulation_metrics.json`** uses a fixed **10-hour shift** (600 minutes) for its calculations.

The **`activity_log`** in `results.json` confirms the runner's active time was approximately 7.15 hours. The metrics should be standardized to use a consistent measure of the runner's work time.

---

### Verification and Validation Strategy

1.  **Review Activity Log**: Confirm the runner's total active time from the `activity_log` in `results.json` by summing the durations of all activities.
2.  **Code Review**: Find the code sections that calculate utilization for both reports. One will likely use a hardcoded shift duration (e.g., 10 hours * 60 minutes), while the other will dynamically calculate it from the simulation results.

### Fix Strategy

1.  **Standardize Time Basis**: Decide on the appropriate time basis for utilization metrics. For runner-specific performance, `active_hours` is more telling. For overall operational efficiency and cost analysis, `shift_hours` is relevant.
2.  **Clarify Metric Names**: If both metrics are valuable, they should be named more clearly to avoid confusion:
    - `runner_utilization_active`: Based on active hours.
    - `runner_utilization_shift`: Based on total shift hours.
3.  **Implement Consistently**: Update the reporting scripts to use the agreed-upon definitions and names. If only one metric is to be kept, refactor the code to remove the other.
