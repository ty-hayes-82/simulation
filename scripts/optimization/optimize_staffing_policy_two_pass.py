#!/usr/bin/env python3
"""
Two-pass staffing and blocking policy optimizer.

Pass 1 (first_pass):
- Run 10 simulations with minimal outputs for ALL variant/runner combinations.

Pass 2 (second_pass):
- For the recommended option(s) per orders level, run another 10 simulations
  without the minimal-output flags to generate richer artifacts.

Notes:
- This substitutes the staged 4/8/8 logic with a simpler 10 + 10 confirmation.
- Outputs are organized under `<output_root>/<stamp>_<scenario>/{first_pass|second_pass}/orders_XXX/...`.

Example (single course):
  python scripts/optimization/optimize_staffing_policy_two_pass.py --course-dir courses/pinetree_country_club --tee-scenario real_tee_sheet --orders-levels 20 30 40 50 --runner-range 1-3 --concurrency 3

Example (all courses):
  python scripts/optimization/optimize_staffing_policy_two_pass.py --run-all-courses --tee-scenario real_tee_sheet --orders-levels 10 20 30 40 50 --runner-range 1-3 --concurrency 10
"""

from __future__ import annotations

import argparse
import json
import math
import csv
import os
import re
import shutil
import subprocess
import sys
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
from dataclasses import dataclass, field
import geopandas as gpd

# Heatmap aggregation
from golfsim.viz.heatmap_viz import create_course_heatmap

# GEOJSON EXPORT
from golfsim.viz.heatmap_viz import load_geofenced_holes

# Optional .env loader (for GEMINI_API_KEY/GOOGLE_API_KEY)
try:
    from dotenv import load_dotenv as _load_dotenv  # type: ignore
except Exception:
    _load_dotenv = None

@dataclass
class BlockingVariant:
    key: str
    cli_flags: List[str]
    description: str


BLOCKING_VARIANTS: List[BlockingVariant] = [
    BlockingVariant(key="none", cli_flags=[], description="no blocked holes"),
    BlockingVariant(key="front", cli_flags=["--block-holes", "1", "2", "3"], description="block holes 1–3"),
    BlockingVariant(key="back", cli_flags=["--block-holes", "10", "11", "12"], description="block holes 10–12"),
    BlockingVariant(key="front_mid", cli_flags=["--block-holes", "1", "2", "3", "4", "5", "6"], description="block holes 1–6"),
    BlockingVariant(key="front_back", cli_flags=["--block-holes", "1", "2", "3", "10", "11", "12"], description="block holes 1–3 & 10–12"),
    BlockingVariant(key="front_mid_back", cli_flags=["--block-holes", "1", "2", "3", "4", "5", "6", "10", "11", "12"], description="block holes 1–6 & 10–12"),
]


def parse_range(spec: str) -> List[int]:
    spec = spec.strip()
    if "-" in spec:
        a, b = spec.split("-", 1)
        return list(range(int(a), int(b) + 1))
    return [int(spec)]


def mean(values: Iterable[float]) -> float:
    vals = list(values)
    return (sum(vals) / len(vals)) if vals else 0.0


def wilson_ci(successes: int, total: int, confidence: float = 0.95) -> Tuple[float, float]:
    if total <= 0:
        return (0.0, 0.0)
    z = 1.96 if abs(confidence - 0.95) < 1e-6 else 1.96
    phat = successes / total
    denom = 1 + z * z / total
    center = phat + z * z / (2 * total)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * total)) / total)
    lower = (center - margin) / denom
    upper = (center + margin) / denom
    return (max(0.0, lower), min(1.0, upper))


@dataclass
class RunMetrics:
    on_time_rate: float
    failed_rate: float
    p90: float
    avg: float
    orders_per_runner_hour: float
    successful_orders: int
    total_orders: int
    delivery_stats: List[Dict[str, Any]]
    # New fields for detailed delivery metrics
    queue_wait_avg: Optional[float] = None
    runner_utilization_pct: Optional[float] = None
    runner_utilization_by_runner: Dict[str, float] = field(default_factory=dict)
    runner_utilization_driving_pct: Optional[float] = None
    total_revenue: Optional[float] = None
    failed_orders: Optional[int] = None
    active_runner_hours: Optional[float] = None


