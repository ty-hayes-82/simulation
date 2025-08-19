"""Prepare React map animations from a given outputs folder.

This script scans a specified directory (e.g., SLA optimization outputs) for
coordinate CSV files, copies them into the React app's public/coordinates/
folder, generates a manifest, and optionally starts the React app.

Usage (from repo root):
  python scripts/viz/load_animations.py --source-dir outputs/sla_optimization_YYYYMMDD_HHMMSS --start-app
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def _resolve_paths() -> tuple[Path, Path]:
	this_file = Path(__file__).resolve()
	repo_root = this_file.parents[2]
	app_dir = repo_root / "my-map-animation"
	return repo_root, app_dir


def _ensure_app_available(app_dir: Path) -> None:
	run_map_app_py = app_dir / "run_map_app.py"
	if not run_map_app_py.exists():
		raise FileNotFoundError(
			f"Could not find {run_map_app_py}. Ensure the React app exists at 'my-map-animation/'."
		)


def _import_run_map_app(app_dir: Path):
	# Prepend app_dir to import path just for this script run
	if str(app_dir) not in sys.path:
		sys.path.insert(0, str(app_dir))
	import importlib
	return importlib.import_module("run_map_app")


def main() -> None:
	parser = argparse.ArgumentParser(description="Load animations into React app from a source directory")
	parser.add_argument("--source-dir", required=True, help="Folder to scan for coordinate CSVs (e.g., outputs/sla_optimization_...)")
	parser.add_argument("--default-id", default=None, help="Preferred default simulation id for the manifest (optional)")
	parser.add_argument("--start-app", action="store_true", help="Start the React app after preparing the manifest")
	args = parser.parse_args()

	repo_root, app_dir = _resolve_paths()
	_ensure_app_available(app_dir)

	source_dir = Path(args.source_dir).resolve()
	if not source_dir.exists() or not source_dir.is_dir():
		raise FileNotFoundError(f"Source directory not found or not a directory: {source_dir}")

	# Point the app's scanner at the chosen folder
	os.environ["SIM_BASE_DIR"] = str(source_dir)

	run_map_app = _import_run_map_app(app_dir)

	print(f"Scanning for coordinate files under: {source_dir}")
	all_sims = run_map_app.find_all_simulations()
	total = sum(len(v) for v in all_sims.values())
	if total == 0:
		print("No coordinate CSVs found (expects coordinates.csv or bev_cart_coordinates.csv). Nothing to do.")
		return

	print(f"Found {total} simulations. Copying to public/coordinates and writing manifest.json...")
	ok = run_map_app.copy_all_coordinate_files(all_sims, preferred_default_id=args.default_id)
	if not ok:
		raise RuntimeError("Failed to copy coordinates or write manifest.json")

	print("Done preparing animations.")
	print(f"Manifest path: {app_dir / 'public' / 'coordinates' / 'manifest.json'}")

	if args.start_app:
		# Change CWD to app dir and start the React app via helper
		cwd_before = Path.cwd()
		try:
			os.chdir(app_dir)
			started = run_map_app.run_react_app()
			if not started:
				raise SystemExit(1)
		except KeyboardInterrupt:
			pass
		finally:
			os.chdir(cwd_before)


if __name__ == "__main__":
	main()


