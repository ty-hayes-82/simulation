from __future__ import annotations

from pathlib import Path
import runpy
import sys
import time


def _list_phase02_dirs(outputs_root: Path) -> list[Path]:
    return [p for p in outputs_root.glob("*_phase_02") if p.is_dir()]


def test_phase02_generates_5_runs_with_artifacts() -> None:
    outputs_root = Path("outputs")
    outputs_root.mkdir(exist_ok=True)

    before = {p.name for p in _list_phase02_dirs(outputs_root)}

    # Ensure repo root is importable for 'golfsim'
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    # Execute phase 2 script via runpy
    script_path = Path("scripts/sim/phase_02_golfer_only/run_golfer_only_phase2.py")
    assert script_path.is_file(), f"Missing script: {script_path}"
    runpy.run_path(str(script_path), run_name="__main__")
    time.sleep(0.2)

    after = [p for p in _list_phase02_dirs(outputs_root) if p.name not in before]
    assert after, "No new phase_02 output folder created"
    phase_dir = max(after, key=lambda p: p.stat().st_mtime)

    for idx in range(1, 6):
        sim_dir = phase_dir / f"sim_{idx:02d}"
        assert sim_dir.is_dir(), f"Missing folder: {sim_dir}"
        assert (sim_dir / "golfer_route.png").is_file(), "Missing PNG"
        assert (sim_dir / "coordinates.csv").is_file(), "Missing CSV"
        assert (sim_dir / "stats.md").is_file(), "Missing stats.md"

        # Validate timestamps are within one of the configured hours in tee_times_config
        import json as _json
        from golfsim.config.loaders import load_tee_times_config as _load_cfg

        cfg = _load_cfg("courses/pinetree_country_club")
        scenarios = cfg.scenarios
        scenario_key = "testing_rainy_day" if "testing_rainy_day" in scenarios else next(iter(scenarios))
        hourly = scenarios[scenario_key]["hourly_golfers"]
        valid_starts = []
        for hhmm, count in hourly.items():
            if isinstance(count, int) and count > 0:
                hh, mm = hhmm.split(":")
                valid_starts.append((int(hh) - 7) * 3600 + int(mm) * 60)
        # Read CSV first/last timestamps
        import csv as _csv
        with (sim_dir / "coordinates.csv").open("r", encoding="utf-8") as f:
            reader = _csv.DictReader(f)
            times = [int(row["timestamp"]) for row in reader]
        assert times, "empty coordinates"
        first_ts = times[0]
        assert any(abs(first_ts - s) < 1e-6 for s in valid_starts), f"first timestamp {first_ts} not aligned to any tee-time hour"

    assert (phase_dir / "summary.md").is_file(), "Missing summary.md at root"


