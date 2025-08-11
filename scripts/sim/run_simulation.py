#!/usr/bin/env python3
"""
Compatibility wrapper for historical entrypoint expected by tests and docs.

Delegates to `scripts.sim.run_single_golfer_simulation.main`.
"""
from __future__ import annotations

import sys

from scripts.sim.run_single_golfer_simulation import main


if __name__ == "__main__":
    sys.exit(main())


