#!/usr/bin/env python3
"""
Generate a GM-ready recommendations markdown by reading experiment outputs:
- staffing_summary.csv, experiment_summary.md, and hole_policy_1_runner.md files

Writes docs/recommendations_<exp-name>.md without modifying existing files.

Usage:
  python scripts/optimization/generate_recommendations.py --exp-root outputs/experiments/baseline --course Pinetree --out docs/recommendations_baseline.md
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any, Dict, List, Tuple


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate GM recommendations from experiment outputs")
    p.add_argument("--exp-root", required=True, help="Experiment root folder (outputs/experiments/<exp>)")
    p.add_argument("--course", required=True, help="Course name for the report header")
    p.add_argument("--out", required=True, help="Output markdown path (docs/recommendations_<exp>.md)")
    return p.parse_args()


def read_staffing_csv(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        return list(r)


def read_experiment_summary(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def find_hole_policies(exp_root: Path) -> List[Tuple[str, int, Path]]:
    items: List[Tuple[str, int, Path]] = []
    for md in exp_root.rglob("hole_policy_1_runner.md"):
        try:
            # Expect .../<scenario>/orders_XXX/hole_policy_1_runner.md
            parts = md.parts
            orders_part = md.parent.name  # orders_XXX
            orders = int(orders_part.split("_")[-1])
            scenario = md.parent.parent.name  # scenario name folder
            items.append((scenario, orders, md))
        except Exception:
            continue
    return sorted(items, key=lambda t: (t[0], t[1]))


def build_staffing_table(rows: List[Dict[str, Any]]) -> str:
    if not rows:
        return "No staffing data found.\n"
    # Filter meets_targets True and pick minimal per scenario/orders
    by_key: Dict[Tuple[str, int], Dict[str, Any]] = {}
    for r in rows:
        scenario = r.get("tee_scenario", "")
        orders = int(float(r.get("orders", 0)))
        meets = str(r.get("meets_targets", "")).lower() in ("true", "1", "yes")
        if not meets:
            continue
        key = (scenario, orders)
        prev = by_key.get(key)
        if prev is None or int(float(r.get("num_runners", 999))) < int(float(prev.get("num_runners", 999))):
            by_key[key] = r
    
    lines: List[str] = []
    lines.append("| Scenario | Orders | Minimal Runners | On-Time (95% CI) | Failed (95% CI) | p90 (95% CI) | Stability | Frontier |\n")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|\n")
    
    for (scenario, orders), r in sorted(by_key.items(), key=lambda t: (t[0][0], t[0][1])):
        # Format confidence intervals
        on_time_ci = f"{float(r.get('on_time_rate_mean', 0)):.2f} ({float(r.get('on_time_rate_ci_lower', 0)):.2f}-{float(r.get('on_time_rate_ci_upper', 0)):.2f})"
        failed_ci = f"{float(r.get('failed_rate_mean', 0)):.3f} ({float(r.get('failed_rate_ci_lower', 0)):.3f}-{float(r.get('failed_rate_ci_upper', 0)):.3f})"
        p90_ci = f"{float(r.get('p90_mean', 0)):.1f} ({float(r.get('p90_ci_lower', 0)):.1f}-{float(r.get('p90_ci_upper', 0)):.1f})"
        
        # Stability and frontier flags
        is_stable = str(r.get("is_stable", "")).lower() in ("true", "1", "yes")
        is_frontier = str(r.get("is_frontier_point", "")).lower() in ("true", "1", "yes")
        is_knee = str(r.get("is_knee_point", "")).lower() in ("true", "1", "yes")
        
        stability_badge = "✅ Stable" if is_stable else "⚠️ Unstable"
        frontier_badge = ""
        if is_knee:
            frontier_badge = "🎯 Knee Point"
        elif is_frontier:
            frontier_badge = "⭐ Frontier"
        else:
            frontier_badge = "-"
        
        lines.append(
            f"| {scenario} | {orders} | {int(float(r['num_runners']))} | {on_time_ci} | {failed_ci} | {p90_ci} | {stability_badge} | {frontier_badge} |\n"
        )
    return "".join(lines)


def build_hole_policy_section(items: List[Tuple[str, int, Path]]) -> str:
    if not items:
        return "No hole policy files found.\n"
    lines: List[str] = []
    for scenario, orders, md_path in items:
        lines.append(f"- Scenario: {scenario}, Orders: {orders} — see {md_path}\n")
    return "".join(lines)


def main() -> None:
    a = parse_args()
    exp_root = Path(a.exp_root)
    out_path = Path(a.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    staffing_rows = read_staffing_csv(exp_root / "staffing_summary.csv")
    experiment_summary = read_experiment_summary(exp_root / "experiment_summary.md")
    hole_policies = find_hole_policies(exp_root)

    lines: List[str] = []
    lines.append(f"## GM Recommendations — {a.course} — {exp_root.name}\n\n")
    lines.append("### Executive Summary\n")
    lines.append("See experiment summary below; staffing curve table and hole policy links follow.\n\n")
    lines.append("### Staffing Curve (meets targets)\n")
    lines.append("Targets: on_time_rate ≥ 95%, failed_rate ≤ 5%, p90 ≤ 40 min.\n\n")
    lines.append(build_staffing_table(staffing_rows) + "\n")
    lines.append("### 1-Runner Day Policy (Hole Restrictions)\n\n")
    lines.append(build_hole_policy_section(hole_policies) + "\n")
    lines.append("### Experiment Summary\n\n")
    lines.append(experiment_summary or "(No experiment_summary.md found)\n")

    out_path.write_text("".join(lines), encoding="utf-8")
    print(f"Wrote recommendations to {out_path}")


if __name__ == "__main__":
    main()


