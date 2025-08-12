from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List

from golfsim.logging import init_logging, get_logger
from golfsim.simulation.phase_simulations import run_phase3_beverage_cart_simulation
from golfsim.io.phase_reporting import save_phase3_output_files, write_phase3_summary


logger = get_logger(__name__)


def main() -> None:
    init_logging()

    course_dir = "courses/pinetree_country_club"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path("outputs") / f"{ts}_phase_03"
    output_root.mkdir(parents=True, exist_ok=True)

    summary_rows: List[Dict] = []

    for run_idx in range(1, 6):
        logger.info("Phase 03 run %d starting", run_idx)
        sim = run_phase3_beverage_cart_simulation(course_dir=course_dir, run_idx=run_idx, use_synchronized_timing=False)
        sim["course_dir"] = course_dir

        run_dir = output_root / f"sim_{run_idx:02d}"
        save_phase3_output_files(sim, run_dir, include_coordinates=True, include_visualizations=True, include_stats=True)

        summary_rows.append({
            "run_idx": run_idx,
            "revenue": float(sim.get("sales_result", {}).get("revenue", 0.0)),
            "num_sales": int(len(sim.get("sales_result", {}).get("sales", []))),
            "tee_time_s": int(sim.get("tee_time_s", (9 - 7) * 3600)),
            "crossings": sim.get("crossings"),
        })

    write_phase3_summary(summary_rows, output_root)
    logger.info("Phase 03 complete: %s", output_root)


if __name__ == "__main__":
    main()


