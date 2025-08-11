import subprocess
import sys


def test_imports():
    import golfsim
    from golfsim.data.osm_ingest import load_course, build_cartpath_graph
    from golfsim.preprocess.course_model import build_traditional_route
    from golfsim.simulation.engine import run_simulation

    assert hasattr(golfsim, "run_simulation")


def test_simulation_cli_smoke():
    """Run the primary simulation CLI as a smoke test."""
    command = [
        sys.executable,
        "-m",
        "scripts.sim.run_simulation",
        "--course-dir",
        "courses/pinetree_country_club",
        "--hole",
        "16",
        "--prep-time",
        "1",
        "--runner-speed",
        "6.0",
        "--no-visualization",
        "--log-level",
        "ERROR",
    ]

    result = subprocess.run(command, capture_output=True, text=True)
    assert result.returncode == 0, f"run_simulation failed:\n{result.stdout}\n{result.stderr}"
