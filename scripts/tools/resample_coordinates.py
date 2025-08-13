from __future__ import annotations

"""
Resample unified coordinates CSV to fixed temporal spacing for smooth animation.

Input CSV schema (as produced by write_unified_coordinates_csv):
  id, latitude, longitude, timestamp, type, hole, ...

Behavior:
- Groups points by `id`
- Sorts by `timestamp`
- Linearly interpolates latitude/longitude at a fixed cadence (e.g., 1s)
- Optionally applies a simple moving-average smoothing window (odd size)
- Writes a new CSV with the same core columns

Windows/PowerShell friendly: no prompts, one-shot execution.
"""

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional

import math
import pandas as pd

from golfsim.logging import init_logging, get_logger


logger = get_logger(__name__)


@dataclass
class ResampleConfig:
    input_csv: Path
    output_csv: Path
    step_s: int = 1
    smooth_window: int = 0  # 0 or 1 disables smoothing; must be odd if >1
    id_filter: Optional[str] = None
    start_ts: Optional[int] = None
    end_ts: Optional[int] = None


def _validate_config(cfg: ResampleConfig) -> None:
    if cfg.step_s <= 0:
        raise SystemExit("--step-s must be >= 1")
    if cfg.smooth_window < 0:
        raise SystemExit("--smooth-window must be >= 0")
    if cfg.smooth_window > 1 and cfg.smooth_window % 2 == 0:
        logger.warning("--smooth-window %d is not odd; increasing by 1 for symmetry", cfg.smooth_window)
        cfg.smooth_window += 1


