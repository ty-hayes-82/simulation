"""
I/O and Reporting Module

Handles writing simulation outputs, logs, and metric reports.
"""

from __future__ import annotations
import csv
from pathlib import Path
from typing import Dict, List, Any, Optional
from golfsim.utils import seconds_to_clock_str

def build_simulation_id(output_root: Path, run_idx: int) -> str:
    """Create a compact simulation_id for a run directory."""
    try:
        return f"{output_root.name}_run_{run_idx:02d}"
    except Exception:
        return f"sim_run_{run_idx:02d}"

def events_from_activity_log(
    activity_log: List[Dict[str, Any]],
    simulation_id: str,
    default_entity_type: str,
    default_entity_id: str,
) -> List[Dict[str, Any]]:
    """Map service activity logs to event rows."""
    events: List[Dict[str, Any]] = []
    earliest_open_ts: Dict[str, int] = {}
    for entry in activity_log or []:
        try:
            ts_s = int(entry.get("timestamp_s", 0))
        except Exception:
            ts_s = 0
        runner_id = entry.get("runner_id")
        cart_id = entry.get("cart_id")
        entity_id = str(runner_id or cart_id or default_entity_id)
        if str(entry.get("activity_type", entry.get("event", ""))).lower() == "service_opened":
            if entity_id not in earliest_open_ts or ts_s < earliest_open_ts[entity_id]:
                earliest_open_ts[entity_id] = ts_s
    for entry in activity_log or []:
        ts_s = int(entry.get("timestamp_s", 0))
        time_str = entry.get("time_str") or seconds_to_clock_str(ts_s)
        runner_id = entry.get("runner_id")
        cart_id = entry.get("cart_id")
        entity_id = runner_id or cart_id or default_entity_id
        if cart_id:
            etype = "beverage_cart"
        elif runner_id:
            etype = "delivery_runner"
        else:
            etype = default_entity_type
        action_raw = str(entry.get("activity_type") or entry.get("event") or "activity")
        action = action_raw
        eid = str(entity_id)
        if action_raw == "service_closed" and eid in earliest_open_ts and ts_s < int(earliest_open_ts[eid]):
            action = "service_idle"
        events.append(
            {
                "simulation_id": simulation_id,
                "ID": entity_id,
                "timestamp": time_str,
                "timestamp_s": ts_s,
                "action": action,
                "node_id": entry.get("node_index"),
                "hole": entry.get("hole") or entry.get("hole_num"),
                "ttl_amt": entry.get("revenue"),
                "type": etype,
                "order_id": entry.get("order_id"),
                "runner_id": runner_id,
                "cart_id": cart_id,
                "group_id": entry.get("golfer_group_id") or entry.get("group_id"),
                "latitude": entry.get("latitude"),
                "longitude": entry.get("longitude"),
                "status": entry.get("status"),
                "details": entry.get("description"),
            }
        )
    return events

def events_from_groups_tee_off(groups: List[Dict[str, Any]], simulation_id: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for g in groups or []:
        tee_s = int(g.get("tee_time_s", 0))
        events.append(
            {
                "simulation_id": simulation_id,
                "ID": f"golf_group_{int(g.get('group_id', 0))}",
                "timestamp": seconds_to_clock_str(tee_s),
                "timestamp_s": tee_s,
                "action": "tee_off",
                "hole": 1,
                "type": "golfer_group",
                "group_id": int(g.get("group_id", 0)),
            }
        )
    return events

def events_from_orders_list(orders: List[Dict[str, Any]] | None, simulation_id: str) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for o in orders or []:
        ts_s = int(o.get("order_time_s", 0))
        events.append(
            {
                "simulation_id": simulation_id,
                "ID": f"order_{o.get('order_id') or ''}",
                "timestamp": seconds_to_clock_str(ts_s),
                "timestamp_s": ts_s,
                "action": "order_placed",
                "type": "order",
                "order_id": o.get("order_id"),
                "group_id": o.get("golfer_group_id"),
                "hole": o.get("hole_num"),
                "status": o.get("status"),
            }
        )
    return events


# ------------------------------ CSV Reporting ------------------------------

def write_event_log_csv(events: List[Dict[str, Any]], save_path: Path) -> None:
    """Write a unified, replay-friendly events CSV."""
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "simulation_id", "ID", "timestamp", "timestamp_s", "action", "node_id",
        "hole", "ttl_amt", "type", "order_id", "runner_id", "cart_id",
        "group_id", "latitude", "longitude", "status", "details"
    ]
    with save_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for ev in sorted(events, key=lambda e: int(e.get("timestamp_s", 0))):
            writer.writerow(ev)

