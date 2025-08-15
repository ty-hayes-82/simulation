from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Optional, Tuple

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

    repo_root = Path(__file__).resolve().parents[1]
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Test connection to Google Gemini using GOOGLE_API_KEY.")
    parser.add_argument(
        "--model",
        default="gemini-2.5-pro",
        help="Model name to test. Falls back to common models if this fails.",
    )
    parser.add_argument(
        "--prompt",
        default="Reply with the single word: pong.",
        help="Prompt to send for the connectivity test.",
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("LOG_LEVEL", "INFO"),
        help="Logging level (DEBUG, INFO, WARNING, ERROR).",
    )
    args = parser.parse_args()

    init_logging(level=args.log_level)
    logger = get_logger("test_gemini_connection")

    api_key = ensure_env_loaded("GOOGLE_API_KEY")
    if not api_key:
        logger.error(
            "GOOGLE_API_KEY is not set. Define it in the environment or in ',env'/.env at repo root."
        )
        logger.error(
            "If the SDKs are not installed, install one of: 'pip install google-genai' or 'pip install google-generativeai'."
        )
        return 1

    ok, used_model, result = attempt_models(api_key=api_key, requested_model=args.model, prompt=args.prompt)
    if ok:
        logger.info(f"Connection successful using model '{used_model}'.")
        # Keep stdout minimal and machine-friendly
        print(result)
        return 0

    logger.error("Failed to connect to Gemini with all attempted models.")
    logger.error(result)
    logger.error(
        "Ensure the model name is valid for your account/region and that one of the SDKs is installed:"
    )
    logger.error("  pip install google-genai     # modern SDK")
    logger.error("  pip install google-generativeai  # legacy SDK")
    return 1


if __name__ == "__main__":
    sys.exit(main())


