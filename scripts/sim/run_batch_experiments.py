#!/usr/bin/env python3
"""
Batch experiment runner for golf simulations (beverage carts or delivery runners).

Runs all combinations (or a limited subset via CLI) multiple times and writes only:
- batch_stats.csv: one row per simulation run with summary metrics and parameters
- batch_events.csv: minimal per-run event records to allow later recreation

Avoids writing heavy artifacts (coordinates, images, HTML).

Windows PowerShell friendly: one short command per line, no piping/chaining.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import simpy

from golfsim.logging import init_logging, get_logger
from golfsim.config.loaders import load_tee_times_config, load_simulation_config
from golfsim.simulation.phase_simulations import generate_golfer_track
from golfsim.simulation.bev_cart_pass import simulate_beverage_cart_sales
from golfsim.simulation.crossings import compute_crossings_from_files
from golfsim.simulation.services import (
    DeliveryOrder,
    MultiRunnerDeliveryService,
)
from golfsim.analysis.bev_cart_metrics import calculate_bev_cart_metrics
from golfsim.analysis.delivery_runner_metrics import calculate_delivery_runner_metrics


logger = get_logger(__name__)


# -------------------- Helpers --------------------

def _parse_float_list(spec: str) -> List[float]:
    return [float(x.strip()) for x in str(spec).split(",") if str(x).strip()]


def _parse_int_list_or_range(spec: str) -> List[int]:
    s = str(spec).strip()
    if "-" in s and "," not in s:
        a, b = s.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(x.strip()) for x in s.split(",") if x.strip()]


def _timestamped_dirname(prefix: str) -> str:
    ts = time.strftime("%Y%m%d_%H%M%S")
    return f"{prefix}_{ts}"


def _ensure_csv(path: Path, fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()


def _append_csv(path: Path, fieldnames: Sequence[str], row: Dict[str, Any]) -> None:
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writerow(row)


def _load_scenario_keys(course_dir: str, selected: Optional[str]) -> List[str]:
    cfg = load_tee_times_config(course_dir)
    scenarios = sorted((cfg.scenarios or {}).keys())
    if not selected or selected.lower() == "all":
        return scenarios
    chosen = [s.strip() for s in selected.split(",") if s.strip()]
    return [s for s in scenarios if s in chosen]


def _groups_from_scenario(course_dir: str, scenario_key: str, default_group_size: int = 4) -> List[Dict[str, Any]]:
    config = load_tee_times_config(course_dir)
    scenarios = config.scenarios or {}
    scenario = scenarios.get(scenario_key) or {}
    hourly: Dict[str, int] = scenario.get("hourly_golfers", {}) or {}
    if not hourly:
        logger.warning("tee-scenario '%s' missing 'hourly_golfers'", scenario_key)
        return []

    def _hhmm_to_seconds_since_7am(hhmm: str) -> int:
        try:
            hh, mm = hhmm.split(":")
            return (int(hh) - 7) * 3600 + int(mm) * 60
        except Exception:
            return 0

    groups: List[Dict[str, Any]] = []
    group_id = 1
    for hour_label, golfers in sorted(hourly.items(), key=lambda kv: _hhmm_to_seconds_since_7am(kv[0])):
        golfers_int = int(golfers or 0)
        if golfers_int <= 0:
            continue
        groups_this_hour = (golfers_int + default_group_size - 1) // default_group_size
        base_s = _hhmm_to_seconds_since_7am(hour_label)
        interval_seconds = int(3600 / max(groups_this_hour, 1))
        remaining = golfers_int
        for i in range(groups_this_hour):
            size = min(default_group_size, remaining)
            if size <= 0:
                break
            tee_time_s = base_s + i * interval_seconds
            groups.append({
                "group_id": group_id,
                "tee_time_s": int(tee_time_s),
                "num_golfers": int(size),
            })
            group_id += 1
            remaining -= size
    return groups


def _generate_golfer_points_for_groups(course_dir: str, groups: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    all_points: List[Dict[str, Any]] = []
    for g in groups:
        pts = generate_golfer_track(course_dir, g["tee_time_s"]) or []
        for p in pts:
            p["group_id"] = g["group_id"]
        all_points.extend(pts)
    return all_points


def _compute_crossings(course_dir: str, groups: List[Dict[str, Any]], random_seed: int) -> Optional[Dict[str, Any]]:
    try:
        nodes_geojson = str(Path(course_dir) / "geojson" / "generated" / "lcm_course_nodes.geojson")
        holes_geojson = str(Path(course_dir) / "geojson" / "generated" / "holes_geofenced.geojson")
        config_json = str(Path(course_dir) / "config" / "simulation_config.json")
        first_tee_s = min(g["tee_time_s"] for g in groups) if groups else (9 - 7) * 3600
        last_tee_s = max(g["tee_time_s"] for g in groups) if groups else first_tee_s
        from scripts.sim.run_unified_simulation import _seconds_to_clock_str  # local import to reuse utility
        return compute_crossings_from_files(
            nodes_geojson=nodes_geojson,
            holes_geojson=holes_geojson,
            config_json=config_json,
            v_fwd_mph=None,
            v_bwd_mph=None,
            bev_start=_seconds_to_clock_str((9 - 7) * 3600),
            groups_start=_seconds_to_clock_str(first_tee_s),
            groups_end=_seconds_to_clock_str(last_tee_s),
            groups_count=len(groups) if groups else 0,
            random_seed=random_seed,
            tee_mode="interval",
            groups_interval_min=15.0,
        )
    except Exception as e:
        logger.warning("Crossings computation failed: %s", e)
        return None


# -------------------- Runner orders with constraints --------------------

def _simulate_delivery_orders_with_constraints(
    groups: List[Dict[str, Any]],
    delivery_prob_per_9: float,
    prevent_front_upto_hole: int = 0,
    front9_prob_if_prevent: Optional[float] = None,
    minutes_per_hole: int = 12,
) -> List[DeliveryOrder]:
    orders: List[DeliveryOrder] = []
    prevent_upto = int(prevent_front_upto_hole or 0)
    use_prevent = prevent_upto >= 1
    front_prob = float(front9_prob_if_prevent) if (use_prevent and front9_prob_if_prevent is not None) else float(delivery_prob_per_9)
    front_min_hole = max(prevent_upto + 1, 1)
    front_max_hole = 9
    for group in groups:
        group_id = group["group_id"]
        tee_time_s = int(group["tee_time_s"])

        # Front nine
        if use_prevent:
            if random.random() < front_prob and front_min_hole <= front_max_hole:
                hole_front = random.randint(front_min_hole, front_max_hole)
                order_time_front_s = tee_time_s + (hole_front - 1) * minutes_per_hole * 60
                orders.append(DeliveryOrder(
                    order_id=None,
                    golfer_group_id=group_id,
                    golfer_id=f"G{group_id}",
                    order_time_s=order_time_front_s,
                    hole_num=hole_front,
                ))
        else:
            if random.random() < float(delivery_prob_per_9):
                hole_front = random.randint(1, 9)
                order_time_front_s = tee_time_s + (hole_front - 1) * minutes_per_hole * 60
                orders.append(DeliveryOrder(
                    order_id=None,
                    golfer_group_id=group_id,
                    golfer_id=f"G{group_id}",
                    order_time_s=order_time_front_s,
                    hole_num=hole_front,
                ))

        # Back nine
        if random.random() < float(delivery_prob_per_9):
            hole_back = random.randint(10, 18)
            order_time_back_s = tee_time_s + (hole_back - 1) * minutes_per_hole * 60
            orders.append(DeliveryOrder(
                order_id=None,
                golfer_group_id=group_id,
                golfer_id=f"G{group_id}",
                order_time_s=order_time_back_s,
                hole_num=hole_back,
            ))

    orders.sort(key=lambda x: x.order_time_s)
    for i, order in enumerate(orders, 1):
        order.order_id = f"{i:03d}"
    return orders


# -------------------- Batch execution --------------------

@dataclass
class BatchRunContext:
    batch_id: str
    course_dir: str
    output_root: Path
    stats_csv: Path
    events_csv: Path
    metrics_csv: Path
    events_runs_dir: Path


def _init_batch_output(root_dir: Optional[str]) -> BatchRunContext:
    batch_id = _timestamped_dirname("batch")
    output_root = Path(root_dir or (Path("outputs") / batch_id))
    output_root.mkdir(parents=True, exist_ok=True)
    stats_csv = output_root / "batch_stats.csv"
    events_csv = output_root / "batch_events.csv"
    metrics_csv = output_root / "batch_metrics.csv"
    events_runs_dir = output_root / "events_by_run"
    events_runs_dir.mkdir(parents=True, exist_ok=True)

    _ensure_csv(stats_csv, [
        "batch_id", "mode", "run_index", "scenario", "num_carts", "num_runners",
        "bev_order_prob", "delivery_order_prob", "prevent_front_1_5", "front9_prob_if_prevent", "prevent_front_upto_hole",
        "groups", "orders_placed", "orders_processed", "orders_failed", "num_sales", "total_revenue_usd",
        "avg_order_time_s", "total_delivery_distance_m", "seed",
    ])
    _ensure_csv(events_csv, [
        "batch_id", "simulation_id", "mode", "run_key", "scenario", "timestamp_s", "action", "entity_id",
        "order_id", "group_id", "hole", "ttl_amt", "details",
    ])

    # Unified metrics CSV (superset of bev-cart and runner metrics + sim details)
    _ensure_csv(metrics_csv, [
        # Identification
        "batch_id", "simulation_id", "mode", "run_index", "run_key", "scenario", "seed",
        # Simulation details
        "num_carts", "num_runners", "groups", "bev_order_prob", "bev_price_usd", "delivery_order_prob",
        "prevent_front_1_5", "front9_prob_if_prevent", "prevent_front_upto_hole", "runner_speed_mps", "prep_time_min",
        # Bev-cart metrics
        "bev_revenue_per_round", "bev_average_order_value", "bev_total_revenue", "bev_order_penetration_rate",
        "bev_orders_per_cart_hour", "bev_total_orders", "bev_unique_customers", "bev_tip_rate", "bev_tips_per_order",
        "bev_total_tips", "bev_holes_covered_per_hour", "bev_minutes_per_hole_per_cart", "bev_total_holes_covered",
        "bev_golfer_repeat_rate", "bev_average_orders_per_customer", "bev_customers_with_multiple_orders",
        "bev_golfer_visibility_interval_minutes", "bev_total_visibility_events", "bev_service_hours", "bev_rounds_in_service_window",
        # Runner metrics
        "run_revenue_per_round", "run_order_penetration_rate", "run_average_order_value", "run_orders_per_runner_hour",
        "run_on_time_rate", "run_delivery_cycle_time_p50", "run_delivery_cycle_time_p90", "run_dispatch_delay_avg",
        "run_travel_time_avg", "run_failed_rate", "run_util_driving_pct", "run_util_waiting_pct", "run_util_handoff_pct",
        "run_util_deadhead_pct", "run_distance_per_delivery_avg", "run_queue_depth_avg", "run_queue_wait_avg",
        "run_capacity_15min_window", "run_second_runner_break_even_orders", "run_total_revenue", "run_total_orders",
        "run_successful_orders", "run_failed_orders", "run_total_rounds", "run_active_runner_hours",
        # Complex JSON fields (optional)
        "run_zone_service_times_json", "run_util_by_runner_json",
    ])

    return BatchRunContext(batch_id=batch_id, course_dir="", output_root=output_root, stats_csv=stats_csv, events_csv=events_csv, metrics_csv=metrics_csv, events_runs_dir=events_runs_dir)


def _record_event(ctx: BatchRunContext, mode: str, run_key: str, scenario: str, timestamp_s: int, action: str,
                  entity_id: Optional[str] = None, order_id: Optional[str] = None, group_id: Optional[int] = None,
                  hole: Optional[int] = None, ttl_amt: Optional[float] = None, details: Optional[str] = None) -> None:
    sim_id = f"{ctx.batch_id}_{run_key}"
    fieldnames = [
        "batch_id", "simulation_id", "mode", "run_key", "scenario", "timestamp_s", "action", "entity_id",
        "order_id", "group_id", "hole", "ttl_amt", "details",
    ]
    row = {
        "batch_id": ctx.batch_id,
        "simulation_id": sim_id,
        "mode": mode,
        "run_key": run_key,
        "scenario": scenario,
        "timestamp_s": int(timestamp_s),
        "action": action,
        "entity_id": entity_id,
        "order_id": order_id,
        "group_id": group_id,
        "hole": hole,
        "ttl_amt": ttl_amt,
        "details": details,
    }
    _append_csv(ctx.events_csv, fieldnames, row)

    # Also write a per-run events file under events_by_run/<simulation_id>.csv
    per_run_path = ctx.events_runs_dir / f"{sim_id}.csv"
    _ensure_csv(per_run_path, fieldnames)
    _append_csv(per_run_path, fieldnames, row)


def _write_stats_row(ctx: BatchRunContext, row: Dict[str, Any]) -> None:
    _append_csv(ctx.stats_csv, [
        "batch_id", "mode", "run_index", "scenario", "num_carts", "num_runners",
        "bev_order_prob", "delivery_order_prob", "prevent_front_1_5", "front9_prob_if_prevent", "prevent_front_upto_hole",
        "groups", "orders_placed", "orders_processed", "orders_failed", "num_sales", "total_revenue_usd",
        "avg_order_time_s", "total_delivery_distance_m", "seed",
    ], row)


def _write_metrics_row(ctx: BatchRunContext, row: Dict[str, Any]) -> None:
    _append_csv(ctx.metrics_csv, [
        "batch_id", "simulation_id", "mode", "run_index", "run_key", "scenario", "seed",
        "num_carts", "num_runners", "groups", "bev_order_prob", "bev_price_usd", "delivery_order_prob",
        "prevent_front_1_5", "front9_prob_if_prevent", "prevent_front_upto_hole", "runner_speed_mps", "prep_time_min",
        "bev_revenue_per_round", "bev_average_order_value", "bev_total_revenue", "bev_order_penetration_rate",
        "bev_orders_per_cart_hour", "bev_total_orders", "bev_unique_customers", "bev_tip_rate", "bev_tips_per_order",
        "bev_total_tips", "bev_holes_covered_per_hour", "bev_minutes_per_hole_per_cart", "bev_total_holes_covered",
        "bev_golfer_repeat_rate", "bev_average_orders_per_customer", "bev_customers_with_multiple_orders",
        "bev_golfer_visibility_interval_minutes", "bev_total_visibility_events", "bev_service_hours", "bev_rounds_in_service_window",
        "run_revenue_per_round", "run_order_penetration_rate", "run_average_order_value", "run_orders_per_runner_hour",
        "run_on_time_rate", "run_delivery_cycle_time_p50", "run_delivery_cycle_time_p90", "run_dispatch_delay_avg",
        "run_travel_time_avg", "run_failed_rate", "run_util_driving_pct", "run_util_waiting_pct", "run_util_handoff_pct",
        "run_util_deadhead_pct", "run_distance_per_delivery_avg", "run_queue_depth_avg", "run_queue_wait_avg",
        "run_capacity_15min_window", "run_second_runner_break_even_orders", "run_total_revenue", "run_total_orders",
        "run_successful_orders", "run_failed_orders", "run_total_rounds", "run_active_runner_hours",
        "run_zone_service_times_json", "run_util_by_runner_json",
    ], row)


# -------------------- End-of-batch summaries --------------------

def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        s = str(value).strip()
    except Exception:
        return None
    if not s:
        return None
    try:
        return float(s)
    except Exception:
        return None


def _group_rows(rows: Iterable[Dict[str, Any]], keys: List[str]) -> Dict[Tuple[Any, ...], List[Dict[str, Any]]]:
    grouped: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    for r in rows:
        k = tuple(r.get(k) for k in keys)
        grouped.setdefault(k, []).append(r)
    return grouped


def _compute_mean(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / float(len(values))


def _compute_median(values: List[float]) -> float:
    if not values:
        return 0.0
    try:
        import statistics
        return float(statistics.median(values))
    except Exception:
        values_sorted = sorted(values)
        n = len(values_sorted)
        mid = n // 2
        if n % 2 == 1:
            return float(values_sorted[mid])
        return float((values_sorted[mid - 1] + values_sorted[mid]) / 2.0)


def _summarize_mode(
    rows: List[Dict[str, Any]],
    keys: List[str],
    metric_names: List[str],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    groups = _group_rows(rows, keys)

    # Header
    fieldnames: List[str] = [*keys, "n"]
    for m in metric_names:
        fieldnames.append(f"{m}_mean")
        fieldnames.append(f"{m}_median")

    with output_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for key_tuple, group_rows in sorted(groups.items(), key=lambda kv: tuple(str(x) for x in kv[0])):
            row_out: Dict[str, Any] = {k: v for k, v in zip(keys, key_tuple)}
            row_out["n"] = len(group_rows)
            for m in metric_names:
                vals: List[float] = []
                for r in group_rows:
                    v = _to_float(r.get(m))
                    if v is not None:
                        vals.append(v)
                row_out[f"{m}_mean"] = _compute_mean(vals) if vals else ""
                row_out[f"{m}_median"] = _compute_median(vals) if vals else ""
            writer.writerow(row_out)


def _generate_end_of_batch_summaries(ctx: BatchRunContext) -> None:
    try:
        # Read metrics CSV
        with ctx.metrics_csv.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Split
        bevcart_rows = [r for r in rows if (r.get("mode") or "").strip().lower() == "bevcart"]
        runner_rows = [r for r in rows if (r.get("mode") or "").strip().lower() == "runner"]

        # BevCart summary by scenario, carts, bev prob
        if bevcart_rows:
            bev_keys = ["scenario", "num_carts", "bev_order_prob", "bev_price_usd"]
            bev_metrics = [
                "bev_total_orders",
                "bev_total_revenue",
                "bev_order_penetration_rate",
                "bev_orders_per_cart_hour",
                "bev_holes_covered_per_hour",
                "bev_total_visibility_events",
            ]
            _summarize_mode(
                rows=bevcart_rows,
                keys=bev_keys,
                metric_names=bev_metrics,
                output_path=ctx.output_root / "batch_summary_bevcart.csv",
            )

        # Runner summary by scenario, runners, delivery prob, prevention, speed/prep
        if runner_rows:
            run_keys = [
                "scenario",
                "num_runners",
                "delivery_order_prob",
                "prevent_front_upto_hole",
                "runner_speed_mps",
                "prep_time_min",
            ]
            run_metrics = [
                "run_on_time_rate",
                "run_delivery_cycle_time_p50",
                "run_orders_per_runner_hour",
                "run_failed_rate",
                "run_queue_depth_avg",
                "run_queue_wait_avg",
                "run_total_orders",
                "run_total_revenue",
                "run_successful_orders",
                "run_failed_orders",
            ]
            _summarize_mode(
                rows=runner_rows,
                keys=run_keys,
                metric_names=run_metrics,
                output_path=ctx.output_root / "batch_summary_runner.csv",
            )

        # Optional Markdown report using existing aggregator
        try:
            from scripts.analysis.aggregate_batch_metrics import read_csv_rows as _agg_read_rows, generate_report as _agg_generate_report
            agg_rows = _agg_read_rows(ctx.metrics_csv)
            report = _agg_generate_report(agg_rows)
            (ctx.output_root / "aggregated_metrics_report.md").write_text(report, encoding="utf-8")
        except Exception:
            pass

    except Exception as e:
        logger.warning("Summary generation failed: %s", e)


def _run_bevcart_once(ctx: BatchRunContext, course_dir: str, scenario: str, run_index: int,
                       num_carts: int, bev_order_prob: float, price_per_order: float, seed: int) -> None:
    # Build groups and golfer track data
    groups = _groups_from_scenario(course_dir, scenario)
    golfer_points = _generate_golfer_points_for_groups(course_dir, groups) if groups else []

    # Compute crossings once (seeded)
    crossings = _compute_crossings(course_dir, groups, random_seed=seed)

    # Run for each cart independently and record per-cart metrics row
    for cart_idx in range(int(num_carts)):
        random.seed(seed + cart_idx)
        res = simulate_beverage_cart_sales(
            course_dir=course_dir,
            groups=groups or [],
            pass_order_probability=float(bev_order_prob),
            price_per_order=float(price_per_order),
            minutes_between_holes=2.0,
            minutes_per_hole=None,
            golfer_points=golfer_points,
            crossings_data=crossings,
        )
        sales = res.get("sales", []) if isinstance(res, dict) else []
        # Minimal event logging (sale events only)
        for sale in sales:
            _record_event(
                ctx, mode="bevcart", run_key=f"{scenario}_run{run_index:02d}_cart{cart_idx+1}", scenario=scenario,
                timestamp_s=int(sale.get("timestamp_s", 0)), action="sale", entity_id=f"bev_cart_{cart_idx+1}",
                group_id=int(sale.get("group_id", 0)), hole=int(sale.get("hole_num", 0)), ttl_amt=float(sale.get("price", 0.0)),
            )

        # Compute bev-cart metrics (coordinates/golfer_data omitted for speed)
        sim_id = f"{ctx.batch_id}_{scenario}_run{run_index:02d}_cart{cart_idx+1}"
        metrics = calculate_bev_cart_metrics(
            sales_data=sales,
            coordinates=[],
            golfer_data=None,
            service_start_s=7200,
            service_end_s=36000,
            simulation_id=sim_id,
            cart_id=f"bev_cart_{cart_idx+1}",
        )

        # Write one metrics row per cart simulation
        _write_metrics_row(ctx, {
            "batch_id": ctx.batch_id,
            "simulation_id": sim_id,
            "mode": "bevcart",
            "run_index": run_index,
            "run_key": f"{scenario}_run{run_index:02d}_cart{cart_idx+1}",
            "scenario": scenario,
            "seed": int(seed + cart_idx),
            "num_carts": 1,
            "num_runners": 0,
            "groups": len(groups),
            "bev_order_prob": float(bev_order_prob),
            "bev_price_usd": float(price_per_order),
            "delivery_order_prob": "",
            "prevent_front_1_5": "",
            "front9_prob_if_prevent": "",
            "runner_speed_mps": "",
            "prep_time_min": "",
            # Bev metrics
            "bev_revenue_per_round": metrics.revenue_per_round,
            "bev_average_order_value": metrics.average_order_value,
            "bev_total_revenue": metrics.total_revenue,
            "bev_order_penetration_rate": metrics.order_penetration_rate,
            "bev_orders_per_cart_hour": metrics.orders_per_cart_hour,
            "bev_total_orders": metrics.total_orders,
            "bev_unique_customers": metrics.unique_customers,
            "bev_tip_rate": metrics.tip_rate,
            "bev_tips_per_order": metrics.tips_per_order,
            "bev_total_tips": metrics.total_tips,
            "bev_holes_covered_per_hour": metrics.holes_covered_per_hour,
            "bev_minutes_per_hole_per_cart": metrics.minutes_per_hole_per_cart,
            "bev_total_holes_covered": metrics.total_holes_covered,
            "bev_golfer_repeat_rate": metrics.golfer_repeat_rate,
            "bev_average_orders_per_customer": metrics.average_orders_per_customer,
            "bev_customers_with_multiple_orders": metrics.customers_with_multiple_orders,
            "bev_golfer_visibility_interval_minutes": metrics.golfer_visibility_interval_minutes,
            "bev_total_visibility_events": metrics.total_visibility_events,
            "bev_service_hours": metrics.service_hours,
            "bev_rounds_in_service_window": metrics.rounds_in_service_window,
            # Runner metrics empty for bev-cart runs
            "run_revenue_per_round": "",
            "run_order_penetration_rate": "",
            "run_average_order_value": "",
            "run_orders_per_runner_hour": "",
            "run_on_time_rate": "",
            "run_delivery_cycle_time_p50": "",
            "run_delivery_cycle_time_p90": "",
            "run_dispatch_delay_avg": "",
            "run_travel_time_avg": "",
            "run_failed_rate": "",
            "run_util_driving_pct": "",
            "run_util_waiting_pct": "",
            "run_util_handoff_pct": "",
            "run_util_deadhead_pct": "",
            "run_distance_per_delivery_avg": "",
            "run_queue_depth_avg": "",
            "run_queue_wait_avg": "",
            "run_capacity_15min_window": "",
            "run_second_runner_break_even_orders": "",
            "run_total_revenue": "",
            "run_total_orders": "",
            "run_successful_orders": "",
            "run_failed_orders": "",
            "run_total_rounds": "",
            "run_active_runner_hours": "",
            "run_zone_service_times_json": "",
            "run_util_by_runner_json": "",
        })

        # Print progress for this cart simulation
        print(f"[bevcart] scenario={scenario} run={run_index:02d} cart={cart_idx+1} sales={len(sales)} revenue=${res.get('revenue', 0.0):.2f}")
        logger.info("[bevcart] %s run %02d cart %d: sales=%d revenue=%.2f", scenario, run_index, cart_idx + 1, len(sales), float(res.get('revenue', 0.0)))

    # Stats row per cart simulation for quick progress tracking
    # Each cart counts as a separate simulation row
    for cart_idx in range(int(num_carts)):
        # Recompute seed alignment for clarity
        seed_for_cart = int(seed + cart_idx)
        # We don't have per-cart summaries separated post-loop; approximate via metrics CSV where needed.
        # Here we add a minimal stats row keyed by run_index/cart index with sales count derived from events
        # For accuracy, we re-run a very light sales-only call (no crossings) with same seed
        random.seed(seed_for_cart)
        res_check = simulate_beverage_cart_sales(
            course_dir=course_dir,
            groups=groups or [],
            pass_order_probability=float(bev_order_prob),
            price_per_order=float(price_per_order),
            minutes_between_holes=2.0,
            minutes_per_hole=None,
            golfer_points=golfer_points,
            crossings_data=crossings,
        )
        sales_check = res_check.get("sales", []) if isinstance(res_check, dict) else []
        revenue_check = float(res_check.get("revenue", 0.0)) if isinstance(res_check, dict) else 0.0
        _write_stats_row(ctx, {
            "batch_id": ctx.batch_id,
            "mode": "bevcart",
            "run_index": run_index,
            "scenario": scenario,
            "num_carts": 1,
            "num_runners": 0,
            "bev_order_prob": float(bev_order_prob),
            "delivery_order_prob": "",
            "prevent_front_1_5": "",
            "front9_prob_if_prevent": "",
            "groups": len(groups),
            "orders_placed": "",
            "orders_processed": "",
            "orders_failed": "",
            "num_sales": int(len(sales_check)),
            "total_revenue_usd": float(revenue_check),
            "avg_order_time_s": "",
            "total_delivery_distance_m": "",
            "seed": seed_for_cart,
        })


def _run_runner_once(ctx: BatchRunContext, course_dir: str, scenario: str, run_index: int,
                     num_runners: int, delivery_prob_per_9: float,
                     prevent_front_upto_hole: int, front9_prob_if_prevent: Optional[float],
                     runner_speed_mps: float, prep_time_min: int, seed: int,
                     prevention_label: Optional[str] = None) -> None:
    # Build groups
    groups = _groups_from_scenario(course_dir, scenario)

    # Orders with constraints
    random.seed(seed)
    orders = _simulate_delivery_orders_with_constraints(
        groups=groups,
        delivery_prob_per_9=float(delivery_prob_per_9),
        prevent_front_upto_hole=int(prevent_front_upto_hole or 0),
        front9_prob_if_prevent=float(front9_prob_if_prevent) if front9_prob_if_prevent is not None else None,
        minutes_per_hole=12,
    )

    # MultiRunner service even for a single runner (to inject orders)
    env = simpy.Environment()
    service = MultiRunnerDeliveryService(
        env=env,
        course_dir=course_dir,
        num_runners=int(num_runners),
        runner_speed_mps=float(runner_speed_mps),
        prep_time_min=int(prep_time_min),
    )

    def order_arrivals():
        last_time = env.now
        for order in orders:
            target_time = max(order.order_time_s, service.service_open_s)
            if target_time > last_time:
                yield env.timeout(target_time - last_time)
            service.place_order(order)
            last_time = target_time

    env.process(order_arrivals())
    run_until = max(service.service_close_s + 1, max((o.order_time_s for o in orders), default=0) + 4 * 3600)
    env.run(until=run_until)

    # Summaries
    delivery_stats = service.delivery_stats or []
    failed_orders = service.failed_orders or []
    avg_order_time_s = 0.0
    total_distance_m = 0.0
    if delivery_stats:
        avg_order_time_s = sum(d.get("total_completion_time_s", 0.0) for d in delivery_stats) / max(len(delivery_stats), 1)
        total_distance_m = sum(d.get("delivery_distance_m", 0.0) for d in delivery_stats)

    base_run_key = f"{scenario}_run{run_index:02d}"
    run_key = base_run_key if (not prevention_label or prevention_label == "none") else f"{base_run_key}_{prevention_label}"

    # Minimal per-order events: order_placed and delivery_complete
    for o in orders:
        _record_event(ctx, mode="runner", run_key=run_key, scenario=scenario,
                      timestamp_s=int(o.order_time_s), action="order_placed", entity_id="order",
                      order_id=o.order_id, group_id=o.golfer_group_id, hole=o.hole_num)
    for d in delivery_stats:
        _record_event(ctx, mode="runner", run_key=run_key, scenario=scenario,
                      timestamp_s=int(d.get("delivered_at_time_s", 0)), action="order_delivered",
                      entity_id=d.get("runner_id", "runner"), order_id=d.get("order_id"),
                      group_id=d.get("golfer_group_id"), hole=d.get("hole_num"))

    # Compute delivery runner metrics
    # Convert orders and failed_orders to dicts
    orders_dicts = [
        {
            "order_id": getattr(o, "order_id", None),
            "golfer_group_id": getattr(o, "golfer_group_id", None),
            "golfer_id": getattr(o, "golfer_id", None),
            "order_time_s": getattr(o, "order_time_s", None),
            "hole_num": getattr(o, "hole_num", None),
            "status": getattr(o, "status", None),
        }
        for o in orders
    ]
    failed_orders_dicts = [
        {
            "order_id": getattr(o, "order_id", None),
            "reason": getattr(o, "failure_reason", None),
        }
        for o in failed_orders
    ]

    sim_id = f"{ctx.batch_id}_{run_key}"
    metrics = calculate_delivery_runner_metrics(
        delivery_stats=delivery_stats,
        activity_log=service.activity_log or [],
        orders=orders_dicts,
        failed_orders=failed_orders_dicts,
        revenue_per_order=25.0,
        sla_minutes=30,
        simulation_id=sim_id,
        runner_id="runner_1" if int(num_runners) == 1 else f"{int(num_runners)}_runners",
        service_hours=float((service.service_close_s - service.service_open_s) / 3600.0) if hasattr(service, 'service_close_s') else 10.0,
    )

    # Write metrics row for this runner simulation
    _write_metrics_row(ctx, {
        "batch_id": ctx.batch_id,
        "simulation_id": sim_id,
        "mode": "runner",
        "run_index": run_index,
        "run_key": run_key,
        "scenario": scenario,
        "seed": int(seed),
        "num_carts": 0,
        "num_runners": int(num_runners),
        "groups": len(groups),
        "bev_order_prob": "",
        "bev_price_usd": "",
        "delivery_order_prob": float(delivery_prob_per_9),
        "prevent_front_1_5": "",
        "front9_prob_if_prevent": float(front9_prob_if_prevent) if front9_prob_if_prevent is not None else "",
        "prevent_front_upto_hole": int(prevent_front_upto_hole or 0) if int(prevent_front_upto_hole or 0) > 0 else "",
        "runner_speed_mps": float(runner_speed_mps),
        "prep_time_min": int(prep_time_min),
        # Bev metrics empty
        "bev_revenue_per_round": "",
        "bev_average_order_value": "",
        "bev_total_revenue": "",
        "bev_order_penetration_rate": "",
        "bev_orders_per_cart_hour": "",
        "bev_total_orders": "",
        "bev_unique_customers": "",
        "bev_tip_rate": "",
        "bev_tips_per_order": "",
        "bev_total_tips": "",
        "bev_holes_covered_per_hour": "",
        "bev_minutes_per_hole_per_cart": "",
        "bev_total_holes_covered": "",
        "bev_golfer_repeat_rate": "",
        "bev_average_orders_per_customer": "",
        "bev_customers_with_multiple_orders": "",
        "bev_golfer_visibility_interval_minutes": "",
        "bev_total_visibility_events": "",
        "bev_service_hours": "",
        "bev_rounds_in_service_window": "",
        # Runner metrics
        "run_revenue_per_round": metrics.revenue_per_round,
        "run_order_penetration_rate": metrics.order_penetration_rate,
        "run_average_order_value": metrics.average_order_value,
        "run_orders_per_runner_hour": metrics.orders_per_runner_hour,
        "run_on_time_rate": metrics.on_time_rate,
        "run_delivery_cycle_time_p50": metrics.delivery_cycle_time_p50,
        "run_delivery_cycle_time_p90": metrics.delivery_cycle_time_p90,
        "run_dispatch_delay_avg": metrics.dispatch_delay_avg,
        "run_travel_time_avg": metrics.travel_time_avg,
        "run_failed_rate": metrics.failed_rate,
        "run_util_driving_pct": metrics.runner_utilization_driving_pct,
        "run_util_waiting_pct": metrics.runner_utilization_waiting_pct,
        "run_util_handoff_pct": metrics.runner_utilization_handoff_pct,
        "run_util_deadhead_pct": metrics.runner_utilization_deadhead_pct,
        "run_distance_per_delivery_avg": metrics.distance_per_delivery_avg,
        "run_queue_depth_avg": metrics.queue_depth_avg,
        "run_queue_wait_avg": metrics.queue_wait_avg,
        "run_capacity_15min_window": metrics.capacity_15min_window,
        "run_second_runner_break_even_orders": metrics.second_runner_break_even_orders,
        "run_total_revenue": metrics.total_revenue,
        "run_total_orders": metrics.total_orders,
        "run_successful_orders": metrics.successful_orders,
        "run_failed_orders": metrics.failed_orders,
        "run_total_rounds": metrics.total_rounds,
        "run_active_runner_hours": metrics.active_runner_hours,
        "run_zone_service_times_json": json.dumps(metrics.zone_service_times),
        "run_util_by_runner_json": json.dumps(metrics.runner_utilization_by_runner or {}),
    })

    # Print progress for this runner simulation
    label_for_print = prevention_label or "none"
    print(f"[runner] scenario={scenario} run={run_index:02d} runners={num_runners} prevent_front={label_for_print} orders={len(orders)} processed={len(delivery_stats)} failed={len(failed_orders)}")
    logger.info("[runner] %s run %02d runners=%d prevent_front=%s: orders=%d processed=%d failed=%d", scenario, run_index, int(num_runners), label_for_print, len(orders), len(delivery_stats), len(failed_orders))

    # Also write a minimal stats row for the runner simulation (after each run)
    _write_stats_row(ctx, {
        "batch_id": ctx.batch_id,
        "mode": "runner",
        "run_index": run_index,
        "scenario": scenario,
        "num_carts": 0,
        "num_runners": int(num_runners),
        "bev_order_prob": "",
        "delivery_order_prob": float(delivery_prob_per_9),
        "prevent_front_1_5": "",
        "front9_prob_if_prevent": float(front9_prob_if_prevent) if (front9_prob_if_prevent is not None and int(prevent_front_upto_hole or 0) > 0) else "",
        "prevent_front_upto_hole": int(prevent_front_upto_hole or 0) if int(prevent_front_upto_hole or 0) > 0 else "",
        "groups": len(groups),
        "orders_placed": len(orders),
        "orders_processed": len(delivery_stats),
        "orders_failed": len(failed_orders),
        "num_sales": "",
        "total_revenue_usd": metrics.total_revenue,
        "avg_order_time_s": float(avg_order_time_s),
        "total_delivery_distance_m": float(total_distance_m),
        "seed": int(seed),
    })


# -------------------- CLI --------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Batch runner for golf simulations (bevcart or runner)")
    parser.add_argument("--course-dir", default="courses/pinetree_country_club", help="Course directory")
    parser.add_argument("--runs-per-combo", type=int, default=5, help="Number of runs per parameter combination")
    parser.add_argument("--output-dir", type=str, default=None, help="Where to store batch CSV outputs only")
    parser.add_argument("--log-level", type=str, default="INFO", help="Log level")

    # Dimensions to sweep (defaults cover all)
    parser.add_argument("--tee-scenarios", type=str, default="all", help="Comma-separated scenario keys or 'all'")
    parser.add_argument("--modes", type=str, default="bevcart,runner", help="Comma-separated: bevcart,runner")

    parser.add_argument("--bev-cart-counts", type=str, default="1,2", help="Comma-separated counts: e.g., 1,2")
    parser.add_argument("--bev-order-probs", type=str, default="0.3,0.4,0.5", help="Bev cart pass order probabilities")
    parser.add_argument("--bev-price-usd", type=float, default=12.0, help="Bev cart price per order")

    parser.add_argument("--runner-counts", type=str, default="1-4", help="Runner counts: range '1-4' or list '1,2,3' ")
    parser.add_argument("--delivery-order-probs", type=str, default="0.1,0.2,0.3", help="Delivery order probability per nine")
    parser.add_argument("--prevent-front-1-5", action="store_true", help="[Deprecated] Also include variant preventing ordering on holes 1-5")
    parser.add_argument("--front9-prob-if-prevent", type=float, default=0.1, help="Front-9 order prob if preventing front holes (used for 1-5 or custom variants)")
    parser.add_argument("--front-preventions", type=str, default="none,1-3,1-6", help="Comma-separated prevention variants to run: any of 'none', '1-3', '1-5', '1-6'")
    parser.add_argument("--runner-speed-mps", type=float, default=2.68, help="Runner speed in m/s")
    parser.add_argument("--prep-time-min", type=int, default=10, help="Food preparation time in minutes")

    parser.add_argument("--seed-base", type=int, default=12345, help="Base seed; actual seeds are derived per run")

    args = parser.parse_args()
    init_logging(args.log_level)

    # Context and dimensions
    ctx = _init_batch_output(args.output_dir)
    ctx.course_dir = args.course_dir

    scenario_keys = _load_scenario_keys(args.course_dir, args.tee_scenarios)
    modes = [m.strip().lower() for m in str(args.modes).split(",") if m.strip()]

    bev_cart_counts = _parse_int_list_or_range(args.bev_cart_counts)
    bev_order_probs = _parse_float_list(args.bev_order_probs)

    runner_counts = _parse_int_list_or_range(args.runner_counts)
    delivery_probs = _parse_float_list(args.delivery_order_probs)

    # Build prevention variants
    front_preventions_raw = [t.strip().lower() for t in str(args.front_preventions).split(",") if t.strip()]
    variants: List[Dict[str, Any]] = []
    seen_upto: set = set()
    for tok in front_preventions_raw:
        if tok in ("none", "0", "no", "false"):
            if 0 not in seen_upto:
                variants.append({"label": "none", "upto": 0, "front_prob": None})
                seen_upto.add(0)
        elif tok in ("1-3", "1_to_3", "1..3"):
            if 3 not in seen_upto:
                variants.append({"label": "front1_3", "upto": 3, "front_prob": 0.15})
                seen_upto.add(3)
        elif tok in ("1-6", "1_to_6", "1..6"):
            if 6 not in seen_upto:
                variants.append({"label": "front1_6", "upto": 6, "front_prob": 0.10})
                seen_upto.add(6)
        elif tok in ("1-5", "1_to_5", "1..5"):
            if 5 not in seen_upto:
                variants.append({"label": "front1_5", "upto": 5, "front_prob": float(args.front9_prob_if_prevent)})
                seen_upto.add(5)
    if 0 not in seen_upto:
        variants.insert(0, {"label": "none", "upto": 0, "front_prob": None})
    if args.prevent_front_1_5 and 5 not in seen_upto:
        variants.append({"label": "front1_5", "upto": 5, "front_prob": float(args.front9_prob_if_prevent)})

    logger.info("Batch starting. Output: %s", ctx.output_root)

    run_counter = 0
    for scenario in scenario_keys:
        if "bevcart" in modes:
            for num_carts in bev_cart_counts:
                for p in bev_order_probs:
                    for r in range(1, int(args.runs_per_combo) + 1):
                        seed = int(args.seed_base) + (run_counter * 1000) + r
                        _run_bevcart_once(
                            ctx=ctx,
                            course_dir=args.course_dir,
                            scenario=scenario,
                            run_index=r,
                            num_carts=int(num_carts),
                            bev_order_prob=float(p),
                            price_per_order=float(args.bev_price_usd),
                            seed=seed,
                        )
                        run_counter += 1

        if "runner" in modes:
            for num_runners in runner_counts:
                for p in delivery_probs:
                    for variant in variants:
                        for r in range(1, int(args.runs_per_combo) + 1):
                            seed = int(args.seed_base) + (run_counter * 1000) + r
                            _run_runner_once(
                                ctx=ctx,
                                course_dir=args.course_dir,
                                scenario=scenario,
                                run_index=r,
                                num_runners=int(num_runners),
                                delivery_prob_per_9=float(p),
                                prevent_front_upto_hole=int(variant["upto"]),
                                front9_prob_if_prevent=variant["front_prob"],
                                runner_speed_mps=float(args.runner_speed_mps),
                                prep_time_min=int(args.prep_time_min),
                                seed=seed,
                                prevention_label=variant["label"],
                            )
                            run_counter += 1

    logger.info("Batch complete. Stats: %s, Events: %s", ctx.stats_csv, ctx.events_csv)
    # Generate summaries at the end of the batch
    _generate_end_of_batch_summaries(ctx)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


