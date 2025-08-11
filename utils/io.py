from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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



