#!/usr/bin/env python3
"""
Run a small matrix of `run_unified_simulation.py` combinations.

Windows PowerShell friendly: one short command per line; no piping/chaining.

Default combos are intentionally modest to keep runtimes reasonable.
Use --dry-run to preview commands without executing.

Optionally forward a tee-times scenario key (from course `config/tee_times_config.json`) via
`--tee-scenario` (default: `typical_weekday`). Use `--tee-scenario none` to disable and rely on
manual group args in the child runner.
"""

from __future__ import annotations

import argparse
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

from golfsim.logging import init_logging, get_logger


LOGGER = get_logger(__name__)


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _run(cmd: List[str], dry_run: bool) -> Tuple[bool, str]:
    """Run a single command. Returns (ok, label)."""
    label = " ".join(cmd)
    if dry_run:
        LOGGER.info("DRY RUN: %s", label)
        return True, label
    try:
        LOGGER.info("RUN: %s", label)
        subprocess.run(cmd, check=True)
        return True, label
    except subprocess.CalledProcessError as exc:  # noqa: BLE001
        LOGGER.error("FAILED (%s): %s", exc.returncode, label)
        return False, label


def _build_bev_carts_jobs(course_dir: str, base_out: Path, log_level: str, ts: str) -> List[List[str]]:
    """Two small variations of beverage cart GPS-only runs."""
    jobs: List[List[str]] = []
    combos: List[Dict] = [
        {"num_runs": 1, "num_carts": 1},
        {"num_runs": 1, "num_carts": 2},
    ]
    for c in combos:
        groups = 0
        carts = int(c["num_carts"])
        runners = 0
        sub = base_out / f"{ts}_{groups}_golfers_{carts}_bevcarts_{runners}_runners"
        _ensure_dir(sub)
        jobs.append([
            "python",
            "scripts/sim/run_unified_simulation.py",
            "--mode",
            "bev-carts",
            "--course-dir",
            course_dir,
            "--num-runs",
            str(c["num_runs"]),
            "--num-carts",
            str(c["num_carts"]),
            "--output-dir",
            str(sub),
            "--log-level",
            log_level,
        ])
    return jobs


def _build_bev_with_golfers_jobs(course_dir: str, base_out: Path, log_level: str, ts: str, tee_scenario: str) -> List[List[str]]:
    """A few small variations combining cart GPS with golfer groups and sales."""
    jobs: List[List[str]] = []
    combos: List[Dict] = [
        {"num_runs": 1, "groups": 2, "first_tee": "09:00", "interval": 15, "order_prob": 0.35, "avg_usd": 11.0},
        {"num_runs": 1, "groups": 6, "first_tee": "08:30", "interval": 12, "order_prob": 0.55, "avg_usd": 14.0},
    ]
    for c in combos:
        groups = int(c["groups"])  # single cart by design in this mode
        carts = 1
        runners = 0
        sub = base_out / f"{ts}_{groups}_golfers_{carts}_bevcarts_{runners}_runners"
        _ensure_dir(sub)
        cmd = [
            "python",
            "scripts/sim/run_unified_simulation.py",
            "--mode",
            "bev-with-golfers",
            "--course-dir",
            course_dir,
            "--num-runs",
            str(c["num_runs"]),
            "--groups-count",
            str(c["groups"]),
            "--groups-interval-min",
            str(c["interval"]),
            "--first-tee",
            c["first_tee"],
            "--order-prob",
            str(c["order_prob"]),
            "--avg-order-usd",
            str(c["avg_usd"]),
            "--output-dir",
            str(sub),
            "--log-level",
            log_level,
        ]
        if tee_scenario:
            cmd += ["--tee-scenario", tee_scenario]
        jobs.append(cmd)
    return jobs


def _build_golfers_only_jobs(course_dir: str, base_out: Path, log_level: str, ts: str, tee_scenario: str) -> List[List[str]]:
    """Two small variations generating golfer GPS only."""
    jobs: List[List[str]] = []
    combos: List[Dict] = [
        {"num_runs": 1, "groups": 4, "first_tee": "09:00", "interval": 15},
        {"num_runs": 1, "groups": 8, "first_tee": "08:00", "interval": 10},
    ]
    for c in combos:
        groups = int(c["groups"])  # golfers only
        carts = 0
        runners = 0
        sub = base_out / f"{ts}_{groups}_golfers_{carts}_bevcarts_{runners}_runners"
        _ensure_dir(sub)
        cmd = [
            "python",
            "scripts/sim/run_unified_simulation.py",
            "--mode",
            "golfers-only",
            "--course-dir",
            course_dir,
            "--num-runs",
            str(c["num_runs"]),
            "--groups-count",
            str(c["groups"]),
            "--groups-interval-min",
            str(c["interval"]),
            "--first-tee",
            c["first_tee"],
            "--output-dir",
            str(sub),
            "--log-level",
            log_level,
        ]
        if tee_scenario:
            cmd += ["--tee-scenario", tee_scenario]
        jobs.append(cmd)
    return jobs