def write_order_logs_csv(sim_result: Dict[str, Any], save_path: Path) -> None:
    """Write a per-run CSV summarizing order lifecycle and drive times."""
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "order_id", "placed_ts", "placed_hole", "queue", "mins_to_set",
        "drive_out_min", "drive_total_min", "delivery_hole",
        "golfer_node_idx", "predicted_node_idx", "actual_node_idx"
    ]
    activity = list(sim_result.get("activity_log", []) or [])
    delivery_stats = list(sim_result.get("delivery_stats", []) or [])
    orders_list = list(sim_result.get("orders_all") or sim_result.get("orders") or [])

    placed_by_id: Dict[str, Dict[str, Any]] = {}
    start_by_id: Dict[str, Dict[str, Any]] = {}
    for a in activity:
        oid = a.get("order_id")
        if not oid: continue
        t = int(a.get("timestamp_s", 0))
        if a.get("activity_type") == "order_received" and oid not in placed_by_id:
            placed_by_id[oid] = {
                "timestamp_s": t,
                "time_str": a.get("time_str") or seconds_to_clock_str(t),
                "location": a.get("location") or "",
                "orders_in_queue": a.get("orders_in_queue"),
            }
        elif a.get("activity_type") == "delivery_start" and oid not in start_by_id:
            start_by_id[oid] = {"timestamp_s": t, "time_str": a.get("time_str") or seconds_to_clock_str(t)}

    stats_by_id = {str(s.get("order_id")): s for s in delivery_stats if s.get("order_id")}
    
    with save_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for o in orders_list:
            oid = str(o.get("order_id"))
            ots = int(o.get("order_time_s", 0))
            stat = stats_by_id.get(oid)
            placed = placed_by_id.get(oid)
            start = start_by_id.get(oid)
            placed_ts_str = seconds_to_clock_str(ots)
            
            writer.writerow({
                "order_id": oid,
                "placed_ts": placed_ts_str,
                "placed_hole": o.get("hole_num", (placed or {}).get("location", "")),
                "queue": (placed or {}).get("orders_in_queue", ""),
                "mins_to_set": ((start or {}).get("timestamp_s", ots) - ots) / 60.0 if start else "",
                "drive_out_min": (stat.get("delivery_time_s", 0) / 60.0) if stat else "",
                "drive_total_min": ((stat.get("delivery_time_s", 0) + stat.get("return_time_s", 0)) / 60.0) if stat else "",
                "delivery_hole": stat.get("hole_num", "") if stat else "",
                "golfer_node_idx": stat.get("order_node_idx", "") if stat else "",
                "predicted_node_idx": stat.get("predicted_delivery_node_idx", "") if stat else "",
                "actual_node_idx": stat.get("actual_delivery_node_idx", "") if stat else ""
            })

# ------------------------------ Metrics Generation ------------------------------

def generate_simulation_metrics_json(
    sim_result: Dict[str, Any], save_path: Path, service_hours: float = 10.0,
    sla_minutes: int = 30, revenue_per_order: float = 25.0,
    avg_bev_order_value: float = 12.0
) -> None:
    """Generate standardized metrics JSON file for map animation display."""
    save_path.parent.mkdir(parents=True, exist_ok=True)
    metrics = {"deliveryMetrics": None, "bevCartMetrics": None, "hasRunners": False, "hasBevCart": False}
    
    delivery_stats = sim_result.get("delivery_stats", []) or []
    activity_log = sim_result.get("activity_log", []) or []
    orders = sim_result.get("orders", []) or []
    failed_orders = sim_result.get("failed_orders", []) or []
    
    if delivery_stats or activity_log or orders:
        metrics["hasRunners"] = True
        completion_times = [float(d.get("total_completion_time_s", 0)) for d in delivery_stats]
        avg_order_time_min = (sum(completion_times) / len(completion_times) / 60.0) if completion_times else 0.0
        on_time_rate = (sum(1 for t in completion_times if t <= sla_minutes * 60) / len(completion_times) * 100.0) if completion_times else 0.0
        # Compute simple revenue model and productivity for UI
        successful = len(delivery_stats)
        # Business rule: Orders placed before service close contribute to revenue unless failed.
        total_orders = len(orders)
        failed_count = len(failed_orders)
        realized_orders = max(0, total_orders - failed_count)
        total_revenue = float(realized_orders) * float(revenue_per_order)
        orders_per_runner_hour = (float(successful) / float(service_hours)) if float(service_hours) > 0 else 0.0
        
        metrics["deliveryMetrics"] = {
            "totalOrders": len(orders),
            "successfulDeliveries": len(delivery_stats),
            "failedDeliveries": len(failed_orders),
            "avgOrderTime": avg_order_time_min,
            "onTimePercentage": on_time_rate,
            # Fields used by the map UI
            "revenue": total_revenue,
            "ordersPerRunnerHour": orders_per_runner_hour,
        }

    # Placeholder for bev cart metrics
    if sim_result.get("bev_cart_passes"):
        metrics["hasBevCart"] = True
        # ... bev cart metrics logic ...

    with save_path.open("w", encoding="utf-8") as f:
        import json
        json.dump(metrics, f, indent=2)

