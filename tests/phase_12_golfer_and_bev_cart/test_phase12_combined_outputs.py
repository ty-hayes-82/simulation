from __future__ import annotations

from pathlib import Path
import runpy
import sys
import time
import csv


def _list_phase12_dirs(outputs_root: Path) -> list[Path]:
    return [p for p in outputs_root.glob("*_phase_12") if p.is_dir()]


def test_phase12_generates_combined_artifacts_and_cadence_alignment() -> None:
    outputs_root = Path("outputs")
    outputs_root.mkdir(exist_ok=True)

    before = {p.name for p in _list_phase12_dirs(outputs_root)}

    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    script_path = Path("scripts/sim/phase_12_golfer_and_bev_cart/run_phase12_golfer_and_bev.py")
    assert script_path.is_file(), f"Missing script: {script_path}"
    runpy.run_path(str(script_path), run_name="__main__")
    time.sleep(0.2)

    after = [p for p in _list_phase12_dirs(outputs_root) if p.name not in before]
    assert after, "No new phase_12 output folder created"
    phase_dir = max(after, key=lambda p: p.stat().st_mtime)

    sim_dir = phase_dir / "sim_01"
    assert sim_dir.is_dir(), "Missing sim_01"

    # Required artifacts
    assert (sim_dir / "coordinates.csv").is_file(), "Missing combined CSV"
    assert (sim_dir / "golfer_route.png").is_file(), "Missing golfer PNG"
    assert (sim_dir / "bev_cart_route.png").is_file(), "Missing cart PNG"

    # Cadence alignment checks (both 60s steps; non-decreasing)
    def read_times(csv_path: Path) -> list[int]:
        with csv_path.open("r", encoding="utf-8") as f:
            r = csv.DictReader(f)
            ts = [int(row["timestamp"]) for row in r]
        return ts

    # Read the combined CSV and split by id for cadence checks
    combined = sim_dir / "coordinates.csv"
    with combined.open("r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        g_times = [int(row["timestamp"]) for row in r if row.get("id") == "golfer_1"]
    with combined.open("r", encoding="utf-8") as f:
        r = csv.DictReader(f)
        c_times = [int(row["timestamp"]) for row in r if row.get("id") == "bev_cart_1"]
    assert g_times and c_times
    gd = [b - a for a, b in zip(g_times, g_times[1:])]
    cd = [b - a for a, b in zip(c_times, c_times[1:])]
    assert all(d > 0 for d in gd)
    assert all(d > 0 for d in cd)
    # Both minute-cadence
    assert all(d == 60 for d in gd), "Golfer not at 60s cadence"
    # Bev cart is 60s cadence as well
    assert all(d == 60 for d in cd), "Cart not at 60s cadence"


