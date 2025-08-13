from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import simpy

from golfsim.logging import init_logging, get_logger
from golfsim.simulation.services import BeverageCartService
from golfsim.io.phase_reporting import save_phase3_output_files, write_phase3_summary


logger = get_logger(__name__)


def main() -> None:
    init_logging()

    course_dir = "courses/pinetree_country_club"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path("outputs") / f"{ts}_phase_01"
    output_root.mkdir(parents=True, exist_ok=True)

    summary_rows: List[Dict] = []

    for run_idx in range(1, 6):
        logger.info("Phase 01 run %d starting", run_idx)
        env = simpy.Environment()
        svc = BeverageCartService(
            env=env,
            course_dir=course_dir,
            cart_id="bev_cart_1",
            track_coordinates=True,
            starting_hole=18,
        )
        env.run(until=svc.service_end_s)
        bev_points = svc.coordinates or []

        sim_result: Dict = {
            "type": "standard",
            "run_idx": run_idx,
            "sales_result": {"sales": [], "revenue": 0.0},
            "golfer_points": [],
            "bev_points": bev_points,
            "pass_events": [],
            "tee_time_s": (9 - 7) * 3600,
            "course_dir": course_dir,
            "beverage_cart_service": None,
        }

        run_dir = output_root / f"sim_{run_idx:02d}"
        save_phase3_output_files(sim_result, run_dir, include_coordinates=True, include_visualizations=True, include_stats=True)

        # Minimal per-run metadata for summary
        summary_rows.append({
            "run_idx": run_idx,
            "revenue": 0.0,
            "num_sales": 0,
            "tee_time_s": sim_result["tee_time_s"],
        })

    write_phase3_summary(summary_rows, output_root)
    logger.info("Phase 01 complete: %s", output_root)


if __name__ == "__main__":
    main()