def _build_delivery_runner_jobs(course_dir: str, base_out: Path, log_level: str, ts: str, tee_scenario: str) -> List[List[str]]:
    """Small variations for the delivery runner dynamic sim."""
    jobs: List[List[str]] = []
    combos: List[Dict] = [
        {
            "num_runs": 1,
            "groups": 0,
            "first_tee": "09:00",
            "interval": 15,
            "order_prob_9": 0.45,
            "prep_min": 8,
            "speed_mps": 5.0,
            "revenue": 22.0,
            "sla_min": 30,
        },
        {
            "num_runs": 1,
            "groups": 4,
            "first_tee": "08:45",
            "interval": 12,
            "order_prob_9": 0.55,
            "prep_min": 10,
            "speed_mps": 6.0,
            "revenue": 28.0,
            "sla_min": 28,
        },
    ]
    for c in combos:
        g = int(c["groups"])  # delivery-runner uses one runner
        carts = 0
        runners = 1
        sub = base_out / f"{ts}_{g}_golfers_{carts}_bevcarts_{runners}_runners"
        _ensure_dir(sub)
        cmd = [
            "python",
            "scripts/sim/run_unified_simulation.py",
            "--mode",
            "delivery-runner",
            "--course-dir",
            course_dir,
            "--num-runs",
            str(c["num_runs"]),
            "--groups-count",
            str(g),
            "--groups-interval-min",
            str(c["interval"]),
            "--first-tee",
            c["first_tee"],
            "--order-prob-9",
            str(c["order_prob_9"]),
            "--prep-time",
            str(c["prep_min"]),
            "--runner-speed",
            str(c["speed_mps"]),
            "--revenue-per-order",
            str(c["revenue"]),
            "--sla-minutes",
            str(c["sla_min"]),
            "--output-dir",
            str(sub),
            "--log-level",
            log_level,
        ]
        eff_scenario = "none" if g == 0 else tee_scenario
        if eff_scenario:
            cmd += ["--tee-scenario", eff_scenario]
        jobs.append(cmd)
    return jobs


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a matrix of unified simulation combinations")
    parser.add_argument("--course-dir", default="courses/pinetree_country_club", help="Course directory")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Base output directory (defaults to outputs/matrix_<timestamp>)",
    )
    parser.add_argument(
        "--modes",
        nargs="+",
        choices=["bev-carts", "bev-with-golfers", "golfers-only", "delivery-runner"],
        default=["bev-carts", "bev-with-golfers", "golfers-only", "delivery-runner"],
        help="Subset of modes to run",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing")
    parser.add_argument("--log-level", default="INFO", help="Log level for this orchestrator and children")
    parser.add_argument(
        "--tee-scenario",
        default="typical_weekday",
        help=(
            "Scenario key from course tee_times_config.json; use 'none' to disable and use manual group args."
        ),
    )

    args = parser.parse_args()

    init_logging(args.log_level)
    ts = _timestamp()
    base_out = Path(args.output_dir) if args.output_dir else Path("outputs") / f"matrix_{ts}"
    _ensure_dir(base_out)

    jobs: List[List[str]] = []
    if "bev-carts" in args.modes:
        jobs.extend(_build_bev_carts_jobs(args.course_dir, base_out, args.log_level, ts))
    if "bev-with-golfers" in args.modes:
        jobs.extend(_build_bev_with_golfers_jobs(args.course_dir, base_out, args.log_level, ts, args.tee_scenario))
    if "golfers-only" in args.modes:
        jobs.extend(_build_golfers_only_jobs(args.course_dir, base_out, args.log_level, ts, args.tee_scenario))
    if "delivery-runner" in args.modes:
        jobs.extend(_build_delivery_runner_jobs(args.course_dir, base_out, args.log_level, ts, args.tee_scenario))

    LOGGER.info("Planned jobs: %d", len(jobs))
    successes = 0
    failures = 0

    for cmd in jobs:
        ok, _ = _run(cmd, args.dry_run)
        if ok:
            successes += 1
        else:
            failures += 1

    LOGGER.info("Done. Success: %d Failure: %d Output root: %s", successes, failures, base_out)


if __name__ == "__main__":
    main()