def load_one_run_metrics(run_dir: Path) -> Optional[RunMetrics]:
    # Prefer detailed metrics JSON
    for path in run_dir.glob("delivery_runner_metrics_run_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        
        # Load delivery_stats from results.json for heatmap data
        delivery_stats: List[Dict[str, Any]] = []
        try:
            results_path = run_dir / "results.json"
            if results_path.exists():
                results_data = json.loads(results_path.read_text(encoding="utf-8"))
                delivery_stats = results_data.get("delivery_stats") or []
        except Exception:
            pass # Non-fatal if results.json is missing or malformed

        # Extract new detailed metrics
        queue_wait_avg = data.get("queue_wait_avg")
        runner_utilization_driving_pct = data.get("runner_utilization_driving_pct")
        runner_utilization_prep_pct = data.get("runner_utilization_prep_pct")
        runner_utilization_pct = None
        if runner_utilization_driving_pct is not None:
            runner_utilization_pct = float(runner_utilization_driving_pct) + float(runner_utilization_prep_pct or 0.0)
        
        total_revenue = data.get("total_revenue")
        failed_orders = data.get("failed_orders")
        active_runner_hours = data.get("active_runner_hours")

        return RunMetrics(
            on_time_rate=float(data.get("on_time_rate", 0.0) or 0.0),
            failed_rate=float(data.get("failed_rate", 0.0) or 0.0),
            p90=float(data.get("delivery_cycle_time_p90", 0.0) or 0.0),
            avg=float(data.get("delivery_cycle_time_avg", 0.0) or 0.0),
            orders_per_runner_hour=float(data.get("orders_per_runner_hour", 0.0) or 0.0),
            successful_orders=int(data.get("successful_orders", data.get("successfulDeliveries", 0)) or 0),
            total_orders=int(data.get("total_orders", data.get("totalOrders", 0)) or 0),
            delivery_stats=delivery_stats,
            queue_wait_avg=float(queue_wait_avg) if queue_wait_avg is not None else None,
            runner_utilization_pct=runner_utilization_pct,
            runner_utilization_driving_pct=float(runner_utilization_driving_pct) if runner_utilization_driving_pct is not None else None,
            total_revenue=float(total_revenue) if total_revenue is not None else None,
            failed_orders=int(failed_orders) if failed_orders is not None else None,
            active_runner_hours=float(active_runner_hours) if active_runner_hours is not None else None,
        )

    # Fallback simulation_metrics.json
    sm = run_dir / "simulation_metrics.json"
    if sm.exists():
        try:
            data = json.loads(sm.read_text(encoding="utf-8"))
            dm = data.get("deliveryMetrics") or {}
            
            # Extract runner utilization breakdown
            runner_util_breakdown = {}
            raw_rubr = (dm.get("runnerUtilizationByRunner") or {})
            if isinstance(raw_rubr, dict):
                for runner_id, stats in raw_rubr.items():
                    if isinstance(stats, dict) and "utilizationPct" in stats:
                        try:
                            runner_util_breakdown[runner_id] = float(stats["utilizationPct"])
                        except (ValueError, TypeError):
                            continue

            on_time_pct = float(dm.get("onTimePercentage", 0.0) or 0.0) / 100.0
            successful = int(dm.get("successfulDeliveries", 0) or 0)
            total = int(dm.get("totalOrders", 0) or 0)
            failed = int(dm.get("failedDeliveries", 0) or (total - successful))
            failed_rate = (failed / total) if total > 0 else 0.0
            # Try to extract p90 from fallback JSON if available
            p90_val = float(dm.get("deliveryCycleTimeP90", float("nan")) or float("nan"))
            avg_val = float(dm.get("avgOrderTime", 0.0) or 0.0)
            
            # Try to load delivery_stats from results.json in fallback path too
            delivery_stats_fallback: List[Dict[str, Any]] = []
            try:
                results_path = run_dir / "results.json"
                if results_path.exists():
                    results_data = json.loads(results_path.read_text(encoding="utf-8"))
                    delivery_stats_fallback = results_data.get("delivery_stats") or []
            except Exception:
                pass

            return RunMetrics(
                on_time_rate=on_time_pct,
                failed_rate=failed_rate,
                p90=p90_val,
                avg=avg_val,
                orders_per_runner_hour=float(dm.get("ordersPerRunnerHour", 0.0) or 0.0),
                successful_orders=successful,
                total_orders=total,
                delivery_stats=delivery_stats_fallback,
                queue_wait_avg=float(dm.get("queueWaitAvg")) if dm.get("queueWaitAvg") is not None else None,
                runner_utilization_pct=float(dm.get("runnerUtilizationPct")) if dm.get("runnerUtilizationPct") is not None else None,
                runner_utilization_by_runner=runner_util_breakdown,
                runner_utilization_driving_pct=None,  # Not available in simulation_metrics.json
                total_revenue=float(dm.get("revenue")) if dm.get("revenue") is not None else None,
                failed_orders=failed,
                active_runner_hours=None,  # Not available in simulation_metrics.json
            )
        except Exception:
            return None
    return None


def aggregate_runs(run_dirs: List[Path]) -> Dict[str, Any]:
    items: List[RunMetrics] = []
    for rd in run_dirs:
        m = load_one_run_metrics(rd)
        if m is not None:
            items.append(m)
    if not items:
        return {"runs": 0}

    on_time_vals = [m.on_time_rate for m in items if not math.isnan(m.on_time_rate)]
    failed_vals = [m.failed_rate for m in items if not math.isnan(m.failed_rate)]
    p90_vals = [m.p90 for m in items if not math.isnan(m.p90)]
    avg_vals = [m.avg for m in items if not math.isnan(m.avg)]
    oph_vals = [m.orders_per_runner_hour for m in items if not math.isnan(m.orders_per_runner_hour)]

    # Aggregate drive time per hole from all delivery_stats
    total_drive_time_per_hole: Dict[int, float] = {}
    orders_per_hole: Dict[int, int] = {}
    for m in items:
        for stat in m.delivery_stats:
            try:
                hole = int(stat.get("hole_num", 0))
                drive_time = float(stat.get("delivery_time_s", 0.0))  # Use one-way delivery time, not total_drive_time_s
                if not math.isnan(drive_time):
                    total_drive_time_per_hole[hole] = total_drive_time_per_hole.get(hole, 0.0) + drive_time
                    orders_per_hole[hole] = orders_per_hole.get(hole, 0) + 1
            except (ValueError, TypeError):
                continue

    avg_drive_time_per_hole: Dict[int, float] = {
        hole: total_drive_time_per_hole.get(hole, 0.0) / orders_per_hole.get(hole, 1)
        for hole in orders_per_hole.keys()
    }

    total_successes = sum(m.successful_orders for m in items)
    total_orders = sum(m.total_orders for m in items)
    ot_lo, ot_hi = wilson_ci(total_successes, total_orders, confidence=0.95)

    # --- New Detailed Metrics Aggregation ---
    
    # 1. Runner utilization imbalance
    all_runner_utils: List[float] = []
    for m in items:
        if m.runner_utilization_by_runner:
            all_runner_utils.extend(m.runner_utilization_by_runner.values())
    
    runner_utilization_imbalance = {}
    if all_runner_utils:
        runner_utilization_imbalance = {
            "min": min(all_runner_utils) if all_runner_utils else 0.0,
            "max": max(all_runner_utils) if all_runner_utils else 0.0,
            "std_dev": statistics.stdev(all_runner_utils) if len(all_runner_utils) > 1 else 0.0,
            "mean": mean(all_runner_utils),
        }

    # 2. Queue wait time
    queue_wait_vals = [m.queue_wait_avg for m in items if m.queue_wait_avg is not None and not math.isnan(m.queue_wait_avg)]
    avg_queue_wait_minutes = mean(queue_wait_vals) if queue_wait_vals else None

    # 3. Delivery time histogram and Peak/Off-peak analysis
    all_delivery_times_min: List[float] = []
    peak_delivery_times_min: List[float] = []
    
    # Assuming simulation starts at 7 AM for peak hour calculation
    SIM_START_TIME_HR = 7.0
    PEAK_START_HR = 11.5  # 11:30 AM
    PEAK_END_HR = 13.5    # 1:30 PM

    for m in items:
        for stat in m.delivery_stats:
            try:
                # delivery_time_s is one-way, use total_completion_time_s for full cycle
                cycle_time_s = float(stat.get("total_completion_time_s", 0.0))
                order_time_s = float(stat.get("order_time_s", -1.0))

                if not math.isnan(cycle_time_s):
                    all_delivery_times_min.append(cycle_time_s / 60.0)
                
                # Peak time analysis
                if order_time_s >= 0:
                    order_hour_of_day = SIM_START_TIME_HR + (order_time_s / 3600.0)
                    if PEAK_START_HR <= order_hour_of_day < PEAK_END_HR:
                        peak_delivery_times_min.append(cycle_time_s / 60.0)

            except (ValueError, TypeError):
                continue

    delivery_time_histogram = {}
    if all_delivery_times_min:
        bins = {"under_15_min": 0, "15_to_20_min": 0, "20_to_25_min": 0, "over_25_min": 0}
        for t in all_delivery_times_min:
            if t < 15:
                bins["under_15_min"] += 1
            elif 15 <= t < 20:
                bins["15_to_20_min"] += 1
            elif 20 <= t < 25:
                bins["20_to_25_min"] += 1
            else:
                bins["over_25_min"] += 1
        total_deliveries = len(all_delivery_times_min)
        delivery_time_histogram = {k: round(v / total_deliveries, 3) for k, v in bins.items()}

    peak_metrics = {}
    if peak_delivery_times_min:
        peak_metrics = {
            "avg_delivery_time": mean(peak_delivery_times_min),
            "p90": sorted(peak_delivery_times_min)[int(len(peak_delivery_times_min) * 0.9)] if peak_delivery_times_min else 0.0,
            "order_count": len(peak_delivery_times_min)
        }

    # --- End of New Metrics ---

    return {
        "runs": len(items),
        "on_time_mean": mean(on_time_vals),
        "failed_mean": mean(failed_vals),
        "p90_mean": mean(p90_vals) if p90_vals else float("nan"),
        "avg_delivery_time_mean": mean(avg_vals) if avg_vals else float("nan"),
        "oph_mean": mean(oph_vals),
        "avg_drive_time_per_hole": avg_drive_time_per_hole,
        "total_drive_time_per_hole": total_drive_time_per_hole,
        "orders_per_hole": orders_per_hole,
        "on_time_wilson_lo": ot_lo,
        "on_time_wilson_hi": ot_hi,
        "total_successful_orders": total_successes,
        "total_orders": total_orders,
        "raw_metrics": items,  # Pass raw metrics for detailed summary
        # --- New Detailed Metrics ---
        "runner_utilization_imbalance": runner_utilization_imbalance,
        "avg_queue_wait_minutes": avg_queue_wait_minutes,
        "delivery_time_histogram": delivery_time_histogram,
        "peak_hours_metrics": peak_metrics,
    }


def blocking_penalty(variant_key: str) -> float:
    """Return a penalty score for blocking variants (higher = more disruptive)."""
    penalties = {
        "none": 0.0,
        "front": 1.0,
        "back": 1.0,
        "front_mid": 2.0,
        "front_back": 2.0,
        "front_mid_back": 3.0,
    }
    return penalties.get(variant_key, 0.0)


def utility_score(variant_key: str, runners: int, agg: Dict[str, Any]) -> float:
    """Compute utility score balancing runners, blocking, and performance metrics.
    Lower is better (minimization problem).
    """
    # Weights for different factors
    alpha_runners = 1.0      # Cost of additional runners
    beta_blocking = 0.5      # Cost of blocking holes
    gamma_p90 = 0.02         # Cost per minute of p90 delivery time
    delta_on_time = -10.0    # Benefit of higher on-time rate (negative = reward)
    epsilon_failed = 20.0    # Cost of failed deliveries
    
    on_time_lo = float(agg.get("on_time_wilson_lo", 0.0) or 0.0)
    failed_mean = float(agg.get("failed_mean", 1.0) or 1.0)
    p90_mean = float(agg.get("p90_mean", 60.0) or 60.0)  # Default to 60 min if missing
    if math.isnan(p90_mean):
        p90_mean = 60.0  # Penalize missing p90 data
    
    score = (
        alpha_runners * runners +
        beta_blocking * blocking_penalty(variant_key) +
        gamma_p90 * p90_mean +
        delta_on_time * on_time_lo +
        epsilon_failed * failed_mean
    )
    return score


def choose_best_variant(results_by_variant: Dict[str, Dict[int, Dict[str, Any]]], *, target_on_time: float, max_failed: float, max_p90: float) -> Optional[Tuple[str, int, Dict[str, Any]]]:
    # Find all candidates that meet targets (with strict p90 enforcement)
    candidates: List[Tuple[str, int, Dict[str, Any]]] = []
    for variant_key, per_runner in results_by_variant.items():
        for n in sorted(per_runner.keys()):
            agg = per_runner[n]
            if not agg or not agg.get("runs"):
                continue
            
            p90_mean = agg.get("p90_mean", float("nan"))
            # If p90 data is available, enforce the target; if missing (NaN), allow it to pass
            p90_meets = math.isnan(p90_mean) or p90_mean <= max_p90
            
            meets = (
                agg.get("on_time_wilson_lo", 0.0) >= target_on_time
                and agg.get("failed_mean", 1.0) <= max_failed
                and p90_meets
            )
            if meets:
                candidates.append((variant_key, n, agg))

    if not candidates:
        return None

    # Sort by utility score (lower is better)
    candidates.sort(key=lambda t: utility_score(t[0], t[1], t[2]))
    return candidates[0]


def choose_top_variants(
    results_by_variant: Dict[str, Dict[int, Dict[str, Any]]], *, target_on_time: float, max_failed: float, max_p90: float
) -> List[Tuple[str, int, Dict[str, Any]]]:
    """Find all candidates that meet targets and return the top 3 based on utility score."""
    candidates: List[Tuple[str, int, Dict[str, Any]]] = []
    for variant_key, per_runner in results_by_variant.items():
        for n in sorted(per_runner.keys()):
            agg = per_runner[n]
            if not agg or not agg.get("runs"):
                continue

            p90_mean = agg.get("p90_mean", float("nan"))
            p90_meets = math.isnan(p90_mean) or p90_mean <= max_p90

            meets = (
                agg.get("on_time_wilson_lo", 0.0) >= target_on_time
                and agg.get("failed_mean", 1.0) <= max_failed
                and p90_meets
            )
            if meets:
                candidates.append((variant_key, n, agg))

    if not candidates:
        return []

    candidates.sort(key=lambda t: utility_score(t[0], t[1], t[2]))
    return candidates[:3]


def _make_group_context(*, course_dir: Path, tee_scenario: str, orders: int, variant_key: str, runners: int) -> Dict[str, Any]:
    return {
        "course": str(course_dir),
        "tee_scenario": tee_scenario,
        "orders": int(orders),
        "variant": variant_key,
        "runners": int(runners),
    }


def _write_group_aggregate_file(group_dir: Path, context: Dict[str, Any], agg: Dict[str, Any]) -> None:
    """Persist per-group aggregate so it can be referenced later.

    Writes an '@aggregate.json' file under the provided group directory
    (e.g., .../orders_030/none/runners_2/@aggregate.json).
    """
    try:
        # Avoid serializing raw_metrics which can be large and contains objects
        serializable_agg = agg.copy()
        if "raw_metrics" in serializable_agg:
            del serializable_agg["raw_metrics"]

        payload: Dict[str, Any] = {
            **context,
            **serializable_agg,
            "group_dir": str(group_dir),
        }
        (group_dir / "@aggregate.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except Exception:
        # Non-fatal: continue even if we cannot write
        pass


def _write_group_aggregate_heatmap(
    group_dir: Path,
    *,
    course_dir: Path,
    tee_scenario: str,
    variant_key: str,
    runners: int,
    run_dirs: List[Path],
) -> Optional[Path]:
    """Create a single averaged heatmap.png for a runners group by combining all runs.

    The heatmap uses concatenated orders and delivery_stats from each run's results.json
    and is written to `<group_dir>/heatmap.png`.
    """
    try:
        combined: Dict[str, Any] = {"orders": [], "delivery_stats": []}
        for rd in run_dirs:
            rp = rd / "results.json"
            if not rp.exists():
                continue
            try:
                data = json.loads(rp.read_text(encoding="utf-8"))
            except Exception:
                continue

            # To avoid cross-run collisions where order_ids typically restart at 1
            # for every run, we rewrite order_id values with a run-specific suffix
            # for both orders and delivery_stats before concatenation.
            run_tag = rd.name  # e.g., "run_01"

            raw_orders = data.get("orders") or []
            raw_stats = data.get("delivery_stats") or []

            if isinstance(raw_orders, list):
                rewritten_orders: List[Dict[str, Any]] = []
                for idx, o in enumerate(raw_orders):
                    try:
                        oi = o.copy()
                        base_id = oi.get("order_id", f"order_{idx}")
                        oi["order_id"] = f"{base_id}@{run_tag}"
                        rewritten_orders.append(oi)
                    except Exception:
                        # Best-effort: skip malformed entry
                        continue
                combined["orders"].extend(rewritten_orders)

            if isinstance(raw_stats, list):
                rewritten_stats: List[Dict[str, Any]] = []
                for idx, s in enumerate(raw_stats):
                    try:
                        si = s.copy()
                        base_id = si.get("order_id", f"order_{idx}")
                        si["order_id"] = f"{base_id}@{run_tag}"
                        rewritten_stats.append(si)
                    except Exception:
                        continue
                combined["delivery_stats"].extend(rewritten_stats)

        # If no orders found across runs, skip
        if not combined["orders"]:
            return None

        course_name = Path(str(course_dir)).name.replace("_", " ").title()
        title = (
            f"{course_name} - Delivery Runner Heatmap (Avg across {len(run_dirs)} runs)\n"
            f"Variant: {variant_key} | Runners: {runners} | Scenario: {tee_scenario}"
        )
        save_path = group_dir / "heatmap.png"
        create_course_heatmap(
            results=combined,
            course_dir=course_dir,
            save_path=save_path,
            title=title,
            colormap="white_to_red",
        )
        return save_path
    except Exception:
        return None


def _csv_headers() -> List[str]:
    return [
        "course",
        "tee_scenario",
        "orders",
        "variant",
        "runners",
        "runs",
        "on_time_mean",
        "on_time_wilson_lo",
        "on_time_wilson_hi",
        "failed_mean",
        "p90_mean",
        "avg_delivery_time_mean",
        "oph_mean",
        "avg_queue_wait_minutes",
        "runner_utilization_mean",
        "runner_utilization_std_dev",
        "delivery_time_histogram",
        "peak_hours_avg_delivery_time",
        "avg_drive_time_per_hole",
        "total_drive_time_per_hole",
        "orders_per_hole",
        "total_successful_orders",
        "total_orders",
        "group_dir",
    ]


def _row_from_context_and_agg(context: Dict[str, Any], agg: Dict[str, Any], group_dir: Path) -> Dict[str, Any]:
    row: Dict[str, Any] = {
        **{k: context.get(k) for k in ["course", "tee_scenario", "orders", "variant", "runners"]},
        "runs": agg.get("runs"),
        "on_time_mean": agg.get("on_time_mean"),
        "on_time_wilson_lo": agg.get("on_time_wilson_lo"),
        "on_time_wilson_hi": agg.get("on_time_wilson_hi"),
        "failed_mean": agg.get("failed_mean"),
        "p90_mean": agg.get("p90_mean"),
        "avg_delivery_time_mean": agg.get("avg_delivery_time_mean"),
        "oph_mean": agg.get("oph_mean"),
        "avg_queue_wait_minutes": agg.get("avg_queue_wait_minutes"),
        "runner_utilization_mean": (agg.get("runner_utilization_imbalance") or {}).get("mean"),
        "runner_utilization_std_dev": (agg.get("runner_utilization_imbalance") or {}).get("std_dev"),
        "delivery_time_histogram": json.dumps(agg.get("delivery_time_histogram")),
        "peak_hours_avg_delivery_time": (agg.get("peak_hours_metrics") or {}).get("avg_delivery_time"),
        "avg_drive_time_per_hole": json.dumps(agg.get("avg_drive_time_per_hole")),
        "total_drive_time_per_hole": json.dumps(agg.get("total_drive_time_per_hole")),
        "orders_per_hole": json.dumps(agg.get("orders_per_hole")),
        "total_successful_orders": agg.get("total_successful_orders"),
        "total_orders": agg.get("total_orders"),
        "group_dir": str(group_dir),
    }
    return row


def _row_from_saved_aggregate(agg_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Build a CSV row directly from a saved @aggregate.json payload.

    Ensures parity with _row_from_context_and_agg so CSV and aggregates stay in sync.
    """
    try:
        # Context fields are written alongside metrics in the payload
        row: Dict[str, Any] = {
            "course": agg_payload.get("course"),
            "tee_scenario": agg_payload.get("tee_scenario"),
            "orders": int(agg_payload.get("orders")) if agg_payload.get("orders") is not None else None,
            "variant": agg_payload.get("variant"),
            "runners": int(agg_payload.get("runners")) if agg_payload.get("runners") is not None else None,
            "runs": agg_payload.get("runs"),
            "on_time_mean": agg_payload.get("on_time_mean"),
            "on_time_wilson_lo": agg_payload.get("on_time_wilson_lo"),
            "on_time_wilson_hi": agg_payload.get("on_time_wilson_hi"),
            "failed_mean": agg_payload.get("failed_mean"),
            "p90_mean": agg_payload.get("p90_mean"),
            "avg_delivery_time_mean": agg_payload.get("avg_delivery_time_mean"),
            "oph_mean": agg_payload.get("oph_mean"),
            "avg_queue_wait_minutes": agg_payload.get("avg_queue_wait_minutes"),
            "runner_utilization_mean": (agg_payload.get("runner_utilization_imbalance") or {}).get("mean"),
            "runner_utilization_std_dev": (agg_payload.get("runner_utilization_imbalance") or {}).get("std_dev"),
            "delivery_time_histogram": json.dumps(agg_payload.get("delivery_time_histogram")),
            "peak_hours_avg_delivery_time": (agg_payload.get("peak_hours_metrics") or {}).get("avg_delivery_time"),
            "avg_drive_time_per_hole": json.dumps(agg_payload.get("avg_drive_time_per_hole")),
            "total_drive_time_per_hole": json.dumps(agg_payload.get("total_drive_time_per_hole")),
            "orders_per_hole": json.dumps(agg_payload.get("orders_per_hole")),
            "total_successful_orders": agg_payload.get("total_successful_orders"),
            "total_orders": agg_payload.get("total_orders"),
            "group_dir": str(agg_payload.get("group_dir") or ""),
        }
        return row
    except Exception:
        # Best-effort: skip malformed aggregates
        return {}


def _collect_rows_from_saved_aggregates(root: Path) -> List[Dict[str, Any]]:
    """Scan first_pass and second_pass for @aggregate.json and build CSV rows.

    Preference order: second_pass overrides first_pass for identical (course, tee_scenario, orders, variant, runners).
    """
    rows: List[Dict[str, Any]] = []
    # Prefer second_pass values when duplicates exist
    for pass_dir in [root / "second_pass", root / "first_pass"]:
        if not pass_dir.exists():
            continue
        for agg_path in pass_dir.rglob("@aggregate.json"):
            try:
                payload = json.loads(agg_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            row = _row_from_saved_aggregate(payload)
            if not row:
                continue
            _upsert_row(rows, row)
    return rows


def _write_final_csv(root: Path, rows: List[Dict[str, Any]]) -> Optional[Path]:
    try:
        csv_path = root / "all_metrics.csv"
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=_csv_headers())
            writer.writeheader()
            for r in rows:
                writer.writerow(r)
        return csv_path
    except Exception:
        return None


def _upsert_row(rows: List[Dict[str, Any]], new_row: Dict[str, Any]) -> None:
    """Insert or replace a row identified by (course, tee_scenario, orders, variant, runners)."""
    key = (
        new_row.get("course"),
        new_row.get("tee_scenario"),
        int(new_row.get("orders", 0)),
        new_row.get("variant"),
        int(new_row.get("runners", 0)),
    )
    for i, r in enumerate(rows):
        rkey = (
            r.get("course"),
            r.get("tee_scenario"),
            int(r.get("orders", 0)),
            r.get("variant"),
            int(r.get("runners", 0)),
        )
        if rkey == key:
            rows[i] = new_row
            return
    rows.append(new_row)


def _write_group_delivery_geojson(
    group_dir: Path,
    *,
    course_dir: Path,
    tee_scenario: str,
    variant_key: str,
    runners: int,
) -> Optional[Path]:
    """Create a `hole_delivery_times.geojson` for this group using its aggregate data."""
    try:
        agg_path = group_dir / "@aggregate.json"
        if not agg_path.exists():
            return None

        with agg_path.open("r", encoding="utf-8") as f:
            agg_data = json.load(f)

        # Reformat aggregate data into the hole_stats structure
        hole_stats: Dict[int, Dict[str, Union[float, int]]] = {}
        avg_times = agg_data.get("avg_drive_time_per_hole", {})
        orders_counts = agg_data.get("orders_per_hole", {})

        for hole_str, avg_time_sec in avg_times.items():
            try:
                hole_num = int(hole_str)
                count = int(orders_counts.get(hole_str, 0))
                if count > 0:
                    hole_stats[hole_num] = {
                        "avg_time": float(avg_time_sec) / 60.0,  # Convert to minutes
                        "count": count,
                        "min_time": 0.0,
                        "max_time": 0.0,
                    }
            except (ValueError, TypeError):
                continue
        
        hole_polygons = load_geofenced_holes(course_dir)
        feature_collection = build_feature_collection(hole_polygons, hole_stats)

        save_path = group_dir / "hole_delivery_times.geojson"
        with save_path.open("w", encoding="utf-8") as f:
            json.dump(feature_collection, f)
        
        return save_path
    except Exception:
        return None


def build_feature_collection(
    hole_polygons: Dict[int, Any],
    hole_stats: Dict[int, Dict[str, Union[float, int]]],
) -> Dict[str, Any]:
    """Build a GeoJSON FeatureCollection of hole polygons with delivery stats.

    Each feature contains properties:
      - hole: int
      - has_data: bool
      - avg_time, min_time, max_time, count (when available)
    """
    features: list[Dict[str, Any]] = []

    for hole_num, geom in hole_polygons.items():
        props: Dict[str, Any] = {"hole": int(hole_num)}
        stats = hole_stats.get(hole_num)
        if stats:
            props.update(
                {
                    "has_data": True,
                    "avg_time": float(stats.get("avg_time", 0.0)),
                    "min_time": float(stats.get("min_time", 0.0)),
                    "max_time": float(stats.get("max_time", 0.0)),
                    "count": int(stats.get("count", 0)),
                }
            )
        else:
            props.update({"has_data": False})

        # Convert shapely geometry to GeoJSON-like mapping
        gdf = gpd.GeoDataFrame({"geometry": [geom]}, crs="EPSG:4326")
        feature_geom = json.loads(gdf.to_json())["features"][0]["geometry"]

        features.append(
            {
                "type": "Feature",
                "properties": props,
                "geometry": feature_geom,
            }
        )

    return {"type": "FeatureCollection", "features": features}


def _call_gemini(prompt: str) -> Optional[str]:
    """Call Google Gemini with the given prompt if configured; otherwise return None.

    Requires environment variable GEMINI_API_KEY (or GOOGLE_API_KEY) and the
    package `google-generativeai` to be installed.
    """
    try:
        api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if not api_key:
            return None
        # Lazy import so the script runs without this dependency present
        try:
            import google.generativeai as genai  # type: ignore
        except (ImportError, KeyboardInterrupt, SystemExit) as e:
            # Handle import failures gracefully, including KeyboardInterrupt during import
            return None
        genai.configure(api_key=api_key)
        model_name = os.environ.get("GEMINI_MODEL", "gemini-2.5-pro")
        model = genai.GenerativeModel(model_name)
        resp = model.generate_content(prompt)
        # Prefer resp.text if available
        text = getattr(resp, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
        # Fallback to stringifying
        return str(resp).strip() or None
    except (KeyboardInterrupt, SystemExit):
        # Re-raise these specific exceptions
        raise
    except Exception:
        return None


def _write_executive_summary_markdown(
    *,
    out_dir: Path,
    course_dir: Path,
    tee_scenario: str,
    orders_levels: List[int],
    summary: Dict[int, Dict[str, Any]],
    targets: Dict[str, float],
) -> Tuple[Optional[Path], bool]:
    """Create an executive summary Markdown file under out_dir.

    Attempts to use Gemini for a polished summary; otherwise writes a concise
    local summary. Returns the path if written.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "executive_summary.md"

    # Build compact data for LLM prompt and for fallback
    variant_desc = {v.key: v.description for v in BLOCKING_VARIANTS}
    compact: List[Dict[str, Any]] = []
    for orders in sorted(summary.keys()):
        chosen = summary[orders].get("chosen") or {}
        chosen_variant = chosen.get("variant")
        chosen_runners = chosen.get("runners")
        metrics = chosen.get("metrics") or {}
        baseline_info = summary[orders].get("baseline_none") or {}
        baseline_runners = baseline_info.get("runners")
        baseline_metrics = (baseline_info.get("metrics") or {})
        # Collect all variant metrics for comparison
        variant_comparisons = {}
        for variant_key, per_runner in summary[orders].get("per_variant", {}).items():
            if variant_key in per_runner:
                # Find the minimal runner count that meets targets for this variant
                for n in sorted(per_runner.keys()):
                    agg = per_runner[n]
                    if not agg or not agg.get("runs"):
                        continue
                    p90_mean = agg.get("p90_mean", float("nan"))
                    p90_meets = math.isnan(p90_mean) or p90_mean <= targets.get("max_p90", 40.0)
                    meets = (
                        agg.get("on_time_wilson_lo", 0.0) >= targets.get("on_time", 0.90)
                        and agg.get("failed_mean", 1.0) <= targets.get("max_failed", 0.05)
                        and p90_meets
                    )
                    if meets:
                        variant_comparisons[variant_key] = {
                            "runners": n,
                            "avg_delivery_time": agg.get("avg_delivery_time_mean"),
                            "p90_mean": agg.get("p90_mean"),
                            "on_time_wilson_lo": agg.get("on_time_wilson_lo"),
                            "failed_mean": agg.get("failed_mean"),
                            "oph_mean": agg.get("oph_mean"),
                        }
                        break

        compact.append({
            "orders": int(orders),
            "recommended_variant": chosen_variant,
            "recommended_variant_description": variant_desc.get(str(chosen_variant), variant_desc.get(chosen_variant, chosen_variant)),
            "recommended_runners": chosen_runners,
            "runs": metrics.get("runs"),
            "on_time_wilson_lo": metrics.get("on_time_wilson_lo"),
            "failed_mean": metrics.get("failed_mean"),
            "p90_mean": metrics.get("p90_mean"),
            "avg_delivery_time_mean": metrics.get("avg_delivery_time_mean"),
            "orders_per_runner_hour": metrics.get("oph_mean"),
            "baseline_none_runners": baseline_runners,
            "baseline_on_time_wilson_lo": (baseline_metrics or {}).get("on_time_wilson_lo"),
            "baseline_failed_mean": (baseline_metrics or {}).get("failed_mean"),
            "baseline_p90_mean": (baseline_metrics or {}).get("p90_mean"),
            "baseline_avg_delivery_time": (baseline_metrics or {}).get("avg_delivery_time_mean"),
            "baseline_oph_mean": (baseline_metrics or {}).get("oph_mean"),
            "variant_comparisons": variant_comparisons,
        })

    # Build list of available blocking variants for the prompt
    variant_options = []
    for v in BLOCKING_VARIANTS:
        variant_options.append(f"- '{v.key}': {v.description}")
    variant_list = "\n".join(variant_options)
    
    # Build deterministic data-driven sections (table, quick guide, confidence) -----------------
    orders_levels_sorted: List[int] = sorted(int(o) for o in orders_levels)

    # Derive per-orders rows and confidence
    def _confidence_for_metrics(m: Dict[str, Any]) -> str:
        try:
            runs_cnt = int(m.get("runs") or 0)
            ot_lo = float(m.get("on_time_wilson_lo", 0.0) or 0.0)
            failed_mean = float(m.get("failed_mean", 0.0) or 0.0)
            near_edges = (
                abs(ot_lo - float(targets.get("on_time", 0.90))) <= 0.01
                or abs(failed_mean - float(targets.get("max_failed", 0.05))) <= 0.005
            )
            return "High" if (runs_cnt >= 16 and not near_edges) else ("Medium" if runs_cnt >= 8 else "Low")
        except Exception:
            return "Medium"

    # Build deterministic staffing table (Orders/hr | Baseline | Optimized | Policy)
    table_lines: List[str] = []
    table_lines.append("| Orders/hr | Baseline Runners (No Blocking) | Optimized Runners (With Blocking) | Policy |")
    table_lines.append("|-----------|-------------------------------:|-----------------------------------:|--------|")
    quick_guide_lines: List[str] = []
    confidence_lines: List[str] = []

    # Map orders -> row info from compact
    orders_to_compact: Dict[int, Dict[str, Any]] = {int(r["orders"]): r for r in compact}

    for orders in orders_levels_sorted:
        row = orders_to_compact.get(int(orders), {})
        base_runners = row.get("baseline_none_runners")
        runners = row.get("recommended_runners")
        variant_desc_val = row.get("recommended_variant_description") or "none"
        policy_short = variant_desc_val.replace("block holes ", "").replace(" & ", "+") if variant_desc_val != "none" else "none"

        # Table
        table_lines.append(
            f"| {int(orders)} | {base_runners if base_runners is not None else '?'} | {runners if runners is not None else '?'} | {policy_short} |"
        )

        # Quick guide bullets (data-driven, no invented ranges)
        if runners is not None:
            quick_guide_lines.append(
                f"- {int(orders)} orders/hr: schedule {int(runners)} runner(s) and use '{policy_short}' blocking."
            )

        # Confidence per orders-level
        m = (summary.get(int(orders), {}).get("chosen") or {}).get("metrics") or {}
        confidence_lines.append(
            f"**{int(orders)} orders/hr**: { _confidence_for_metrics(m) } confidence."
        )

    # Build variant insights (avg order time differences across passing variants) ---------------
    insights_lines: List[str] = []
    try:
        # Helper: check if a given metrics dict meets targets
        def _meets(agg: Dict[str, Any]) -> bool:
            try:
                if not agg or not agg.get("runs"):
                    return False
                ot_ok = float(agg.get("on_time_wilson_lo", 0.0) or 0.0) >= float(targets.get("on_time", 0.90))
                fail_ok = float(agg.get("failed_mean", 1.0) or 1.0) <= float(targets.get("max_failed", 0.05))
                p90_v = agg.get("p90_mean", float("nan"))
                p90_ok = math.isnan(p90_v) or float(p90_v) <= float(targets.get("max_p90", 40.0))
                return bool(ot_ok and fail_ok and p90_ok)
            except Exception:
                return False

        # Find the best orders level and runner count to compare based on which combination
        # has the most passing variants (must be > 1 to be useful).
        best_comparison_candidate: Tuple[Optional[int], Optional[int], int] = (None, None, 0)  # (orders, runners, count)

        for orders_level in orders_levels_sorted:
            per_orders_summary = summary.get(int(orders_level), {})
            per_variant = per_orders_summary.get("per_variant", {}) or {}

            passing_variants_by_runner: Dict[int, int] = {}
            for v_key, per_runner in per_variant.items():
                for r_count_str, agg in per_runner.items():
                    r_count = int(r_count_str)
                    if _meets(agg):
                        passing_variants_by_runner[r_count] = passing_variants_by_runner.get(r_count, 0) + 1

            if not passing_variants_by_runner:
                continue

            max_passing_count = 0
            best_runner_for_level: Optional[int] = None
            for r_count, num_passing in passing_variants_by_runner.items():
                if num_passing > max_passing_count:
                    max_passing_count = num_passing
                    best_runner_for_level = r_count

            if max_passing_count > 1 and max_passing_count > best_comparison_candidate[2]:
                best_comparison_candidate = (orders_level, best_runner_for_level, max_passing_count)

        target_orders_level, runner_to_compare, _ = best_comparison_candidate

        # Build insights rows for the chosen runner count and orders level
        if runner_to_compare is not None and target_orders_level is not None:
            per_orders_summary = summary.get(int(target_orders_level), {})
            per_variant = per_orders_summary.get("per_variant", {}) or {}
            variant_desc_map_local: Dict[str, str] = {v.key: v.description for v in BLOCKING_VARIANTS}
            rows: List[Tuple[str, int, float, float, float]] = []  # (policy, runners, avg, p90, on_time)
            for v_key, per_runner in per_variant.items():
                agg = per_runner.get(int(runner_to_compare))
                if not agg or not _meets(agg):
                    continue
                avg_v = agg.get("avg_delivery_time_mean")
                p90_v = agg.get("p90_mean")
                ot_lo_v = agg.get("on_time_wilson_lo")
                try:
                    avg_f = float(avg_v) if avg_v is not None else float("nan")
                    p90_f = float(p90_v) if p90_v is not None else float("nan")
                    ot_f = float(ot_lo_v) if ot_lo_v is not None else float("nan")
                except Exception:
                    continue
                policy_desc = variant_desc_map_local.get(v_key, v_key)
                policy_short = policy_desc.replace("block holes ", "").replace(" & ", "+") if policy_desc != "none" else "none"
                rows.append((policy_short, int(runner_to_compare), avg_f, p90_f, ot_f))

            # Only show if we have at least 2 passing variants to compare
            rows = [r for r in rows if not math.isnan(r[2])]
            if len(rows) >= 2:
                rows.sort(key=lambda x: x[2])  # sort by avg delivery time asc
                insights_lines.append("### Variant insights — average order time differences")
                insights_lines.append("")
                insights_lines.append(f"At {int(target_orders_level)} orders/hr with {int(runner_to_compare)} runner(s), multiple policies meet targets but differ in speed:")
                insights_lines.append("")
                insights_lines.append("| Policy | Runners | Avg time (min) | P90 (min) | On-time (conservative) |")
                insights_lines.append("|--------|---------:|---------------:|----------:|------------------------:|")
                for policy_short, r_cnt, avg_f, p90_f, ot_f in rows:
                    avg_str = f"{avg_f:.1f}" if not math.isnan(avg_f) else "?"
                    p90_str = f"{p90_f:.0f}" if not math.isnan(p90_f) else "?"
                    ot_str = f"{ot_f*100:.0f}%" if not math.isnan(ot_f) else "?"
                    insights_lines.append(f"| {policy_short} | {r_cnt} | {avg_str} | {p90_str} | {ot_str} |")
                insights_lines.append("")
                # Call out the fastest option
                best = rows[0]
                insights_lines.append(
                    f"Fastest among passing policies: {best[0]} with ~{best[2]:.1f} min average."
                )
                insights_lines.append("")
    except Exception:
        # Insights are best-effort; ignore errors silently to keep report generation robust
        insights_lines = []

    # Gemini prompt ONLY for a short summary paragraph -----------------------------------------
    orders_levels_str = ", ".join(str(o) for o in orders_levels_sorted)
    prompt = (
        "You are advising a golf course General Manager. Write a concise 2-3 sentence summary in Markdown. "
        "Be direct and actionable. Do not include any tables or bullet lists.\n\n"
        f"Course: {course_dir}\n"
        f"Tee scenario: {tee_scenario}\n"
        f"Targets: on_time ≥ {targets.get('on_time')}, failed_rate ≤ {targets.get('max_failed')}, p90 ≤ {targets.get('max_p90')} min\n"
        f"Simulated orders levels (MUST use only these if mentioned): [{orders_levels_str}]\n\n"
        f"Available blocking variants:\n{variant_list}\n\n"
        "Data (summaries):\n" + json.dumps(compact, indent=2) + "\n\n"
        "Constraints:\n"
        "- Do NOT invent new order volumes (e.g., 20/hr or 30/hr if not listed).\n"
        "- Avoid Low/Medium/High buckets unless they directly map to the listed orders.\n"
        "- Do NOT include a date; the caller will add it.\n"
        "- Focus on the staffing vs blocking tradeoff and when blocking helps.\n"
    )

    llm_summary = _call_gemini(prompt)
    used_gemini = bool(llm_summary)

    # Sanitize summary: remove any sentences referencing un-simulated orders/hr values
    def _remove_unlisted_order_refs(text: str, allowed: List[int]) -> str:
        try:
            import re
            allowed_set = set(int(x) for x in allowed)
            # Split into sentences; conservative split on period/newline
            parts = re.split(r"(?<=[.!?])\s+|\n+", text)
            kept: List[str] = []
            for p in parts:
                # Find patterns like '10/hr' or '10 orders/hr'
                bad = False
                for m in re.finditer(r"\b(\d{1,3})\s*(?:orders\s*/\s*hr|/\s*hr)\b", p):
                    val = int(m.group(1))
                    if val not in allowed_set:
                        bad = True
                        break
                if not bad and p.strip():
                    kept.append(p.strip())
            # Rejoin with space
            return " ".join(kept).strip()
        except Exception:
            return text

    if llm_summary:
        llm_summary = _remove_unlisted_order_refs(llm_summary, orders_levels_sorted)
        if not llm_summary:
            used_gemini = False

    if not llm_summary:
        llm_summary = (
            "Strategic blocking of selected holes reduces runner requirements while maintaining on-time targets. "
            "Use minimal blocking at lower volumes and progressively expand only when service targets are at risk."
        )

    # Compose final Markdown ----------------------------------------------------------------------------------
    from datetime import datetime
    course_name = Path(str(course_dir)).name.replace("_", " ").title()
    today_str = datetime.now().strftime("%B %d, %Y")

    lines: List[str] = []
    lines.append(f"### **Executive Summary: F&B Delivery for {course_name}**")
    lines.append("")
    lines.append("**To:** General Manager")
    lines.append(f"**Date:** {today_str}")
    lines.append("**Subject:** Runner Staffing & Delivery Optimization")
    lines.append("")
    lines.append("### 1. Summary")
    lines.append("")
    lines.append(llm_summary.strip())
    lines.append("")
    lines.append("### 2. Staffing Table")
    lines.append("")
    lines.append("This table is rendered from the actual simulation results.")
    lines.append("")
    lines.extend(table_lines)
    lines.append("")
    if insights_lines:
        lines.extend(insights_lines)
        lines.append("")
    lines.append("### 3. Quick Guide: Action Plan")
    lines.append("")
    if len(quick_guide_lines) == 1:
        lines.append("Use the following for the simulated volume:")
    else:
        lines.append("Adjust operations based on the simulated orders levels:")
    lines.append("")
    lines.extend(quick_guide_lines)
    lines.append("")
    lines.append("### 4. Confidence in Projections")
    lines.append("")
    lines.extend(confidence_lines)
    lines.append("")
    if used_gemini:
        lines.append("_Source: Gemini_")

    try:
        md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return md_path, used_gemini
    except Exception:
        return None, used_gemini


def _write_gm_staffing_policy_report(
    *,
    out_dir: Path,
    course_dir: Path,
    tee_scenario: str,
    orders_levels: List[int],
    summary: Dict[int, Dict[str, Any]],
    targets: Dict[str, float],
) -> Optional[Path]:
    """Generate a GM-facing staffing policy report in Markdown following the
    docs/gm_staffing_policy_report.md layout as closely as possible, using
    aggregated results from this optimization run.

    Returns the written path or None on error.
    """
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    md_path = out_dir / "gm_staffing_policy_report.md"

    # Helpers ---------------------------------------------------------------
    def _fmt_pct(x: Optional[float], *, digits: int = 0) -> str:
        try:
            if x is None or math.isnan(float(x)):
                return "?"
            return f"{float(x) * 100:.{digits}f}%"
        except Exception:
            return "?"

    def _fmt_min(x: Optional[float], *, digits: int = 1) -> str:
        try:
            if x is None or math.isnan(float(x)):
                return "?"
            return f"{float(x):.{digits}f}"
        except Exception:
            return "?"

    def _fmt_int(x: Optional[float]) -> str:
        try:
            if x is None or math.isnan(float(x)):
                return "?"
            return f"{int(round(float(x)))}"
        except Exception:
            return "?"

    variant_desc_map: Dict[str, str] = {v.key: v.description for v in BLOCKING_VARIANTS}
    course_name = Path(str(course_dir)).name.replace("_", " ").title()
    tee_name = str(tee_scenario).replace("_", " ").title()

    # Build recommended staffing rows --------------------------------------
    rec_rows: List[Dict[str, Any]] = []
    baseline_savings_notes: List[str] = []
    unmet_notes: List[str] = []
    top_candidate_rows: List[Dict[str, Any]] = []
    tested_variants: set = set()
    tested_runner_counts: set = set()
    for orders in sorted(orders_levels):
        info = summary.get(orders, {})
        chosen = info.get("chosen", {}) or {}
        chosen_variant = chosen.get("variant")
        chosen_runners = chosen.get("runners")
        m = chosen.get("metrics") or {}
        baseline_info = info.get("baseline_none", {}) or {}
        base_runners = baseline_info.get("runners")
        base_metrics = baseline_info.get("metrics") or {}

        # Confidence heuristic: high if we have ~20 total runs or comfortably inside targets
        runs_cnt = int(m.get("runs") or 0)
        ot_lo = float(m.get("on_time_wilson_lo", 0.0) or 0.0)
        failed_mean = float(m.get("failed_mean", 0.0) or 0.0)
        p90_mean = m.get("p90_mean", float("nan"))
        near_edges = (
            abs(ot_lo - float(targets.get("on_time", 0.90))) <= 0.01
            or abs(failed_mean - float(targets.get("max_failed", 0.05))) <= 0.005
        )
        confidence = "High" if (runs_cnt >= 16 and not near_edges) else ("Medium" if runs_cnt >= 8 else "Low")

        # Track tested variants and runner counts for context and fallback summaries
        per_variant: Dict[str, Dict[int, Dict[str, Any]]] = info.get("per_variant", {}) or {}
        for v_key, per_runner in per_variant.items():
            tested_variants.add(variant_desc_map.get(v_key, v_key))
            for r_count in per_runner.keys():
                try:
                    tested_runner_counts.add(int(r_count))
                except Exception:
                    continue

        rec_rows.append({
            "orders": orders,
            "policy": variant_desc_map.get(str(chosen_variant), variant_desc_map.get(chosen_variant, str(chosen_variant))),
            "runners": chosen_runners,
            "on_time": _fmt_pct(m.get("on_time_wilson_lo"), digits=0),
            "failed": _fmt_pct(m.get("failed_mean"), digits=1),
            "avg_min": _fmt_min(m.get("avg_delivery_time_mean"), digits=1),
            "p90": _fmt_int(m.get("p90_mean")),
            "oph": _fmt_min(m.get("oph_mean"), digits=1),
            "confidence": confidence,
        })

        if base_runners is not None and chosen_runners is not None and int(base_runners) > int(chosen_runners):
            baseline_savings_notes.append(
                f"- Baseline (no blocking) would require {base_runners} runner(s) at {orders} orders/hr. Recommended policy saves {int(base_runners) - int(chosen_runners)} runner(s)."
            )

        # If no policy met targets, synthesize helpful notes and top candidates
        if chosen_variant is None or chosen_runners is None or not m:
            # Determine max runners tested for this orders level
            max_runners_tested = max([int(r) for v in per_variant.values() for r in v.keys()] or [0])

            unmet_notes.append(
                f"- At {orders} orders/hr, no policy met targets up to {max_runners_tested} runner(s)."
            )

            # Build a scored list of near-miss candidates across variants and runner counts
            scored: List[Tuple[int, str, int, Dict[str, Any]]] = []  # (score, variant_key, runners, metrics)
            for v_key, per_runner in per_variant.items():
                for r_count, agg in per_runner.items():
                    if not agg or not agg.get("runs"):
                        continue
                    ot_lo_v = float(agg.get("on_time_wilson_lo", 0.0) or 0.0)
                    failed_v = float(agg.get("failed_mean", 1.0) or 1.0)
                    p90_v = float(agg.get("p90_mean", float("inf")) or float("inf"))
                    # Violations: on_time below target, failed above target, p90 above target
                    violations = 0
                    if ot_lo_v < float(targets.get("on_time", 0.90)):
                        violations += 1
                    if failed_v > float(targets.get("max_failed", 0.05)):
                        violations += 1
                    if not math.isnan(p90_v) and p90_v > float(targets.get("max_p90", 40.0)):
                        violations += 1
                    # Score: prioritize fewer violations, then lower p90, then higher on_time, then lower failed, then fewer runners
                    score_tuple = (
                        violations,
                        int(p90_v) if not math.isnan(p90_v) else 10**6,
                        int(-round(ot_lo_v * 1000)),
                        int(round(failed_v * 1000)),
                        int(r_count),
                    )
                    scored.append((score_tuple[0], v_key, int(r_count), {**agg, "score_tuple": score_tuple}))

            # Take top 3 candidates by score
            scored.sort(key=lambda x: x[3]["score_tuple"])  # sort by the composite tuple
            for item in scored[:3]:
                _, v_key, r_count, agg = item
                top_candidate_rows.append({
                    "orders": orders,
                    "policy": variant_desc_map.get(v_key, v_key),
                    "runners": r_count,
                    "on_time": _fmt_pct(agg.get("on_time_wilson_lo"), digits=0),
                    "failed": _fmt_pct(agg.get("failed_mean"), digits=1),
                    "avg_min": _fmt_min(agg.get("avg_delivery_time_mean"), digits=1),
                    "p90": _fmt_int(agg.get("p90_mean")),
                    "oph": _fmt_min(agg.get("oph_mean"), digits=1),
                    "note": "Does not meet targets",
                })

    # Build Markdown --------------------------------------------------------
    lines: List[str] = []
    lines.append("### Staffing and Blocking Policy Recommendation")
    lines.append(f"Course: {course_name}  ")
    lines.append(f"Tee scenario: {tee_name}  ")
    lines.append(
        f"Targets: on-time ≥ {int(targets.get('on_time', 0.90) * 100)}%, failed deliveries ≤ {int(targets.get('max_failed', 0.05) * 100)}%, p90 ≤ {int(targets.get('max_p90', 40.0))} min  "
    )
    lines.append("Source: `scripts/optimization/optimize_staffing_policy_two_pass.py` (two-pass optimization with enhanced metrics)")
    lines.append("")
    lines.append("## Executive summary")
    lines.append("- Strategic blocking of specific holes can reduce the number of runners needed while keeping service within target thresholds.")
    lines.append("- Two-pass optimization: 10 minimal runs for all combinations, then 10 full runs for top candidates.")
    lines.append("- Enhanced metrics include runner utilization imbalance, queue wait time breakdown, delivery time histograms, and peak-hour analysis.")
    lines.append("")
    lines.append("## Recommended staffing by volume")
    lines.append("- \"Conservative on-time\" is the lower bound of the 95% Wilson interval.")
    lines.append("- \"Policy\" is the minimal-blocking variant that met targets with the fewest runners; ties broken by a utility function (runners < blocking < p90 < on-time < failed).")
    lines.append("")
    # Staffing table
    lines.append("| Orders/hr | Policy | Runners | On-time (conservative) | Failed | Avg time (min) | p90 (min) | Orders/Runner/Hr | Confidence |")
    lines.append("|-----------|--------|---------|------------------------|--------|----------------|-----------|------------------|------------|")
    for r in rec_rows:
        policy_str = str(r['policy']).title() if r['policy'] not in (None, 'none') else 'None'
        runners_str = str(r['runners']) if r['runners'] is not None else 'n/a'
        lines.append(
            f"| {r['orders']}        | {policy_str} | {runners_str} | {r['on_time']}                 | {r['failed']}   | {r['avg_min']}           | {r['p90']}        | {r['oph']}              | {r['confidence']}     |"
        )
    lines.append("")
    if baseline_savings_notes:
        lines.append("Notes:")
        lines.extend(baseline_savings_notes)
        lines.append("")

    # Unmet targets notes and top candidates (if any)
    if unmet_notes:
        lines.append("Unmet targets:")
        lines.extend(unmet_notes)
        lines.append("")
        if top_candidate_rows:
            lines.append("Top candidates (did not meet targets):")
            lines.append("| Orders/hr | Policy | Runners | On-time (conservative) | Failed | Avg time (min) | p90 (min) | Orders/Runner/Hr | Note |")
            lines.append("|-----------|--------|---------|------------------------|--------|----------------|-----------|------------------|------|")
            for r in top_candidate_rows:
                lines.append(
                    f"| {r['orders']}        | {str(r['policy']).title()} | {r['runners']} | {r['on_time']}                 | {r['failed']}   | {r['avg_min']}           | {r['p90']}        | {r['oph']}              | {r['note']} |"
                )
            lines.append("")

    # Operational interpretation
    lines.append("")
    lines.append("## What this means operationally")
    for r in rec_rows:
        lines.append(
            f"- At {r['orders']} orders/hr: Use {r['runners']} runner(s) with policy \"{r['policy']}\" to keep on-time around {r['on_time']} and p90 ≈ {r['p90']} min."
        )

    # Quick playbook (simple thresholds from provided orders levels)
    lines.append("")
    lines.append("## Quick playbook")
    if rec_rows:
        for i, r in enumerate(rec_rows):
            lo = rec_rows[i - 1]["orders"] + 1 if i > 0 else r["orders"]
            hi = rec_rows[i + 1]["orders"] - 1 if i + 1 < len(rec_rows) else r["orders"]
            if lo == hi:
                range_text = f"{lo} orders/hr"
            else:
                range_text = f"{lo}–{hi} orders/hr"
            if r['runners'] is None:
                lines.append(f"- {range_text}: No tested policy met targets up to {max(tested_runner_counts) if tested_runner_counts else '?'} runner(s).")
            else:
                lines.append(f"- {range_text}: {r['policy']}; {r['runners']} runner(s).")

    # Data context and next steps -----------------------------------------------------------------
    lines.append("")
    lines.append("## Data context")
    lines.append(f"- Orders levels analyzed: {', '.join(str(o) for o in sorted(orders_levels))}")
    if tested_runner_counts:
        lines.append(f"- Runner counts tested: {min(tested_runner_counts)}–{max(tested_runner_counts)}")
    if tested_variants:
        lines.append(f"- Variants tested: {', '.join(sorted(str(v) for v in tested_variants))}")

    lines.append("")
    lines.append("## Next steps")
    if unmet_notes:
        lines.append("- Increase runner range (e.g., --runner-range 1-4) and re-run optimization.")
        lines.append("- Increase confirmation runs (e.g., --second-pass-runs 20) for tighter estimates.")
        lines.append("- Review targets or policies; consider enabling broader blocking if operations allow.")
    else:
        lines.append("- Validate staffing vs. utilization during peak windows and adjust blocking as needed.")

    # Operational guardrails and checks (static, aligned with docs)
    lines.append("")
    lines.append("## Operational guardrails")
    lines.append("- Trigger to add a runner:")
    lines.append("  - Conservative on-time < 90% for 15 minutes OR")
    lines.append("  - p90 > 40 min for 10 minutes with utilization rising OR")
    lines.append("  - Failed > 5% at any time")
    lines.append("- Trigger to lift blocking:")
    lines.append("  - Conservative on-time ≥ 92% for 30 minutes and p90 ≤ 35 min")
    lines.append("- Route health checks:")
    lines.append("  - Ensure blocked segments are clearly communicated to runners and tee sheet operations.")
    lines.append("  - Validate that start/end coordinates for runners map to valid graph nodes (prevents routing stalls).")
    lines.append("")
    lines.append("- Data artifacts written per group:")
    lines.append("  - `@aggregate.json` in each group directory (roll-up of metrics with enhanced data)")
    lines.append("  - `all_metrics.csv` at the optimization root (all groups combined)")
    lines.append("  - Optional `executive_summary.md` (human summary)")
    lines.append("  - `gm_staffing_policy_report.md` (this report)")

    try:
        md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return md_path
    except Exception:
        return None


def run_combo(
    *,
    py: str,
    course_dir: Path,
    scenario: str,
    runners: int,
    orders: int,
    runs: int,
    out: Path,
    log_level: str,
    variant: BlockingVariant,
    runner_speed: Optional[float],
    prep_time: Optional[int],
    minimal_output: bool,
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    cmd: List[str] = [
        py,
        "scripts/sim/run_new.py",
        "--course-dir",
        str(course_dir),
        "--tee-scenario",
        scenario,
        "--num-runners",
        str(runners),
        "--delivery-total-orders",
        str(orders),
        "--num-runs",
        str(runs),
        "--output-dir",
        str(out),
        "--log-level",
        log_level,
    ]

    # Minimal outputs only for first pass
    if minimal_output:
        cmd += ["--minimal-outputs"]
    # Always ensure only run_01 coordinates are generated and avoid auto-publish
    # so that aggregation and map copying are handled centrally after optimization
    cmd += ["--coordinates-only-for-first-run", "--skip-publish"]

    if variant.cli_flags:
        cmd += variant.cli_flags
    if runner_speed is not None:
        cmd += ["--runner-speed", str(runner_speed)]
    if prep_time is not None:
        cmd += ["--prep-time", str(prep_time)]
    subprocess.run(cmd, check=True)


def _collect_run_dirs(
    root: Path, orders: int, variant_key: str, runners: int, include_first: bool = True, include_second: bool = True
) -> List[Path]:
    """Collect run_* directories from first_pass and/or second_pass for a specific combo."""
    run_dirs: List[Path] = []
    details = f"orders_{orders:03d}/runners_{runners}/{variant_key}"
    if include_first:
        fp = root / "first_pass" / details
        if fp.exists():
            run_dirs += sorted([p for p in fp.glob("run_*") if p.is_dir()])
    if include_second:
        sp = root / "second_pass" / details
        if sp.exists():
            run_dirs += sorted([p for p in sp.glob("run_*") if p.is_dir()])
    return run_dirs


def meets_targets(agg: Dict[str, Any], args: argparse.Namespace) -> bool:
    """Check if an aggregated result meets performance targets."""
    if not agg or not agg.get("runs"):
        return False

    p90_mean = agg.get("p90_mean", float("nan"))
    p90_meets = math.isnan(p90_mean) or p90_mean <= args.max_p90

    return (
        agg.get("on_time_wilson_lo", 0.0) >= args.target_on_time
        and agg.get("failed_mean", 1.0) <= args.max_failed_rate
        and p90_meets
    )


def _publish_map_assets(*, optimization_root: Path, project_root: Path) -> None:
    """Finds and copies simulation artifacts to the map app's public directories."""

    # --- BEGIN MAP ASSETS PUBLISHING LOGIC ---
    # This code is moved and adapted from my-map-animation/run_map_app.py

    # Path Configuration
    map_animation_dir = project_root / "my-map-animation"
    public_dirs = [str(map_animation_dir / "public")]
    setup_public_dir = project_root / "my-map-setup" / "public"
    coordinates_dir_name = "coordinates"
    local_csv_file = str(map_animation_dir / "public" / "coordinates.csv")
    sim_base_dir = str(optimization_root)

    def _humanize(name: str) -> str:
        name = name.replace("-", " ").replace("_", " ").strip()
        parts = [p for p in name.split(" ") if p]
        return " ".join(w.capitalize() for w in parts) if parts else name

    def _parse_simulation_folder_name(folder_name: str) -> Dict[str, str]:
        result = {
            "date": "",
            "time": "",
            "bev_carts": "0",
            "runners": "0",
            "golfers": "0",
            "scenario": "",
            "original": folder_name,
        }
        if "_" in folder_name:
            parts = folder_name.split("_")
            if len(parts) > 0 and len(parts[0]) == 8 and parts[0].isdigit():
                result["date"] = parts[0]
                if len(parts) > 1 and len(parts[1]) == 6 and parts[1].isdigit():
                    result["time"] = parts[1]
                    config_parts = parts[2:]
                    config_str = "_".join(config_parts)
                    bev_match = re.search(r"(\d+)bev_?carts?", config_str, re.IGNORECASE)
                    if bev_match:
                        result["bev_carts"] = bev_match.group(1)
                    runner_match = re.search(r"(\d+)_?runners?", config_str, re.IGNORECASE)
                    if runner_match:
                        result["runners"] = runner_match.group(1)
                    golfer_match = re.search(r"(\d+)golfers?", config_str, re.IGNORECASE)
                    if golfer_match:
                        result["golfers"] = golfer_match.group(1)
                    scenario_parts = []
                    for part in config_parts:
                        if not (
                            re.match(r"^\d+[a-zA-Z]+$", part) or re.match(r"^(sim|run)_\d+$", part, re.IGNORECASE)
                        ):
                            scenario_parts.append(part)
                    if scenario_parts:
                        result["scenario"] = "_".join(scenario_parts)
        return result

    def _format_simple_simulation_name(parsed: Dict[str, str]) -> str:
        components = []
        config_parts = []
        if parsed["bev_carts"] != "0":
            config_parts.append(f"{parsed['bev_carts']} Cart{'s' if parsed['bev_carts'] != '1' else ''}")
        if parsed["runners"] != "0":
            config_parts.append(f"{parsed['runners']} Runner{'s' if parsed['runners'] != '1' else ''}")
        if parsed["golfers"] != "0":
            config_parts.append(f"{parsed['golfers']} Golfer{'s' if parsed['golfers'] != '1' else ''}")
        if config_parts:
            components.append(" + ".join(config_parts))
        if parsed["scenario"]:
            scenario_name = _humanize(parsed["scenario"])
            components.append(scenario_name)
        if "variant_key" in parsed and parsed["variant_key"] != "none":
            components.append(f"({_humanize(parsed['variant_key'])})")
        return " | ".join(components) if components else parsed["original"]

    def _create_group_name(parsed: Dict[str, str]) -> str:
        if parsed["scenario"]:
            return _humanize(parsed["scenario"])
        if parsed["bev_carts"] != "0" and parsed["runners"] != "0":
            return "Mixed Operations"
        elif parsed["bev_carts"] != "0":
            return "Beverage Cart Only"
        elif parsed["runners"] != "0":
            return "Delivery Runners Only"
        else:
            return "Other Simulations"

    def _get_course_id_from_run_dir(run_dir: Path) -> Optional[str]:
        try:
            results_path = run_dir / "results.json"
            if not results_path.exists():
                return None
            with results_path.open("r", encoding="utf-8") as f:
                results = json.load(f)
            course_dir_str = results.get("metadata", {}).get("course_dir")
            if isinstance(course_dir_str, str) and course_dir_str:
                return os.path.basename(course_dir_str.replace("\\", "/").rstrip("/"))
        except Exception:
            pass
        return None

    def _sanitize_and_copy_coordinates_csv(source_path: str, target_path: str) -> None:
        import csv as _csv

        with open(source_path, "r", newline="", encoding="utf-8") as fsrc:
            reader = _csv.DictReader(fsrc)
            fieldnames = reader.fieldnames or []
            rows = list(reader)
        first_move_ts_by_id: Dict[str, Optional[int]] = {}
        for r in rows:
            rid = str(r.get("id", "") or "")
            rtype = (r.get("type") or "").strip().lower()
            if rtype != "runner" and not rid.startswith("runner"):
                continue
            hole = (r.get("hole") or "").strip().lower()
            try:
                ts = int(float(r.get("timestamp") or 0))
            except Exception:
                continue
            if hole != "clubhouse":
                prev = first_move_ts_by_id.get(rid)
                if prev is None or ts < prev:
                    first_move_ts_by_id[rid] = ts
        filtered: List[Dict[str, str]] = []
        for r in rows:
            rid = str(r.get("id", "") or "")
            rtype = (r.get("type") or "").strip().lower()
            hole = (r.get("hole") or "").strip().lower()
            try:
                ts = int(float(r.get("timestamp") or 0))
            except Exception:
                filtered.append(r)
                continue
            first_move_ts = first_move_ts_by_id.get(rid)
            if (
                (rtype == "runner" or rid.startswith("runner"))
                and hole == "clubhouse"
                and first_move_ts is not None
                and ts < int(first_move_ts)
            ):
                continue
            filtered.append(r)
        chosen: Dict[Tuple[str, int], Dict[str, str]] = {}
        for r in filtered:
            rid = str(r.get("id", "") or "")
            try:
                ts = int(float(r.get("timestamp") or 0))
            except Exception:
                filtered.append(r)
                continue
            key = (rid, ts)
            hole = (r.get("hole") or "").strip().lower()
            if key not in chosen:
                chosen[key] = r
            else:
                prev_hole = (chosen[key].get("hole") or "").strip().lower()
                if prev_hole == "clubhouse" and hole != "clubhouse":
                    chosen[key] = r
        deduped = list(chosen.values())
        try:
            deduped.sort(key=lambda d: (str(d.get("id", "")), int(float(d.get("timestamp") or 0))))
        except Exception:
            pass
        with open(target_path, "w", newline="", encoding="utf-8") as fdst:
            writer = _csv.DictWriter(fdst, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            for r in deduped:
                writer.writerow(r)

    def find_all_simulations() -> Dict[str, List[Tuple[str, str, str]]]:
        simulations: Dict[str, List[Tuple[str, str, str]]] = {}
        if os.path.exists(local_csv_file):
            any_outputs = (
                any(True for _ in Path(sim_base_dir).rglob("coordinates.csv"))
                if os.path.exists(sim_base_dir)
                else False
            )
            if not any_outputs:
                simulations.setdefault("Local", []).append(("coordinates", "GPS Coordinates", local_csv_file))
        if not os.path.exists(sim_base_dir):
            return simulations
        valid_filenames = {"coordinates.csv", "bev_cart_coordinates.csv"}
        for root, dirs, files in os.walk(sim_base_dir):
            csv_files = [f for f in files if f in valid_filenames]
            if not csv_files:
                continue
            for file_name in csv_files:
                full_path = os.path.join(root, file_name)
                rel_path = os.path.relpath(full_path, sim_base_dir)
                parts = rel_path.split(os.sep)
                if len(parts) >= 3:
                    sim_folder_name = parts[-3]
                    run_folder = parts[-2]
                    parsed = _parse_simulation_folder_name(sim_folder_name)
                    group_name = _create_group_name(parsed)
                    base_sim_name = _format_simple_simulation_name(parsed)
                    run_id = run_folder.upper() if run_folder.startswith(("sim_", "run_")) else ""
                    if file_name == "coordinates.csv":
                        friendly_type = "GPS Coordinates"
                    elif file_name == "bev_cart_coordinates.csv":
                        friendly_type = "Beverage Cart GPS"
                    else:
                        friendly_type = os.path.splitext(file_name)[0].replace("_", " ").title()
                    display_components = [base_sim_name]
                    if run_id:
                        display_components.append(run_id)
                    display_components.append(friendly_type)
                    display_name = " | ".join(display_components)
                elif len(parts) >= 2:
                    sim_folder_name = parts[-2]
                    parsed = _parse_simulation_folder_name(sim_folder_name)
                    group_name = _create_group_name(parsed)
                    base_sim_name = _format_simple_simulation_name(parsed)
                    if file_name == "coordinates.csv":
                        friendly_type = "GPS Coordinates"
                    elif file_name == "bev_cart_coordinates.csv":
                        friendly_type = "Beverage Cart GPS"
                    else:
                        friendly_type = os.path.splitext(file_name)[0].replace("_", " ").title()
                    display_name = f"{base_sim_name} | {friendly_type}"
                else:
                    group_name = "Simulations"
                    display_name = f"Coordinates ({os.path.splitext(file_name)[0]})"
                sim_id = rel_path.replace(os.sep, "_").replace(".csv", "")
                simulations.setdefault(group_name, []).append((sim_id, display_name, full_path))
        sorted_simulations: Dict[str, List[Tuple[str, str, str]]] = {}
        for group in sorted(simulations.keys()):
            sorted_simulations[group] = sorted(simulations[group], key=lambda x: x[0])
        return sorted_simulations

    def _derive_combo_key_from_path(csv_path: str) -> Optional[str]:
        try:
            p = Path(csv_path)
            run_dir = p.parent
            variant_dir = run_dir.parent if run_dir.name.startswith("run_") else p.parent
            runners_dir = variant_dir.parent
            orders_dir = runners_dir.parent
            scenario_dir = orders_dir.parent
            if runners_dir.name.startswith("runners_") and orders_dir.name.startswith("orders_"):
                try:
                    n_runners = int(runners_dir.name.split("_")[1])
                except Exception:
                    n_runners = None
                try:
                    orders_val = int(orders_dir.name.split("_")[1])
                except Exception:
                    orders_val = None
                scenario = scenario_dir.name
                variant_key = variant_dir.name
                if n_runners is not None and orders_val is not None:
                    return f"{scenario}|orders_{orders_val:03d}|runners_{n_runners}|{variant_key}"
            for ancestor in p.parents:
                name = ancestor.name
                if ("runners" in name) and ("delivery_runner" in name or "runners_" in name):
                    scenario = None
                    orders_val = None
                    m_orders = re.search(r"orders[_-]?([0-9]{2,3})", name, re.IGNORECASE)
                    if m_orders:
                        try:
                            orders_val = int(m_orders.group(1))
                        except Exception:
                            orders_val = None
                    m_runners = re.search(r"runners[_-]?([0-9]+)", name, re.IGNORECASE)
                    n_runners = int(m_runners.group(1)) if m_runners else None
                    if n_runners and orders_val:
                        scenario = ancestor.parent.name
                        return f"{scenario}|orders_{orders_val:03d}|runners_{n_runners}"
            return None
        except Exception:
            return None

    def _select_representative_runs(all_items: List[Tuple[str, str, str]]) -> Dict[str, str]:
        selection_mode = os.environ.get("RUN_MAP_SELECT_RUNS", "").strip().lower()
        prefer_first_run = selection_mode in {"run_01", "first", "first_run"}
        groups: Dict[str, List[Tuple[str, str, str]]] = {}
        for sim_id, display_name, csv_path in all_items:
            key = _derive_combo_key_from_path(csv_path)
            if key:
                groups.setdefault(key, []).append((sim_id, display_name, csv_path))
        selected: Dict[str, str] = {}

        def load_metrics_for_run(run_dir: Path) -> Dict[str, float]:
            metrics: Dict[str, float] = {}
            try:
                candidates = [
                    *[
                        f
                        for f in os.listdir(run_dir)
                        if f.startswith("delivery_runner_metrics_run_") and f.endswith(".json")
                    ],
                ]
                chosen = None
                if candidates:
                    run_name = run_dir.name.lower()
                    chosen = None
                    for c in candidates:
                        if run_name in c.lower():
                            chosen = c
                            break
                    if not chosen:
                        chosen = sorted(candidates)[0]
                elif (run_dir / "simulation_metrics.json").exists():
                    chosen = "simulation_metrics.json"
                if not chosen:
                    return metrics
                with open(run_dir / chosen, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                return metrics
            try:
                on_time = data.get("on_time_rate")
                failed = data.get("failed_rate")
                p90 = data.get("delivery_cycle_time_p90")
                oph = data.get("orders_per_runner_hour")
                if on_time is None or p90 is None or oph is None:
                    dm = data.get("deliveryMetrics") or {}
                    on_time = dm.get("onTimeRate") if dm is not None else None
                    if isinstance(on_time, (int, float)) and on_time > 1.5:
                        on_time = float(on_time) / 100.0
                    p90 = dm.get("deliveryCycleTimeP90") if dm is not None else None
                    oph = dm.get("ordersPerRunnerHour") if dm is not None else None
                    failed = dm.get("failedRate") if isinstance(dm, dict) else data.get("failed_rate")
                    if isinstance(failed, (int, float)) and failed > 1.5:
                        failed = float(failed) / 100.0
                for k, v in {
                    "on_time": on_time,
                    "failed": failed,
                    "p90": p90,
                    "oph": oph,
                }.items():
                    if isinstance(v, (int, float)) and float("inf") != v and float("-inf") != v:
                        metrics[k] = float(v)
            except Exception:
                pass
            return metrics

        for key, items in groups.items():
            per_run: List[Tuple[str, Path]] = []
            for _, __, csv_path in items:
                run_dir = Path(csv_path).parent
                per_run.append((csv_path, run_dir))
            if len(per_run) <= 1:
                selected[per_run[0][0]] = per_run[0][0]
                continue
            if prefer_first_run:
                try:
                    for csv_path, run_dir in per_run:
                        if run_dir.name.lower() == "run_01":
                            selected[csv_path] = csv_path
                            break
                    else:
                        per_run_sorted = sorted(per_run, key=lambda t: t[1].name)
                        selected[per_run_sorted[0][0]] = per_run_sorted[0][0]
                    continue
                except Exception:
                    pass
            run_metrics: List[Tuple[str, Dict[str, float]]] = []
            for csv_path, run_dir in per_run:
                m = load_metrics_for_run(run_dir)
                run_metrics.append((csv_path, m))
            keys = ["on_time", "failed", "p90", "oph"]
            means: Dict[str, float] = {}
            stds: Dict[str, float] = {}
            for k in keys:
                vals = [m.get(k) for _, m in run_metrics if isinstance(m.get(k), (int, float))]
                if vals:
                    mu = sum(vals) / len(vals)
                    means[k] = mu
                    if len(vals) >= 2:
                        var = sum((x - mu) ** 2 for x in vals) / (len(vals) - 1)
                        stds[k] = (var**0.5) if var > 0 else 1.0
                    else:
                        stds[k] = 1.0
                else:
                    means[k] = 0.0
                    stds[k] = 1.0
            best_csv = per_run[0][0]
            best_dist = float("inf")
            for csv_path, m in run_metrics:
                dist = 0.0
                for k in keys:
                    v = m.get(k)
                    if isinstance(v, (int, float)):
                        z = (v - means[k]) / (stds.get(k) or 1.0)
                        dist += z * z
                if dist < best_dist:
                    best_dist = dist
                    best_csv = csv_path
            selected[best_csv] = best_csv
        return selected

    def get_file_info(file_path: str) -> str:
        try:
            with open(file_path, "r") as f:
                lines = f.readlines()
                if len(lines) > 1:
                    data_rows = len(lines) - 1
                    return f"{data_rows:,} coordinate points"
                else:
                    return "Empty file"
        except Exception as e:
            return f"Error reading file: {e}"

    def _generate_per_run_hole_geojson(run_dir: Path) -> Optional[Path]:
        try:
            results_path = run_dir / "results.json"
            if not results_path.exists():
                return None
            with results_path.open("r", encoding="utf-8") as f:
                results = json.load(f)
            course_dir = None
            try:
                course_dir = results.get("metadata", {}).get("course_dir")
            except Exception:
                course_dir = None
            if not course_dir:
                course_dir = str(project_root / "courses" / "pinetree_country_club")
            from golfsim.viz.heatmap_viz import (
                load_geofenced_holes,
                extract_order_data,
                calculate_delivery_time_stats,
            )

            hole_polygons = load_geofenced_holes(course_dir)
            order_data = extract_order_data(results)
            hole_stats = calculate_delivery_time_stats(order_data)
            import json as _json
            import geopandas as gpd

            features = []
            for hole_num, geom in hole_polygons.items():
                props = {"hole": int(hole_num)}
                stats = hole_stats.get(hole_num)
                if stats:
                    props.update(
                        {
                            "has_data": True,
                            "avg_time": float(stats.get("avg_time", 0.0)),
                            "min_time": float(stats.get("min_time", 0.0)),
                            "max_time": float(stats.get("max_time", 0.0)),
                            "count": int(stats.get("count", 0)),
                        }
                    )
                else:
                    props.update({"has_data": False})
                gdf = gpd.GeoDataFrame({"geometry": [geom]}, crs="EPSG:4326")
                feature_geom = _json.loads(gdf.to_json())["features"][0]["geometry"]
                features.append({"type": "Feature", "properties": props, "geometry": feature_geom})
            fc = {"type": "FeatureCollection", "features": features}
            out_path = run_dir / "hole_delivery_times.geojson"
            with out_path.open("w", encoding="utf-8") as f:
                _json.dump(fc, f)
            return out_path
        except Exception as e:
            return None

    def copy_hole_delivery_geojson(coordinates_dirs: List[str]) -> None:
        source_file = map_animation_dir / "public" / "hole_delivery_times.geojson"
        if os.path.exists(source_file):
            for public_dir in public_dirs:
                target_file = os.path.join(public_dir, "hole_delivery_times.geojson")
                try:
                    temp_target = target_file + ".tmp"
                    shutil.copy2(source_file, temp_target)
                    os.replace(temp_target, target_file)
                except Exception:
                    pass

    def copy_all_coordinate_files(
        all_simulations: Dict[str, List[Tuple[str, str, str]]], preferred_default_id: Optional[str] = None
    ) -> Tuple[bool, List[str]]:
        courses_being_updated = set()
        for _, file_options in all_simulations.items():
            for _, _, source_path in file_options:
                run_dir = Path(source_path).parent
                course_id = _get_course_id_from_run_dir(run_dir)
                if course_id:
                    courses_being_updated.add(course_id)
        if courses_being_updated:
            print(f"ℹ️  This run contains simulations for course(s): {', '.join(courses_being_updated)}")
        try:
            coordinates_dirs = []
            for public_dir in public_dirs:
                try:
                    stale_files = [
                        os.path.join(public_dir, "coordinates.csv"),
                        os.path.join(public_dir, "hole_delivery_times.geojson"),
                        os.path.join(public_dir, "hole_delivery_times_debug.geojson"),
                        os.path.join(public_dir, "simulation_metrics.json"),
                    ]
                    for f in stale_files:
                        if os.path.exists(f):
                            try:
                                os.remove(f)
                            except Exception:
                                pass
                except Exception:
                    pass
                coordinates_dir = os.path.join(public_dir, coordinates_dir_name)
                coordinates_dirs.append(coordinates_dir)
                os.makedirs(coordinates_dir, exist_ok=True)
            simulations_to_keep = []
            manifest_processed = False
            if courses_being_updated:
                for coordinates_dir in coordinates_dirs:
                    manifest_path = os.path.join(coordinates_dir, "manifest.json")
                    if not os.path.exists(manifest_path):
                        continue
                    with open(manifest_path, "r", encoding="utf-8") as f:
                        try:
                            old_manifest = json.load(f)
                        except json.JSONDecodeError:
                            old_manifest = {}
                    current_dir_sims_to_keep = []
                    for sim_entry in old_manifest.get("simulations", []):
                        if sim_entry.get("courseId") in courses_being_updated:
                            for key in ["filename", "heatmapFilename", "metricsFilename", "holeDeliveryGeojson"]:
                                if filename := sim_entry.get(key):
                                    file_to_delete = os.path.join(coordinates_dir, filename)
                                    if os.path.exists(file_to_delete):
                                        try:
                                            os.remove(file_to_delete)
                                        except OSError:
                                            pass
                        else:
                            current_dir_sims_to_keep.append(sim_entry)
                    if not manifest_processed:
                        simulations_to_keep = current_dir_sims_to_keep
                        manifest_processed = True
            manifest = {"simulations": simulations_to_keep, "defaultSimulation": None, "courses": []}
            discovered_courses: Dict[str, str] = {}
            copied_count = 0
            total_size = 0
            id_to_mtime: Dict[str, float] = {}

            def _extract_orders_from_metrics(metrics_path: str) -> int | None:
                try:
                    with open(metrics_path, "r", encoding="utf-8") as f:
                        import json as _json

                        data = _json.load(f)
                    dm = data.get("deliveryMetrics") or {}
                    if isinstance(dm, dict):
                        orders = dm.get("totalOrders") or dm.get("orderCount")
                        if isinstance(orders, (int, float)):
                            return int(orders)
                    for key in ("totalOrders", "orderCount"):
                        if key in data and isinstance(data[key], (int, float)):
                            return int(data[key])
                except Exception:
                    return None
                return None

            def _extract_variant_info_from_metrics(
                metrics_path: str,
            ) -> Tuple[Optional[str], Optional[List[int]]]:
                try:
                    with open(metrics_path, "r", encoding="utf-8") as f:
                        import json as _json

                        data = _json.load(f)
                    variant_key = data.get("variantKey")
                    blocked_holes = data.get("blockedHoles")
                    return variant_key, blocked_holes
                except Exception:
                    return None, None

            flat_items: List[Tuple[str, str, str]] = []
            for gname, items in all_simulations.items():
                for sim_id, disp, src in items:
                    flat_items.append((sim_id, disp, src))
            selected_csvs = _select_representative_runs(flat_items)
            selected_mode_active = len(selected_csvs) > 0
            for group_name, file_options in all_simulations.items():
                for scenario_id, display_name, source_path in file_options:
                    if selected_mode_active:
                        key = _derive_combo_key_from_path(source_path)
                        if key and source_path not in selected_csvs:
                            continue
                    try:
                        p = Path(source_path)
                        parents = list(p.parents)
                        has_orders = any(parent.name.lower().startswith("orders_") for parent in parents)
                        has_delivery_runners = False
                        for parent in parents:
                            name = parent.name.lower()
                            if name.startswith("runners_"):
                                try:
                                    runner_count = int(name.split("_")[1])
                                    if runner_count > 0:
                                        has_delivery_runners = True
                                        break
                                except (ValueError, IndexError):
                                    continue
                        if not has_delivery_runners:
                            for parent in parents:
                                name = parent.name.lower()
                                if "delivery_runner_" in name and "_runners_" in name:
                                    match = re.search(r"_(\d+)_runners_", name)
                                    if match:
                                        try:
                                            runner_count = int(match.group(1))
                                            if runner_count > 0:
                                                has_delivery_runners = True
                                                break
                                        except ValueError:
                                            continue
                        if not (has_orders and has_delivery_runners):
                            continue
                    except Exception:
                        continue
                    if not os.path.exists(source_path):
                        continue
                    target_filename = f"{scenario_id}.csv"
                    all_copies_successful = True
                    sanitized_mode = os.path.basename(source_path) == "coordinates.csv"
                    for coordinates_dir in coordinates_dirs:
                        target_path = os.path.join(coordinates_dir, target_filename)
                        try:
                            if os.path.basename(source_path) == "coordinates.csv":
                                _sanitize_and_copy_coordinates_csv(source_path, target_path)
                            else:
                                shutil.copy2(source_path, target_path)
                        except Exception:
                            all_copies_successful = False
                            break
                        if os.path.exists(target_path):
                            source_size = os.path.getsize(source_path)
                            target_size = os.path.getsize(target_path)
                            if sanitized_mode:
                                if target_size <= 0:
                                    all_copies_successful = False
                                    break
                            else:
                                if source_size != target_size:
                                    all_copies_successful = False
                                    break
                        else:
                            all_copies_successful = False
                            break
                    if all_copies_successful:
                        copied_count += 1
                        total_size += source_size
                        csv_dir = os.path.dirname(source_path)
                        found_heatmap_filename: str | None = None
                        found_metrics_filename: str | None = None
                        found_hole_geojson_filename: str | None = None
                        orders_value: int | None = None
                        variant_key: str | None = "none"
                        blocked_holes: list[int] | None = []
                        for fname in os.listdir(csv_dir):
                            if fname in {"delivery_heatmap.png", "heatmap.png"}:
                                heatmap_source = os.path.join(csv_dir, fname)
                                for coordinates_dir in coordinates_dirs:
                                    heatmap_filename = f"{scenario_id}_{fname}"
                                    heatmap_target = os.path.join(coordinates_dir, heatmap_filename)
                                    try:
                                        shutil.copy2(heatmap_source, heatmap_target)
                                        found_heatmap_filename = heatmap_filename
                                    except Exception:
                                        pass
                                break
                        metrics_candidates = []
                        for fname in os.listdir(csv_dir):
                            if fname == "simulation_metrics.json":
                                metrics_candidates = [fname]
                                break
                            if fname.startswith("delivery_runner_metrics_run_") and fname.endswith(".json"):
                                metrics_candidates.append(fname)
                        if metrics_candidates:
                            metrics_source = os.path.join(csv_dir, metrics_candidates[0])
                            for coordinates_dir in coordinates_dirs:
                                metrics_filename = f"{scenario_id}_metrics.json"
                                metrics_target = os.path.join(coordinates_dir, metrics_filename)
                                try:
                                    shutil.copy2(metrics_source, metrics_target)
                                    found_metrics_filename = metrics_filename
                                except Exception:
                                    pass
                            try:
                                orders_value = _extract_orders_from_metrics(metrics_source)
                                variant_key, blocked_holes = _extract_variant_info_from_metrics(metrics_source)
                            except Exception:
                                orders_value = None
                                variant_key = None
                                blocked_holes = None
                        course_id: Optional[str] = None
                        course_name: Optional[str] = None
                        try:
                            results_path = os.path.join(csv_dir, "results.json")
                            if os.path.exists(results_path):
                                with open(results_path, "r", encoding="utf-8") as f:
                                    _results = json.load(f)
                                course_dir_str = None
                                try:
                                    course_dir_str = _results.get("metadata", {}).get("course_dir")
                                except Exception:
                                    course_dir_str = None
                                if isinstance(course_dir_str, str) and course_dir_str:
                                    course_id = os.path.basename(course_dir_str.replace("\\", "/").rstrip("/"))
                                    course_name = _humanize(course_id)
                        except Exception:
                            course_id = None
                            course_name = None
                        if course_id and course_name:
                            discovered_courses[course_id] = course_name
                        try:
                            existing_geo = None
                            for fname in os.listdir(csv_dir):
                                if fname.startswith("hole_delivery_times") and fname.endswith(".geojson"):
                                    existing_geo = os.path.join(csv_dir, fname)
                                    break
                            if not existing_geo:
                                maybe = _generate_per_run_hole_geojson(Path(csv_dir))
                                if maybe and os.path.exists(maybe):
                                    existing_geo = str(maybe)
                            if existing_geo:
                                for coordinates_dir in coordinates_dirs:
                                    hole_geojson_filename = f"hole_delivery_times_{scenario_id}.geojson"
                                    hole_geojson_target = os.path.join(coordinates_dir, hole_geojson_filename)
                                    try:
                                        shutil.copy2(existing_geo, hole_geojson_target)
                                        found_hole_geojson_filename = hole_geojson_filename
                                    except Exception:
                                        pass
                        except Exception:
                            pass
                        file_info = get_file_info(source_path)
                        try:
                            mtime = os.path.getmtime(source_path)
                            id_to_mtime[scenario_id] = mtime
                            last_modified_iso = datetime.fromtimestamp(mtime).isoformat()
                        except Exception:
                            last_modified_iso = None
                        path_parts = Path(source_path).parts
                        sim_folder_name = None
                        for i, part in enumerate(path_parts):
                            if "delivery_runner" in part and "runners" in part:
                                sim_folder_name = part
                                break
                        parsed = _parse_simulation_folder_name(sim_folder_name) if sim_folder_name else {}
                        extracted_runners: Optional[int] = None
                        extracted_orders: Optional[int] = None
                        for part in path_parts:
                            m_r = re.match(r"runners[_-]?([0-9]+)", part, re.IGNORECASE)
                            if m_r:
                                try:
                                    extracted_runners = int(m_r.group(1))
                                except Exception:
                                    pass
                            m_o = re.match(r"orders[_-]?([0-g]{2,3})", part, re.IGNORECASE)
                            if m_o:
                                try:
                                    extracted_orders = int(m_o.group(1))
                                except Exception:
                                    pass
                        meta = {
                            "runners": (int(parsed.get("runners", "0") or 0) if isinstance(parsed, dict) else None)
                            or extracted_runners,
                            "bevCarts": int(parsed.get("bev_carts", "0") or 0) if isinstance(parsed, dict) else None,
                            "golfers": int(parsed.get("golfers", "0") or 0) if isinstance(parsed, dict) else None,
                            "scenario": parsed.get("scenario") if isinstance(parsed, dict) else None,
                            "orders": (int(orders_value) if isinstance(orders_value, (int, float)) else None)
                            or extracted_orders,
                            "lastModified": last_modified_iso,
                            "blockedHoles": blocked_holes,
                        }
                        entry = {
                            "id": scenario_id,
                            "name": f"{group_name}: {display_name}",
                            "filename": target_filename,
                            "description": file_info,
                            "variantKey": variant_key or "none",
                            "meta": {k: v for k, v in meta.items() if v is not None},
                        }
                        if course_id:
                            entry["courseId"] = course_id
                        if course_name:
                            entry["courseName"] = course_name
                        if found_heatmap_filename:
                            entry["heatmapFilename"] = found_heatmap_filename
                        if found_metrics_filename:
                            entry["metricsFilename"] = found_metrics_filename
                        if found_hole_geojson_filename:
                            entry["holeDeliveryGeojson"] = found_hole_geojson_filename
                        manifest["simulations"].append(entry)
                    else:
                        return False, []
            if manifest["simulations"]:
                env_default_id = os.environ.get("DEFAULT_SIMULATION_ID", "").strip()
                chosen_id = (preferred_default_id or env_default_id or "").strip()
                selected_default = None
                if chosen_id:
                    for sim in manifest["simulations"]:
                        if sim["id"] == chosen_id:
                            selected_default = sim
                            break
                if not selected_default:
                    if id_to_mtime:
                        try:
                            newest_id = max(id_to_mtime.items(), key=lambda kv: kv[1])[0]
                            selected_default = next(
                                (sim for sim in manifest["simulations"] if sim["id"] == newest_id), None
                            )
                        except Exception:
                            selected_default = None
                if not selected_default:
                    selected_default = next(
                        (sim for sim in manifest["simulations"] if not sim["name"].startswith("Local:")),
                        manifest["simulations"][0],
                    )
                manifest["defaultSimulation"] = selected_default["id"]
            if discovered_courses:
                items = list(discovered_courses.items())
                items.sort(key=lambda kv: (0 if kv[0] == "pinetree_country_club" else 1, kv[1].lower()))
                manifest["courses"] = [{"id": cid, "name": cname} for cid, cname in items]
            for coordinates_dir in coordinates_dirs:
                manifest_path = os.path.join(coordinates_dir, "manifest.json")
                with open(manifest_path, "w") as f:
                    json.dump(manifest, f, indent=2)
            metrics_source = map_animation_dir / "public" / "simulation_metrics.json"
            if os.path.exists(metrics_source):
                for coordinates_dir in coordinates_dirs:
                    metrics_target = os.path.join(coordinates_dir, "simulation_metrics.json")
                    try:
                        shutil.copy2(metrics_source, metrics_target)
                    except Exception:
                        pass
            copy_hole_delivery_geojson(coordinates_dirs)
            return True, list(discovered_courses.keys())
        except Exception:
            return False, []

    def ensure_setup_required_assets(course_ids: list[str]) -> None:
        try:
            courses_base_dir = project_root / "courses"
            target_dirs = [setup_public_dir, map_animation_dir / "public"]
            for course_id in course_ids:
                course_src_dir = courses_base_dir / course_id
                for base in target_dirs:
                    course_target_dir = base / course_id
                    course_target_dir.mkdir(exist_ok=True)
                assets_to_copy = {
                    "holes_connected.geojson": f"geojson{os.sep}holes_connected.geojson",
                    "cart_paths.geojson": f"geojson{os.sep}cart_paths.geojson",
                    "course_polygon.geojson": f"geojson{os.sep}course_polygon.geojson",
                    "holes.geojson": f"geojson{os.sep}holes.geojson",
                    "greens.geojson": f"geojson{os.sep}greens.geojson",
                    "tees.geojson": f"geojson{os.sep}tees.geojson",
                    "holes_geofenced.geojson": f"geojson{os.sep}generated{os.sep}holes_geofenced.geojson",
                }
                for target_name, source_subpath in assets_to_copy.items():
                    source_path = course_src_dir / source_subpath
                    if not source_path.exists():
                        if target_name == "holes_connected.geojson":
                            fallback_dir = map_animation_dir / "public" / course_id
                            if fallback_dir.exists():
                                source_path = fallback_dir / target_name
                        if not source_path.exists():
                            continue
                    for base in target_dirs:
                        course_target_dir = base / course_id
                        target_path = course_target_dir / target_name
                        try:
                            if (
                                not target_path.exists()
                                or source_path.stat().st_mtime > target_path.stat().st_mtime
                            ):
                                shutil.copy2(str(source_path), str(target_path))
                        except Exception:
                            pass
        except Exception:
            pass

    # Main publishing logic starts here
    try:
        all_simulations = find_all_simulations()
        if not all_simulations:
            print("No new simulation results found to publish.")
            return

        ok, courses = copy_all_coordinate_files(all_simulations, preferred_default_id=None)
        if not ok:
            print("⚠️  Failed to copy coordinate files for map display.")
            return

        ensure_setup_required_assets(courses)
        print("✅ Map assets updated successfully.")

    except Exception as e:
        print(f"⚠️  Skipped map asset update due to error: {e}")


def main() -> None:
    p = argparse.ArgumentParser(description="Two-pass optimization: 10 minimal for all; 10 full for winners")
    p.add_argument("--course-dir", default="courses/pinetree_country_club")
    p.add_argument(
        "--run-all-courses", action="store_true", help="Run optimization for all courses in the 'courses' directory."
    )
    p.add_argument("--tee-scenario", default="real_tee_sheet")
    p.add_argument("--orders-levels", nargs="+", type=int, default=None, help="Orders totals to simulate (required unless --summarize-only)")
    p.add_argument("--runner-range", type=str, default="1-3")
    p.add_argument("--first-pass-runs", type=int, default=10, help="runs per combo in first pass (minimal outputs)")
    p.add_argument("--second-pass-runs", type=int, default=10, help="runs for winner confirmation in second pass (full outputs)")
    p.add_argument("--python-bin", default=sys.executable)
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--runner-speed", type=float, default=None)
    p.add_argument("--prep-time", type=int, default=None)
    p.add_argument("--variants", nargs="+", default=[v.key for v in BLOCKING_VARIANTS], help="Subset of variant keys to test")
    p.add_argument("--output-root", default=None, help="Base for outputs, defaults to output/<course_name>")
    p.add_argument("--summarize-only", action="store_true", help="Skip running sims; summarize an existing output root")
    p.add_argument("--existing-root", type=str, default=None, help="Path to existing optimization output root to summarize")
    # Targets for recommendation
    p.add_argument("--target-on-time", type=float, default=0.90)
    p.add_argument("--max-failed-rate", type=float, default=0.05)
    p.add_argument("--max-p90", type=float, default=40.0)
    p.add_argument("--concurrency", type=int, default=max(1, min(4, (os.cpu_count() or 2))), help="max concurrent simulations")
    p.add_argument("--auto-report", action="store_true", help="Automatically generate GM-friendly reports after simulations complete")
    args = p.parse_args()

    project_root = Path(__file__).resolve().parents[2]
    
    # Load environment variables from .env at project root if available
    if _load_dotenv is not None:
        try:
            _load_dotenv(dotenv_path=project_root / ".env", override=False)
            _load_dotenv(override=False)
        except Exception:
            pass

    if args.run_all_courses:
        courses_root = project_root / "courses"
        # A course is valid if it's a directory and has a tee times config.
        # This helps filter out temporary directories or copies.
        course_dirs = [
            d for d in courses_root.iterdir() if d.is_dir() and (d / "config" / "tee_times_config.json").exists()
        ]

        # Reconstruct the command line, removing --run-all-courses and any existing --course-dir
        cmd_args = [sys.argv[0]]  # script name
        i = 1
        while i < len(sys.argv):
            arg = sys.argv[i]
            if arg == "--run-all-courses":
                i += 1
                continue
            if arg == "--course-dir":
                i += 2  # skip value
                continue
            if arg.startswith("--course-dir="):
                i += 1
                continue
            cmd_args.append(arg)
            i += 1

        base_cmd = [sys.executable] + cmd_args

        print(f"Found {len(course_dirs)} valid courses to process.")
        for course_d in course_dirs:
            print(f"\n{'=' * 20}\nRunning for course: {course_d.name}\n{'=' * 20}\n")
            cmd = base_cmd + ["--course-dir", str(course_d.resolve())]
            subprocess.run(cmd, check=False)
        return
    
    course_dir = Path(args.course_dir)
    if not course_dir.is_absolute():
        course_dir = (project_root / args.course_dir).resolve()
    if not course_dir.exists():
        print(json.dumps({"error": f"Course dir not found: {course_dir}"}))
        sys.exit(1)

    variant_map: Dict[str, BlockingVariant] = {v.key: v for v in BLOCKING_VARIANTS}
    selected_variants: List[BlockingVariant] = [variant_map[k] for k in args.variants if k in variant_map]
    runner_values = parse_range(args.runner_range)

    # Determine output root
    if args.summarize_only:
        if not args.existing_root:
            print(json.dumps({"error": "--summarize-only requires --existing-root <path>"}))
            sys.exit(2)
        root = Path(args.existing_root)
        if not root.is_absolute():
            root = (project_root / args.existing_root)
        if not root.exists():
            print(json.dumps({"error": f"Existing root not found: {root}"}))
            sys.exit(2)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if args.output_root:
            out_base = Path(args.output_root)
            if not out_base.is_absolute():
                out_base = project_root / out_base
        else:
            # Extract course name from course_dir path
            course_name = course_dir.name
            out_base = project_root / "output" / course_name
        root = out_base / f"{stamp}_{args.tee_scenario}"

    # Identify orders levels
    if args.summarize_only:
        orders_found: List[int] = []
        seen: set = set()
        for pass_dir in [root / "first_pass", root / "second_pass"]:
            if not pass_dir.exists():
                continue
            for d in sorted(pass_dir.glob("orders_*")):
                if not d.is_dir():
                    continue
                try:
                    val = int(str(d.name).split("_")[-1])
                    if val not in seen:
                        orders_found.append(val)
                        seen.add(val)
                except Exception:
                    continue
        # Fallback for legacy layouts that may have orders_* at the root
        if not orders_found:
            for d in sorted(root.glob("orders_*")):
                if not d.is_dir():
                    continue
                try:
                    val = int(str(d.name).split("_")[-1])
                    if val not in seen:
                        orders_found.append(val)
                        seen.add(val)
                except Exception:
                    continue
        orders_iter = sorted(orders_found)
    else:
        if not args.orders_levels:
            print(json.dumps({"error": "--orders-levels is required unless --summarize-only is set"}))
            sys.exit(2)
        orders_iter = args.orders_levels

    summary: Dict[int, Dict[str, Any]] = {}
    csv_rows: List[Dict[str, Any]] = []

    for orders in orders_iter:
        results_by_variant: Dict[str, Dict[int, Dict[str, Any]]] = {}

        # First pass: run all combos (minimal outputs)
        if not args.summarize_only:
            future_to_combo: Dict[Any, Tuple[BlockingVariant, int, Path]] = {}
            with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
                for variant in selected_variants:
                    for n in runner_values:
                        details = f"orders_{orders:03d}/runners_{n}/{variant.key}"
                        out_dir = root / "first_pass" / details
                        group_dir = root / "first_pass" / details
                        fut = executor.submit(
                            run_combo,
                            py=args.python_bin,
                            course_dir=course_dir,
                            scenario=args.tee_scenario,
                            runners=n,
                            orders=orders,
                            runs=args.first_pass_runs,
                            out=out_dir,
                            log_level=args.log_level,
                            variant=variant,
                            runner_speed=args.runner_speed,
                            prep_time=args.prep_time,
                            minimal_output=True,
                        )
                        future_to_combo[fut] = (variant, n, group_dir)
                for fut in as_completed(future_to_combo):
                    _ = fut.result()

        # Aggregate after first pass (only first_pass runs for selection)
        for variant in selected_variants:
            for n in runner_values:
                details = f"orders_{orders:03d}/runners_{n}/{variant.key}"
                group_dir = root / "first_pass" / details
                run_dirs = _collect_run_dirs(
                    root, orders=orders, variant_key=variant.key, runners=n, include_first=True, include_second=False
                )
                agg = aggregate_runs(run_dirs)
                results_by_variant.setdefault(variant.key, {})[n] = agg
                context = _make_group_context(
                    course_dir=course_dir,
                    tee_scenario=args.tee_scenario,
                    orders=orders,
                    variant_key=variant.key,
                    runners=n,
                )
                _write_group_aggregate_file(group_dir, context, agg)
                # Write averaged heatmap across available runs (best-effort)
                _write_group_aggregate_heatmap(
                    group_dir,
                    course_dir=course_dir,
                    tee_scenario=args.tee_scenario,
                    variant_key=variant.key,
                    runners=n,
                    run_dirs=run_dirs,
                )
                _write_group_delivery_geojson(
                    group_dir,
                    course_dir=course_dir,
                    tee_scenario=args.tee_scenario,
                    variant_key=variant.key,
                    runners=n,
                )
                _row = _row_from_context_and_agg(context, agg, group_dir)
                _write = _row  # clarity
                # Upsert into CSV rows
                _upsert_row(csv_rows, _write)

        # Select top 3 + baseline for each runner count for the second pass
        winners_for_2nd_pass: List[Tuple[str, int]] = []
        for n in runner_values:
            candidates_for_n: List[Tuple[str, int, Dict[str, Any]]] = []
            for variant in selected_variants:
                if variant.key == "none":
                    continue
                agg = results_by_variant.get(variant.key, {}).get(n)
                if meets_targets(agg, args):
                    candidates_for_n.append((variant.key, n, agg))

            candidates_for_n.sort(key=lambda t: utility_score(t[0], t[1], t[2]))
            top_3_blocking_for_n = candidates_for_n[:3]
            for v_key, v_runners, _ in top_3_blocking_for_n:
                winners_for_2nd_pass.append((v_key, v_runners))

            none_agg = results_by_variant.get("none", {}).get(n)
            if meets_targets(none_agg, args):
                winners_for_2nd_pass.append(("none", n))

        winners = sorted(list(set(winners_for_2nd_pass)))

        if not winners:
            print(f"Orders {orders}: No variant met targets up to {max(runner_values)} runners after first pass.")
        else:
            print(f"Orders {orders}: Found {len(winners)} candidates for second pass...")
            for v_key, v_runners in winners:
                desc = next((v.description for v in BLOCKING_VARIANTS if v.key == v_key), v_key)
                print(f"  - Candidate: {v_runners} runner(s) with policy: {desc}")

            # Second pass: run confirmation for all winners (full outputs)
            if not args.summarize_only:
                with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
                    futures = []
                    for v_key, v_runners in winners:
                        details = f"orders_{orders:03d}/runners_{v_runners}/{v_key}"
                        out_dir = root / "second_pass" / details
                        fut = executor.submit(
                            run_combo,
                            py=args.python_bin,
                            course_dir=course_dir,
                            scenario=args.tee_scenario,
                            runners=v_runners,
                            orders=orders,
                            runs=args.second_pass_runs,
                            out=out_dir,
                            log_level=args.log_level,
                            variant=next(v for v in BLOCKING_VARIANTS if v.key == v_key),
                            runner_speed=args.runner_speed,
                            prep_time=args.prep_time,
                            minimal_output=False,
                        )
                        futures.append(fut)
                    for fut in as_completed(futures):
                        _ = fut.result()

            # Re-aggregate winners including both passes
            for v_key, v_runners in winners:
                details = f"orders_{orders:03d}/runners_{v_runners}/{v_key}"
                group_dir = root / "second_pass" / details
                win_run_dirs = _collect_run_dirs(
                    root, orders=orders, variant_key=v_key, runners=v_runners, include_first=True, include_second=True
                )
                win_agg = aggregate_runs(win_run_dirs)
                results_by_variant.setdefault(v_key, {})[v_runners] = win_agg
                win_context = _make_group_context(
                    course_dir=course_dir,
                    tee_scenario=args.tee_scenario,
                    orders=orders,
                    variant_key=v_key,
                    runners=v_runners,
                )
                _write_group_aggregate_file(group_dir, win_context, win_agg)
                _write_group_aggregate_heatmap(
                    group_dir,
                    course_dir=course_dir,
                    tee_scenario=args.tee_scenario,
                    variant_key=v_key,
                    runners=v_runners,
                    run_dirs=win_run_dirs,
                )
                _write_group_delivery_geojson(
                    group_dir,
                    course_dir=course_dir,
                    tee_scenario=args.tee_scenario,
                    variant_key=v_key,
                    runners=v_runners,
                )
                _upsert_row(csv_rows, _row_from_context_and_agg(win_context, win_agg, group_dir))

        # Final choice after second pass
        chosen = choose_best_variant(
            results_by_variant,
            target_on_time=args.target_on_time,
            max_failed=args.max_failed_rate,
            max_p90=args.max_p90,
        )

        # Baseline reporting for transparency (no-blocks)
        baseline_none_runners = None
        if "none" in results_by_variant:
            for n in sorted(results_by_variant["none"].keys()):
                agg = results_by_variant["none"][n]
                if not agg or not agg.get("runs"):
                    continue
                p90_mean = agg.get("p90_mean", float("nan"))
                p90_meets = math.isnan(p90_mean) or p90_mean <= args.max_p90
                if (
                    agg.get("on_time_wilson_lo", 0.0) >= args.target_on_time
                    and agg.get("failed_mean", 1.0) <= args.max_failed_rate
                    and p90_meets
                ):
                    baseline_none_runners = n
                    break
        if baseline_none_runners is not None:
            print(f"Orders {orders} (no blocked holes): Recommended {baseline_none_runners} runner(s).")
        else:
            print(f"Orders {orders} (no blocked holes): No runner count up to {max(runner_values)} met targets.")

        # Persist summary entry
        summary[orders] = {
            "chosen": {
                "variant": chosen[0] if chosen else None,
                "runners": chosen[1] if chosen else None,
                "metrics": chosen[2] if chosen else None,
            },
            "per_variant": results_by_variant,
            "baseline_none": {
                "runners": baseline_none_runners,
                "metrics": results_by_variant.get("none", {}).get(baseline_none_runners) if baseline_none_runners is not None else None,
            },
        }

    # Print machine-readable JSON at the end (with serialization fix)
    def make_serializable(obj):
        """Convert non-serializable objects to serializable format"""
        if hasattr(obj, '__dict__'):
            return {k: make_serializable(v) for k, v in obj.__dict__.items() if not k.startswith('_')}
        elif isinstance(obj, dict):
            return {k: make_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [make_serializable(item) for item in obj]
        elif isinstance(obj, (str, int, float, bool)) or obj is None:
            return obj
        else:
            return str(obj)  # fallback to string representation
    
    serializable_summary = make_serializable(summary)
    
    print(
        json.dumps(
            {
                "course": str(course_dir),
                "tee_scenario": args.tee_scenario,
                "targets": {
                    "on_time": args.target_on_time,
                    "max_failed": args.max_failed_rate,
                    "max_p90": args.max_p90,
                },
                "orders_levels": list(orders_iter),
                "summary": serializable_summary,
                "output_root": str(root),
            },
            indent=2,
        )
    )

    # Write final CSV combining group aggregates
    try:
        csv_path = _write_final_csv(root, csv_rows)
        if csv_path is not None:
            print(f"Aggregated metrics CSV written to {csv_path}")
    except Exception:
        pass

    # Final consistency: rebuild CSV purely from saved @aggregate.json files
    # so that the CSV on disk exactly mirrors the persisted aggregates.
    try:
        rebuilt_rows = _collect_rows_from_saved_aggregates(root)
        rebuilt_csv = _write_final_csv(root, rebuilt_rows)
        if rebuilt_csv is not None:
            print(f"all_metrics.csv rebuilt from @aggregate.json files: {rebuilt_csv}")
    except Exception:
        pass

    # Generate executive summary Markdown (best-effort)
    try:
        md_path, used_gemini = _write_executive_summary_markdown(
            out_dir=root,
            course_dir=course_dir,
            tee_scenario=args.tee_scenario,
            orders_levels=list(orders_iter),
            summary=summary,
            targets={"on_time": args.target_on_time, "max_failed": args.max_failed_rate, "max_p90": args.max_p90},
        )
        if md_path is not None:
            print(f"Executive summary written to {md_path} (source: {'gemini' if used_gemini else 'local'})")
    except Exception as _e:
        # Non-fatal: keep CLI behavior unchanged if summary generation fails
        pass

    # Write GM staffing policy report (best-effort)
    try:
        gm_md = _write_gm_staffing_policy_report(
            out_dir=root,
            course_dir=course_dir,
            tee_scenario=args.tee_scenario,
            orders_levels=list(orders_iter),
            summary=summary,
            targets={"on_time": args.target_on_time, "max_failed": args.max_failed_rate, "max_p90": args.max_p90},
        )
        if gm_md is not None:
            print(f"GM staffing policy report written to {gm_md}")
    except Exception:
        pass

    # Generate reports if requested
    if args.auto_report and not args.summarize_only:
        try:
            print(f"\n📊 Generating GM-friendly reports for {root}")
            report_cmd = [
                sys.executable,
                "scripts/report/auto_report.py",
                "--scenario-dir", str(root)
            ]
            result = subprocess.run(report_cmd, check=False, cwd=project_root)
            if result.returncode == 0:
                print("✅ Reports generated successfully.")
                # Open the scenario index
                index_path = root / "index.html"
                if index_path.exists():
                    print(f"🎯 Scenario index available at: {index_path}")
                    try:
                        subprocess.run(["start", str(index_path)], shell=True, check=False)
                    except Exception:
                        pass
            else:
                print("⚠️  Report generation completed with warnings.")
        except Exception as e:
            print(f"⚠️  Report generation failed: {e}")

    # Post-run: sync assets for this specific course only
    try:
        print(f"Syncing assets for course: {course_dir.name}")
        sync_cmd = [
            sys.executable, 
            "sync_simulation_assets.py"
        ]
        subprocess.run(sync_cmd, check=False, cwd=project_root)
        print("✅ Assets synced successfully.")
    except Exception as e:
        print(f"⚠️  Asset sync failed: {e}")


if __name__ == "__main__":
    main()


