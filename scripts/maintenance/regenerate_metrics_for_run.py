from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Optional


def compute_runner_utilization_from_events(events_csv: Path, runner_id: str = "runner_1") -> Optional[float]:
    if not events_csv.exists():
        return None

    # Load events for the runner sorted by timestamp_s
    rows = []
    with events_csv.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if (r.get("runner_id") or "").strip() != runner_id:
                continue
            try:
                r_ts = float(r.get("timestamp_s") or 0)
            except Exception:
                r_ts = 0.0
            r_action = (r.get("action") or r.get("activity_type") or "").strip()
            rows.append({"ts": r_ts, "action": r_action})

    if not rows:
        return 0.0

    rows.sort(key=lambda x: x["ts"])

    # Determine service window
    service_start = None
    service_end = None
    for r in rows:
        if r["action"] == "service_opened" and service_start is None:
            service_start = r["ts"]
        if r["action"] == "service_closed":
            service_end = r["ts"]
    if service_start is None:
        service_start = rows[0]["ts"]
    if service_end is None:
        service_end = rows[-1]["ts"]
    service_seconds = max(0.0, float(service_end) - float(service_start))
    if service_seconds <= 0:
        return 0.0

    # Sum outbound and return legs
    outbound_start: Optional[float] = None
    return_start: Optional[float] = None
    driving_time = 0.0

    for r in rows:
        act = r["action"]
        ts = r["ts"]
        if act == "delivery_start":
            outbound_start = ts
        elif act == "delivery_complete" and outbound_start is not None:
            driving_time += max(0.0, ts - outbound_start)
            outbound_start = None

        if act == "returning":
            return_start = ts
        elif act == "arrived_clubhouse" and return_start is not None:
            driving_time += max(0.0, ts - return_start)
            return_start = None

    # Close incomplete legs at service end
    if outbound_start is not None:
        driving_time += max(0.0, service_end - outbound_start)
    if return_start is not None:
        driving_time += max(0.0, service_end - return_start)

    util_pct = (driving_time / service_seconds) * 100.0
    return max(0.0, min(100.0, util_pct))


def update_simulation_metrics(run_dir: Path, utilization_pct: float, runner_id: str = "runner_1") -> Path:
    metrics_path = run_dir / "simulation_metrics.json"
    data = {}
    if metrics_path.exists():
        try:
            data = json.loads(metrics_path.read_text(encoding="utf-8"))
        except Exception:
            data = {}

    delivery_metrics = data.get("deliveryMetrics") or {}
    delivery_metrics["runnerUtilizationPct"] = float(utilization_pct)
    # Ensure basic keys exist
    data["deliveryMetrics"] = delivery_metrics
    data["hasRunners"] = True
    if "hasBevCart" not in data:
        data["hasBevCart"] = bool(data.get("bevCartMetrics"))

    metrics_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return metrics_path


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/maintenance/regenerate_metrics_for_run.py <run_dir> [runner_id]", file=sys.stderr)
        sys.exit(2)
    run_dir = Path(sys.argv[1])
    runner_id = sys.argv[2] if len(sys.argv) > 2 else "runner_1"
    events_csv = run_dir / "events.csv"
    if not events_csv.exists():
        print(f"events.csv not found in {run_dir}", file=sys.stderr)
        sys.exit(1)
    util = compute_runner_utilization_from_events(events_csv, runner_id=runner_id)
    if util is None:
        print("Failed to compute utilization", file=sys.stderr)
        sys.exit(1)
    metrics_path = update_simulation_metrics(run_dir, util, runner_id=runner_id)
    print(f"Updated {metrics_path} with runnerUtilizationPct={util:.2f}")


if __name__ == "__main__":
    main()


