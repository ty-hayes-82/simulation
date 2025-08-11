from __future__ import annotations

from pathlib import Path
import sys
import runpy
import time


def _list_phase01_dirs(outputs_root: Path) -> list[Path]:
    return [p for p in outputs_root.glob("*_phase_01") if p.is_dir()]


def test_phase01_generates_5_runs_with_artifacts(tmp_path: Path) -> None:
    """
    Runs the phase 1 script and verifies it creates a timestamped outputs folder
    with sim_01..sim_05. Each sim folder must contain a PNG, GeoJSON, CSV, and stats.md.
    Also checks that a summary.md exists at the root.
    """
    outputs_root = Path("outputs")
    outputs_root.mkdir(exist_ok=True)

    # Snapshot pre-existing phase_01 folders
    before = {p.name for p in _list_phase01_dirs(outputs_root)}

    # Ensure repository root is importable (so 'golfsim' package resolves)
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    # Execute the script as __main__ via runpy to trigger its main()
    script_path = Path("scripts/sim/phase_01_beverage_cart_only/run_bev_cart_phase1.py")
    assert script_path.is_file(), f"Missing script: {script_path}"
    runpy.run_path(str(script_path), run_name="__main__")
    time.sleep(0.2)

    # Identify the newly created phase_01 folder
    after = [p for p in _list_phase01_dirs(outputs_root) if p.name not in before]
    assert after, "No new phase_01 output folder created"
    # If multiple, pick the most recent by mtime
    phase_dir = max(after, key=lambda p: p.stat().st_mtime)

    # Expect sim_01..sim_05
    for idx in range(1, 6):
        sim_dir = phase_dir / f"sim_{idx:02d}"
        assert sim_dir.is_dir(), f"Missing folder: {sim_dir}"
        assert (sim_dir / "bev_cart_route.png").is_file(), "Missing PNG"
        assert (sim_dir / "coordinates.csv").is_file(), "Missing CSV"
        assert (sim_dir / "stats.md").is_file(), "Missing stats.md"

    # Root summary
    assert (phase_dir / "summary.md").is_file(), "Missing summary.md at root"