def build_runner_action_segments(activity_logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Build contiguous runner action segments from activity logs.

    Produces segments that fully partition the on-duty window into exactly three action types:
    - delivery_drive: delivery_start → (order_delivered | delivery_failed | delivered)
    - return_drive: returning → (runner_returned | returned_to_clubhouse | returned)
    - waiting_at_clubhouse: all remaining time within [service_opened, service_closed]

    Any incomplete drive/return segments are closed at service end.
    """
    if not activity_logs:
        return []

    by_runner: Dict[str, List[Dict[str, Any]]] = {}
    for a in activity_logs:
        rid = a.get("runner_id") or "runner_1"
        by_runner.setdefault(str(rid), []).append(a)

    drive_like: List[Dict[str, Any]] = []
    return_like: List[Dict[str, Any]] = []

    def _is_delivery_end(tag: str) -> bool:
        t = tag.lower()
        return (
            "order_delivered" in t
            or ("delivered" in t and "order" in t)
            or "delivery_complete" in t
            or ("delivery_failed" in t or ("failed" in t and "delivery" in t))
        )

    def _is_return_end(tag: str) -> bool:
        t = tag.lower()
        return (
            "runner_returned" in t
            or "returned_to_clubhouse" in t
            or ("returned" in t and "runner" in t)
            or "return_complete" in t
        )

    segments_all: List[Dict[str, Any]] = []

    for runner_id, entries in by_runner.items():
        entries_sorted = sorted(entries, key=lambda x: int(x.get("timestamp_s", 0)))

        service_open_s: Optional[int] = None
        service_close_s: Optional[int] = None
        delivery_start_s: Optional[int] = None
        return_start_s: Optional[int] = None

        for e in entries_sorted:
            ts = int(e.get("timestamp_s", 0))
            tag = str(e.get("activity_type", e.get("event", "")))
            tag_l = tag.lower()

            if "service_opened" in tag_l and service_open_s is None:
                service_open_s = ts
            elif "service_closed" in tag_l:
                if service_open_s is not None and ts >= service_open_s:
                    service_close_s = ts

            if "delivery_start" in tag_l and delivery_start_s is None:
                delivery_start_s = ts
            elif delivery_start_s is not None and _is_delivery_end(tag):
                drive_like.append({
                    "runner_id": runner_id,
                    "action_type": "delivery_drive",
                    "start_timestamp_s": int(delivery_start_s),
                    "end_timestamp_s": int(ts),
                })
                delivery_start_s = None

            if "returning" in tag_l and return_start_s is None:
                return_start_s = ts
            else:
                if return_start_s is not None and ts > return_start_s and not tag_l.startswith("returning"):
                    return_like.append({
                        "runner_id": runner_id,
                        "action_type": "return_drive",
                        "start_timestamp_s": int(return_start_s),
                        "end_timestamp_s": int(ts),
                    })
                    return_start_s = None

        if service_open_s is None:
            try:
                service_open_s = int(min(int(e.get("timestamp_s", 0)) for e in entries_sorted)) if entries_sorted else None
            except Exception:
                service_open_s = None
        if service_close_s is None:
            try:
                service_close_s = int(max(int(e.get("timestamp_s", 0)) for e in entries_sorted)) if entries_sorted else None
            except Exception:
                service_close_s = None

        if service_close_s is not None:
            if delivery_start_s is not None and service_close_s > delivery_start_s:
                drive_like.append({
                    "runner_id": runner_id,
                    "action_type": "delivery_drive",
                    "start_timestamp_s": int(delivery_start_s),
                    "end_timestamp_s": int(service_close_s),
                })
            if return_start_s is not None and service_close_s > return_start_s:
                return_like.append({
                    "runner_id": runner_id,
                    "action_type": "return_drive",
                    "start_timestamp_s": int(return_start_s),
                    "end_timestamp_s": int(service_close_s),
                })

        if service_open_s is None or service_close_s is None or service_close_s <= service_open_s:
            continue

        combined: List[Dict[str, Any]] = []
        for seg in drive_like + return_like:
            s = max(int(seg["start_timestamp_s"]), int(service_open_s))
            e = min(int(seg["end_timestamp_s"]), int(service_close_s))
            if e > s:
                combined.append({**seg, "start_timestamp_s": s, "end_timestamp_s": e})

        combined.sort(key=lambda d: (int(d.get("start_timestamp_s", 0)), int(d.get("end_timestamp_s", 0))))

        cursor = int(service_open_s)
        full_segments: List[Dict[str, Any]] = []
        for seg in combined:
            s = int(seg["start_timestamp_s"])
            e = int(seg["end_timestamp_s"])
            if s > cursor:
                full_segments.append({
                    "runner_id": runner_id,
                    "action_type": "waiting_at_clubhouse",
                    "start_timestamp_s": int(cursor),
                    "end_timestamp_s": int(s),
                })
                cursor = s
            if e > cursor:
                seg2 = dict(seg)
                seg2["start_timestamp_s"] = int(cursor)
                full_segments.append(seg2)
                cursor = e

        if cursor < int(service_close_s):
            full_segments.append({
                "runner_id": runner_id,
                "action_type": "waiting_at_clubhouse",
                "start_timestamp_s": int(cursor),
                "end_timestamp_s": int(service_close_s),
            })

        if full_segments:
            full_segments.sort(key=lambda d: (int(d.get("start_timestamp_s", 0)), int(d.get("end_timestamp_s", 0))))
            coalesced: List[Dict[str, Any]] = []
            for seg in full_segments:
                if not coalesced:
                    coalesced.append(dict(seg))
                    continue
                prev = coalesced[-1]
                same_type = str(prev.get("action_type")) == str(seg.get("action_type"))
                if same_type and int(seg.get("start_timestamp_s", 0)) <= int(prev.get("end_timestamp_s", 0)):
                    prev["end_timestamp_s"] = int(max(int(prev.get("end_timestamp_s", 0)), int(seg.get("end_timestamp_s", 0))))
                elif same_type and int(seg.get("start_timestamp_s", 0)) == int(prev.get("end_timestamp_s", 0)) + 0:
                    prev["end_timestamp_s"] = int(seg.get("end_timestamp_s", 0))
                else:
                    coalesced.append(dict(seg))
        else:
            coalesced = full_segments

        for s in coalesced:
            s["start_timestamp"] = seconds_to_clock_str(int(s["start_timestamp_s"]))
            s["end_timestamp"] = seconds_to_clock_str(int(s["end_timestamp_s"]))
            s["duration_s"] = int(max(0, int(s["end_timestamp_s"]) - int(s["start_timestamp_s"])) )

        segments_all.extend(coalesced)

    segments_all.sort(key=lambda d: (str(d.get("runner_id")), int(d.get("start_timestamp_s", 0)), str(d.get("action_type"))))
    return segments_all


def write_runner_action_log(activity_logs: List[Dict[str, Any]], save_path: Path) -> None:
    """Write runner action segments to CSV."""
    segments = build_runner_action_segments(activity_logs)
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "runner_id",
        "action_type",
        "start_timestamp",
        "end_timestamp",
        "start_timestamp_s",
        "end_timestamp_s",
        "duration_s",
    ]
    with save_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for seg in segments:
            writer.writerow({k: seg.get(k) for k in fieldnames})

def write_order_timing_logs_csv(order_timings: List[Dict[str, Any]], save_path: Path) -> None:
    """Write a per-run CSV with detailed order timing events."""
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "order_id", "order_time_s", "ready_for_pickup_time_s", 
        "departure_time_s", "delivery_timestamp_s", "return_timestamp_s"
    ]
    with save_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in order_timings:
            writer.writerow(row)
