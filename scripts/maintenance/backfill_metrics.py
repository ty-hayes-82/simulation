from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/maintenance/backfill_metrics.py <run_dir>", file=sys.stderr)
        sys.exit(2)

    run_dir = Path(sys.argv[1])
    results_path = run_dir / "results.json"
    if not results_path.exists():
        print(f"results.json not found in {run_dir}", file=sys.stderr)
        sys.exit(1)

    with results_path.open("r", encoding="utf-8") as f:
        sim_result: Dict[str, Any] = json.load(f)

    # Derive service_hours and variant metadata
    meta = sim_result.get("metadata", {}) if isinstance(sim_result, dict) else {}
    try:
        open_s = float(meta.get("service_open_s", 0) or 0)
        close_s = float(meta.get("service_close_s", 0) or 0)
        service_hours = max(0.0, (close_s - open_s) / 3600.0) if close_s > open_s else 10.0
    except Exception:
        service_hours = 10.0

    variant_key = meta.get("variant_key")
    blocked_holes = meta.get("blocked_holes")

    # Re-generate metrics
    from golfsim.io.reporting import generate_simulation_metrics_json

    out_path = run_dir / "simulation_metrics.json"
    generate_simulation_metrics_json(
        sim_result=sim_result,
        save_path=out_path,
        service_hours=float(service_hours),
        sla_minutes=int(meta.get("sla_minutes", 30) or 30),
        revenue_per_order=float(meta.get("revenue_per_order", 25.0) or 25.0),
        avg_bev_order_value=float(meta.get("avg_bev_order_value", 12.0) or 12.0),
        variant_key=variant_key,
        blocked_holes=blocked_holes,
    )

    # Print a small confirmation summary
    try:
        data = json.loads(out_path.read_text(encoding="utf-8"))
        dm = data.get("deliveryMetrics", {})
        print(json.dumps({
            "variantKey": data.get("variantKey"),
            "blockedHoles": data.get("blockedHoles"),
            "hasRunners": data.get("hasRunners"),
            "totalRunnerShiftMinutes": dm.get("totalRunnerShiftMinutes"),
            "totalRunnerDriveMinutes": dm.get("totalRunnerDriveMinutes"),
            "runnerUtilizationPct": dm.get("runnerUtilizationPct"),
            "runnerUtilizationByRunner": dm.get("runnerUtilizationByRunner"),
        }, indent=2))
    except Exception:
        print(f"Wrote updated metrics to {out_path}")


if __name__ == "__main__":
    main()


