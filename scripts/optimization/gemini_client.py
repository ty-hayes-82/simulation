#!/usr/bin/env python3
"""
Reusable Gemini submission client for optimization outputs.

Other scripts under scripts/optimization/ can import and call:
  from scripts.optimization.gemini_client import generate_executive_summary

Or run from CLI:
  python scripts/optimization/gemini_client.py --exp-root outputs/experiments/<name> --model gemini-2.5-flash
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional


def _ensure_repo_on_path() -> None:
    # repo_root = simulation/ (2 levels up from this file)
    repo_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(repo_root))


_ensure_repo_on_path()

# Now we can import the existing analysis helpers
from scripts.analysis.generate_gemini_executive_summary import (  # type: ignore
    ensure_env_loaded,
    parse_env_file,
    collect_non_png_files,
    build_executive_summary_prompt,
    attempt_models,
    save_executive_summary,
)
from golfsim.logging import get_logger, init_logging  # type: ignore


def generate_executive_summary(exp_root: Path, *, model: str = "gemini-2.5-flash") -> Optional[Path]:
    """Generate an executive summary markdown for the given experiment root.

    Returns the path to the saved markdown, or None on failure.
    """
    logger = get_logger(__name__)

    if not exp_root.exists() or not exp_root.is_dir():
        logger.error(f"Experiment root not found or not a directory: {exp_root}")
        return None

    # Try standard key first
    api_key = ensure_env_loaded("GOOGLE_API_KEY")
    if not api_key:
        # Fallback: load from common alternative variable names in .env and map to GOOGLE_API_KEY
        repo_root = Path(__file__).resolve().parents[2]
        for candidate in [repo_root / ",env", repo_root / ".env"]:
            vars_map = parse_env_file(candidate)
            for alt in ("GEMINI_API_KEY", "GOOGLE_GENAI_API_KEY", "GOOGLEAI_API_KEY", "GENAI_API_KEY"):
                val = vars_map.get(alt)
                if val:
                    import os
                    os.environ.setdefault("GOOGLE_API_KEY", val)
                    api_key = val
                    break
            if api_key:
                break
        if not api_key:
            logger.error("GOOGLE_API_KEY not set; also could not find alternate keys in .env/.env (GEMINI_API_KEY, GOOGLE_GENAI_API_KEY, GOOGLEAI_API_KEY, GENAI_API_KEY)")
            return None

    files_content = collect_non_png_files(exp_root)
    if not files_content:
        logger.error("No readable files found under experiment root")
        return None

    prompt = build_executive_summary_prompt(exp_root, files_content)
    logger.info("Submitting experiment results to Google Gemini...")
    ok, used_model, result = attempt_models(api_key=api_key, requested_model=model, prompt=prompt)
    if not ok:
        logger.error(f"Gemini submission failed: {result}")
        return None

    out_md = save_executive_summary(result, exp_root, used_model)
    logger.info(f"Executive summary written to: {out_md}")
    return out_md


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Submit optimization experiment outputs to Google Gemini")
    p.add_argument("--exp-root", required=True, help="Experiment root directory (outputs/experiments/<name>)")
    p.add_argument("--model", default="gemini-2.5-flash", help="Gemini model to use")
    p.add_argument("--log-level", default="INFO")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    init_logging(args.log_level)
    out = generate_executive_summary(Path(args.exp_root), model=args.model)
    return 0 if out else 1


if __name__ == "__main__":
    raise SystemExit(main())


