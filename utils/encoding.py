from __future__ import annotations

import sys
from typing import NoReturn


def setup_encoding() -> None:
    """
    Configure UTF-8 encoding for Windows compatibility.

    Idempotent. Safe to call from any CLI entrypoint before printing/logging.
    """
    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        else:  # pragma: no cover - legacy fallback
            import codecs  # local import to avoid overhead

            sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, errors="replace")  # type: ignore[attr-defined]
            sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, errors="replace")  # type: ignore[attr-defined]
    except Exception:
        # Silently ignore encoding setup failures to avoid breaking CLIs
        pass


