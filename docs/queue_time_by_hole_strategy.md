### Delivery Queue Time Attribution by Hole

#### Purpose
- **Goal**: Attribute added queue wait time to the delivery hole that caused it.
- **Example**: If a runner departs to Hole 5 and the outbound drive is 12 minutes, and during that time later orders are waiting 8 minutes before they can start, attribute those 8 minutes to Hole 5.

#### Definitions
- **Queue wait (per order)**: `departure_time_s - order_time_s` from `order_timing_logs.csv`.
- **Delivery window (per delivery)**: The runner’s outbound driving segment for that order: `[delivery_start, order_delivered]`.
  - From data: `delivery_start = departure_time_s` (order_timing logs), `order_delivered = delivery_timestamp_s` (order_timing logs).
- **Delivery hole**: `hole_num` recorded in `delivery_stats` for the delivered order.

#### Data sources in this repo
- **Per-run order timing**: `order_timing_logs.csv` with `order_id`, `order_time_s`, `departure_time_s`, `delivery_timestamp_s`, `return_timestamp_s`.
- **Per-delivery stats**: `delivery_stats` entries with `order_id`, `hole_num`, `delivery_time_s`, `return_time_s`, `runner_id`, `delivered_at_time_s`.
- **Runner action segments (optional)**: `runner_action_log.csv` with contiguous segments including `delivery_drive` and `return_drive`. This can replace reconstructing delivery windows.

#### Scope of attribution
- **Primary (recommended)**: Attribute only during outbound driving (delivery_drive). This aligns with the example and keeps causality clear.
- **Optional variants**:
  - Include `return_drive` to capture unavailability while returning. Attribute those minutes to the same hole.
  - Include prior-order `prep` time at clubhouse, attributing that time to the prior order’s hole. Use only if you want a full unavailability budget.

#### Multi-runner policy
- When multiple runners are active, queue forms only when all runners are busy.
- **Attribution rule**: Split the queue-wait being accrued at time t evenly across all concurrent `delivery_drive` segments at t. This fairly assigns responsibility among simultaneous trips.

#### Algorithm (outbound-only, single or multi-runner)
1. **Build wait intervals (orders)**
   - For each order i: `Wait_i = [order_time_s_i, departure_time_s_i)` if `departure_time_s_i` exists.
   - Ignore orders with no departure (failed) or handle separately if desired.
2. **Build delivery segments (trips)**
   - For each delivered order j: `Trip_j = [departure_time_s_j, delivery_timestamp_s_j)` and `Hole_j = hole_num_j`.
   - Optionally, instead of (2), read `runner_action_log.csv` and use `delivery_drive` segments with their `runner_id`; join to `delivery_stats` by nearest-in-time `order_id` to get `hole_num`.
3. **Attribute overlap minutes**
   - For any time t, define `Q(t)` = number of orders currently waiting: count of i where `t ∈ Wait_i`.
   - Define `A(t)` = set of active outbound trips at t.
   - If `Q(t) == 0` or `A(t) == ∅`, attribute 0 at t.
   - Else, each active trip j in `A(t)` receives `Q(t) / |A(t)|` queue-minutes per minute at t, credited to `Hole_j`.
4. **Aggregate by hole**
   - `queue_minutes_by_hole[h] = ∑ over trips j with Hole_j = h ∫ attribution_j(t) dt`.

This ensures the total attributed minutes equals the total queue wait minutes across all orders within the chosen scope.

#### Minimal implementation sketch (Python)
```python
# Inputs: order_timing_logs (list of dicts), delivery_stats (list of dicts)
# Output: dict hole -> queue_minutes (float)

# 1) Wait intervals per order
waits = []
for o in order_timing_logs:
    if o.get("departure_time_s") is None:
        continue  # skip failed or not started
    start = int(o["order_time_s"])
    end = int(o["departure_time_s"])  # exclusive
    if end > start:
        waits.append((start, end))

# 2) Delivery (outbound) segments with hole
hole_by_order = {str(d["order_id"]): int(d["hole_num"]) for d in delivery_stats if d.get("order_id")}
trips = []
for o in order_timing_logs:
    oid = str(o.get("order_id"))
    if o.get("departure_time_s") is None or o.get("delivery_timestamp_s") is None:
        continue
    h = hole_by_order.get(oid)
    if h is None:
        continue
    s = int(o["departure_time_s"])  # outbound start
    e = int(o["delivery_timestamp_s"])  # delivery timestamp
    if e > s:
        trips.append((s, e, h))

# 3) Line-sweep over all boundary timestamps
bounds = sorted({t for a,b in waits for t in (a,b)} | {t for s,e,_ in trips for t in (s,e)})
queue_by_hole = {}
for t0, t1 in zip(bounds, bounds[1:]):
    dt_min = max(0, (t1 - t0) / 60.0)
    if dt_min == 0: 
        continue
    # active waits and trips
    q = sum(1 for a,b in waits if a < t1 and b > t0)
    active_trips = [(s,e,h) for s,e,h in trips if s < t1 and e > t0]
    if q <= 0 or not active_trips:
        continue
    share = float(q) / float(len(active_trips))
    for _,_,h in active_trips:
        queue_by_hole[h] = queue_by_hole.get(h, 0.0) + share * dt_min

# queue_by_hole now maps hole -> attributed queue minutes
```

#### Validation checks
- **Mass balance**: `sum(queue_by_hole.values())` should equal the total queue minutes across all orders, restricted to periods where at least one outbound trip is active.
- **No negative intervals**: Ensure all `[start, end)` have `end > start`.
- **Time units**: Keep everything in seconds internally; convert to minutes only for reporting.

#### Reporting
- Save per-run as `queue_attribution_by_hole.json` alongside other outputs.
- Optionally include a small markdown/CSV summary with columns: `hole`, `queue_minutes`, `percent_of_total`.
- For multi-run batches, aggregate across runs (sum minutes by hole, then normalize to percent).

#### Extensions (optional)
- Include `return_drive` segments by extending trips to `[departure_time_s, return_timestamp_s)`.
- Attribute clubhouse `prep` time to the prior order’s hole by inserting prep segments between `prep_start` and `prep_complete` and treating them like trips.
- Weight attribution by trip remaining time instead of equal split when multiple trips overlap.

#### Notes
- The repo already writes `order_timing_logs.csv` and `delivery_stats`; no engine changes are required to compute this attribution.
- If you prefer, `runner_action_log.csv` can provide `delivery_drive` segments directly to avoid reconstructing outbound windows.
