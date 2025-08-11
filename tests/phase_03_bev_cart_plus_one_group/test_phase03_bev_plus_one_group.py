from __future__ import annotations

from pathlib import Path
import runpy
import sys
import time
import json


def _list_phase03_dirs(outputs_root: Path) -> list[Path]:
    return [p for p in outputs_root.glob("*_phase_03") if p.is_dir()]


def test_phase03_generates_sales_and_positive_mean_revenue() -> None:
    outputs_root = Path("outputs")
    outputs_root.mkdir(exist_ok=True)

    before = {p.name for p in _list_phase03_dirs(outputs_root)}

    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    script_path = Path("scripts/sim/phase_03_bev_cart_plus_one_group/run_bev_cart_phase3.py")
    assert script_path.is_file(), f"Missing script: {script_path}"
    runpy.run_path(str(script_path), run_name="__main__")
    time.sleep(0.2)

    after = [p for p in _list_phase03_dirs(outputs_root) if p.name not in before]
    assert after, "No new phase_03 output folder created"
    phase_dir = max(after, key=lambda p: p.stat().st_mtime)

    # Check sim_01 exists and has artifacts
    sim_dir = phase_dir / "sim_01"
    assert sim_dir.is_dir(), "Missing sim_01"
    assert (sim_dir / "bev_cart_route.png").is_file(), "Missing bev_cart_route.png"
    assert (sim_dir / "sales.json").is_file(), "Missing sales.json"
    assert (sim_dir / "result.json").is_file(), "Missing result.json"
    assert (sim_dir / "stats.md").is_file(), "Missing stats.md"
    assert (sim_dir / "coordinates.csv").is_file(), "Missing coordinates.csv"

    # Compute mean revenue and ensure > 0 across runs with probabilistic orders
    revenues = []
    pass_intervals_counts = []
    for idx in range(1, 6):
        sd = phase_dir / f"sim_{idx:02d}"
        with (sd / "result.json").open("r", encoding="utf-8") as f:
            res = json.load(f)
        revenues.append(float(res.get("revenue", 0.0)))
        pi = res.get("pass_intervals_per_group", {}).get("1") or res.get("pass_intervals_per_group", {}).get(1)
        if isinstance(pi, list):
            pass_intervals_counts.append(len(pi))

    assert len(revenues) == 5
    # Expect average revenue > 0 for pass_order_probability=0.4
    assert sum(revenues) / len(revenues) > 0.0, "Mean revenue not greater than 0"
    # Ensure we observed at least one pass event in at least one run
    assert any(c > 0 for c in pass_intervals_counts), "No pass intervals recorded"

    # Validate coordinates.csv contains both golfer and bev cart entries
    import csv as _csv
    with (sim_dir / "coordinates.csv").open("r", encoding="utf-8") as f:
        r = _csv.DictReader(f)
        ids = {row.get("id") for row in r}
    assert {"golfer_1", "bev_cart_1"}.issubset(ids), "coordinates.csv missing golfer_1 or bev_cart_1 rows"

    # Root summary exists
    assert (phase_dir / "summary.md").is_file(), "Missing summary.md at root"


