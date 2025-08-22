from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .delivery_service_base import DeliveryOrder

def simulate_golfer_orders(groups: List[Dict], order_probability_per_9_holes: float, rng_seed: Optional[int] = None, *, course_dir: Optional[str] = None) -> List[DeliveryOrder]:
    """Generate delivery orders on a per-group, per-9-holes basis.

    Semantics:
    - Each group has up to two independent chances to place an order: once on the front nine (holes 1–9)
      and once on the back nine (holes 10–18).
    - The probability for each nine is `order_probability_per_9_holes`.
    - Order times are aligned to a random hole within the corresponding nine using ~12 min/hole pacing.
    - Number of golfers in a group is ignored for order generation.
    
    Parameters:
    - rng_seed: Optional random seed for deterministic order generation (for exact replay)
    """
    import random
    
    # Seed the random number generator if provided
    if rng_seed is not None:
        random.seed(rng_seed)

    orders: List[DeliveryOrder] = []
    # Derive node-based pacing from holes_connected.geojson (1 min per node)
    try:
        from pathlib import Path
        import json as _json
        if course_dir:
            data = _json.loads((Path(course_dir) / "geojson" / "generated" / "holes_connected.geojson").read_text(encoding="utf-8"))
            total_nodes = len([f for f in (data.get("features") or []) if (f.get("geometry") or {}).get("type") == "Point"]) or 18 * 12
        else:
            total_nodes = 18 * 12
    except Exception:
        total_nodes = 18 * 12
    nodes_per_hole = max(1, int(round(float(total_nodes) / 18.0)))

    for group in groups:
        group_id = group["group_id"]
        tee_time_s = group["tee_time_s"]

        # Front nine (holes 1..9)
        if random.random() < order_probability_per_9_holes:
            hole_front = int(random.randint(1, 9))
            start_node = int(round((hole_front - 1) * nodes_per_hole))
            order_time_front_s = tee_time_s + start_node * 60
            orders.append(
                DeliveryOrder(
                    order_id=None,
                    golfer_group_id=group_id,
                    golfer_id=f"G{group_id}",
                    order_time_s=order_time_front_s,
                    hole_num=hole_front,
                )
            )

        # Back nine (holes 10..18)
        if random.random() < order_probability_per_9_holes:
            hole_back = int(random.randint(10, 18))
            start_node = int(round((hole_back - 1) * nodes_per_hole))
            order_time_back_s = tee_time_s + start_node * 60
            orders.append(
                DeliveryOrder(
                    order_id=None,
                    golfer_group_id=group_id,
                    golfer_id=f"G{group_id}",
                    order_time_s=order_time_back_s,
                    hole_num=hole_back,
                )
            )

    orders.sort(key=lambda x: x.order_time_s)
    for i, order in enumerate(orders, 1):
        order.order_id = f"{i:03d}"
    return orders
