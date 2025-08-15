"""Export busy_weekend_matrix run stats to a single CSV.

This script scans `outputs/busy_weekend_matrix/` for configuration folders
and per-run JSON metrics, then writes a flat CSV with one row per run.

Usage (PowerShell-friendly, single command):
  python scripts/analysis/export_busy_weekend_matrix_stats.py \
    --matrix-dir outputs/busy_weekend_matrix \
    --output-csv outputs/busy_weekend_matrix/matrix_stats.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from dataclasses import dataclass, asdict
import logging
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from golfsim.logging import init_logging


@dataclass
class RunRecord:
    scenario: str
    with_bev: bool
    runner_count: int
    delivery_orders: int
    config_dir: str
    run_id: str
    # Delivery runner metrics fields (present in delivery_runner_metrics_run_XX.json)
    simulation_id: Optional[str] = None
    runner_id: Optional[str] = None
    revenue_per_round: Optional[float] = None
    orders_per_runner_hour: Optional[float] = None
    on_time_rate: Optional[float] = None
    delivery_cycle_time_p90: Optional[float] = None
    delivery_cycle_time_avg: Optional[float] = None
    failed_rate: Optional[float] = None
    second_runner_break_even_orders: Optional[float] = None
    queue_wait_avg: Optional[float] = None
    runner_utilization_driving_pct: Optional[float] = None
    runner_utilization_waiting_pct: Optional[float] = None
    distance_per_delivery_avg: Optional[float] = None
    total_revenue: Optional[float] = None
    total_orders: Optional[int] = None
    successful_orders: Optional[int] = None
    failed_orders: Optional[int] = None
    total_rounds: Optional[int] = None
    active_runner_hours: Optional[float] = None


DIR_PATTERN = re.compile(
    r"^(?P<scenario>.+?)_delivery_(?P<runners>\d+)r_(?P<orders>\d+)orders_(?P<bev>with|no)_bev(?:_.+)?$"
)


def parse_config_from_dirname(dirname: str) -> Optional[Tuple[str, int, int, bool]]:
    match = DIR_PATTERN.match(dirname)
    if not match:
        return None
    scenario = match.group("scenario")
    runners = int(match.group("runners"))
    orders = int(match.group("orders"))
    with_bev = match.group("bev") == "with"
    return scenario, runners, orders, with_bev


def find_run_metric_files(config_dir: Path) -> Iterable[Tuple[str, Path]]:
    for run_dir in sorted(config_dir.glob("run_*")):
        if not run_dir.is_dir():
            continue
        run_id = run_dir.name
        # expected file naming convention
        json_candidates = list(run_dir.glob("delivery_runner_metrics_*.json"))
        if not json_candidates:
            # Some directories may place JSON under run dir with a fixed name
            json_candidates = list(run_dir.glob("*.json"))
        if not json_candidates:
            continue
        # Choose first candidate deterministically (sorted above)
        yield run_id, json_candidates[0]


def load_json_safely(path: Path) -> Optional[Dict]:
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def collect_records(matrix_dir: Path) -> List[RunRecord]:
    logger = logging.getLogger(__name__)
    records: List[RunRecord] = []

    # Optionally leverage matrix_summary.json if present for directory listing
    summary_file = matrix_dir / "matrix_summary.json"
    config_dirs: List[Path] = []
    if summary_file.exists():
        summary = load_json_safely(summary_file)
        if summary and isinstance(summary.get("output_directories"), list):
            for d in summary["output_directories"]:
                p = matrix_dir / d
                if p.is_dir():
                    config_dirs.append(p)
        logger.debug("Loaded %d config dirs from matrix_summary.json", len(config_dirs))

    # Fallback: discover directories by pattern if summary missing/incomplete
    if not config_dirs:
        for p in matrix_dir.iterdir():
            if not p.is_dir():
                continue
            if parse_config_from_dirname(p.name):
                config_dirs.append(p)

    logger.info("Scanning %d configuration directories in %s", len(config_dirs), matrix_dir)
    # Log a brief sample of directory names and regex match result to diagnose parsing
    sample = config_dirs[:10]
    for p in sample:
        logger.info("Dir candidate: %s | match=%s", p.name, bool(DIR_PATTERN.match(p.name)))

    for config_dir in sorted(config_dirs, key=lambda p: p.name):
        parsed = parse_config_from_dirname(config_dir.name)
        if not parsed:
            logger.debug("Skipping non-matching directory: %s", config_dir.name)
            continue
        scenario, runners, orders, with_bev = parsed

        run_count = 0
        for run_id, json_path in find_run_metric_files(config_dir):
            run_count += 1
            data = load_json_safely(json_path)
            if not data:
                logger.warning("Failed to read JSON: %s", json_path)
                continue

            record = RunRecord(
                scenario=scenario,
                with_bev=with_bev,
                runner_count=runners,
                delivery_orders=orders,
                config_dir=config_dir.name,
                run_id=run_id,
                simulation_id=data.get("simulation_id"),
                runner_id=data.get("runner_id"),
                revenue_per_round=data.get("revenue_per_round"),
                orders_per_runner_hour=data.get("orders_per_runner_hour"),
                on_time_rate=data.get("on_time_rate"),
                delivery_cycle_time_p90=data.get("delivery_cycle_time_p90"),
                delivery_cycle_time_avg=data.get("delivery_cycle_time_avg"),
                failed_rate=data.get("failed_rate"),
                second_runner_break_even_orders=data.get("second_runner_break_even_orders"),
                queue_wait_avg=data.get("queue_wait_avg"),
                runner_utilization_driving_pct=data.get("runner_utilization_driving_pct"),
                runner_utilization_waiting_pct=data.get("runner_utilization_waiting_pct"),
                distance_per_delivery_avg=data.get("distance_per_delivery_avg"),
                total_revenue=data.get("total_revenue"),
                total_orders=data.get("total_orders"),
                successful_orders=data.get("successful_orders"),
                failed_orders=data.get("failed_orders"),
                total_rounds=data.get("total_rounds"),
                active_runner_hours=data.get("active_runner_hours"),
            )
            records.append(record)
        logger.info("%s: found %d runs", config_dir.name, run_count)

    return records


def write_csv(records: List[RunRecord], output_csv: Path) -> None:
    logger = logging.getLogger(__name__)
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    rows = [asdict(r) for r in records]
    # Stable column order
    fieldnames = [
        "scenario",
        "with_bev",
        "runner_count",
        "delivery_orders",
        "config_dir",
        "run_id",
        "simulation_id",
        "runner_id",
        "revenue_per_round",
        "orders_per_runner_hour",
        "on_time_rate",
        "delivery_cycle_time_p90",
        "delivery_cycle_time_avg",
        "failed_rate",
        "second_runner_break_even_orders",
        "queue_wait_avg",
        "runner_utilization_driving_pct",
        "runner_utilization_waiting_pct",
        "distance_per_delivery_avg",
        "total_revenue",
        "total_orders",
        "successful_orders",
        "failed_orders",
        "total_rounds",
        "active_runner_hours",
    ]

    with output_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    logger.info("Wrote %d rows to %s", len(rows), output_csv)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export busy_weekend_matrix stats to CSV")
    parser.add_argument(
        "--matrix-dir",
        type=Path,
        default=Path("outputs/busy_weekend_matrix"),
        help="Path to busy_weekend_matrix directory",
    )
    parser.add_argument(
        "--output-csv",
        type=Path,
        default=Path("outputs/busy_weekend_matrix/matrix_stats.csv"),
        help="Output CSV file path",
    )
    return parser.parse_args()


def main() -> int:
    init_logging()
    args = parse_args()
    records = collect_records(args.matrix_dir)
    logging.getLogger(__name__).info("Collected %d run records", len(records))
    write_csv(records, args.output_csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