def _iter_linear_interp(
    rows: List[Dict],
    step_s: int,
    start_ts: Optional[int] = None,
    end_ts: Optional[int] = None,
) -> Iterator[Dict]:
    if not rows:
        return

    rows_sorted = sorted(rows, key=lambda r: int(r.get("timestamp", 0)))
    # Optionally trim by time range (keep original points for edge interpolation)
    if start_ts is not None or end_ts is not None:
        s = start_ts if start_ts is not None else int(rows_sorted[0]["timestamp"])
        e = end_ts if end_ts is not None else int(rows_sorted[-1]["timestamp"])
    else:
        s = int(rows_sorted[0]["timestamp"])
        e = int(rows_sorted[-1]["timestamp"])

    # Walk consecutive pairs and emit on a fixed grid within each segment
    for i in range(len(rows_sorted) - 1):
        a = rows_sorted[i]
        b = rows_sorted[i + 1]
        t0 = int(a.get("timestamp", 0))
        t1 = int(b.get("timestamp", 0))
        if t1 <= t0:
            continue

        seg_start = max(s, t0)
        seg_end = min(e, t1)
        if seg_end < seg_start:
            continue

        # Ensure we include the segment start aligned to the grid
        # First grid timestamp >= seg_start
        first_t = ((seg_start + step_s - 1) // step_s) * step_s
        last_t = (seg_end // step_s) * step_s
        if first_t < seg_start:
            first_t = seg_start
        if last_t > seg_end:
            last_t = seg_end

        # Always emit the exact endpoint b if it lies on the grid or is the last segment
        for t in range(first_t, last_t + 1, step_s):
            ratio = (t - t0) / float(t1 - t0)
            lon = float(a["longitude"]) + ratio * (float(b["longitude"]) - float(a["longitude"]))
            lat = float(a["latitude"]) + ratio * (float(b["latitude"]) - float(a["latitude"]))
            out = {
                "id": a.get("id", ""),
                "latitude": lat,
                "longitude": lon,
                "timestamp": int(t),
                "type": a.get("type", b.get("type", "")),
                "hole": a.get("hole", b.get("hole", "")),
            }
            yield out


def _apply_moving_average(points: List[Dict], window: int) -> List[Dict]:
    if window <= 1 or len(points) <= 2:
        return points
    half = window // 2
    latitudes = [float(p["latitude"]) for p in points]
    longitudes = [float(p["longitude"]) for p in points]
    smoothed: List[Dict] = []
    for i, p in enumerate(points):
        a = max(0, i - half)
        b = min(len(points), i + half + 1)
        span = b - a
        if span <= 0:
            smoothed.append(p)
            continue
        lat = sum(latitudes[a:b]) / span
        lon = sum(longitudes[a:b]) / span
        q = dict(p)
        q["latitude"] = lat
        q["longitude"] = lon
        smoothed.append(q)
    return smoothed


def resample_file(cfg: ResampleConfig) -> None:
    logger.info(
        "Resampling %s → %s (step=%ds, smooth_window=%d)",
        cfg.input_csv,
        cfg.output_csv,
        cfg.step_s,
        cfg.smooth_window,
    )

    df = pd.read_csv(cfg.input_csv)
    required_cols = {"id", "latitude", "longitude", "timestamp"}
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise SystemExit(f"Input CSV missing required columns: {missing}")

    if cfg.id_filter:
        df = df[df["id"].astype(str) == str(cfg.id_filter)]
        if df.empty:
            raise SystemExit(f"No rows for id '{cfg.id_filter}' in {cfg.input_csv}")

    groups = df.groupby("id")
    output_rows: List[Dict] = []
    for stream_id, g in groups:
        rows = g.to_dict(orient="records")
        stream_rows = list(
            _iter_linear_interp(
                rows,
                step_s=cfg.step_s,
                start_ts=cfg.start_ts,
                end_ts=cfg.end_ts,
            )
        )
        if cfg.smooth_window and cfg.smooth_window > 1:
            stream_rows = _apply_moving_average(stream_rows, cfg.smooth_window)

        output_rows.extend(stream_rows)

    if not output_rows:
        logger.warning("No resampled points produced; check input ranges and step size")

    out_df = pd.DataFrame(output_rows)
    # Ensure core column order; preserve extras if present
    base_cols = ["id", "latitude", "longitude", "timestamp", "type", "hole"]
    other_cols = [c for c in out_df.columns if c not in base_cols]
    ordered_cols = base_cols + other_cols
    out_df = out_df[ordered_cols]

    cfg.output_csv.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(cfg.output_csv, index=False)
    logger.info("Wrote %d resampled points to %s", len(out_df), cfg.output_csv)


def parse_args() -> ResampleConfig:
    p = argparse.ArgumentParser(description="Resample unified coordinates CSV to fixed temporal spacing")
    p.add_argument("--input", required=True, help="Path to input coordinates CSV")
    p.add_argument("--output", required=True, help="Path to output resampled CSV")
    p.add_argument("--step-s", type=int, default=1, help="Temporal spacing in seconds (default: 1)")
    p.add_argument("--smooth-window", type=int, default=0, help="Optional moving average window (odd number). 0 to disable")
    p.add_argument("--id", dest="id_filter", default=None, help="Optional stream id to resample (default: all)")
    p.add_argument("--start-ts", type=int, default=None, help="Optional earliest timestamp to include")
    p.add_argument("--end-ts", type=int, default=None, help="Optional latest timestamp to include")
    p.add_argument("--log-level", default="INFO", help="Log level (default: INFO)")
    args = p.parse_args()

    init_logging(args.log_level)

    cfg = ResampleConfig(
        input_csv=Path(args.input),
        output_csv=Path(args.output),
        step_s=int(args.step_s),
        smooth_window=int(args.smooth_window or 0),
        id_filter=str(args.id_filter) if args.id_filter else None,
        start_ts=int(args.start_ts) if args.start_ts is not None else None,
        end_ts=int(args.end_ts) if args.end_ts is not None else None,
    )
    _validate_config(cfg)
    return cfg


def main() -> None:
    cfg = parse_args()
    resample_file(cfg)


if __name__ == "__main__":
    main()


