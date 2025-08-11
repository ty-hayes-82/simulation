from __future__ import annotations

import json
from pathlib import Path

from golfsim.simulation.services import run_multi_golfer_simulation


def main() -> None:
    course_dir = "courses/pinetree_country_club"
    groups = [
        {"group_id": 1, "tee_time_s": 7200, "num_golfers": 4},
    ]

    results = run_multi_golfer_simulation(
        course_dir=course_dir,
        groups=groups,
        order_probability_per_9_holes=0.9,
        prep_time_min=10,
        runner_speed_mps=6.0,
        output_dir="outputs/single_runner_one_group",
        create_visualization=True,
    )

    out_dir = Path("outputs/single_runner_one_group")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "results.json").write_text(json.dumps(results, indent=2))
    print(
        f"orders={len(results.get('orders', []))} processed={len(results.get('delivery_stats', []))} failed={len(results.get('failed_orders', []))}"
    )


if __name__ == "__main__":
    main()


