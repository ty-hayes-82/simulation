from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import simpy

from golfsim.logging import init_logging, get_logger
from golfsim.simulation.services import BeverageCartService


logger = get_logger(__name__)


def main() -> None:
    init_logging()

    course_dir = "courses/pinetree_country_club"
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_root = Path("outputs") / f"{ts}_phase_11"
    output_root.mkdir(parents=True, exist_ok=True)

    for run_idx in range(1, 6):
        logger.info("Phase 11 run %d starting", run_idx)
        env = simpy.Environment()
        services: Dict[str, BeverageCartService] = {}
        for n in range(1, 3):
            starting_hole = 18 if n == 1 else 9
            services[str(n)] = BeverageCartService(
                env=env,
                course_dir=course_dir,
                cart_id=f"bev_cart_{n}",
                track_coordinates=True,
                starting_hole=starting_hole,
            )
        any_service = next(iter(services.values()))
        env.run(until=any_service.service_end_s)

        run_dir = output_root / f"sim_{run_idx:02d}"
        run_dir.mkdir(parents=True, exist_ok=True)

        # Combined CSV
        from golfsim.io.results import write_unified_coordinates_csv
        write_unified_coordinates_csv(
            {label: svc.coordinates for label, svc in services.items()},
            run_dir / "bev_cart_coordinates.csv",
        )

        # Visualization
        from golfsim.viz.matplotlib_viz import render_beverage_cart_plot
        all_coords: List[Dict] = []
        for svc in services.values():
            all_coords.extend(svc.coordinates)
        if all_coords:
            render_beverage_cart_plot(all_coords, course_dir=course_dir, save_path=run_dir / "bev_cart_route.png")

        # Stats
        (run_dir / "stats.md").write_text("\n".join([
            f"# Phase 11 — Two beverage carts",
            f"Run: {run_idx:02d}",
            f"Carts: 2",
        ]), encoding="utf-8")

    # Root summary
    (output_root / "summary.md").write_text("# Phase 11 summary", encoding="utf-8")
    logger.info("Phase 11 complete: %s", output_root)


if __name__ == "__main__":
    main()


