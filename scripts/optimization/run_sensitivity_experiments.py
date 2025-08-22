#!/usr/bin/env python3
"""
Sweep sensitivity to runner speed and prep time WITHOUT modifying existing repo files.

- Copies the course directory into outputs/experiments/<exp-name>/
- Sets delivery_total_orders in the copied config
- For each (speed, prep) combo, runs scripts/sim/run_new.py into an isolated output dir
- Aggregates metrics across runs and writes a CSV + Markdown summary

Example:
  python scripts/optimization/run_sensitivity_experiments.py \
    --base-course-dir courses/pinetree_country_club \
    --tee-scenario typical_weekday \
    --orders 28 \
    --num-runners 1 \
    --speeds 5.0 6.0 7.0 \
    --preps 8 12 15 \
    --runs-per 5 \
    --exp-name sens_weekday_28
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class Agg:
    on_time: float
    failed: float
    p90: float
    oph: float
    runs: int


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Runner speed and prep-time sensitivity sweep")
    p.add_argument("--base-course-dir", required=True)
    p.add_argument("--tee-scenario", default="typical_weekday")
    p.add_argument("--orders", type=int, required=True)
    p.add_argument("--num-runners", type=int, default=1)
    p.add_argument("--speeds", nargs="+", type=float, required=True)
    p.add_argument("--preps", nargs="+", type=int, required=True)
    p.add_argument("--runs-per", type=int, default=5)
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--python-bin", default=sys.executable)
    p.add_argument("--exp-name", default=None)
    p.add_argument("--output-root", default="outputs/experiments")
    return p.parse_args()


def copy_course(src: Path, dst: Path) -> None:
    if not dst.exists():
        shutil.copytree(src, dst)


def set_orders(course_dir: Path, orders: int) -> None:
    cfg = course_dir / "config" / "simulation_config.json"
    data = json.loads(cfg.read_text(encoding="utf-8"))
    data["delivery_total_orders"] = int(orders)
    cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")


def run_combo(*, py: str, course_dir: Path, scenario: str, runners: int, runs: int, speed: float, prep: int, out: Path, log_level: str) -> None:
    out.mkdir(parents=True, exist_ok=True)
    cmd = [
        py, "scripts/sim/run_new.py",
        "--course-dir", str(course_dir),
        "--tee-scenario", scenario,
        "--num-runners", str(runners),
        "--num-runs", str(runs),
        "--runner-speed", str(speed),
        "--prep-time", str(prep),
        "--output-dir", str(out),
        "--log-level", log_level,
    ]
    subprocess.run(cmd, check=True)


def load_metrics(out_dir: Path, runs: int) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for i in range(1, runs + 1):
        fp = out_dir / f"run_{i:02d}" / f"delivery_runner_metrics_run_{i:02d}.json"
        if fp.exists():
            try:
                items.append(json.loads(fp.read_text(encoding="utf-8")))
            except Exception:
                pass
    return items


def mean(vals: Iterable[float]) -> float:
    vals = list(vals)
    return sum(vals) / len(vals) if vals else 0.0


def aggregate(items: List[Dict[str, Any]]) -> Agg:
    return Agg(
        on_time=mean(x.get("on_time_rate", 0.0) for x in items),
        failed=mean(x.get("failed_rate", 0.0) for x in items),
        p90=mean(x.get("delivery_cycle_time_p90", 0.0) for x in items),
        oph=mean(x.get("orders_per_runner_hour", 0.0) for x in items),
        runs=len(items),
    )


def write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main() -> None:
    a = parse_args()
    exp = a.exp_name or datetime.now().strftime("%Y%m%d_%H%M%S")
    root = Path(a.output_root) / exp
    root.mkdir(parents=True, exist_ok=True)

    course_copy = root / "course_copy"
    copy_course(Path(a.base_course_dir).resolve(), course_copy)
    set_orders(course_copy, a.orders)

    rows: List[Dict[str, Any]] = []
    for s in a.speeds:
        for p in a.preps:
            out = root / f"scenario_{a.tee_scenario}" / f"orders_{a.orders:03d}" / f"speed_{s:.1f}_prep_{p}"
            run_combo(py=a.python_bin, course_dir=course_copy, scenario=a.tee_scenario, runners=a.num_runners, runs=a.runs_per, speed=s, prep=p, out=out, log_level=a.log_level)
            items = load_metrics(out, a.runs_per)
            agg = aggregate(items)
            rows.append({
                "tee_scenario": a.tee_scenario,
                "orders": a.orders,
                "num_runners": a.num_runners,
                "runner_speed": s,
                "prep_time": p,
                "runs": agg.runs,
                "on_time_rate_mean": round(agg.on_time, 4),
                "failed_rate_mean": round(agg.failed, 4),
                "p90_mean": round(agg.p90, 2),
                "orders_per_runner_hour_mean": round(agg.oph, 3),
            })

    write_csv(root / "sensitivity_summary.csv", rows)

    # Simple markdown
    md = root / "sensitivity_summary.md"
    lines = [f"## Sensitivity summary: scenario {a.tee_scenario}, orders {a.orders}, runners {a.num_runners}\n\n"]
    lines.append("Columns: speed, prep, on_time_rate_mean, failed_rate_mean, p90_mean, orders_per_runner_hour_mean\n\n")
    for r in rows:
        lines.append(f"- {r['runner_speed']} m/s, prep {r['prep_time']} min → on-time {r['on_time_rate_mean']:.2%}, failed {r['failed_rate_mean']:.2%}, p90 {r['p90_mean']:.1f} min, O/R-hr {r['orders_per_runner_hour_mean']:.2f}\n")
    md.write_text("".join(lines), encoding="utf-8")

    print(f"Done. Experiment directory: {root}")


if __name__ == "__main__":
    main()


