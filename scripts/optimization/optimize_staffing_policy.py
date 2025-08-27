#!/usr/bin/env python3
"""
Optimize staffing and blocking policy across order levels.

For each orders level and each blocked-holes variant, this script:
- Runs the delivery simulation across a range of runner counts
- Aggregates per-run metrics and computes Wilson CI for on-time rate
- Chooses the minimal runner count per variant that meets targets
- Recommends the best variant with the lowest runners (ties broken by CI and p90)

Example (PowerShell line breaks with `):

  python scripts/optimization/optimize_staffing_policy.py `
    --course-dir courses/pinetree_country_club `
    --tee-scenario real_tee_sheet `
    --orders-levels 20 30 40 50`
    --runner-range 1-3 `
    --runs-per 4 `
    --target-on-time 0.90 --max-failed-rate 0.05 --max-p90 40

Outputs a human-readable summary and prints a JSON recommendation to stdout.
"""

from __future__ import annotations

import argparse
import json
import math
import csv
import subprocess
import sys
from dataclasses import dataclass
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Heatmap aggregation
from golfsim.viz.heatmap_viz import create_course_heatmap

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
    BlockingVariant(key="mid", cli_flags=["--block-holes", "4", "5", "6"], description="block holes 4–6"),
    BlockingVariant(key="back", cli_flags=["--block-holes", "10", "11", "12"], description="block holes 10–12"),
    BlockingVariant(key="front_mid", cli_flags=["--block-holes", "1", "2", "3", "4", "5", "6"], description="block holes 1–6"),
    BlockingVariant(key="front_back", cli_flags=["--block-holes", "1", "2", "3", "10", "11", "12"], description="block holes 1–3 & 10–12"),
    BlockingVariant(key="mid_back", cli_flags=["--block-holes", "4", "5", "6", "10", "11", "12"], description="block holes 4–6 & 10–12"),
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


