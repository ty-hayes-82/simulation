#!/usr/bin/env python3
"""
Simple Google Gemini connectivity test.

Usage (PowerShell):
  # optional but recommended
  pip install google-generativeai python-dotenv
  # set key in env or .env at repo root
  # $env:GEMINI_API_KEY = 'YOUR_KEY'

  python scripts/test/gemini_smoke_test.py --model gemini-1.5-pro --prompt "Reply with the single word: pong."

Exit codes:
  0 = success, 1 = missing dependency, 2 = missing API key, 3 = Gemini error
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def load_dotenv_if_available(project_root: Path) -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return
    try:
        load_dotenv(dotenv_path=project_root / ".env", override=False)
        load_dotenv(override=False)
    except Exception:
        pass


def main() -> None:
    p = argparse.ArgumentParser(description="Gemini smoke test")
    p.add_argument("--model", default=os.environ.get("GEMINI_MODEL", "gemini-2.5-pro"))
    p.add_argument("--prompt", default="Reply with the single word: pong.")
    args = p.parse_args()

    project_root = Path(__file__).resolve().parents[2]
    load_dotenv_if_available(project_root)

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("GEMINI_API_KEY/GOOGLE_API_KEY not found in environment or .env")
        sys.exit(2)

    try:
        import google.generativeai as genai  # type: ignore
    except Exception as e:
        print("google-generativeai is not installed. Install with: pip install google-generativeai")
        print(f"Import error: {e}")
        sys.exit(1)

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(args.model)
        resp = model.generate_content(args.prompt)
        text = getattr(resp, "text", None)
        if isinstance(text, str) and text.strip():
            print(f"Gemini call succeeded. Model: {args.model}")
            print("--- Response ---")
            print(text.strip())
            sys.exit(0)
        print("Gemini returned no text response.")
        sys.exit(3)
    except Exception as e:
        print("Gemini call failed:", e)
        sys.exit(3)


if __name__ == "__main__":
    main()


