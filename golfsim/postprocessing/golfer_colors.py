from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from golfsim.logging import get_logger


logger = get_logger(__name__)


@dataclass
class OrderState:
    order_id: str
    placed_ts: int
    delivered_ts: Optional[int]


# Color palette
BLUE_NO_ORDER = "#007cbf"  # default golfer blue
GREEN_DELIVERED_SLA = "#00b894"  # remain green if delivered within 30 minutes

# 6 shades escalating to red for waiting since order placed (last one is red)
WAITING_SHADES: List[Tuple[int, str]] = [
    (0, "#ffe6cc"),    # 0-10 min
    (10, "#ffcc99"),   # 10-20 min
    (20, "#ffb366"),   # 20-30 min
    (30, "#ff9933"),   # 30-40 min
    (40, "#ff6600"),   # 40-50 min
    (50, "#ff0000"),   # 50-60+ min (approaching red -> red)
]

SIXTY_MIN_S = 60 * 60
THIRTY_MIN_S = 30 * 60


def _parse_group_id_from_entity(entity_id: str) -> Optional[int]:
    try:
        if not entity_id:
            return None
        eid = str(entity_id).lower()
        if eid.startswith("golfer_group_"):
            return int(eid.split("golfer_group_")[-1])
        return None
    except Exception:
        return None


def _build_orders_index(events: List[Dict[str, Any]]) -> Dict[int, List[OrderState]]:
    by_group: Dict[int, Dict[str, OrderState]] = {}

    for ev in events or []:
        try:
            action = str(ev.get("action", "")).lower()
            ts = int(ev.get("timestamp_s", 0))
            order_id = ev.get("order_id")
        except Exception:
            continue

        # Order placed carries group_id
        if action == "order_placed":
            try:
                gid = int(ev.get("group_id"))
            except Exception:
                continue
            if order_id is None:
                continue
            group_orders = by_group.setdefault(gid, {})
            if str(order_id) not in group_orders:
                group_orders[str(order_id)] = OrderState(order_id=str(order_id), placed_ts=ts, delivered_ts=None)
            else:
                # Keep earliest placed_ts
                group_orders[str(order_id)].placed_ts = min(group_orders[str(order_id)].placed_ts, ts)

    # Attach delivered timestamps by matching order_id
    for ev in events or []:
        try:
            action = str(ev.get("action", "")).lower()
            ts = int(ev.get("timestamp_s", 0))
            order_id = ev.get("order_id")
        except Exception:
            continue
        if action == "delivery_complete" and order_id is not None:
            # We don't have group_id on this event; scan groups that know this order_id
            for gid, orders in by_group.items():
                if str(order_id) in orders:
                    # First delivered event wins
                    if orders[str(order_id)].delivered_ts is None:
                        orders[str(order_id)].delivered_ts = ts
                    else:
                        orders[str(order_id)].delivered_ts = min(orders[str(order_id)].delivered_ts or ts, ts)

    # Convert inner dicts to lists sorted by placed_ts
    finalized: Dict[int, List[OrderState]] = {}
    for gid, orders in by_group.items():
        finalized[gid] = sorted(list(orders.values()), key=lambda o: o.placed_ts)
    return finalized


