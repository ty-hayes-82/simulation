from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict

from golfsim.logging import init_logging, get_logger
from golfsim.simulation.phase_simulations import run_phase4_beverage_cart_simulation
from golfsim.io.phase_reporting import save_phase4_output_files, write_phase4_summary


logger = get_logger(__name__)


def main() -> None:
    init_logging()

    course_dir = "courses/pinetree_country_club"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path("outputs") / f"{ts}_phase_12"
    output_root.mkdir(parents=True, exist_ok=True)

    results_rows = []

    for run_idx in range(1, 6):
        logger.info("Phase 12 run %d starting", run_idx)
        sim = run_phase4_beverage_cart_simulation(course_dir=course_dir, run_idx=run_idx, use_synchronized_timing=False)
        sim["course_dir"] = course_dir

        run_dir = output_root / f"sim_{run_idx:02d}"
        save_phase4_output_files(sim, run_dir, include_coordinates=True, include_visualizations=True, include_stats=True)

        results_rows.append({
            "run_idx": sim.get("run_idx", run_idx),
            "first_tee_time_s": sim.get("first_tee_time_s", (9 - 7) * 3600),
            "last_tee_time_s": sim.get("last_tee_time_s", (10 - 7) * 3600),
            "revenue": sim.get("sales_result", {}).get("revenue", 0.0),
            "num_sales": len(sim.get("sales_result", {}).get("sales", [])),
            "crossings": sim.get("crossings"),
        })

    write_phase4_summary(results_rows, output_root)
    logger.info("Phase 12 complete: %s", output_root)


if __name__ == "__main__":
    main()


