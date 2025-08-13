from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional
import os

import pandas as pd


def write_json(path: str | Path, data: Any) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
    return p


def read_json(path: str | Path) -> Any:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_table_csv(path: str | Path, table: pd.DataFrame | list[dict[str, Any]]) -> Path:  # type: ignore[name-defined]
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(table, pd.DataFrame):
        table.to_csv(p, index=False)
    else:
        df = pd.DataFrame(table)
        df.to_csv(p, index=False)
    return p


def copy_to_visualization_public(
    source_path: str | Path,
    *,
    subfolder: Optional[str] = None,
    filename: Optional[str] = None,
    env_var: str = "VIS_PUBLIC_DIR",
) -> Path:
    """Copy a file into the visualization public folder.

    - Destination root is taken from environment variable VIS_PUBLIC_DIR when set,
      otherwise falls back to C:\Main\GIT\visualization\public.
    - You can specify a subfolder (e.g. "coordinates") and/or override filename.
    """
    import shutil as _shutil

    src = Path(source_path)
    if not src.exists():
        raise FileNotFoundError(f"Source file does not exist: {src}")

    root = os.environ.get(env_var) or r"C:\\Main\\GIT\\visualization\\public"
    dest_root = Path(root)
    if subfolder:
        dest_root = dest_root / subfolder
    dest_root.mkdir(parents=True, exist_ok=True)

    dest = dest_root / (filename or src.name)
    _shutil.copy2(src, dest)
    return dest


def update_coordinates_manifest(
    copied_file_path: str | Path,
    *,
    group_name: str = "Local",
    manifest_filename: str = "manifest.json",
) -> Path:
    """Update (or create) a manifest JSON alongside the copied coordinates file.

    Schema example:
    {
      "simulationGroups": {
        "Local": [
          {
            "id": "delivery_runner_run_05_20250812_154735",
            "name": "Run 05 (Delivery Runner)",
            "filename": "delivery_runner_run_05_20250812_154735.csv",
            "description": "Delivery runner - run 05"
          }
        ]
      },
      "defaultGroup": "Local",
      "defaultSimulation": "delivery_runner_run_05_20250812_154735"
    }

    If the manifest file does not exist, it will be created with the provided structure.
    """
    p = Path(copied_file_path)
    manifest_path = p.parent / manifest_filename

    # Load existing or initialize new manifest
    if manifest_path.exists():
        try:
            manifest = read_json(manifest_path)
        except Exception:
            manifest = {}
    else:
        manifest = {}

    # Ensure base structure
    simulation_groups = manifest.get("simulationGroups")
    if not isinstance(simulation_groups, dict):
        simulation_groups = {}
        manifest["simulationGroups"] = simulation_groups

    group_list = simulation_groups.get(group_name)
    if not isinstance(group_list, list):
        group_list = []
        simulation_groups[group_name] = group_list

    # Build entry from filename
    stem = p.stem  # e.g., delivery_runner_run_05_20250812_154735
    filename = p.name

    # Derive mode and run number for friendly labels
    mode = stem.split("_run_")[0] if "_run_" in stem else stem
    run_num_str = None
    try:
        # Expect pattern *_run_XX_*
        after = stem.split("_run_")[1] if "_run_" in stem else ""
        run_num_str = after.split("_")[0]
    except Exception:
        run_num_str = None

    def _format_mode_label(s: str) -> str:
        return s.replace("_", " ").title()

    mode_label = _format_mode_label(mode)
    try:
        run_num_int = int(run_num_str) if run_num_str is not None else None
    except Exception:
        run_num_int = None

    name = f"Run {run_num_int:02d} ({mode_label})" if isinstance(run_num_int, int) else f"{mode_label}"
    description = (
        f"{mode_label} - run {run_num_int:02d}" if isinstance(run_num_int, int) else f"{mode_label} run"
    )

    new_entry = {
        "id": stem,
        "name": name,
        "filename": filename,
        "description": description,
    }

    # Deduplicate by id; replace if exists
    existing_idx = next((i for i, e in enumerate(group_list) if e.get("id") == stem), None)
    if existing_idx is not None:
        group_list[existing_idx] = new_entry
    else:
        group_list.append(new_entry)

    # Set defaults
    manifest["defaultGroup"] = group_name
    manifest["defaultSimulation"] = stem

    # Persist manifest
    write_json(manifest_path, manifest)
    return manifest_path

