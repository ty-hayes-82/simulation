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
WHITE_FILL = "#FFFFFF"
GREEN_DELIVERED_SLA = "#00b894"  # remain green if delivered within 30 minutes
WHITE_BORDER = "#FFFFFF"
YELLOW_FILL = "#FFFF00"
RED_FILL = "#FF0000"


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
            group_id_from_event = ev.get("group_id")
        except Exception:
            continue
        
        if action == "delivery_complete" and order_id is not None:
            # Find the group_id for this order
            gid_to_update = None
            if group_id_from_event is not None:
                gid_to_update = int(group_id_from_event)
            else:
                # Fallback: scan groups if group_id is not on the event
                for gid_scan, orders in by_group.items():
                    if str(order_id) in orders:
                        gid_to_update = gid_scan
                        break
            
            if gid_to_update is not None and gid_to_update in by_group:
                order_state = by_group[gid_to_update].get(str(order_id))
                if order_state:
                    # First delivered event wins
                    if order_state.delivered_ts is None:
                        order_state.delivered_ts = ts
                    else:
                        order_state.delivered_ts = min(order_state.delivered_ts, ts)

    # Convert inner dicts to lists sorted by placed_ts
    finalized: Dict[int, List[OrderState]] = {}
    for gid, orders in by_group.items():
        finalized[gid] = sorted(list(orders.values()), key=lambda o: o.placed_ts)
    return finalized


def _color_for_wait_time(seconds_since_order: int) -> Dict[str, str]:
    minutes = max(0, seconds_since_order // 60)

    if minutes >= 30:
        return {"fill": RED_FILL, "border": RED_FILL}

    return {"fill": YELLOW_FILL, "border": YELLOW_FILL}


def annotate_golfer_colors(
    points_by_id: Dict[str, List[Dict[str, Any]]],
    events: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """Annotate golfer GPS points with a 'color' property based on order/delivery timing.

    Rules:
    - Default (no active order): WHITE circle.
    - Order placed and waiting for delivery:
      - YELLOW circle if waiting < 30 minutes.
      - RED circle if waiting >= 30 minutes.
    - Order delivered:
      - GREEN circle if delivered within 30 minutes of order placement.
        (Remains green until the next order is placed).
      - WHITE circle if delivered after 30 minutes.
    - Border color always matches fill color.
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
            enhanced[entity_id] = [
                {**p, "fill_color": WHITE_FILL, "border_color": WHITE_BORDER, "type": p.get("type", "golfer")}
                for p in points
            ]
            continue

        orders_for_group = orders_index.get(gid, [])
        if not orders_for_group:
            # Never ordered
            enhanced[entity_id] = [
                {**p, "fill_color": WHITE_FILL, "border_color": WHITE_BORDER, "type": p.get("type", "golfer")}
                for p in points
            ]
            continue

        # Build a simple list of (placed_ts, delivered_ts) in time order
        order_pairs: List[Tuple[int, Optional[int]]] = [
            (o.placed_ts, o.delivered_ts) for o in orders_for_group
        ]

        annotated_points: List[Dict[str, Any]] = []

        for p in sorted(points, key=lambda x: int(x.get("timestamp", 0))):
            ts = int(p.get("timestamp", 0))

            # Determine the latest order placed at or before ts
            active_idx = -1
            for i, (placed_ts, _del_ts) in enumerate(order_pairs):
                if ts >= placed_ts:
                    active_idx = i
                else:
                    break
            
            colors: Dict[str, str]

            if active_idx == -1:
                # Before the first order
                colors = {"fill": WHITE_FILL, "border": WHITE_BORDER}
            else:
                placed_ts, delivered_ts = order_pairs[active_idx]

                if delivered_ts is not None and ts >= delivered_ts:
                    # Delivered. Determine SLA and coloring after delivery until next order
                    met_sla = (delivered_ts - placed_ts) <= THIRTY_MIN_S
                    if met_sla:
                        colors = {"fill": GREEN_DELIVERED_SLA, "border": GREEN_DELIVERED_SLA}
                    else:
                        # Delivered but missed SLA: back to default
                        colors = {"fill": WHITE_FILL, "border": WHITE_BORDER}
                else:
                    # Waiting for delivery (or before delivery timestamp)
                    secs_since = max(0, ts - placed_ts)
                    colors = _color_for_wait_time(secs_since)
            
            # Remove old color key if it exists
            p.pop("color", None)

            annotated_points.append({**p, "fill_color": colors["fill"], "border_color": colors["border"], "type": p.get("type", "golfer")})

        enhanced[entity_id] = annotated_points

    return enhanced