def load_one_run_metrics(run_dir: Path) -> Optional[RunMetrics]:
    # Prefer detailed metrics JSON
    for path in run_dir.glob("delivery_runner_metrics_run_*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        return RunMetrics(
            on_time_rate=float(data.get("on_time_rate", 0.0) or 0.0),
            failed_rate=float(data.get("failed_rate", 0.0) or 0.0),
            p90=float(data.get("delivery_cycle_time_p90", 0.0) or 0.0),
            avg=float(data.get("delivery_cycle_time_avg", 0.0) or 0.0),
            orders_per_runner_hour=float(data.get("orders_per_runner_hour", 0.0) or 0.0),
            successful_orders=int(data.get("successful_orders", data.get("successfulDeliveries", 0)) or 0),
            total_orders=int(data.get("total_orders", data.get("totalOrders", 0)) or 0),
        )

    # Fallback simulation_metrics.json
    sm = run_dir / "simulation_metrics.json"
    if sm.exists():
        try:
            data = json.loads(sm.read_text(encoding="utf-8"))
            dm = data.get("deliveryMetrics") or {}
            on_time_pct = float(dm.get("onTimePercentage", 0.0) or 0.0) / 100.0
            successful = int(dm.get("successfulDeliveries", 0) or 0)
            total = int(dm.get("totalOrders", 0) or 0)
            failed = int(dm.get("failedDeliveries", 0) or (total - successful))
            failed_rate = (failed / total) if total > 0 else 0.0
            # Try to extract p90 from fallback JSON if available
            p90_val = float(dm.get("deliveryCycleTimeP90", float("nan")) or float("nan"))
            avg_val = float(dm.get("avgOrderTime", 0.0) or 0.0)
            return RunMetrics(
                on_time_rate=on_time_pct,
                failed_rate=failed_rate,
                p90=p90_val,
                avg=avg_val,
                orders_per_runner_hour=float(dm.get("ordersPerRunnerHour", 0.0) or 0.0),
                successful_orders=successful,
                total_orders=total,
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

    total_successes = sum(m.successful_orders for m in items)
    total_orders = sum(m.total_orders for m in items)
    ot_lo, ot_hi = wilson_ci(total_successes, total_orders, confidence=0.95)

    return {
        "runs": len(items),
        "on_time_mean": mean(on_time_vals),
        "failed_mean": mean(failed_vals),
        "p90_mean": mean(p90_vals) if p90_vals else float("nan"),
        "avg_delivery_time_mean": mean(avg_vals) if avg_vals else float("nan"),
        "oph_mean": mean(oph_vals),
        "on_time_wilson_lo": ot_lo,
        "on_time_wilson_hi": ot_hi,
        "total_successful_orders": total_successes,
        "total_orders": total_orders,
    }


def _write_group_aggregate_file(group_dir: Path, context: Dict[str, Any], agg: Dict[str, Any]) -> None:
    """Persist per-group aggregate so it can be referenced later.

    Writes an '@aggregate.json' file under the provided group directory
    (e.g., .../orders_030/none/runners_2/@aggregate.json).
    """
    try:
        payload: Dict[str, Any] = {
            **context,
            **agg,
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
            orders = data.get("orders") or []
            stats = data.get("delivery_stats") or []
            if isinstance(orders, list):
                combined["orders"].extend(orders)
            if isinstance(stats, list):
                combined["delivery_stats"].extend(stats)

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


def _make_group_context(*, course_dir: Path, tee_scenario: str, orders: int, variant_key: str, runners: int) -> Dict[str, Any]:
    return {
        "course": str(course_dir),
        "tee_scenario": tee_scenario,
        "orders": int(orders),
        "variant": variant_key,
        "runners": int(runners),
    }


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
        "total_successful_orders": agg.get("total_successful_orders"),
        "total_orders": agg.get("total_orders"),
        "group_dir": str(group_dir),
    }
    return row


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


def run_combo(*, py: str, course_dir: Path, scenario: str, runners: int, orders: int, runs: int, out: Path, log_level: str, variant: BlockingVariant, runner_speed: Optional[float], prep_time: Optional[int]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    cmd: List[str] = [
        py, "scripts/sim/run_new.py",
        "--course-dir", str(course_dir),
        "--tee-scenario", scenario,
        "--num-runners", str(runners),
        "--delivery-total-orders", str(orders),
        "--num-runs", str(runs),
        "--output-dir", str(out),
        "--log-level", log_level,
        "--no-export-geojson",
        "--keep-old-outputs",
        "--skip-publish",
        "--coordinates-only-for-first-run",
    ]
    if variant.cli_flags:
        cmd += variant.cli_flags
    if runner_speed is not None:
        cmd += ["--runner-speed", str(runner_speed)]
    if prep_time is not None:
        cmd += ["--prep-time", str(prep_time)]
    subprocess.run(cmd, check=True)


def blocking_penalty(variant_key: str) -> float:
    """Return a penalty score for blocking variants (higher = more disruptive)."""
    penalties = {
        "none": 0.0,
        "front": 1.0,
        "mid": 1.0, 
        "back": 1.0,
        "front_mid": 2.0,
        "front_back": 2.0,
        "mid_back": 2.0,
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
        import google.generativeai as genai  # type: ignore
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
    
    prompt = (
        "You are advising a golf course General Manager. Write a CONCISE executive summary in Markdown. "
        "Keep it under 400 words total. Be direct and actionable.\n\n"
        f"Course: {course_dir}\n"
        f"Tee scenario: {tee_scenario}\n"
        f"Targets: on_time ≥ {targets.get('on_time')}, failed_rate ≤ {targets.get('max_failed')}, p90 ≤ {targets.get('max_p90')} min\n\n"
        f"Available blocking variants:\n{variant_list}\n\n"
        "Data:\n" + json.dumps(compact, indent=2) + "\n\n"
        "Format:\n"
        "1. **Summary** (2-3 sentences): Key insight about staffing vs blocking tradeoffs\n"
        "2. **Staffing Table**: Single table showing orders/hr → runners needed (baseline vs optimized)\n"
        "3. **Quick Guide**: 3-4 bullet points for when to add runners/enable blocking\n"
        "4. **Confidence**: One sentence per orders level (High/Medium/Low)\n\n"
        "Keep metrics brief: just on-time %, avg delivery time, utilization rate.\n"
        "Use plain language. No verbose explanations or detailed performance breakdowns.\n"
    )

    llm_md = _call_gemini(prompt)

    used_gemini = bool(llm_md)
    if not llm_md:
        # Concise fallback summary
        lines: List[str] = []
        lines.append(f"## Staffing Summary ({tee_scenario})")
        lines.append("")
        lines.append("Strategic hole blocking reduces runner needs while maintaining service targets.")
        lines.append("")
        
        # Single compact table
        lines.append("| Orders/Hr | Baseline | Optimized | Policy | Avg Time | Confidence |")
        lines.append("|-----------|----------|-----------|--------|----------|------------|")
        
        for row in compact:
            orders = row["orders"]
            base_runners = row.get("baseline_none_runners", "?")
            runners = row["recommended_runners"] or "?"
            variant = row.get("recommended_variant_description", "none")
            avg_time = row.get("avg_delivery_time_mean") or row.get("baseline_avg_delivery_time")
            avg_str = f"{avg_time:.1f}min" if isinstance(avg_time, (int, float)) and not math.isnan(avg_time) else "?"
            
            # Simple confidence based on utilization
            oph = row.get("orders_per_runner_hour") or row.get("baseline_oph_mean")
            if isinstance(oph, (int, float)) and oph > 10:
                confidence = "Medium"
            else:
                confidence = "High"
            
            # Shorten policy description
            policy_short = variant.replace("block holes ", "").replace(" & ", "+") if variant != "none" else "none"
            
            lines.append(f"| {orders} | {base_runners} | **{runners}** | {policy_short} | {avg_str} | {confidence} |")
        
        lines.append("")
        lines.append("**Quick Guide:**")
        lines.append("- Low volume (<30/hr): 2 runners, block distant holes")
        lines.append("- High volume (40+/hr): 3-4 runners, expand blocking")
        lines.append("- Low utilization: Use on-call staffing")
        
        llm_md = "\n".join(lines)
    else:
        # Add a provenance footer for clarity
        llm_md = llm_md.rstrip() + "\n\n_Source: Gemini_\n"

    try:
        md_path.write_text(llm_md, encoding="utf-8")
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

    # Policy comparison tables ---------------------------------------------
    def _policy_comparison_table(orders: int) -> List[str]:
        lines: List[str] = []
        per_variant = (summary.get(orders, {}).get("per_variant") or {})
        # Collect the two smallest runner counts observed across variants
        all_ns: List[int] = []
        for v_key, per_n in per_variant.items():
            try:
                all_ns += [int(n) for n in per_n.keys()]
            except Exception:
                continue
        all_ns = sorted(sorted(set(all_ns))[:2])
        if not all_ns:
            return lines

        # Header
        cols = " | ".join(["Holes blocked"] + [f"{n} runners (min)" for n in all_ns])
        lines.append(f"| {cols} |")
        lines.append(f"| {'|'.join(['-' * len('Holes blocked')] + ['-' * len(f'{n} runners (min)') for n in all_ns])}|")

        # Rows
        for v_key in [v.key for v in BLOCKING_VARIANTS if v.key in per_variant]:
            desc = variant_desc_map.get(v_key, v_key)
            cells: List[str] = [desc]
            per_n = per_variant.get(v_key, {}) or {}
            for n in all_ns:
                m = per_n.get(n) or {}
                cells.append(_fmt_min(m.get("avg_delivery_time_mean"), digits=1))
            lines.append(f"| {' | '.join(cells)} |")
        return lines

    # Build Markdown --------------------------------------------------------
    lines: List[str] = []
    lines.append("### Staffing and Blocking Policy Recommendation")
    lines.append(f"Course: {course_name}  ")
    lines.append(f"Tee scenario: {tee_name}  ")
    lines.append(
        f"Targets: on-time ≥ {int(targets.get('on_time', 0.90) * 100)}%, failed deliveries ≤ {int(targets.get('max_failed', 0.05) * 100)}%, p90 ≤ {int(targets.get('max_p90', 40.0))} min  "
    )
    lines.append("Source: `scripts/optimization/optimize_staffing_policy.py` (multi-stage confirmation with conservative on-time via Wilson lower bound)")
    lines.append("")
    lines.append("## Executive summary")
    lines.append("- Strategic blocking of specific holes can reduce the number of runners needed while keeping service within target thresholds.")
    lines.append("- Recommendations use conservative on-time (95% Wilson lower bound) and p90 checks; finalists receive extra confirmation runs for stability.")
    lines.append("- Ops playbook: keep minimal runners at low volume; enable targeted blocking to delay adding extra runners until demand persists.")
    lines.append("")
    lines.append("## Recommended staffing by volume")
    lines.append("- \"Conservative on-time\" is the lower bound of the 95% Wilson interval.")
    lines.append("- \"Policy\" is the minimal-blocking variant that met targets with the fewest runners; ties broken by a utility function (runners < blocking < p90 < on-time < failed).")
    lines.append("")
    # Staffing table
    lines.append("| Orders/hr | Policy | Runners | On-time (conservative) | Failed | Avg time (min) | p90 (min) | Orders/Runner/Hr | Confidence |")
    lines.append("|-----------|--------|---------|------------------------|--------|----------------|-----------|------------------|------------|")
    for r in rec_rows:
        lines.append(
            f"| {r['orders']}        | {r['policy']} | {r['runners']} | {r['on_time']}                 | {r['failed']}   | {r['avg_min']}           | {r['p90']}        | {r['oph']}              | {r['confidence']}     |"
        )
    lines.append("")
    if baseline_savings_notes:
        lines.append("Notes:")
        lines.extend(baseline_savings_notes)
        lines.append("")

    lines.append("## Policy comparison by orders volume")
    for orders in sorted(orders_levels):
        comp = _policy_comparison_table(orders)
        if not comp:
            continue
        lines.append("")
        lines.append(f"### {orders} orders/hr")
        lines.extend(comp)

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
            lines.append(f"- {range_text}: {r['policy']}; {r['runners']} runner(s).")

    # Service expectations across recommended policies
    lines.append("")
    lines.append("## Service quality expectations (recommended policies)")
    ot_vals = [summary.get(o, {}).get("chosen", {}).get("metrics", {}).get("on_time_wilson_lo") for o in orders_levels]
    ot_vals = [v for v in ot_vals if isinstance(v, (int, float)) and not math.isnan(v)]
    failed_vals = [summary.get(o, {}).get("chosen", {}).get("metrics", {}).get("failed_mean") for o in orders_levels]
    failed_vals = [v for v in failed_vals if isinstance(v, (int, float)) and not math.isnan(v)]
    p90_vals = [summary.get(o, {}).get("chosen", {}).get("metrics", {}).get("p90_mean") for o in orders_levels]
    p90_vals = [v for v in p90_vals if isinstance(v, (int, float)) and not math.isnan(v)]
    avg_vals = [summary.get(o, {}).get("chosen", {}).get("metrics", {}).get("avg_delivery_time_mean") for o in orders_levels]
    avg_vals = [v for v in avg_vals if isinstance(v, (int, float)) and not math.isnan(v)]
    oph_vals = [summary.get(o, {}).get("chosen", {}).get("metrics", {}).get("oph_mean") for o in orders_levels]
    oph_vals = [v for v in oph_vals if isinstance(v, (int, float)) and not math.isnan(v)]

    if ot_vals:
        lines.append(f"- On-time (conservative): {_fmt_pct(min(ot_vals))}–{_fmt_pct(max(ot_vals))} across volumes.")
    if p90_vals:
        lines.append(f"- p90: {_fmt_int(min(p90_vals))}–{_fmt_int(max(p90_vals))} minutes in recommended configurations.")
    if failed_vals:
        lines.append(f"- Failed deliveries: {_fmt_pct(min(failed_vals), digits=1)}–{_fmt_pct(max(failed_vals), digits=1)}.")
    if avg_vals:
        lines.append(f"- Average delivery time: {_fmt_min(min(avg_vals), digits=1)}–{_fmt_min(max(avg_vals), digits=1)} minutes.")
    if oph_vals:
        lines.append(f"- Orders/runner/hour: {_fmt_min(min(oph_vals), digits=1)}–{_fmt_min(max(oph_vals), digits=1)}.")

    # Risk and confidence (simple narrative)
    lines.append("")
    lines.append("## Risk and confidence")
    for r in rec_rows:
        lines.append(f"- {r['orders']} orders/hr: {r['confidence']} confidence.")

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
    lines.append("  - `@aggregate.json` in each group directory (roll-up of metrics)")
    lines.append("  - `all_metrics.csv` at the optimization root (all groups combined)")
    lines.append("  - Optional `executive_summary.md` (human summary)")
    lines.append("  - `gm_staffing_policy_report.md` (this report)")

    try:
        md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return md_path
    except Exception:
        return None

def main() -> None:
    p = argparse.ArgumentParser(description="Optimize runners and blocking policy across orders levels")
    p.add_argument("--course-dir", default="courses/pinetree_country_club")
    p.add_argument("--tee-scenario", default="real_tee_sheet")
    p.add_argument("--orders-levels", nargs="+", type=int, default=None, help="Orders totals to simulate (required unless --summarize-only)")
    p.add_argument("--runner-range", type=str, default="1-3")
    p.add_argument("--runs-per", type=int, default=4)
    # Auto confirmation pass for borderline results
    p.add_argument("--confirm-runs-per", type=int, default=16, help="rerun borderline combos with this many runs for higher confidence (used if multi-stage disabled)")
    p.add_argument("--borderline-margin", type=float, default=0.02, help="treat on_time_wilson_lo within this of target as borderline")
    p.add_argument("--no-auto-confirm", action="store_true", help="disable automatic high-confidence rerun for borderline results")
    # Multi-stage tuning
    p.add_argument("--enable-multi-stage", action="store_true", default=True, help="enable staged confirmation runs (4 + 8 + 8) to reach ~20 on finalists")
    p.add_argument("--initial-filter-margin", type=float, default=0.10, help="keep combos with conservative on_time within this of target in Stage 1")
    p.add_argument("--stage2-extra-runs", type=int, default=8, help="additional runs for remaining combos after initial filter")
    p.add_argument("--stage2-top-k", type=int, default=3, help="keep this many top combos after Stage 2 (min 2 if available)")
    p.add_argument("--stage3-extra-runs", type=int, default=8, help="additional runs for finalists to reach ~20 total")
    p.add_argument("--python-bin", default=sys.executable)
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--runner-speed", type=float, default=None)
    p.add_argument("--prep-time", type=int, default=None)
    p.add_argument("--variants", nargs="+", default=[v.key for v in BLOCKING_VARIANTS], help="Subset of variant keys to test")
    p.add_argument("--output-root", default="outputs/policy_opt")
    p.add_argument("--summarize-only", action="store_true", help="Skip running sims; summarize an existing output root")
    p.add_argument("--existing-root", type=str, default=None, help="Path to existing optimization output root to summarize")
    # Targets
    p.add_argument("--target-on-time", type=float, default=0.90)
    p.add_argument("--max-failed-rate", type=float, default=0.05)
    p.add_argument("--max-p90", type=float, default=40.0)
    p.add_argument("--concurrency", type=int, default=max(1, min(4, (os.cpu_count() or 2))), help="max concurrent simulations")
    args = p.parse_args()

    project_root = Path(__file__).resolve().parents[2]
    # Load environment variables from .env at project root if available
    if _load_dotenv is not None:
        try:
            _load_dotenv(dotenv_path=project_root / ".env", override=False)
            _load_dotenv(override=False)
        except Exception:
            pass
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
        root = Path(args.output_root)
        if not root.is_absolute():
            root = (project_root / args.output_root)
        root = (root / f"{stamp}_{args.tee_scenario}")

    summary: Dict[int, Dict[str, Any]] = {}
    csv_rows: List[Dict[str, Any]] = []

    # If summarize-only, infer orders levels and variants from folder structure
    inferred_orders: List[int] = []
    if args.summarize_only:
        for d in sorted(root.glob("orders_*")):
            if not d.is_dir():
                continue
            try:
                inferred_orders.append(int(str(d.name).split("_")[-1]))
            except Exception:
                continue
        orders_iter = sorted(inferred_orders)
    else:
        if not args.orders_levels:
            print(json.dumps({"error": "--orders-levels is required unless --summarize-only is set"}))
            sys.exit(2)
        orders_iter = args.orders_levels

    for orders in orders_iter:
        results_by_variant: Dict[str, Dict[int, Dict[str, Any]]] = {}
        # Either run combos or just aggregate existing dirs
        if not args.summarize_only:
            # Run all variant/runner combos in parallel for this orders level
            future_to_combo: Dict[Any, Tuple[BlockingVariant, int, Path]] = {}
            with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
                for variant in selected_variants:
                    for n in runner_values:
                        out_dir = root / f"orders_{orders:03d}" / variant.key / f"runners_{n}"
                        fut = executor.submit(
                            run_combo,
                            py=args.python_bin,
                            course_dir=course_dir,
                            scenario=args.tee_scenario,
                            runners=n,
                            orders=orders,
                            runs=args.runs_per,
                            out=out_dir,
                            log_level=args.log_level,
                            variant=variant,
                            runner_speed=args.runner_speed,
                            prep_time=args.prep_time,
                        )
                        future_to_combo[fut] = (variant, n, out_dir)
                for fut in as_completed(future_to_combo):
                    _ = fut.result()

        # Aggregate after all complete
        if args.summarize_only:
            orders_dir = root / f"orders_{orders:03d}"
            # Iterate all variants found under this orders dir
            for variant_dir in sorted([p for p in orders_dir.iterdir() if p.is_dir()]):
                v_key = variant_dir.name
                for runner_dir in sorted([p for p in variant_dir.glob("runners_*") if p.is_dir()]):
                    try:
                        n = int(str(runner_dir.name).split("_")[-1])
                    except Exception:
                        continue
                    run_dirs = sorted([p for p in runner_dir.glob("run_*") if p.is_dir()])
                    # Include confirm runs if present
                    for extra_name in ["confirm", "confirm_winner", "confirm_baseline", "stage2", "stage3_finalists"]:
                        extra_dir = runner_dir / extra_name
                        if extra_dir.exists():
                            run_dirs += sorted([p for p in extra_dir.glob("run_*") if p.is_dir()])
                    agg = aggregate_runs(run_dirs)
                    results_by_variant.setdefault(v_key, {})[n] = agg
                    # Persist per-group aggregate and add CSV row
                    context = _make_group_context(course_dir=course_dir, tee_scenario=args.tee_scenario, orders=orders, variant_key=v_key, runners=n)
                    _write_group_aggregate_file(runner_dir, context, agg)
                    # Write averaged heatmap across all runs in this group (best-effort)
                    _write_group_aggregate_heatmap(
                        runner_dir,
                        course_dir=course_dir,
                        tee_scenario=args.tee_scenario,
                        variant_key=v_key,
                        runners=n,
                        run_dirs=run_dirs,
                    )
                    _upsert_row(csv_rows, _row_from_context_and_agg(context, agg, runner_dir))
        else:
            for variant in selected_variants:
                for n in runner_values:
                    out_dir = root / f"orders_{orders:03d}" / variant.key / f"runners_{n}"
                    run_dirs = sorted([p for p in out_dir.glob("run_*") if p.is_dir()])
                    # Include confirm-style runs if present
                    for extra_name in ["confirm", "confirm_winner", "confirm_baseline", "stage2", "stage3_finalists"]:
                        extra_dir = out_dir / extra_name
                        if extra_dir.exists():
                            run_dirs += sorted([p for p in extra_dir.glob("run_*") if p.is_dir()])
                    agg = aggregate_runs(run_dirs)
                    results_by_variant.setdefault(variant.key, {})[n] = agg
                    # Persist per-group aggregate and add CSV row
                    context = _make_group_context(course_dir=course_dir, tee_scenario=args.tee_scenario, orders=orders, variant_key=variant.key, runners=n)
                    _write_group_aggregate_file(out_dir, context, agg)
                    # Write averaged heatmap across all runs in this group (best-effort)
                    _write_group_aggregate_heatmap(
                        out_dir,
                        course_dir=course_dir,
                        tee_scenario=args.tee_scenario,
                        variant_key=variant.key,
                        runners=n,
                        run_dirs=run_dirs,
                    )
                    _upsert_row(csv_rows, _row_from_context_and_agg(context, agg, out_dir))

        # Multi-stage confirmation pipeline or fallback to borderline confirm
        if not args.summarize_only:
            if args.enable_multi_stage:
                # Stage 1: filter obvious non-options using initial 4 runs
                # For each variant, keep up to two smallest runner counts that pass the broadened screen
                keep_stage1: List[Tuple[BlockingVariant, int]] = []
                for variant in selected_variants:
                    per_runner = (results_by_variant.get(variant.key, {}) or {})
                    candidates_for_variant: List[int] = []
                    for n in sorted(per_runner.keys()):
                        agg = per_runner.get(n)
                        if not agg or not agg.get("runs"):
                            continue
                        ot_lo = float(agg.get("on_time_wilson_lo", 0.0) or 0.0)
                        failed_mean = float(agg.get("failed_mean", 1.0) or 1.0)
                        p90_mean = agg.get("p90_mean", float("nan"))
                        
                        # Broadened screening: check all three targets with margins
                        ot_passes = ot_lo >= (args.target_on_time - args.initial_filter_margin)
                        failed_passes = failed_mean <= (args.max_failed_rate * (1.0 + args.initial_filter_margin))
                        p90_passes = (math.isnan(p90_mean) or 
                                     p90_mean <= (args.max_p90 * (1.0 + args.initial_filter_margin)))
                        
                        if ot_passes and failed_passes and p90_passes:
                            candidates_for_variant.append(n)
                    
                    # Keep up to two smallest passing runner counts per variant
                    for n in sorted(candidates_for_variant)[:2]:
                        keep_stage1.append((variant, n))

                # Stage 2: add runs to all kept combos
                with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
                    futures: Dict[Any, Tuple[BlockingVariant, int, Path]] = {}
                    for variant, n in keep_stage1:
                        out_dir = root / f"orders_{orders:03d}" / variant.key / f"runners_{n}"
                        stage2_dir = out_dir / "stage2"
                        fut = executor.submit(
                            run_combo,
                            py=args.python_bin,
                            course_dir=course_dir,
                            scenario=args.tee_scenario,
                            runners=n,
                            orders=orders,
                            runs=args.stage2_extra_runs,
                            out=stage2_dir,
                            log_level=args.log_level,
                            variant=variant,
                            runner_speed=args.runner_speed,
                            prep_time=args.prep_time,
                        )
                        futures[fut] = (variant, n, stage2_dir)
                    for fut in as_completed(futures):
                        _ = fut.result()

                # Re-aggregate after Stage 2
                for variant, n in keep_stage1:
                    out_dir = root / f"orders_{orders:03d}" / variant.key / f"runners_{n}"
                    run_dirs = sorted([p for p in out_dir.glob("run_*") if p.is_dir()])
                    for extra_name in ["stage2"]:
                        extra_dir = out_dir / extra_name
                        if extra_dir.exists():
                            run_dirs += sorted([p for p in extra_dir.glob("run_*") if p.is_dir()])
                    agg2 = aggregate_runs(run_dirs)
                    results_by_variant.setdefault(variant.key, {})[n] = agg2
                    # Write group aggregate and update CSV row
                    context = _make_group_context(course_dir=course_dir, tee_scenario=args.tee_scenario, orders=orders, variant_key=variant.key, runners=n)
                    _write_group_aggregate_file(out_dir, context, agg2)
                    # Update averaged heatmap including Stage 2 runs
                    _write_group_aggregate_heatmap(
                        out_dir,
                        course_dir=course_dir,
                        tee_scenario=args.tee_scenario,
                        variant_key=variant.key,
                        runners=n,
                        run_dirs=run_dirs,
                    )
                    _upsert_row(csv_rows, _row_from_context_and_agg(context, agg2, out_dir))

                # Rank all kept combos by utility score (no hard filter on minimal runners)
                scored_all: List[Tuple[float, BlockingVariant, int]] = []
                for variant, n in keep_stage1:
                    agg = results_by_variant.get(variant.key, {}).get(n)
                    if not agg or not agg.get("runs"):
                        continue
                    score = utility_score(variant.key, n, agg)
                    scored_all.append((score, variant, n))
                
                if not scored_all:
                    finalists = []
                else:
                    # Sort by utility score (lower is better) and take top k
                    scored_all.sort(key=lambda t: t[0])
                    k = max(2, min(args.stage2_top_k, len(scored_all)))
                    finalists = [(v, n) for _, v, n in scored_all[:k]]

                # Stage 3: add runs for finalists
                with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
                    futures3: Dict[Any, Tuple[BlockingVariant, int, Path]] = {}
                    for variant, n in finalists:
                        out_dir = root / f"orders_{orders:03d}" / variant.key / f"runners_{n}"
                        stage3_dir = out_dir / "stage3_finalists"
                        fut = executor.submit(
                            run_combo,
                            py=args.python_bin,
                            course_dir=course_dir,
                            scenario=args.tee_scenario,
                            runners=n,
                            orders=orders,
                            runs=args.stage3_extra_runs,
                            out=stage3_dir,
                            log_level=args.log_level,
                            variant=variant,
                            runner_speed=args.runner_speed,
                            prep_time=args.prep_time,
                        )
                        futures3[fut] = (variant, n, stage3_dir)
                    for fut in as_completed(futures3):
                        _ = fut.result()

                # Re-aggregate finalists after Stage 3
                for variant, n in finalists:
                    out_dir = root / f"orders_{orders:03d}" / variant.key / f"runners_{n}"
                    run_dirs = sorted([p for p in out_dir.glob("run_*") if p.is_dir()])
                    for extra_name in ["stage2", "stage3_finalists"]:
                        extra_dir = out_dir / extra_name
                        if extra_dir.exists():
                            run_dirs += sorted([p for p in extra_dir.glob("run_*") if p.is_dir()])
                    agg3 = aggregate_runs(run_dirs)
                    results_by_variant.setdefault(variant.key, {})[n] = agg3
                    # Write group aggregate and update CSV row
                    context = _make_group_context(course_dir=course_dir, tee_scenario=args.tee_scenario, orders=orders, variant_key=variant.key, runners=n)
                    _write_group_aggregate_file(out_dir, context, agg3)
                    # Update averaged heatmap including Stage 3 runs
                    _write_group_aggregate_heatmap(
                        out_dir,
                        course_dir=course_dir,
                        tee_scenario=args.tee_scenario,
                        variant_key=variant.key,
                        runners=n,
                        run_dirs=run_dirs,
                    )
                    _upsert_row(csv_rows, _row_from_context_and_agg(context, agg3, out_dir))
            elif not args.no_auto_confirm:
                # Fallback to simple borderline confirm behavior
                borderline: List[Tuple[BlockingVariant, int]] = []
                for variant in selected_variants:
                    per_runner = results_by_variant.get(variant.key, {})
                    for n, agg in per_runner.items():
                        if not agg or not agg.get("runs"):
                            continue
                        ot_lo = float(agg.get("on_time_wilson_lo", 0.0) or 0.0)
                        if abs(ot_lo - args.target_on_time) <= args.borderline_margin:
                            borderline.append((variant, n))

                with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
                    future_to_confirm: Dict[Any, Tuple[BlockingVariant, int, Path]] = {}
                    for variant, n in borderline:
                        out_dir = root / f"orders_{orders:03d}" / variant.key / f"runners_{n}"
                        confirm_dir = out_dir / "confirm"
                        fut = executor.submit(
                            run_combo,
                            py=args.python_bin,
                            course_dir=course_dir,
                            scenario=args.tee_scenario,
                            runners=n,
                            orders=orders,
                            runs=args.confirm_runs_per,
                            out=confirm_dir,
                            log_level=args.log_level,
                            variant=variant,
                            runner_speed=args.runner_speed,
                            prep_time=args.prep_time,
                        )
                        future_to_confirm[fut] = (variant, n, confirm_dir)
                    for fut in as_completed(future_to_confirm):
                        _ = fut.result()

                for variant, n in borderline:
                    out_dir = root / f"orders_{orders:03d}" / variant.key / f"runners_{n}"
                    confirm_dir = out_dir / "confirm"
                    orig_dirs = sorted([p for p in out_dir.glob("run_*") if p.is_dir()])
                    confirm_dirs = sorted([p for p in confirm_dir.glob("run_*") if p.is_dir()])
                    agg = aggregate_runs(orig_dirs + confirm_dirs)
                    results_by_variant.setdefault(variant.key, {})[n] = agg
                    context = _make_group_context(course_dir=course_dir, tee_scenario=args.tee_scenario, orders=orders, variant_key=variant.key, runners=n)
                    _write_group_aggregate_file(out_dir, context, agg)
                    _upsert_row(csv_rows, _row_from_context_and_agg(context, agg, out_dir))

        chosen = choose_best_variant(
            results_by_variant,
            target_on_time=args.target_on_time,
            max_failed=args.max_failed_rate,
            max_p90=args.max_p90,
        )

        human: str
        baseline = None
        baseline_metrics: Optional[Dict[str, Any]] = None
        if chosen is not None:
            v_key, v_runners, v_agg = chosen
            # Compute baseline (no blocks) minimal before confirm
            if "none" in results_by_variant:
                for n in sorted(results_by_variant["none"].keys()):
                    agg = results_by_variant["none"][n]
                    if not agg or not agg.get("runs"):
                        continue
                    
                    p90_mean = agg.get("p90_mean", float("nan"))
                    # If p90 data is available, enforce the target; if missing (NaN), allow it to pass
                    p90_meets = math.isnan(p90_mean) or p90_mean <= args.max_p90
                    
                    if (agg.get("on_time_wilson_lo", 0.0) >= args.target_on_time
                        and agg.get("failed_mean", 1.0) <= args.max_failed_rate
                        and p90_meets):
                        baseline = n
                        baseline_metrics = agg
                        break

            # Winner confirm pass: rerun the chosen combo with higher runs for accuracy
            if not args.summarize_only:
                if chosen is not None:
                    v_key, v_runners, _ = chosen
                    winner_dir = root / f"orders_{orders:03d}" / v_key / f"runners_{v_runners}"
                    confirm_winner_dir = winner_dir / "confirm_winner"
                    run_combo(
                        py=args.python_bin,
                        course_dir=course_dir,
                        scenario=args.tee_scenario,
                        runners=v_runners,
                        orders=orders,
                        runs=args.confirm_runs_per,
                        out=confirm_winner_dir,
                        log_level=args.log_level,
                        variant=variant_map[v_key],
                        runner_speed=args.runner_speed,
                        prep_time=args.prep_time,
                    )
                    
                    # Symmetric baseline confirm pass: if winner uses blocking or fewer runners than baseline
                    if baseline is not None and (v_key != "none" or v_runners < baseline):
                        baseline_dir = root / f"orders_{orders:03d}" / "none" / f"runners_{baseline}"
                        confirm_baseline_dir = baseline_dir / "confirm_baseline"
                        run_combo(
                            py=args.python_bin,
                            course_dir=course_dir,
                            scenario=args.tee_scenario,
                            runners=baseline,
                            orders=orders,
                            runs=args.confirm_runs_per,
                            out=confirm_baseline_dir,
                            log_level=args.log_level,
                            variant=variant_map["none"],
                            runner_speed=args.runner_speed,
                            prep_time=args.prep_time,
                        )
                        # Re-aggregate baseline including confirm runs
                        baseline_run_dirs = sorted([p for p in baseline_dir.glob("run_*") if p.is_dir()])
                        for extra_name in ["confirm", "confirm_winner", "confirm_baseline"]:
                            extra_dir = baseline_dir / extra_name
                            if extra_dir.exists():
                                baseline_run_dirs += sorted([p for p in extra_dir.glob("run_*") if p.is_dir()])
                        results_by_variant.setdefault("none", {})[baseline] = aggregate_runs(baseline_run_dirs)
                        # Update baseline group aggregate and CSV
                        base_out_dir = baseline_dir
                        base_context = _make_group_context(course_dir=course_dir, tee_scenario=args.tee_scenario, orders=orders, variant_key="none", runners=baseline)
                        base_agg = results_by_variant.get("none", {}).get(baseline, {})
                        if base_agg:
                            _write_group_aggregate_file(base_out_dir, base_context, base_agg)
                            # Update averaged heatmap including confirm baseline runs
                            _write_group_aggregate_heatmap(
                                base_out_dir,
                                course_dir=course_dir,
                                tee_scenario=args.tee_scenario,
                                variant_key="none",
                                runners=baseline,
                                run_dirs=baseline_run_dirs,
                            )
                            _upsert_row(csv_rows, _row_from_context_and_agg(base_context, base_agg, base_out_dir))
                    
                    # Re-aggregate winner combo including confirm directories
                    run_dirs = sorted([p for p in winner_dir.glob("run_*") if p.is_dir()])
                    for extra_name in ["confirm", "confirm_winner", "confirm_baseline"]:
                        extra_dir = winner_dir / extra_name
                        if extra_dir.exists():
                            run_dirs += sorted([p for p in extra_dir.glob("run_*") if p.is_dir()])
                    results_by_variant.setdefault(v_key, {})[v_runners] = aggregate_runs(run_dirs)
                    # Update winner group aggregate and CSV
                    win_out_dir = winner_dir
                    win_context = _make_group_context(course_dir=course_dir, tee_scenario=args.tee_scenario, orders=orders, variant_key=v_key, runners=v_runners)
                    win_agg = results_by_variant.get(v_key, {}).get(v_runners, {})
                    if win_agg:
                        _write_group_aggregate_file(win_out_dir, win_context, win_agg)
                        # Update averaged heatmap including confirm winner runs
                        _write_group_aggregate_heatmap(
                            win_out_dir,
                            course_dir=course_dir,
                            tee_scenario=args.tee_scenario,
                            variant_key=v_key,
                            runners=v_runners,
                            run_dirs=run_dirs,
                        )
                        _upsert_row(csv_rows, _row_from_context_and_agg(win_context, win_agg, win_out_dir))
                    
                    # Recompute chosen after higher-accuracy aggregation
                    chosen = choose_best_variant(
                        results_by_variant,
                        target_on_time=args.target_on_time,
                        max_failed=args.max_failed_rate,
                        max_p90=args.max_p90,
                    )

        if chosen is None:
            human = f"Orders {orders}: No variant met targets up to {max(runner_values)} runners."
        else:
            v_key, v_runners, v_agg = chosen
            desc = variant_map[v_key].description
            if baseline is not None and v_runners < baseline:
                human = f"Orders {orders}: You can use {v_runners} runner(s) if you {desc}; otherwise you need {baseline} runner(s)."
            else:
                human = f"Orders {orders}: Recommended {v_runners} runner(s) with policy: {desc}."

        print(human)

        # Always also report a recommendation for the no-blocks baseline
        baseline_none_runners = None
        baseline_none_metrics: Optional[Dict[str, Any]] = None
        if "none" in results_by_variant:
            for n in sorted(results_by_variant["none"].keys()):
                agg = results_by_variant["none"][n]
                if not agg or not agg.get("runs"):
                    continue
                
                p90_mean = agg.get("p90_mean", float("nan"))
                # If p90 data is available, enforce the target; if missing (NaN), allow it to pass
                p90_meets = math.isnan(p90_mean) or p90_mean <= args.max_p90
                
                if (agg.get("on_time_wilson_lo", 0.0) >= args.target_on_time
                    and agg.get("failed_mean", 1.0) <= args.max_failed_rate
                    and p90_meets):
                    baseline_none_runners = n
                    baseline_none_metrics = agg
                    break
        if baseline_none_runners is not None:
            print(f"Orders {orders} (no blocked holes): Recommended {baseline_none_runners} runner(s).")
        else:
            print(f"Orders {orders} (no blocked holes): No runner count up to {max(runner_values)} met targets.")

        summary[orders] = {
            "chosen": {
                "variant": chosen[0] if chosen else None,
                "runners": chosen[1] if chosen else None,
                "metrics": chosen[2] if chosen else None,
            },
            "per_variant": results_by_variant,
            "baseline_none": {
                "runners": baseline_none_runners,
                "metrics": baseline_none_metrics,
            },
        }

    # Print machine-readable JSON at the end
    print(json.dumps({
        "course": str(course_dir),
        "tee_scenario": args.tee_scenario,
        "runs_per": args.runs_per,
        "targets": {"on_time": args.target_on_time, "max_failed": args.max_failed_rate, "max_p90": args.max_p90},
        "orders_levels": orders_iter,
        "summary": summary,
        "output_root": str(root),
    }, indent=2))

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

    # Write final CSV with all group aggregates collected
    try:
        csv_path = _write_final_csv(root, csv_rows)
        if csv_path is not None:
            print(f"Aggregated metrics CSV written to {csv_path}")
    except Exception:
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


if __name__ == "__main__":
    main()


