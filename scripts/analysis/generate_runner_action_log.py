#!/usr/bin/env python3
"""
Generate runner_action_log.csv from results.json activity logs.

Usage:
  python scripts/analysis/generate_runner_action_log.py <path>

Where <path> can be:
  - A run directory containing results.json
  - An outputs directory containing run_*/results.json subfolders
  - A direct path to a results.json file

Writes runner_action_log.csv next to each results.json discovered.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, List, Any, Optional, Iterable
import csv

from golfsim.logging import init_logging, get_logger


logger = get_logger(__name__)


def _seconds_to_clock_str(sec_since_7am: int) -> str:
    total = max(0, int(sec_since_7am))
    hh = 7 + (total // 3600)
    mm = (total % 3600) // 60
    ss = total % 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def _build_runner_action_segments(activity_logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not activity_logs:
        return []

    by_runner: Dict[str, List[Dict[str, Any]]] = {}
    for a in activity_logs:
        rid = a.get("runner_id") or "runner_1"
        by_runner.setdefault(str(rid), []).append(a)

    def _is_delivery_end(tag: str) -> bool:
        t = tag.lower()
        return (
            "order_delivered" in t
            or ("delivered" in t and "order" in t)
            or "delivery_complete" in t
            or ("delivery_failed" in t or ("failed" in t and "delivery" in t))
        )

    def _is_return_end(tag: str) -> bool:
        t = tag.lower()
        return (
            "runner_returned" in t
            or "returned_to_clubhouse" in t
            or ("returned" in t and "runner" in t)
            or "return_complete" in t
        )

    segments: List[Dict[str, Any]] = []
    for runner_id, entries in by_runner.items():
        entries_sorted = sorted(entries, key=lambda x: int(x.get("timestamp_s", 0)))
        service_open_s: Optional[int] = None
        service_close_s: Optional[int] = None
        delivery_start_s: Optional[int] = None
        return_start_s: Optional[int] = None

        drive_like: List[Dict[str, Any]] = []
        return_like: List[Dict[str, Any]] = []

        for e in entries_sorted:
            ts = int(e.get("timestamp_s", 0))
            tag = str(e.get("activity_type", e.get("event", "")))
            tag_l = tag.lower()

            if "service_opened" in tag_l and service_open_s is None:
                service_open_s = ts
            elif "service_closed" in tag_l:
                # Only treat as end-of-day close if it happens after opening
                if service_open_s is not None and ts >= service_open_s:
                    service_close_s = ts

            if "delivery_start" in tag_l and delivery_start_s is None:
                delivery_start_s = ts
            elif delivery_start_s is not None and _is_delivery_end(tag):
                drive_like.append({
                    "runner_id": runner_id,
                    "action_type": "delivery_drive",
                    "start_timestamp_s": int(delivery_start_s),
                    "end_timestamp_s": int(ts),
                })
                delivery_start_s = None
                # Immediately begin return drive at delivery completion to avoid gaps
                if return_start_s is None:
                    return_start_s = ts

            if "returning" in tag_l and return_start_s is None:
                return_start_s = ts
            else:
                # Infer return end at the next event after return_start
                if return_start_s is not None and ts > return_start_s and not tag_l.startswith("returning"):
                    return_like.append({
                        "runner_id": runner_id,
                        "action_type": "return_drive",
                        "start_timestamp_s": int(return_start_s),
                        "end_timestamp_s": int(ts),
                    })
                    return_start_s = None

        # Determine open/close window if not explicitly closed
        if service_open_s is None:
            try:
                service_open_s = int(min(int(e.get("timestamp_s", 0)) for e in entries_sorted)) if entries_sorted else None
            except Exception:
                service_open_s = None
        if service_close_s is None:
            try:
                service_close_s = int(max(int(e.get("timestamp_s", 0)) for e in entries_sorted)) if entries_sorted else None
            except Exception:
                service_close_s = None

        # Close any incomplete segments at service_close_s
        if service_close_s is not None:
            if delivery_start_s is not None and service_close_s > delivery_start_s:
                drive_like.append({
                    "runner_id": runner_id,
                    "action_type": "delivery_drive",
                    "start_timestamp_s": int(delivery_start_s),
                    "end_timestamp_s": int(service_close_s),
                })
            if return_start_s is not None and service_close_s > return_start_s:
                return_like.append({
                    "runner_id": runner_id,
                    "action_type": "return_drive",
                    "start_timestamp_s": int(return_start_s),
                    "end_timestamp_s": int(service_close_s),
                })

        if service_open_s is None:
            try:
                service_open_s = int(min(int(e.get("timestamp_s", 0)) for e in entries_sorted)) if entries_sorted else None
            except Exception:
                service_open_s = None
        if service_close_s is None:
            try:
                service_close_s = int(max(int(e.get("timestamp_s", 0)) for e in entries_sorted)) if entries_sorted else None
            except Exception:
                service_close_s = None

        if service_open_s is None or service_close_s is None or service_close_s <= service_open_s:
            continue

        combined: List[Dict[str, Any]] = []
        for seg in drive_like + return_like:
            s = max(int(seg["start_timestamp_s"]), int(service_open_s))
            e = min(int(seg["end_timestamp_s"]), int(service_close_s))
            if e > s:
                combined.append({**seg, "start_timestamp_s": s, "end_timestamp_s": e})

        combined.sort(key=lambda d: (int(d.get("start_timestamp_s", 0)), int(d.get("end_timestamp_s", 0))))

        cursor = int(service_open_s)
        full_segments: List[Dict[str, Any]] = []
        for seg in combined:
            s = int(seg["start_timestamp_s"])
            e = int(seg["end_timestamp_s"])
            if s > cursor:
                full_segments.append({
                    "runner_id": runner_id,
                    "action_type": "waiting_at_clubhouse",
                    "start_timestamp_s": int(cursor),
                    "end_timestamp_s": int(s),
                })
                cursor = s
            if e > cursor:
                seg2 = dict(seg)
                seg2["start_timestamp_s"] = int(cursor)
                full_segments.append(seg2)
                cursor = e

        if cursor < int(service_close_s):
            full_segments.append({
                "runner_id": runner_id,
                "action_type": "waiting_at_clubhouse",
                "start_timestamp_s": int(cursor),
                "end_timestamp_s": int(service_close_s),
            })

        for s in full_segments:
            s["start_timestamp"] = _seconds_to_clock_str(int(s["start_timestamp_s"]))
            s["end_timestamp"] = _seconds_to_clock_str(int(s["end_timestamp_s"]))
            s["duration_s"] = int(max(0, int(s["end_timestamp_s"]) - int(s["start_timestamp_s"])) )

        segments.extend(full_segments)

    segments.sort(key=lambda d: (str(d.get("runner_id")), int(d.get("start_timestamp_s", 0)), str(d.get("action_type"))))
    return segments


def _discover_results_jsons(root: Path) -> Iterable[Path]:
    if root.is_file() and root.name == "results.json":
        yield root
        return
    if root.is_dir():
        # Case: direct run directory
        cand = root / "results.json"
        if cand.exists():
            yield cand
        # Case: outputs directory with run_*/
        for sub in sorted(root.glob("run_*/results.json")):
            yield sub


def _write_runner_action_log(segments: List[Dict[str, Any]], save_path: Path) -> None:
    save_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "runner_id",
        "action_type",
        "start_timestamp",
        "end_timestamp",
        "start_timestamp_s",
        "end_timestamp_s",
        "duration_s",
    ]
    with save_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for seg in segments:
            writer.writerow({k: seg.get(k) for k in fieldnames})


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate runner action log CSV from results.json activity logs")
    parser.add_argument("path", type=str, help="Path to run directory, results.json, or outputs directory")
    args = parser.parse_args()

    init_logging("INFO")

    root = Path(args.path)
    found = list(_discover_results_jsons(root))
    if not found:
        logger.warning("No results.json found under: %s", root)
        return

    for rj in found:
        try:
            data = json.loads(rj.read_text(encoding="utf-8"))
            activity = data.get("activity_log", []) if isinstance(data, dict) else []
            segments = _build_runner_action_segments(activity)
            out_csv = rj.parent / "runner_action_log.csv"
            _write_runner_action_log(segments, out_csv)
            logger.info("Wrote runner action log: %s (%d segments)", out_csv, len(segments))
        except Exception as e:  # noqa: BLE001
            logger.warning("Failed to process %s: %s", rj, e)


if __name__ == "__main__":
    main()


