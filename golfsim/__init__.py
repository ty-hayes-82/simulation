"""Lightweight package initializer for golfsim.

Avoid importing heavy submodules at import time to prevent optional dependencies
from being required unless explicitly imported by callers. This also keeps the
package import resilient when optional tools are archived.
"""

__all__ = []
