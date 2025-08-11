from __future__ import annotations

from pathlib import Path
import runpy
import sys
import time


def _list_phase11_dirs(outputs_root: Path) -> list[Path]:
    return [p for p in outputs_root.glob("*_phase_11") if p.is_dir()]


def test_phase11_generates_5_runs_with_dual_cart_artifacts() -> None:
    outputs_root = Path("outputs")
    outputs_root.mkdir(exist_ok=True)

    before = {p.name for p in _list_phase11_dirs(outputs_root)}

    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    script_path = Path("scripts/sim/phase_11_two_beverage_carts/run_bev_cart_phase11.py")
    assert script_path.is_file(), f"Missing script: {script_path}"
    runpy.run_path(str(script_path), run_name="__main__")
    time.sleep(0.2)

    after = [p for p in _list_phase11_dirs(outputs_root) if p.name not in before]
    assert after, "No new phase_11 output folder created"
    phase_dir = max(after, key=lambda p: p.stat().st_mtime)

    for idx in range(1, 6):
        sim_dir = phase_dir / f"sim_{idx:02d}"
        assert sim_dir.is_dir(), f"Missing folder: {sim_dir}"
        # Combined PNG per simulation
        assert (sim_dir / "bev_cart_route.png").is_file(), "Missing combined PNG"
        # Combined files (one per type)
        assert (sim_dir / "bev_cart_coordinates.csv").is_file(), "Missing combined CSV"
        # Stats
        assert (sim_dir / "stats.md").is_file(), "Missing stats.md"

    assert (phase_dir / "summary.md").is_file(), "Missing summary.md at root"


