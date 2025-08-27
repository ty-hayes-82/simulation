#!/usr/bin/env python3
"""
Generate GM staffing policy report via per-section Gemini prompts.

This script:
1) Calls optimize_staffing_policy.py in summarize-only mode for an existing output root
2) Builds compact data for each section
3) Calls Gemini separately per section to produce Markdown
4) Assembles the final gm_staffing_policy_report.md

Requirements:
- Environment variable GEMINI_API_KEY or GOOGLE_API_KEY
- Package google-generativeai installed

Example:
  python scripts/optimization/generate_gm_report_gemini.py \
    --existing-root outputs/policy_opt/20250826_155339_real_tee_sheet
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from dotenv import load_dotenv as _load_dotenv  # type: ignore
except Exception:
    _load_dotenv = None


def _load_optimizer_json(existing_root: Path, *, python_bin: str, optimizer_script: Path) -> Dict[str, Any]:
    """Invoke optimizer in summarize-only mode and capture the JSON payload it prints.

    The optimizer prints human lines before and after the JSON; we extract the JSON
    object by scanning for a balanced {...} that parses and contains the 'summary' key.
    """
    cmd = [
        python_bin,
        str(optimizer_script),
        "--summarize-only",
        "--existing-root",
        str(existing_root),
    ]
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")

    # Attempt to extract JSON by scanning braces from the end
    def _try_extract_json(text: str) -> Optional[Dict[str, Any]]:
        starts: List[int] = [i for i, ch in enumerate(text) if ch == "{"]
        for start in reversed(starts):
            depth = 0
            end_idx = None
            for i in range(start, len(text)):
                ch = text[i]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end_idx = i + 1
                        break
            if end_idx is None:
                continue
            candidate = text[start:end_idx]
            try:
                data = json.loads(candidate)
                if isinstance(data, dict) and "summary" in data and "orders_levels" in data:
                    return data
            except Exception:
                continue
        return None

    data = _try_extract_json(out)
    if not data:
        raise RuntimeError("Failed to extract optimizer JSON from output.")
    return data


def _get_style_reference(existing_root: Path, style_md_path: Optional[Path]) -> Optional[str]:
    # Prefer provided path; otherwise use executive_summary.md in the root if available
    if style_md_path and style_md_path.exists():
        try:
            return style_md_path.read_text(encoding="utf-8")
        except Exception:
            pass
    default_style = existing_root / "executive_summary.md"
    if default_style.exists():
        try:
            return default_style.read_text(encoding="utf-8")
        except Exception:
            pass
    return None


def _compact_data_for_sections(data: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    # Summarize per-orders chosen and baseline for prompting
    summary: Dict[int, Dict[str, Any]] = data.get("summary", {})
    # Variant descriptions from the optimizer constants are not exposed; reconstruct best-effort
    variant_desc = {
        "none": "no blocked holes",
        "front": "block holes 1–3",
        "mid": "block holes 4–6",
        "back": "block holes 10–12",
        "front_mid": "block holes 1–6",
        "front_back": "block holes 1–3 & 10–12",
        "mid_back": "block holes 4–6 & 10–12",
        "front_mid_back": "block holes 1–6 & 10–12",
    }

    compact: List[Dict[str, Any]] = []
    for orders in sorted(summary.keys(), key=lambda x: int(x)):
        info = summary[orders]
        chosen = info.get("chosen", {}) or {}
        chosen_variant = chosen.get("variant")
        chosen_runners = chosen.get("runners")
        m = chosen.get("metrics") or {}
        baseline = (info.get("baseline_none") or {})
        baseline_runners = baseline.get("runners")
        baseline_metrics = baseline.get("metrics") or {}
        compact.append({
            "orders": int(orders),
            "recommended_variant": chosen_variant,
            "recommended_variant_description": variant_desc.get(str(chosen_variant), str(chosen_variant)),
            "recommended_runners": chosen_runners,
            "runs": m.get("runs"),
            "on_time_wilson_lo": m.get("on_time_wilson_lo"),
            "failed_mean": m.get("failed_mean"),
            "p90_mean": m.get("p90_mean"),
            "avg_delivery_time_mean": m.get("avg_delivery_time_mean"),
            "orders_per_runner_hour": m.get("oph_mean"),
            "baseline_none_runners": baseline_runners,
            "baseline_on_time_wilson_lo": baseline_metrics.get("on_time_wilson_lo") if baseline_metrics else None,
            "baseline_failed_mean": baseline_metrics.get("failed_mean") if baseline_metrics else None,
            "baseline_p90_mean": baseline_metrics.get("p90_mean") if baseline_metrics else None,
            "baseline_avg_delivery_time": baseline_metrics.get("avg_delivery_time_mean") if baseline_metrics else None,
            "baseline_oph_mean": baseline_metrics.get("oph_mean") if baseline_metrics else None,
        })
    return compact, variant_desc


def _call_gemini(prompt: str, *, model_name: str = "gemini-2.5-pro") -> Optional[str]:
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return None
    try:
        import google.generativeai as genai  # type: ignore
    except Exception:
        return None
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name)
        resp = model.generate_content(prompt)
        text = getattr(resp, "text", None)
        if isinstance(text, str) and text.strip():
            return text.strip()
        return str(resp).strip() or None
    except Exception:
        return None


def _build_header_section(course: str, tee_scenario: str, style_md: Optional[str]) -> str:
    today = datetime.now().strftime("%B %d, %Y")
    base_hdr = (
        f"**To:** General Manager, {Path(course).name.replace('_',' ').title()}\n"
        f"**From:** Performance Advisory Team\n"
        f"**Date:** {today}\n"
        f"**Subject:** GM Staffing and Blocking Policy Recommendations\n\n"
    )
    # Header is simple; skip LLM to keep deterministic fields
    return base_hdr


def _local_summary_section(compact: List[Dict[str, Any]], targets: Dict[str, Any]) -> str:
    lines: List[str] = []
    lines.append("### 1. Summary")
    lines.append(
        "Strategic, targeted hole blocking can reduce runner requirements while meeting service targets. "
        "Based on the simulated volumes, recommended runner counts and policies maintain on-time ≥ "
        f"{int(float(targets.get('on_time', 0.90))*100)}% with p90 ≤ {int(float(targets.get('max_p90', 40)))} minutes."
    )
    if compact:
        examples = ", ".join([f"{c['orders']} hr → {c.get('recommended_runners','?')} runner(s)" for c in compact[:3]])
        lines.append(f"Examples: {examples}.")
    return "\n".join(lines)


def _prompt_summary_section(compact: List[Dict[str, Any]], targets: Dict[str, Any], style_md: Optional[str]) -> str:
    style_hint = ("\n\nStyle reference (match tone and concision, but do not copy):\n" + style_md) if style_md else ""
    prompt = (
        "Write section '### 1. Summary' in Markdown for a GM. Keep 2-4 sentences.\n"
        "Be direct and actionable. Use the data to highlight staffing vs blocking tradeoffs.\n\n"
        f"Targets: on_time ≥ {targets.get('on_time')}, failed_rate ≤ {targets.get('max_failed')}, p90 ≤ {targets.get('max_p90')} min\n"
        "Data (JSON):\n" + json.dumps(compact, indent=2) + style_hint + "\n\n"
        "Output only the Markdown for this section starting with '### 1. Summary'."
    )
    md = _call_gemini(prompt)
    if not md:
        md = _local_summary_section(compact, targets)
    return md


def _local_staffing_table_section(compact: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    lines.append("### 2. Staffing Table")
    lines.append("| Orders/Hour (Approx.) | Runners Needed (Baseline) | Runners Needed (Optimized) |")
    lines.append("| :-------------------- | :------------------------ | :------------------------- |")
    for row in sorted(compact, key=lambda r: r.get("orders", 0)):
        orders = row.get("orders", "?")
        base = row.get("baseline_none_runners")
        opt = row.get("recommended_runners")
        base_str = str(base) if base is not None else "*Insufficient Data*"
        opt_str = str(opt) if opt is not None else "*Insufficient Data*"
        lines.append(f"| {orders} | {base_str} | {opt_str} |")
    return "\n".join(lines)


def _prompt_staffing_table_section(compact: List[Dict[str, Any]], style_md: Optional[str]) -> str:
    style_hint = ("\n\nStyle reference: \n" + style_md) if style_md else ""
    prompt = (
        "Write section '### 2. Staffing Table' in Markdown.\n"
        "Produce a concise table with these columns: 'Orders per 8-hr Shift' (if not available, omit), 'Orders/Hour (Approx.)', 'Runners Needed (Baseline)', 'Runners Needed (Optimized)'.\n"
        "If data is missing for shift totals, use Orders/Hour only. Derive baseline from baseline_none_runners and optimized from recommended_runners.\n"
        "If a baseline/optimized value is missing, write '*Insufficient Data*'.\n\n"
        "Data (JSON):\n" + json.dumps(compact, indent=2) + style_hint + "\n\n"
        "Output only the Markdown for this section starting with '### 2. Staffing Table'."
    )
    md = _call_gemini(prompt)
    if not md:
        md = _local_staffing_table_section(compact)
    return md


def _local_quick_guide_section(compact: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    lines.append("### 3. Quick Guide")
    lines.append("- Schedule minimal runners at lower volumes; use targeted blocking to delay staffing increases.")
    if compact:
        mins = compact[0]["orders"]
        maxs = compact[-1]["orders"]
        lines.append(f"- At ~{mins} orders/hr: follow optimized policy; monitor on-time and p90.")
        lines.append(f"- At ~{maxs} orders/hr: consider adding a runner or expanding blocking if p90 > 40 min.")
    lines.append("- Use on-call coverage to handle spikes > 20 minutes.")
    return "\n".join(lines)


def _prompt_quick_guide_section(compact: List[Dict[str, Any]], style_md: Optional[str]) -> str:
    style_hint = ("\n\nStyle reference: \n" + style_md) if style_md else ""
    prompt = (
        "Write section '### 3. Quick Guide' in Markdown with 3-5 bullets.\n"
        "Give simple operational guidance based on orders/hour about when to add runners and when to enable blocking.\n"
        "Use the recommended_runners and recommended_variant_description fields to guide advice.\n\n"
        "Data (JSON):\n" + json.dumps(compact, indent=2) + style_hint + "\n\n"
        "Output only the Markdown for this section starting with '### 3. Quick Guide'."
    )
    md = _call_gemini(prompt)
    if not md:
        md = _local_quick_guide_section(compact)
    return md


def _local_confidence_section(compact: List[Dict[str, Any]]) -> str:
    lines: List[str] = []
    lines.append("### 4. Confidence in Recommendations")
    for row in sorted(compact, key=lambda r: r.get("orders", 0)):
        runs = int(row.get("runs") or 0)
        ot = float(row.get("on_time_wilson_lo") or 0.0)
        failed = float(row.get("failed_mean") or 0.0)
        conf = "High" if runs >= 16 and (ot >= 0.92 and failed <= 0.04) else ("Medium" if runs >= 8 else "Low")
        lines.append(f"- {row.get('orders', '?')} Orders/Hour: {conf}.")
    return "\n".join(lines)


def _prompt_confidence_section(compact: List[Dict[str, Any]], style_md: Optional[str]) -> str:
    style_hint = ("\n\nStyle reference: \n" + style_md) if style_md else ""
    prompt = (
        "Write section '### 4. Confidence in Recommendations' in Markdown.\n"
        "For each orders level, provide a brief confidence note (High/Medium/Low) based on 'runs' and proximity to targets (on_time_wilson_lo near 0.90, failed near 0.05).\n"
        "Be concise.\n\n"
        "Data (JSON):\n" + json.dumps(compact, indent=2) + style_hint + "\n\n"
        "Output only the Markdown for this section starting with '### 4. Confidence in Recommendations'."
    )
    md = _call_gemini(prompt)
    if not md:
        md = _local_confidence_section(compact)
    return md


def assemble_markdown(header_md: str, sections: List[str]) -> str:
    parts = [header_md] + sections
    return "\n".join(p.strip() for p in parts if p and p.strip()) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description="Generate GM report with per-section Gemini prompts")
    p.add_argument("--existing-root", required=True, help="Path to existing optimization output root")
    p.add_argument("--python-bin", default=sys.executable)
    p.add_argument("--optimizer-script", default=str(Path(__file__).resolve().parents[0] / "optimize_staffing_policy.py"))
    p.add_argument("--style-md", default=None, help="Optional path to a style reference Markdown file")
    p.add_argument("--model", default=os.environ.get("GEMINI_MODEL", "gemini-2.5-pro"))
    args = p.parse_args()

    project_root = Path(__file__).resolve().parents[2]
    existing_root = Path(args.existing_root)
    if not existing_root.is_absolute():
        existing_root = (project_root / existing_root).resolve()
    if not existing_root.exists():
        print(f"error: existing root not found: {existing_root}")
        sys.exit(2)

    optimizer_script = Path(args.optimizer_script)
    if not optimizer_script.is_absolute():
        optimizer_script = (project_root / optimizer_script).resolve()
    if not optimizer_script.exists():
        print(f"error: optimizer script not found: {optimizer_script}")
        sys.exit(2)

    # Load env from .env if available (best-effort)
    if _load_dotenv is not None:
        try:
            _load_dotenv(dotenv_path=project_root / ".env", override=False)
            _load_dotenv(override=False)
        except Exception:
            pass

    # Load JSON via optimizer
    data = _load_optimizer_json(existing_root, python_bin=args.python_bin, optimizer_script=optimizer_script)
    compact, _variant_desc = _compact_data_for_sections(data)

    course = data.get("course", str(existing_root))
    tee_scenario = data.get("tee_scenario", "")
    targets = data.get("targets", {})
    style_md = _get_style_reference(existing_root, Path(args.style_md) if args.style_md else None)

    # Build header (deterministic) and sections (via Gemini)
    header_md = _build_header_section(course, tee_scenario, style_md)
    # Ensure model name is respected in _call_gemini
    if args.model:
        os.environ.setdefault("GEMINI_MODEL", args.model)

    sections_md: List[str] = []
    sections_md.append(_prompt_summary_section(compact, targets, style_md))
    sections_md.append(_prompt_staffing_table_section(compact, style_md))
    sections_md.append(_prompt_quick_guide_section(compact, style_md))
    sections_md.append(_prompt_confidence_section(compact, style_md))

    final_md = assemble_markdown(header_md, sections_md)

    # Write to gm_staffing_policy_report.md under existing_root
    out_path = existing_root / "gm_staffing_policy_report.md"
    try:
        out_path.write_text(final_md, encoding="utf-8")
        print(f"GM staffing policy report written to {out_path}")
    except Exception as e:
        print(f"error: failed writing report: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()


