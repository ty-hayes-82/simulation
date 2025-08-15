#!/usr/bin/env python3
"""
Aggregate batch_metrics.csv into concise statistics by scenario and capacity.

Outputs a Markdown report with mean/median/std/min/max for key metrics,
separately for beverage carts and delivery runners, grouped by scenario and
capacity (num_carts/num_runners) and demand knob (bev_order_prob/delivery_order_prob).
"""

from __future__ import annotations

import argparse
import csv
import math
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


# ----------------------------- Data Structures ----------------------------- #


@dataclass
class NumericStats:
    count: int
    mean: float
    median: float
    std_dev: float
    min: float
    max: float


# ------------------------------- Utilities -------------------------------- #


def to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s or s.lower() == "nan":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def safe_stats(values: List[float]) -> Optional[NumericStats]:
    if not values:
        return None
    vals = values
    mean = statistics.fmean(vals) if hasattr(statistics, "fmean") else sum(vals) / len(vals)
    median = statistics.median(vals)
    std_dev = statistics.stdev(vals) if len(vals) > 1 else 0.0
    return NumericStats(
        count=len(vals),
        mean=mean,
        median=median,
        std_dev=std_dev,
        min=min(vals),
        max=max(vals),
    )


def fmt_pct(x: Optional[float]) -> str:
    if x is None or math.isnan(x):
        return "—"
    return f"{x*100:.1f}%"


def fmt_num(x: Optional[float], digits: int = 2) -> str:
    if x is None or math.isnan(x):
        return "—"
    return f"{x:.{digits}f}"


def compute_column_stats(rows: List[Dict[str, Any]], col: str) -> Optional[NumericStats]:
    values: List[float] = []
    for r in rows:
        v = to_float(r.get(col))
        if v is None:
            continue
        values.append(v)
    return safe_stats(values)


def read_csv_rows(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def group_rows(rows: Iterable[Dict[str, Any]], keys: Tuple[str, ...]) -> Dict[Tuple[Any, ...], List[Dict[str, Any]]]:
    grouped: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    for r in rows:
        k = tuple(r.get(k) for k in keys)
        grouped.setdefault(k, []).append(r)
    return grouped


# ------------------------------- Reporting -------------------------------- #


BEV_METRICS = [
    ("bev_order_penetration_rate", False),
    ("bev_orders_per_cart_hour", False),
    ("bev_total_orders", False),
    ("bev_total_revenue", False),
    ("bev_total_tips", False),
    ("bev_holes_covered_per_hour", False),
    ("bev_total_visibility_events", False),
]


RUNNER_METRICS = [
    ("run_orders_per_runner_hour", False),
    ("run_on_time_rate", True),
    ("run_delivery_cycle_time_p50", False),
    ("run_delivery_cycle_time_p90", False),
    ("run_dispatch_delay_avg", False),
    ("run_travel_time_avg", False),
    ("run_failed_rate", True),
    ("run_queue_depth_avg", False),
    ("run_queue_wait_avg", False),
    ("run_total_orders", False),
    ("run_total_revenue", False),
    ("run_successful_orders", False),
    ("run_failed_orders", False),
]


def write_section_header(out: List[str], text: str, level: int = 2) -> None:
    # Use '##' and '###' as per project markdown spec
    hashes = "##" if level == 2 else "###"
    out.append(f"{hashes} {text}")
    out.append("")


def append_metric_block(
    out: List[str],
    title: str,
    stats: Optional[NumericStats],
    is_percentage: bool = False,
) -> None:
    out.append(f"- **{title}**:")
    if not stats:
        out.append("  - No data")
        return
    if is_percentage:
        out.append(f"  - mean: {fmt_pct(stats.mean)} | median: {fmt_pct(stats.median)} | std: {fmt_pct(stats.std_dev)}")
        out.append(f"  - min: {fmt_pct(stats.min)} | max: {fmt_pct(stats.max)} | n: {stats.count}")
    else:
        out.append(
            f"  - mean: {fmt_num(stats.mean)} | median: {fmt_num(stats.median)} | std: {fmt_num(stats.std_dev)}"
        )
        out.append(f"  - min: {fmt_num(stats.min)} | max: {fmt_num(stats.max)} | n: {stats.count}")


def render_bevcart_group(out: List[str], group_key: Tuple[Any, ...], rows: List[Dict[str, Any]]) -> None:
    scenario, num_carts, bev_prob = group_key
    write_section_header(out, f"BevCart — {scenario} | {num_carts} cart(s) | bev_order_prob={bev_prob}", level=3)
    for metric_name, is_pct in BEV_METRICS:
        stats = compute_column_stats(rows, metric_name)
        append_metric_block(out, metric_name, stats, is_percentage=is_pct)
    out.append("")


def render_runner_group(out: List[str], group_key: Tuple[Any, ...], rows: List[Dict[str, Any]]) -> None:
    scenario, num_runners, deliv_prob = group_key
    write_section_header(out, f"Runner — {scenario} | {num_runners} runner(s) | delivery_order_prob={deliv_prob}", level=3)
    for metric_name, is_pct in RUNNER_METRICS:
        stats = compute_column_stats(rows, metric_name)
        append_metric_block(out, metric_name, stats, is_percentage=is_pct)
    out.append("")


def generate_report(rows: List[Dict[str, Any]]) -> str:
    out: List[str] = []
    write_section_header(out, "Batch Metrics Aggregate Report", level=2)

    # Split by mode
    bevcart_rows = [r for r in rows if (r.get("mode") or "").strip().lower() == "bevcart"]
    runner_rows = [r for r in rows if (r.get("mode") or "").strip().lower() == "runner"]

    # Executive summary
    out.append("**Overview**:")
    out.append(f"- **BevCart rows**: {len(bevcart_rows)}")
    out.append(f"- **Runner rows**: {len(runner_rows)}")
    out.append("")

    # BevCart groups: by scenario, num_carts, bev_order_prob
    if bevcart_rows:
        write_section_header(out, "Beverage Cart Aggregates", level=2)
        bev_groups = group_rows(bevcart_rows, ("scenario", "num_carts", "bev_order_prob"))
        for key in sorted(bev_groups.keys(), key=lambda k: (str(k[0]), to_float(k[1]) or 0.0, to_float(k[2]) or 0.0)):
            render_bevcart_group(out, key, bev_groups[key])

    # Runner groups: by scenario, num_runners, delivery_order_prob
    if runner_rows:
        write_section_header(out, "Delivery Runner Aggregates", level=2)
        run_groups = group_rows(runner_rows, ("scenario", "num_runners", "delivery_order_prob"))
        for key in sorted(run_groups.keys(), key=lambda k: (str(k[0]), to_float(k[1]) or 0.0, to_float(k[2]) or 0.0)):
            render_runner_group(out, key, run_groups[key])

    return "\n".join(out).strip() + "\n"


# ---------------------------------- CLI ----------------------------------- #


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Aggregate batch metrics by scenario and capacity",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--input",
        default=str(Path("outputs") / "batch_20250814_140519" / "batch_metrics.csv"),
        help="Path to batch_metrics.csv",
    )
    p.add_argument(
        "--output",
        default=str(Path("outputs") / "batch_20250814_140519" / "aggregated_metrics_report.md"),
        help="Path to write Markdown report",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not input_path.exists():
        print(f"ERROR: Input not found: {input_path}")
        return 1

    rows = read_csv_rows(input_path)
    report = generate_report(rows)
    output_path.write_text(report, encoding="utf-8")
    print(f"Wrote: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