def _color_for_wait_time(seconds_since_order: int) -> str:
    # Once at or past 60 minutes, hard red
    if seconds_since_order >= SIXTY_MIN_S:
        return "#ff0000"
    minutes = max(0, seconds_since_order // 60)
    shade = WAITING_SHADES[0][1]
    for threshold_min, color in WAITING_SHADES:
        if minutes >= threshold_min:
            shade = color
        else:
            break
    return shade


def annotate_golfer_colors(
    points_by_id: Dict[str, List[Dict[str, Any]]],
    events: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Annotate golfer GPS points with a 'color' property based on order/delivery timing.

    Rules:
    - No order ever: BLUE throughout.
    - After an order is placed and until delivery:
      escalate through 6 shades ending in RED at 60 min.
      Once 60 min is reached without delivery, remain RED for the rest of the round.
    - If an order is delivered within 30 min, remain GREEN from delivery time
      until end of round or until next order is placed.
    - Between orders (no active waiting), revert to BLUE unless red lock is active.
    """
    orders_index = _build_orders_index(events)

    enhanced: Dict[str, List[Dict[str, Any]]] = {}

    for entity_id, points in points_by_id.items():
        if not points:
            enhanced[entity_id] = points
            continue

        gid = _parse_group_id_from_entity(entity_id)
        is_golfer_stream = entity_id.lower().startswith("golfer_group_")

        if not is_golfer_stream or gid is None:
            # Non-golfer or unrecognized: pass through
            enhanced[entity_id] = points
            continue

        orders_for_group = orders_index.get(gid, [])
        if not orders_for_group:
            # Never ordered
            enhanced[entity_id] = [
                {**p, "color": p.get("color") or BLUE_NO_ORDER, "type": p.get("type", "golfer")}
                for p in points
            ]
            continue

        # Precompute a timeline of state segments
        red_locked = False
        current_green_until_next_order = False
        next_order_iter_idx = 0

        # Build a simple list of (placed_ts, delivered_ts) in time order
        order_pairs: List[Tuple[int, Optional[int]]] = [
            (o.placed_ts, o.delivered_ts) for o in orders_for_group
        ]

        annotated_points: List[Dict[str, Any]] = []

        for p in sorted(points, key=lambda x: int(x.get("timestamp", 0))):
            ts = int(p.get("timestamp", 0))

            # Advance current order window for this timestamp
            # Determine the latest order placed at or before ts
            active_idx = -1
            for i, (placed_ts, _del_ts) in enumerate(order_pairs):
                if ts >= placed_ts:
                    active_idx = i
                else:
                    break

            color: str

            if red_locked:
                color = "#ff0000"
            elif active_idx == -1:
                # Before the first order
                color = BLUE_NO_ORDER
            else:
                placed_ts, delivered_ts = order_pairs[active_idx]

                # Check if there's a later order coming; if so, and ts is after that next placed,
                # the active_idx loop would have advanced already, so we are truly within this or later order.

                if delivered_ts is not None and ts >= delivered_ts:
                    # Delivered. Determine SLA and coloring after delivery until next order
                    met_sla = (delivered_ts - placed_ts) <= THIRTY_MIN_S
                    if met_sla:
                        color = GREEN_DELIVERED_SLA
                        current_green_until_next_order = True
                    else:
                        # Delivered but missed SLA: between orders resume BLUE
                        # unless already in green-until-next-order mode (shouldn't be) or red lock
                        if current_green_until_next_order:
                            color = GREEN_DELIVERED_SLA
                        else:
                            color = BLUE_NO_ORDER
                else:
                    # Waiting for delivery (or before delivery timestamp)
                    secs_since = max(0, ts - placed_ts)
                    color = _color_for_wait_time(secs_since)
                    if secs_since >= SIXTY_MIN_S:
                        red_locked = True

                # Reset green hold when a new order is placed in the future
                if current_green_until_next_order:
                    # If a newer order has been placed after this active one and before ts, loop would move active_idx.
                    # We clear the flag when we detect that ts is before the next order's placed time but a new order exists later.
                    # More simply: once we move past the placed time of the next order, active_idx changes and green flag can be cleared.
                    # Implement by checking if there exists an order with placed_ts > placed_ts and ts < that placed_ts.
                    for j in range(active_idx + 1, len(order_pairs)):
                        next_placed, _ = order_pairs[j]
                        if ts < next_placed:
                            # still before next order; keep green
                            break
                        else:
                            # moved past next order placement, clear hold
                            current_green_until_next_order = False
                            break

            annotated_points.append({**p, "color": p.get("color") or color, "type": p.get("type", "golfer")})

        enhanced[entity_id] = annotated_points

    return enhanced


