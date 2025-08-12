from __future__ import annotations

from typing import Any, Dict


def normalize_coordinate_entry_inplace(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a coordinate-like dict in-place to preferred schema.

    - Ensures keys: latitude, longitude, timestamp, type, hole/current_hole passthrough
    - Maps lat/lon -> latitude/longitude
    - Maps timestamp_s -> timestamp when timestamp is absent
    """
    if "latitude" not in entry and "lat" in entry:
        entry["latitude"] = entry.get("lat")
    if "longitude" not in entry and "lon" in entry:
        entry["longitude"] = entry.get("lon")
    if "timestamp" not in entry and "timestamp_s" in entry:
        try:
            entry["timestamp"] = int(entry.get("timestamp_s") or 0)
        except Exception:
            entry["timestamp"] = 0
    # Normalize type strings
    t = str(entry.get("type", "")).lower()
    if t in {"bev", "bevcart", "beverage", "beverage-cart", "cart"}:
        entry["type"] = "bev_cart"
    elif "golf" in t:
        entry["type"] = "golfer"
    elif "runner" in t:
        entry["type"] = "delivery-runner"
    return entry


