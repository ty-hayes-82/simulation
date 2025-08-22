import subprocess
import sys


def test_imports():
    import golfsim
    from golfsim.data.osm_ingest import load_course, build_cartpath_graph
    from golfsim.preprocess.course_model import build_traditional_route
    from golfsim.simulation.orchestration import run_multi_golfer_simulation
    assert hasattr(golfsim.simulation.orchestration, "run_multi_golfer_simulation")


def test_simulation_cli_smoke():
    """Run the primary simulation CLI as a smoke test."""
    command = [
        sys.executable,
        "scripts/sim/run_new.py",
        "--course-dir",
        "courses/pinetree_country_club",
        "--num-runners",
        "1",
        "--num-runs",
        "1",
        "--log-level",
        "ERROR",
    ]

    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, f"run_new.py failed:\n{result.stdout}\n{result.stderr}"
