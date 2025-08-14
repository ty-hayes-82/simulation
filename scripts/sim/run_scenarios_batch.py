#!/usr/bin/env python3
"""
Scenario batch runner

Runs, for each tee-time scenario in the course config:
- 5 simulations of bev-with-golfers (1 beverage cart)
- 5 simulations of delivery-runner with 1 runner
- 5 simulations of delivery-runner with 2 runners
- 5 simulations of delivery-runner with 3 runners

Leverages unified mode entrypoints in `scripts/sim/run_unified_simulation.py` to ensure
consistent outputs and metrics with the rest of the tooling.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from golfsim.config.loaders import load_tee_times_config, load_simulation_config
from golfsim.logging import get_logger, init_logging
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent.parent))
from utils import setup_encoding, add_log_level_argument, write_json
from scripts.sim import run_unified_simulation as unified


logger = get_logger(__name__)

# Local helper mirroring unified scenario parsing to avoid private imports
def _build_groups_from_scenario(course_dir: str, scenario_key: str, default_group_size: int = 4) -> List[Dict[str, Any]]:
    if not scenario_key or scenario_key.lower() in {"none", "manual"}:
        return []
    try:
        cfg = load_tee_times_config(course_dir)
    except FileNotFoundError:
        logger.warning("tee_times_config.json not found; skipping scenario '%s'", scenario_key)
        return []

    scenarios = cfg.scenarios or {}
    if scenario_key not in scenarios:
        logger.warning("Scenario '%s' not found in tee_times_config.json", scenario_key)
        return []

    scenario = scenarios[scenario_key]
    hourly: Dict[str, int] = scenario.get("hourly_golfers", {})
    if not hourly:
        logger.warning("Scenario '%s' missing 'hourly_golfers' — skipping", scenario_key)
        return []

    def _parse_hhmm_to_seconds_since_7am(hhmm: str) -> int:
        try:
            hh, mm = hhmm.split(":")
            return (int(hh) - 7) * 3600 + int(mm) * 60
        except Exception:
            return 0

    groups: List[Dict[str, Any]] = []
    group_id = 1
    for hour_label, golfers in sorted(hourly.items(), key=lambda kv: _parse_hhmm_to_seconds_since_7am(kv[0])):
        golfers_int = int(golfers or 0)
        if golfers_int <= 0:
            continue
        groups_this_hour = (golfers_int + default_group_size - 1) // default_group_size
        if groups_this_hour <= 0:
            continue
        base_s = _parse_hhmm_to_seconds_since_7am(hour_label)
        interval_seconds = int(3600 / groups_this_hour)
        remaining_golfers = golfers_int
        for i in range(groups_this_hour):
            size = min(default_group_size, remaining_golfers)
            if size <= 0:
                break
            tee_time_s = base_s + i * interval_seconds
            groups.append({
                "group_id": group_id,
                "tee_time_s": int(tee_time_s),
                "num_golfers": int(size),
            })
            group_id += 1
            remaining_golfers -= size
    return groups


def main() -> int:
    setup_encoding()

    parser = argparse.ArgumentParser(
        description="Run scenario batch: bev-with-golfers and delivery-runner (1-3 runners)",
    )
    parser.add_argument(
        "--course-dir",
        default="courses/pinetree_country_club",
        help="Course directory containing config files",
    )
    parser.add_argument(
        "--scenario",
        default=None,
        help="Scenario key from tee_times_config.json; run all if omitted",
    )
    parser.add_argument(
        "--runs-per-scenario",
        type=int,
        default=3,
        help="Number of runs per scenario",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs",
        help="Base output directory",
    )
    # Optional overrides (fall back to simulation_config.json)
    parser.add_argument("--prep-time", type=int, default=None, help="Delivery prep time minutes (override)")
    parser.add_argument("--runner-speed", type=float, default=None, help="Runner speed m/s (override)")
    parser.add_argument("--order-prob-9", type=float, default=None, help="Delivery order probability per 9 holes (override)")
    parser.add_argument("--bev-pass-prob", type=float, default=None, help="Bev cart pass order probability (override)")
    parser.add_argument("--bev-avg-order", type=float, default=None, help="Bev cart average order USD (override)")
    add_log_level_argument(parser)

    args = parser.parse_args()

    init_logging(args.log_level)
    course_dir = Path(args.course_dir)
    output_root = Path(args.output_dir)
    output_root.mkdir(parents=True, exist_ok=True)

    # Load configs for defaults
    sim_cfg = load_simulation_config(course_dir)
    try:
        tee_cfg = load_tee_times_config(course_dir)
        available = list((tee_cfg.scenarios or {}).keys())
    except FileNotFoundError:
        available = []
    if args.scenario:
        scenarios = [args.scenario]
    else:
        scenarios = available
    if not scenarios:
        logger.error("No scenarios found in tee_times_config.json")
        return 1

    # Resolve defaults with overrides
    prep_time_min = int(args.prep_time) if args.prep_time is not None else int(sim_cfg.delivery_prep_time_sec // 60)
    runner_speed_mps = float(args.runner_speed) if args.runner_speed is not None else float(sim_cfg.delivery_runner_speed_mps)
    delivery_prob_9 = float(args.order_prob_9) if args.order_prob_9 is not None else float(sim_cfg.delivery_order_probability_per_9_holes)
    bev_pass_prob = float(args.bev_pass_prob) if args.bev_pass_prob is not None else float(sim_cfg.bev_cart_order_probability)
    bev_avg_order = float(args.bev_avg_order) if args.bev_avg_order is not None else float(sim_cfg.bev_cart_avg_order_usd)

    # Service hours for delivery metrics scaling (fallback to 10h if not set)
    service_hours = 10.0
    if getattr(sim_cfg, "service_hours", None) is not None:
        try:
            service_hours = float(sim_cfg.service_hours.end_hour - sim_cfg.service_hours.start_hour)
        except Exception:
            service_hours = 10.0

    for scenario_name in scenarios:
        logger.info("Running scenario: %s", scenario_name)
        # Verify scenario exists
        groups_preview = _build_groups_from_scenario(str(course_dir), scenario_name)
        if not groups_preview:
            logger.warning("No groups generated for scenario '%s'; skipping", scenario_name)
            continue

        scenario_dir = output_root / f"scenario_{scenario_name}"
        scenario_dir.mkdir(parents=True, exist_ok=True)

        # 1) Bev-with-golfers (1 cart)
        bev_out = scenario_dir / "bev_with_golfers"
        bev_args = argparse.Namespace(
            mode="bev-with-golfers",
            course_dir=str(course_dir),
            num_runs=int(args.runs_per_scenario),
            output_dir=str(bev_out),
            log_level=args.log_level,
            groups_count=0,
            groups_interval_min=15.0,
            first_tee="09:00",
            tee_scenario=scenario_name,
            num_carts=1,
            order_prob=float(bev_pass_prob),
            avg_order_usd=float(bev_avg_order),
        )
        bev_out.mkdir(parents=True, exist_ok=True)
        unified._run_mode_bev_with_golfers(bev_args)

        # 2–4) Delivery-runner with 1, 2, 3 runners
        for rn in (1, 2, 3):
            dr_out = scenario_dir / f"delivery_runner_{rn}r"
            dr_args = argparse.Namespace(
                mode="delivery-runner",
                course_dir=str(course_dir),
                num_runs=int(args.runs_per_scenario),
                output_dir=str(dr_out),
                log_level=args.log_level,
                groups_count=0,
                groups_interval_min=15.0,
                first_tee="09:00",
                tee_scenario=scenario_name,
                order_prob_9=float(delivery_prob_9),
                prep_time=int(prep_time_min),
                runner_speed=float(runner_speed_mps),
                revenue_per_order=float(sim_cfg.delivery_avg_order_usd),
                sla_minutes=30,
                service_hours=float(service_hours),
                num_runners=int(rn),
            )
            dr_out.mkdir(parents=True, exist_ok=True)
            unified._run_mode_delivery_runner(dr_args)

    logger.info("All scenarios complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
