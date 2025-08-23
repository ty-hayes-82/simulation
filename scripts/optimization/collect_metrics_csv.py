#!/usr/bin/env python3
"""
Collect delivery_runner_metrics_run_*.json across an experiment tree into a flat CSV.

Usage:
  python scripts/optimization/collect_metrics_csv.py --root outputs/experiments/20250822_foo --out metrics_flat.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, List


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Flatten metrics JSON into a CSV")
    p.add_argument("--root", required=True, help="Root directory to scan (experiment root)")
    p.add_argument("--out", required=True, help="Output CSV path")
    return p.parse_args()


def find_metrics(root: Path) -> List[Path]:
    out: List[Path] = []
    for path in root.rglob("delivery_runner_metrics_run_*.json"):
        out.append(path)
    return sorted(out)


def load_json(path: Path) -> Dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


FIELDS = [
    "on_time_rate",
    "failed_rate",
    "delivery_cycle_time_p90",
    "delivery_cycle_time_avg",
    "orders_per_runner_hour",
    "second_runner_break_even_orders",
    "queue_wait_avg",
    "runner_utilization_driving_pct",
    "runner_utilization_idle_pct",
    "distance_per_delivery_avg",
    "total_revenue",
    "total_orders",
]


def main() -> None:
    a = parse_args()
    root = Path(a.root)
    out_csv = Path(a.out)
    out_csv.parent.mkdir(parents=True, exist_ok=True)

    rows: List[Dict[str, Any]] = []
    for fp in find_metrics(root):
        d = load_json(fp)
        row: Dict[str, Any] = {
            "file": str(fp.relative_to(root)),
        }
        
        # Extract triad name from path, e.g., "triad_1_3"
        try:
            triad_part = [part for part in fp.parts if "triad_" in part]
            if triad_part:
                row["triad"] = triad_part[0]
        except Exception:
            pass

        for k in FIELDS:
            row[k] = d.get(k)
        rows.append(row)

    if not rows:
        out_csv.write_text("", encoding="utf-8")
        print("No metrics found.")
        return

    # Ensure "triad" is a field if it exists in any row
    fieldnames = list(rows[0].keys())
    if "triad" in rows[0] and "triad" not in fieldnames:
         fieldnames.insert(1, "triad")

    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(f"Wrote {len(rows)} rows to {out_csv}")


if __name__ == "__main__":
    main()


