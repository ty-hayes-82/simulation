#!/usr/bin/env python3
"""
Generate Executive Summary via Google Gemini

Collects all non-PNG output files from a simulation directory,
sends them to Google Gemini for executive summary and guidance,
and saves the response to a markdown file.

Windows PowerShell friendly: one short command per line, no piping/chaining.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple, Dict, Any

from golfsim.logging import init_logging, get_logger


def parse_env_file(env_path: Path) -> dict:
    """Parse a simple KEY=VALUE env file and return a dict.

    Quotes around values are stripped. Lines starting with '#' or blank lines are ignored.
    """
    variables: dict = {}
    if not env_path.exists():
        return variables
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            variables[key] = value
    return variables


def ensure_env_loaded(env_var_name: str = "GOOGLE_API_KEY") -> Optional[str]:
    """Return the API key from environment, attempting to load from ',env' or '.env' if missing."""
    api_key = os.environ.get(env_var_name)
    if api_key:
        return api_key

    repo_root = Path(__file__).resolve().parents[2]
    for candidate in [repo_root / ",env", repo_root / ".env"]:
        variables = parse_env_file(candidate)
        for k, v in variables.items():
            # Do not override already-set environment variables
            os.environ.setdefault(k, v)
        if env_var_name in variables:
            return variables[env_var_name]
    return None


def try_google_genai(api_key: str, model: str, prompt: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """Attempt using the modern google.genai client. Returns (ok, text, error)."""
    try:
        from google import genai  # type: ignore

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(model=model, contents=prompt)
        text = getattr(response, "text", None)
        if not text and hasattr(response, "candidates"):
            # Fallback extraction if needed
            try:
                text = response.candidates[0].content.parts[0].text  # type: ignore[attr-defined]
            except Exception:
                text = None
        return True, text or "(no text in response)", None
    except ModuleNotFoundError as e:
        return False, None, f"google.genai not installed: {e}"
    except Exception as e:
        return False, None, f"google.genai error: {e}"


def try_google_generativeai(api_key: str, model: str, prompt: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """Attempt using the legacy google.generativeai client. Returns (ok, text, error)."""
    try:
        import google.generativeai as genai  # type: ignore

        genai.configure(api_key=api_key)
        gmodel = genai.GenerativeModel(model)
        response = gmodel.generate_content(prompt)
        text = getattr(response, "text", None)
        return True, text or "(no text in response)", None
    except ModuleNotFoundError as e:
        return False, None, f"google-generativeai not installed: {e}"
    except Exception as e:
        return False, None, f"google-generativeai error: {e}"


def attempt_models(api_key: str, requested_model: str, prompt: str) -> Tuple[bool, str, str]:
    """Try the requested model, then fall back to common Gemini model names.

    Returns (ok, used_model, response_text_or_error)
    """
    logger = get_logger(__name__)
    candidate_models: List[str] = [
        requested_model,
        "gemini-2.0-pro",
        "gemini-2.0-flash",
        "gemini-1.5-pro-latest",
    ]

    last_errors: List[str] = []
    for model in candidate_models:
        logger.info(f"Trying model '{model}' via google.genai...")
        ok, text, err = try_google_genai(api_key, model, prompt)
        if ok and text is not None:
            return True, model, text
        if err:
            last_errors.append(f"[genai:{model}] {err}")

        logger.info(f"Trying model '{model}' via google.generativeai...")
        ok, text, err = try_google_generativeai(api_key, model, prompt)
        if ok and text is not None:
            return True, model, text
        if err:
            last_errors.append(f"[generativeai:{model}] {err}")

    return False, requested_model, " | ".join(last_errors) if last_errors else "Unknown error"


def collect_non_png_files(simulation_dir: Path) -> Dict[str, str]:
    """Collect all non-PNG files from the simulation directory and return as filename -> content dict."""
    files_content: Dict[str, str] = {}
    
    if not simulation_dir.exists():
        return files_content
    
    # Walk through all files in the simulation directory
    for file_path in simulation_dir.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() != ".png":
            try:
                relative_path = file_path.relative_to(simulation_dir)
                # Try to read as text
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                files_content[str(relative_path)] = content
            except Exception as e:
                # If we can't read the file, note it in the content
                files_content[str(relative_path)] = f"[Could not read file: {e}]"
    
    return files_content


def build_executive_summary_prompt(simulation_dir: Path, files_content: Dict[str, str]) -> str:
    """Build a concise, insight-focused prompt for Gemini to analyze the simulation results."""
    
    simulation_name = simulation_dir.name
    
    prompt_parts = [
        f"You are an operations analyst. Produce a concise executive summary for the golf course simulation named: {simulation_name}.",
        "",
        "OUTPUT FORMAT (follow exactly):",
        "",
        "### At-a-glance (6–8 bullets)",
        "- Use bold labels and include units. Examples: **On-time rate**: 83.1% (orders delivered within SLA); **P90 delivery time**: 39.2 min (worst 10% experience); **Avg order time**: 22.5 min (typical customer wait); **Orders**: 14 (delivered 12, failed 2); **Revenue per round**: $28.79; **Primary bottleneck**: runner capacity; **Runner utilization**: 78% (time actively delivering).",
        "",
        "### Time-of-day patterns (2–3 bullets)",
        "- Identify peak hours, demand distribution, or timing insights from the data.",
        "",
        "### Recommendations — next actions (3–5 bullets)",
        "- 'Action — rationale and expected impact' on one line.",
        "",
        "### KPIs with context (table, ≤6 rows)",
        "| Metric | Value | Target | What it means |",
        "| - | - | - | - |",
        "",
        "CONSTRAINTS:",
        "- Max 300 words total. No preamble, no filler, no emojis.",
        "- Use only the data provided below; do not invent. If unknown, write 'n/a'.",
        "- If multiple runs exist, compute and report mean and p90 where appropriate (e.g., delivery time, on-time rate).",
        "- Always include average order time if available in the data.",
        "- Look for time-based patterns in order placement, delivery times, or utilization.",
        "- Favor bullets over paragraphs; avoid wide tables.",
        "- Ensure numbers include units and are internally consistent.",
        "",
        "DATA FILES (parse and aggregate as needed):",
        "",
    ]
    
    # Add file contents to the prompt
    for filename, content in files_content.items():
        prompt_parts.extend([
            f"### File: `{filename}`",
            "```",
            content[:8000],  # Limit content length to avoid token limits
            "```" if len(content) <= 8000 else "``` (truncated)",
            "",
        ])
    
    prompt_parts.extend([
        "NOTES:",
        "- Focus on actionable insights for course operations and customer experience.",
        "- When relevant, call out thresholds (e.g., when a second runner becomes necessary).",
    ])
    
    return "\n".join(prompt_parts)


def save_executive_summary(summary_text: str, simulation_dir: Path, model_used: str) -> Path:
    """Save the executive summary to a markdown file in the simulation directory."""
    output_file = simulation_dir / "executive_summary_gemini.md"
    
    content = [
        "# Executive Summary - Golf Course Simulation",
        "",
        f"**Generated by:** Google Gemini ({model_used})",
        f"**Simulation:** {simulation_dir.name}",
        f"**Generated on:** {Path().cwd()}",
        "",
        "---",
        "",
        summary_text,
    ]
    
    output_file.write_text("\n".join(content), encoding="utf-8")
    return output_file


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate executive summary of simulation results using Google Gemini"
    )
    parser.add_argument(
        "simulation_dir",
        type=Path,
        help="Path to simulation output directory"
    )
    parser.add_argument(
        "--model",
        default="gemini-2.5-flash",
        help="Gemini model to use (falls back to available models)"
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "INFO"),
        help="Logging level (DEBUG, INFO, WARNING, ERROR)"
    )
    
    args = parser.parse_args()
    
    init_logging(level=args.log_level)
    logger = get_logger("generate_gemini_executive_summary")
    
    # Validate simulation directory
    if not args.simulation_dir.exists():
        logger.error(f"Simulation directory does not exist: {args.simulation_dir}")
        return 1
    
    if not args.simulation_dir.is_dir():
        logger.error(f"Path is not a directory: {args.simulation_dir}")
        return 1
    
    # Get API key
    api_key = ensure_env_loaded("GOOGLE_API_KEY")
    if not api_key:
        logger.error(
            "GOOGLE_API_KEY is not set. Define it in the environment or in ',env'/.env at repo root."
        )
        logger.error(
            "If the SDKs are not installed, install one of: 'pip install google-genai' or 'pip install google-generativeai'."
        )
        return 1
    
    logger.info(f"Analyzing simulation results from: {args.simulation_dir}")
    
    # Collect non-PNG files
    files_content = collect_non_png_files(args.simulation_dir)
    
    if not files_content:
        logger.warning("No readable files found in simulation directory")
        return 1
    
    logger.info(f"Collected {len(files_content)} files for analysis")
    
    # Build prompt
    prompt = build_executive_summary_prompt(args.simulation_dir, files_content)
    
    # Send to Gemini
    logger.info("Sending simulation data to Google Gemini for analysis...")
    ok, used_model, result = attempt_models(
        api_key=api_key, 
        requested_model=args.model, 
        prompt=prompt
    )
    
    if not ok:
        logger.error("Failed to connect to Gemini with all attempted models.")
        logger.error(result)
        return 1
    
    logger.info(f"Analysis completed using model: {used_model}")
    
    # Save the summary
    output_file = save_executive_summary(result, args.simulation_dir, used_model)
    logger.info(f"Executive summary saved to: {output_file}")
    
    # Also print to stdout for immediate viewing (with encoding handling)
    try:
        print("\n" + "="*60)
        print("EXECUTIVE SUMMARY")
        print("="*60)
        print(result)
        print("="*60)
    except UnicodeEncodeError:
        # Handle console encoding issues on Windows
        print("\n" + "="*60)
        print("EXECUTIVE SUMMARY")
        print("="*60)
        print(result.encode('ascii', 'replace').decode('ascii'))
        print("="*60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
