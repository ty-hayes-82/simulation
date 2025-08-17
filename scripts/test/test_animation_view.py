#!/usr/bin/env python3
"""
Animation View Smoke Test

Prepares the React AnimationView inputs and validates that required assets
exist and are readable without starting a full simulation or the dev server.

This script:
  - Searches an outputs root for any coordinates.csv files
  - Optionally creates a minimal sample coordinates.csv if none exist
  - Runs my-map-animation/run_map_app.py to generate the viewer manifest
  - Validates the generated manifest and referenced CSV file
  - Optionally probes http://localhost:3000/animation if a server is running

Exit codes:
  0 on success; non-zero on failure.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional, Tuple
import subprocess
import socket
import time
import signal

try:
    # Ensure project root is importable for golfsim.logging
    sys.path.append(str(Path(__file__).resolve().parents[2]))
except Exception:
    pass

from golfsim.logging import init_logging, get_logger  # type: ignore


logger = get_logger(__name__)


def _find_any_coordinates_csv(outputs_root: Path) -> Optional[Path]:
    for p in outputs_root.rglob("coordinates.csv"):
        # Skip node_modules or unrelated paths if any
        parts = {part.lower() for part in p.parts}
        if "node_modules" in parts:
            continue
        return p
    return None


def _ensure_sample_coordinates(outputs_root: Path) -> Tuple[Path, Path]:
    """Create a minimal sample coordinates.csv if none exist.

    Returns a tuple of (simulation_root, csv_path).
    """
    sim_root = outputs_root / "test_animation" / "sim_01"
    sim_root.mkdir(parents=True, exist_ok=True)
    csv_path = sim_root / "coordinates.csv"
    if not csv_path.exists():
        # Minimal CSV with required headers used by AnimationView
        # Use 10 minutes (600s) span so the clock visibly advances even at high speed multipliers
        csv_path.write_text(
            """id,latitude,longitude,timestamp,type\n"""
            + "golfer_1,33.987000,-84.580000,0,golfer\n"
            + "golfer_1,33.987500,-84.579500,600,golfer\n",
            encoding="utf-8",
        )
    return sim_root.parent, csv_path


def _run_map_app_prepare(outputs_root: Path, default_id: Optional[str]) -> None:
    """Invoke my-map-animation/run_map_app.py to generate the manifest and copy CSVs."""
    viewer_dir = Path("my-map-animation").resolve()
    script = viewer_dir / "run_map_app.py"
    if not script.exists():
        raise FileNotFoundError(f"Viewer helper script not found: {script}")

    env = os.environ.copy()
    env["SIM_BASE_DIR"] = str(outputs_root.resolve())
    # Ensure child process prints UTF-8 safely on Windows consoles
    env.setdefault("PYTHONIOENCODING", "utf-8")

    cmd = [sys.executable, str(script)]
    if default_id:
        cmd += ["--default-id", str(default_id)]

    # Capture output to keep logs clean (script prints icons/emojis)
    result = subprocess.run(
        cmd,
        cwd=str(viewer_dir),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        logger.error("Coordinate preparation failed (exit %d)", result.returncode)
        if result.stderr:
            logger.error(result.stderr.strip())
        raise SystemExit(result.returncode)


def _validate_manifest_and_csv() -> Tuple[Path, str]:
    """Validate the generated manifest and referenced CSV file.

    Returns: (coordinates_dir, default_csv_filename)
    """
    viewer_dir = Path("my-map-animation").resolve()
    coords_dir = viewer_dir / "public" / "coordinates"
    manifest_path = coords_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    simulations = manifest.get("simulations", [])
    default_id = manifest.get("defaultSimulation")
    if not simulations:
        raise SystemExit("No simulations found in manifest")
    if not default_id:
        raise SystemExit("defaultSimulation not set in manifest")

    selected = next((s for s in simulations if s.get("id") == default_id), None)
    if not selected:
        raise SystemExit("defaultSimulation id not present in simulations list")

    filename = selected.get("filename")
    if not filename:
        raise SystemExit("Selected simulation missing 'filename'")

    csv_path = coords_dir / filename
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV not found: {csv_path}")

    # Basic CSV header validation
    first_line = csv_path.read_text(encoding="utf-8").splitlines()[0].strip().lower()
    required = {"latitude", "longitude", "timestamp"}
    headers = {h.strip() for h in first_line.split(",")}
    if not required.issubset(headers):
        raise SystemExit(
            f"CSV headers missing required columns. Found: {sorted(headers)} Required: {sorted(required)}"
        )

    return coords_dir, filename


def _probe_animation_route(timeout_sec: float = 1.0) -> bool:
    """Try to fetch http://localhost:3000/animation to see if a dev server is up."""
    try:
        import urllib.request

        req = urllib.request.Request("http://localhost:3000/animation")
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            code = getattr(resp, "status", None) or 0
            body = resp.read(4096).decode("utf-8", errors="ignore")
            # Heuristic: page served and contains some HTML
            return code == 200 and ("<!doctype html" in body.lower() or "<div" in body.lower())
    except Exception:
        return False


def _probe_animation_route_at_port(port: int, timeout_sec: float = 1.0) -> bool:
    """Try to fetch http://localhost:{port}/animation to verify dev server is up."""
    try:
        import urllib.request

        req = urllib.request.Request(f"http://localhost:{port}/animation")
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            code = getattr(resp, "status", None) or 0
            body = resp.read(4096).decode("utf-8", errors="ignore")
            return code == 200 and ("<!doctype html" in body.lower() or "<div" in body.lower())
    except Exception:
        return False


