import json
import sys
from pathlib import Path
from typing import List, Dict, Any


def find_timestamp_key(sample: Dict[str, Any]) -> str:
    # Prefer explicit names
    for key in ("timestamp_s", "time_s", "ts", "t_seconds", "t_s", "t"):
        if key in sample:
            return key
    # Fallback: any key containing 'time' or 'timestamp'
    for key in sample.keys():
        lower = key.lower()
        if "timestamp" in lower or lower.endswith("_s") and ("time" in lower or "ts" in lower):
            return key
    raise KeyError("Could not locate a timestamp field in coordinate record")


def validate_coordinates(path: Path) -> None:
    if not path.exists():
        print(f"ERROR: Missing coordinates file: {path}")
        sys.exit(1)

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: Failed to parse JSON {path}: {e}")
        sys.exit(1)

    if not isinstance(data, list) or not data:
        print("ERROR: Coordinates JSON is not a non-empty list")
        sys.exit(1)

    ts_key = find_timestamp_key(data[0])

    try:
        timestamps: List[int] = [int(item[ts_key]) for item in data]
    except Exception as e:
        print(f"ERROR: Failed to read timestamps using key '{ts_key}': {e}")
        sys.exit(1)

    n = len(timestamps)
    if n < 2:
        print("ERROR: Not enough coordinate points to validate intervals")
        sys.exit(1)

    monotonic = all(timestamps[i + 1] > timestamps[i] for i in range(n - 1))
    diffs = [timestamps[i + 1] - timestamps[i] for i in range(n - 1)]
    step60 = all(d == 60 for d in diffs)

    first_ok = timestamps[0] >= 7200  # 09:00 relative to 07:00 start
    last_ok = timestamps[-1] <= 36000  # 17:00 relative to 07:00 start

    print(f"points={n}")
    print(f"monotonic={monotonic}")
    print(f"step60={step60}")
    print(f"first={timestamps[0]}")
    print(f"last={timestamps[-1]}")

    if not (monotonic and step60 and first_ok and last_ok):
        print("ERROR: Validation failed: ", {
            "monotonic": monotonic,
            "step60": step60,
            "first_ok": first_ok,
            "last_ok": last_ok,
        })
        sys.exit(1)


def scan_activity_log(path: Path) -> None:
    if not path.exists():
        print(f"activity_log_absent=True ({path})")
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"ERROR: Failed to parse JSON {path}: {e}")
        sys.exit(1)

    if isinstance(data, dict) and "events" in data:
        events = data["events"]
    else:
        events = data if isinstance(data, list) else []

    errors = []
    for ev in events:
        level = str(ev.get("level", ev.get("severity", "")).lower())
        if level in ("error", "critical"):
            errors.append(ev)
        if ev.get("type") in ("error", "exception"):
            errors.append(ev)

    print(f"activity_events={len(events)}")
    print(f"activity_errors={len(errors)}")

    if errors:
        print("ERROR: Activity log includes error events")
        sys.exit(1)


if __name__ == "__main__":
    out_dir = Path("outputs") / "bev_cart_only"
    coords_path = out_dir / "bev_cart_coordinates.json"
    log_path = out_dir / "bev_cart_activity_log.json"

    validate_coordinates(coords_path)
    scan_activity_log(log_path)

    print("OK: Beverage cart coordinates valid and no errors in activity log")
    sys.exit(0)
