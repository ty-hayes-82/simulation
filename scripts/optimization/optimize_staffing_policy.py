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
import subprocess
import sys
from dataclasses import dataclass
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

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
            return RunMetrics(
                on_time_rate=on_time_pct,
                failed_rate=failed_rate,
                p90=p90_val,
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
    oph_vals = [m.orders_per_runner_hour for m in items if not math.isnan(m.orders_per_runner_hour)]

    total_successes = sum(m.successful_orders for m in items)
    total_orders = sum(m.total_orders for m in items)
    ot_lo, ot_hi = wilson_ci(total_successes, total_orders, confidence=0.95)

    return {
        "runs": len(items),
        "on_time_mean": mean(on_time_vals),
        "failed_mean": mean(failed_vals),
        "p90_mean": mean(p90_vals) if p90_vals else float("nan"),
        "oph_mean": mean(oph_vals),
        "on_time_wilson_lo": ot_lo,
        "on_time_wilson_hi": ot_hi,
        "total_successful_orders": total_successes,
        "total_orders": total_orders,
    }


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
        "--minimal-outputs",
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
            # Enforce real p90 values - no NaN allowed for p90 target checks
            p90_meets = not math.isnan(p90_mean) and p90_mean <= max_p90
            
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
        compact.append({
            "orders": int(orders),
            "recommended_variant": chosen_variant,
            "recommended_variant_description": variant_desc.get(str(chosen_variant), variant_desc.get(chosen_variant, chosen_variant)),
            "recommended_runners": chosen_runners,
            "runs": metrics.get("runs"),
            "on_time_wilson_lo": metrics.get("on_time_wilson_lo"),
            "failed_mean": metrics.get("failed_mean"),
            "p90_mean": metrics.get("p90_mean"),
            "orders_per_runner_hour": metrics.get("oph_mean"),
            "baseline_none_runners": baseline_runners,
            "baseline_on_time_wilson_lo": (baseline_metrics or {}).get("on_time_wilson_lo"),
            "baseline_failed_mean": (baseline_metrics or {}).get("failed_mean"),
            "baseline_p90_mean": (baseline_metrics or {}).get("p90_mean"),
            "baseline_oph_mean": (baseline_metrics or {}).get("oph_mean"),
        })

    prompt = (
        "You are advising a golf course General Manager. Using the simulation optimization results, "
        "write a clear, actionable executive summary in Markdown with staffing and policy guidance by total orders. "
        "Speak directly, avoid jargon, and give pragmatic recommendations a manager can implement today.\n\n"
        f"Course: {course_dir}\n"
        f"Tee scenario: {tee_scenario}\n"
        f"Targets: on_time ≥ {targets.get('on_time')}, failed_rate ≤ {targets.get('max_failed')}, p90 ≤ {targets.get('max_p90')} min\n\n"
        "Data (JSON):\n" + json.dumps(compact, indent=2) + "\n\n"
        "Instructions:\n"
        "- Start with a brief narrative (3-6 sentences) summarizing how staffing should scale with orders. First provide recommendations with no holes blocked, then a separate section with blocking options where helpful.\n"
        "- For each orders level, give a one-line recommendation with:\n"
        "  Orders → Dedicated runners, On-call coverage (if any), Blocking policy, and key metrics "
        "(on_time CI low, failed rate, p90, orders per runner hour).\n"
        "- Explicitly assess utilization and suggest using on-call/float coverage when additional runners have low expected load:\n"
        "  Use orders per runner hour as a utilization proxy. If recommended runners ≥ 2 and orders per runner hour < 1.5, "
        "recommend keeping the last runner on-call rather than fully staffed; if ≥ 3 and orders per runner hour < 1.2, "
        "suggest that the 2nd/3rd runner can be on-call to handle a small number of orders.\n"
        "- Explain confidence in plain language. Avoid statistical jargon. Use phrasing like: \"we tested this plan multiple times,\" \"even on a tougher day it still clears the bar,\" and \"there is a cushion above target.\"\n"
        "  Translate technical ideas: use \"conservative on-time estimate\" instead of \"confidence interval lower bound\".\n"
        "  Flag borderline cases with simple rules of thumb (e.g., add one runner during peak tee-time waves).\n"
        "- Provide a concise ‘Manager Playbook’ section with bullet points: when to add a runner, when on-call is sufficient, "
        "and when to enable hole blocking to meet targets.\n"
        "- End with a bottom line recommendation for each orders level, with a simple confidence tag (High/Medium) and a one-sentence reason.\n"
        "- Add a short section titled 'Why these recommendations will hold' that explains confidence in layman’s terms: "
        "mention the number of times we tested the plan (initial 4-run screen plus any follow-up runs), a conservative on-time estimate vs the target, "
        "and that we eliminated clearly non-viable options early.\n"
    )

    llm_md = _call_gemini(prompt)

    used_gemini = bool(llm_md)
    if not llm_md:
        # Fallback concise summary
        lines: List[str] = []
        lines.append(f"### Executive Summary — Staffing Recommendations ({tee_scenario})")
        lines.append("")
        lines.append("These recommendations are based on aggregated simulation results. Targets: "
                     f"on_time ≥ {targets.get('on_time')}, failed_rate ≤ {targets.get('max_failed')}, "
                     f"p90 ≤ {targets.get('max_p90')} min.")
        lines.append("")
        # Top: No-block recommendations
        lines.append("#### No blocked holes (baseline)")
        for row in compact:
            orders = row["orders"]
            base_runners = row.get("baseline_none_runners")
            base_ot = row.get("baseline_on_time_wilson_lo")
            base_failed = row.get("baseline_failed_mean")
            base_p90 = row.get("baseline_p90_mean")
            base_oph = row.get("baseline_oph_mean")
            base_bits: List[str] = []
            if isinstance(base_ot, (int, float)):
                base_bits.append(f"conservative on-time: {base_ot*100:.0f}%")
            if isinstance(base_failed, (int, float)):
                base_bits.append(f"failed: {base_failed*100:.0f}%")
            if isinstance(base_p90, (int, float)) and not math.isnan(base_p90):
                base_bits.append(f"p90: {base_p90:.1f} min")
            if isinstance(base_oph, (int, float)):
                base_bits.append(f"orders/runner/hr: {base_oph:.1f}")
            base_str = ", ".join(base_bits)
            if base_runners is not None:
                lines.append(f"- Orders {orders}: {base_runners} runner(s); policy: no blocked holes. {base_str}")
            else:
                lines.append(f"- Orders {orders}: No-block baseline did not meet targets.")
        lines.append("")
        # Bottom: With blocking options (if helpful)
        lines.append("#### With blocking (only if needed)")
        for row in compact:
            orders = row["orders"]
            runners = row["recommended_runners"]
            variant = row.get("recommended_variant")
            policy_desc = row.get("recommended_variant_description") or str(variant)
            ot = row.get("on_time_wilson_lo")
            failed = row.get("failed_mean")
            p90 = row.get("p90_mean")
            oph = row.get("orders_per_runner_hour")
            runs_used = row.get("runs")
            metrics_bits: List[str] = []
            if isinstance(ot, (int, float)):
                metrics_bits.append(f"conservative on-time: {ot*100:.0f}%")
            if isinstance(failed, (int, float)):
                metrics_bits.append(f"failed: {failed*100:.0f}%")
            if isinstance(p90, (int, float)) and not math.isnan(p90):
                metrics_bits.append(f"p90: {p90:.1f} min")
            if isinstance(oph, (int, float)):
                metrics_bits.append(f"orders/runner/hr: {oph:.1f}")
            if isinstance(runs_used, int):
                metrics_bits.append(f"runs: {runs_used}")
            metrics_str = ", ".join(metrics_bits)
            on_call_note = ""
            if isinstance(runners, int) and isinstance(oph, (int, float)):
                if runners >= 3 and oph < 1.2:
                    on_call_note = " Consider on-call coverage for additional runners (low utilization)."
                elif runners >= 2 and oph < 1.5:
                    on_call_note = " Consider keeping the last runner on-call (low utilization)."
            if variant == "none":
                lines.append(f"- Orders {orders}: No blocking required; see baseline above.")
            else:
                lines.append(f"- Orders {orders}: {runners} runner(s); policy: {policy_desc}. {metrics_str}.{on_call_note}")
        lines.append("")
        lines.append("#### Why these recommendations will hold (plain English)")
        lines.append("- We tried each plan multiple times. First a quick 4-run screen to toss out bad fits, then extra runs on the best plan to double-check it.")
        lines.append("- The conservative on-time estimate is our \"even on a tougher day\" view. When that number is above your target, there’s a cushion.")
        for row in compact:
            orders = row["orders"]
            ot = row.get("on_time_wilson_lo")
            runs_used = row.get("runs")
            margin_note = ""
            if isinstance(ot, (int, float)) and isinstance(targets.get('on_time'), (int, float)):
                margin = ot - float(targets.get('on_time') or 0.0)
                margin_note = f"; cushion above target: {margin*100:.0f} percentage points" if margin >= 0 else f"; short of target by {abs(margin)*100:.0f} points"
            run_note = f"tested {int(runs_used)} runs" if isinstance(runs_used, int) else "tested 4+ runs"
            lines.append(f"- Orders {orders}: {run_note}{margin_note}")
        lines.append("")
        lines.append("#### Notes")
        lines.append("- Borderline cases (on_time near target) may vary run-to-run; consider +1 runner at peak periods.")
        lines.append("- If orders/runner/hr < 1.5 with 2+ runners, keep the last runner on-call to cover a few orders.")
        lines.append("- If 3+ runners and orders/runner/hr < 1.2, use on-call coverage for the 2nd/3rd runner.")
        lines.append("")
        lines.append("_Source: Local fallback_")
        llm_md = "\n".join(lines)
    else:
        # Add a provenance footer for clarity
        llm_md = llm_md.rstrip() + "\n\n_Source: Gemini_\n"

    try:
        md_path.write_text(llm_md, encoding="utf-8")
        return md_path, used_gemini
    except Exception:
        return None, used_gemini


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
                    results_by_variant.setdefault(variant.key, {})[n] = aggregate_runs(run_dirs)

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
                    results_by_variant.setdefault(variant.key, {})[n] = aggregate_runs(run_dirs)
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
                    # Enforce real p90 values - no NaN allowed for p90 target checks
                    p90_meets = not math.isnan(p90_mean) and p90_mean <= args.max_p90
                    
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
                    
                    # Re-aggregate winner combo including confirm directories
                    run_dirs = sorted([p for p in winner_dir.glob("run_*") if p.is_dir()])
                    for extra_name in ["confirm", "confirm_winner", "confirm_baseline"]:
                        extra_dir = winner_dir / extra_name
                        if extra_dir.exists():
                            run_dirs += sorted([p for p in extra_dir.glob("run_*") if p.is_dir()])
                    results_by_variant.setdefault(v_key, {})[v_runners] = aggregate_runs(run_dirs)
                    
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
                # Enforce real p90 values - no NaN allowed for p90 target checks
                p90_meets = not math.isnan(p90_mean) and p90_mean <= args.max_p90
                
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


if __name__ == "__main__":
    main()