def _find_free_port(preferred_start: int = 3001, max_tries: int = 50) -> int:
    """Find an available localhost TCP port, starting at preferred_start."""
    for i in range(max_tries):
        port = preferred_start + i
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    # Fallback: let OS assign one
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_dev_server_on_port(port: int, npm_exe: Optional[str] = None) -> subprocess.Popen:
    """Start CRA dev server via `npm start` on a specific port. Returns the process handle.

    The server is launched with BROWSER=none to prevent opening a browser. Caller must stop it.
    """
    viewer_dir = Path("my-map-animation").resolve()
    if not (viewer_dir / "package.json").exists():
        raise FileNotFoundError(f"React app not found at {viewer_dir}")

    env = os.environ.copy()
    env["PORT"] = str(port)
    env["BROWSER"] = "none"

    try:
        # On POSIX, create a new process group; on Windows, we'll taskkill the tree later
        creationflags = 0
        preexec_fn = None
        if os.name != "nt":
            preexec_fn = os.setsid  # type: ignore[attr-defined]

        # Select npm executable per-OS
        if npm_exe:
            npm_cmd = npm_exe
        else:
            npm_cmd = "npm.cmd" if os.name == "nt" else "npm"

        proc = subprocess.Popen(
            [npm_cmd, "start"],
            cwd=str(viewer_dir),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
            shell=False,
            preexec_fn=preexec_fn,
            creationflags=creationflags,
        )
    except FileNotFoundError as e:
        raise SystemExit("npm not found. Ensure Node.js and npm are installed and on PATH.") from e

    return proc


def _wait_for_server(port: int, timeout_sec: float) -> bool:
    """Poll the /animation route until the server is ready or timeout occurs."""
    start = time.time()
    # Give CRA a moment to boot before polling
    time.sleep(1.0)
    while time.time() - start < timeout_sec:
        if _probe_animation_route_at_port(port, timeout_sec=1.0):
            return True
        time.sleep(1.0)
    return False


def _stop_dev_server(proc: subprocess.Popen) -> None:
    """Terminate the dev server and its children."""
    try:
        if proc.poll() is not None:
            return
        if os.name == "nt":
            # Kill process tree on Windows
            try:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            except Exception:
                proc.terminate()
        else:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            except Exception:
                proc.terminate()
        # Best-effort wait
        try:
            proc.wait(timeout=10)
        except Exception:
            pass
    except Exception:
        pass


def main() -> None:
    parser = argparse.ArgumentParser(description="Test only the AnimationView assets and route")
    parser.add_argument("--outputs-root", default="outputs", help="Root folder containing simulation outputs")
    parser.add_argument("--course-dir", default="courses/pinetree_country_club", help="Course directory (for context only)")
    parser.add_argument("--default-sim-id", default=None, help="Preferred default simulation id for the viewer manifest")
    parser.add_argument("--create-sample", action="store_true", help="Create a minimal sample coordinates.csv if none found")
    parser.add_argument("--probe-devserver", action="store_true", help="Probe http://localhost:3000/animation if a server is running")
    parser.add_argument("--start-devserver", action="store_true", help="Start a new React dev server on a free port and test /animation")
    parser.add_argument("--port", type=int, default=None, help="Port to run the dev server on (default: find free starting at 3001)")
    parser.add_argument("--startup-timeout", type=float, default=90.0, help="Seconds to wait for the dev server to be ready")
    parser.add_argument("--npm-exe", default=None, help="Path to npm executable (e.g., C:/Program Files/nodejs/npm.cmd)")
    args = parser.parse_args()

    init_logging("INFO")
    outputs_root = Path(args.outputs_root).resolve()

    if not outputs_root.exists():
        logger.info("Creating outputs root at %s", outputs_root)
        outputs_root.mkdir(parents=True, exist_ok=True)

    found_csv = _find_any_coordinates_csv(outputs_root)
    if not found_csv and args.create_sample:
        sim_root, sample_csv = _ensure_sample_coordinates(outputs_root)
        logger.info("Created sample coordinates at %s", sample_csv)
        # Prefer this sample id for default selection
        default_id = f"{sim_root.name}_sim_01_coordinates"
    else:
        default_id = args.default_sim_id

    # Prepare viewer files (manifest and copied CSVs)
    _run_map_app_prepare(outputs_root, default_id)

    # Validate manifest and CSV
    coords_dir, filename = _validate_manifest_and_csv()
    logger.info("AnimationView assets ready: %s/%s", coords_dir, filename)

    # Optionally probe an already-running default dev server
    if args.probe_devserver:
        if _probe_animation_route():
            logger.info("Existing dev server responded at /animation (port 3000)")
        else:
            logger.info("No existing dev server at /animation (port 3000)")

    # Optionally start a fresh dev server on a different port and test
    if args.start_devserver:
        port = args.port or _find_free_port(3001)
        logger.info("Starting React dev server on port %d...", port)
        proc = _start_dev_server_on_port(port, npm_exe=args.npm_exe)
        started_ok = False
        try:
            started_ok = _wait_for_server(port, timeout_sec=float(args.startup_timeout))
            if not started_ok:
                # Read a bit of stdout for diagnostics
                try:
                    if proc.stdout:
                        tail = proc.stdout.read(4096)
                        if tail:
                            logger.info("Dev server output (truncated):\n%s", tail[-1000:])
                except Exception:
                    pass
                raise SystemExit(f"Dev server failed to become ready on port {port} within timeout")
            # Probe /animation once ready
            if _probe_animation_route_at_port(port, timeout_sec=2.0):
                logger.info("Dev server responded at http://localhost:%d/animation", port)
            else:
                raise SystemExit(f"Dev server did not serve /animation correctly on port {port}")
        finally:
            logger.info("Stopping React dev server on port %d...", port)
            _stop_dev_server(proc)

    # Success
    logger.info("Animation view test completed successfully")


if __name__ == "__main__":
    main()


