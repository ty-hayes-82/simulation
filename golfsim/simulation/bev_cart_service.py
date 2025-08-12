from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import simpy

from ..config.loaders import load_simulation_config
from ..logging import get_logger
from ..utils.time import seconds_since_7am


logger = get_logger(__name__)


@dataclass
class BeverageCartService:
    env: simpy.Environment
    course_dir: str
    cart_id: str = "bev_cart_1"
    track_coordinates: bool = True
    starting_hole: int = 18  # New parameter for custom starting hole

    coordinates: List[Dict] = field(default_factory=list)
    activity_log: List[Dict] = field(default_factory=list)

    clubhouse_coords: Tuple[float, float] | None = None
    service_start_s: int = 0
    service_end_s: int = 0
    bev_cart_18_holes_minutes: int = 180

    def __post_init__(self) -> None:
        self._load_course_config()
        if self.track_coordinates:
            self.env.process(self.beverage_cart_process())

    def _load_course_config(self) -> None:
        sim_cfg = load_simulation_config(self.course_dir)
        self.clubhouse_coords = sim_cfg.clubhouse
        # Read configured 18-hole loop durations
        try:
            minutes = int(getattr(sim_cfg, "bev_cart_18_holes_minutes", 180))
            self.bev_cart_18_holes_minutes = max(1, minutes)
        except Exception:
            self.bev_cart_18_holes_minutes = 180
        # Service hours for beverage cart (prefer config, else defaults)
        if getattr(sim_cfg, "bev_cart_hours", None) is not None:
            start_time = f"{int(sim_cfg.bev_cart_hours.start_hour):02d}:00"
            end_time = f"{int(sim_cfg.bev_cart_hours.end_hour):02d}:00"
        else:
            start_time = "09:00"
            end_time = "17:00"
        self.service_start_s = seconds_since_7am(start_time)
        self.service_end_s = seconds_since_7am(end_time)
        logger.info(
            "Beverage cart service hours: %s - %s (%.1fh - %.1fh)",
            start_time,
            end_time,
            self.service_start_s / 3600,
            self.service_end_s / 3600,
        )
        logger.info("Beverage cart 18-hole circuit time: %d minutes", self.bev_cart_18_holes_minutes)

    def _build_hole_sequence(self, minutes_per_loop: int) -> List[int]:
        """Build hole sequence based on starting hole.

        Cart 1 (starting_hole=18): 18→17→16→...→1 (standard reverse)
        Cart 2 (starting_hole=9): 9→8→7→...→1→18→17→...→10→9 (start at 9, complete full circuit)
        """
        minutes_per_hole_in_loop = minutes_per_loop / 18.0
        hole_sequence: List[int] = []

        if self.starting_hole == 18:
            for hole_num in range(18, 0, -1):
                hole_minutes = int(minutes_per_hole_in_loop)
                hole_sequence.extend([hole_num] * hole_minutes)
        elif self.starting_hole == 9:
            sequence = list(range(9, 0, -1)) + list(range(18, 9, -1))
            for hole_num in sequence:
                hole_minutes = int(minutes_per_hole_in_loop)
                hole_sequence.extend([hole_num] * hole_minutes)
        else:
            for hole_num in range(18, 0, -1):
                hole_minutes = int(minutes_per_hole_in_loop)
                hole_sequence.extend([hole_num] * hole_minutes)

        while len(hole_sequence) < minutes_per_loop:
            hole_sequence.append(hole_sequence[-1] if hole_sequence else 1)
        hole_sequence = hole_sequence[:minutes_per_loop]
        return hole_sequence

    @staticmethod
    def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
        import math
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return 6371000.0 * c

    def _flatten_holes_linestrings(self) -> list[tuple[float, float]]:
        import json
        from shapely.geometry import LineString

        holes_path = Path(self.course_dir) / "geojson" / "holes.geojson"
        if not holes_path.exists():
            return []
        data = json.loads(holes_path.read_text(encoding="utf-8"))
        feats = data.get("features", [])

        def _ref(props):
            v = props.get("ref") or props.get("hole")
            try:
                return int(v)
            except Exception:
                return 10**9

        feats.sort(key=lambda f: _ref(f.get("properties", {})))
        coords: list[tuple[float, float]] = []
        for f in feats:
            geom = f.get("geometry", {})
            if geom.get("type") != "LineString":
                continue
            for lon, lat in geom.get("coordinates", []):
                coords.append((float(lon), float(lat)))
        if len(coords) > 1:
            coords.append(coords[0])
        # Deduplicate consecutive duplicates
        dedup: list[tuple[float, float]] = []
        last: tuple[float, float] | None = None
        for pt in coords:
            if last is None or (pt[0] != last[0] or pt[1] != last[1]):
                dedup.append(pt)
                last = pt
        return dedup

    def _resample_uniform(self, coords: list[tuple[float, float]], num_points: int) -> list[tuple[float, float]]:
        if num_points <= 0 or len(coords) < 2:
            return list(coords)
        cum = [0.0]
        total = 0.0
        for i in range(1, len(coords)):
            d = self._haversine_m(*coords[i - 1], *coords[i])
            total += d
            cum.append(total)
        if total <= 0:
            return [coords[0]] * num_points
        step = total / max(num_points - 1, 1)
        targets = [i * step for i in range(num_points)]
        res: list[tuple[float, float]] = []
        j = 0
        for t in targets:
            while j < len(cum) - 1 and cum[j + 1] < t:
                j += 1
            if j >= len(cum) - 1:
                res.append(coords[-1])
                continue
            seg = max(cum[j + 1] - cum[j], 1e-9)
            frac = (t - cum[j]) / seg
            lon = coords[j][0] + frac * (coords[j + 1][0] - coords[j][0])
            lat = coords[j][1] + frac * (coords[j + 1][1] - coords[j][1])
            res.append((lon, lat))
        return res

    def _load_or_build_loop_points(self) -> list[tuple[float, float]]:
        """Load loop points from outputs if present; otherwise build from holes.

        Uses bev_cart_18_holes_minutes to determine per-loop minutes when building.
        """
        prebuilt = Path("outputs") / "holes_path" / "holes_path_points.json"
        if prebuilt.exists():
            try:
                import json
                data = json.loads(prebuilt.read_text(encoding="utf-8"))
                coords = data.get("coordinates", [])
                pts = [(float(lon), float(lat)) for lon, lat in coords]
                if len(pts) >= 2:
                    logger.info("Loaded %d loop points from %s", len(pts), prebuilt)
                    return pts
            except Exception:
                pass

        minutes = int(self.bev_cart_18_holes_minutes)
        base = self._flatten_holes_linestrings()
        if len(base) < 2:
            logger.warning("Could not build holes path; falling back to clubhouse point only")
            return []
        pts = self._resample_uniform(base, max(2, minutes))
        logger.info("Built %d loop points from holes.geojson (%d min per loop)", len(pts), self.bev_cart_18_holes_minutes)
        return pts

    @staticmethod
    def _time_str_to_seconds(time_str: str) -> int:
        return seconds_since_7am(time_str)

    def log_activity(self, activity_type: str, description: str, location: Optional[str] = None) -> None:
        current_time_min = self.env.now / 60
        hours = int(current_time_min // 60) + 7
        minutes = int(current_time_min % 60)
        time_str = f"{hours:02d}:{minutes:02d}"
        self.activity_log.append(
            {
                "timestamp_s": self.env.now,
                "time_str": time_str,
                "activity_type": activity_type,
                "description": description,
                "cart_id": self.cart_id,
                "location": location,
            }
        )

    def beverage_cart_process(self):  # simpy process
        if self.env.now < self.service_start_s:
            wait_time = self.service_start_s - self.env.now
            self.log_activity("service_closed", f"Beverage cart waiting {wait_time/60:.0f} minutes until service starts")
            yield self.env.timeout(wait_time)
            self.log_activity("service_opened", "Beverage cart service started")

        try:
            loop_points = self._load_or_build_loop_points()

            import json
            from shapely.geometry import LineString, Point

            hole_lines: dict[int, LineString] = {}
            holes_file = Path(self.course_dir) / "geojson" / "holes.geojson"
            if holes_file.exists():
                holes_data = json.loads(holes_file.read_text(encoding="utf-8"))
                for feature in holes_data.get("features", []):
                    props = feature.get("properties", {})
                    raw_num = props.get("hole", props.get("ref"))
                    try:
                        hole_num = int(raw_num) if raw_num is not None else None
                    except (TypeError, ValueError):
                        hole_num = None
                    if hole_num and feature.get("geometry", {}).get("type") == "LineString":
                        coords = feature["geometry"]["coordinates"]
                        hole_lines[hole_num] = LineString(coords)

            import math
            timestamps = list(range(int(self.service_start_s), int(self.service_end_s) + 1, 60))

            club_lon, club_lat = self.clubhouse_coords or (0.0, 0.0)
            if timestamps:
                self.coordinates.append(
                    {
                        "latitude": float(club_lat),
                        "longitude": float(club_lon),
                        "timestamp": int(timestamps[0]),
                        "type": "bev_cart",
                        "current_hole": self.starting_hole,
                    }
                )

            if loop_points:
                points = loop_points
                num_points = len(points)
                minutes_per_loop = max(1, int(self.bev_cart_18_holes_minutes))
                rotated = list(reversed(points))

                hole_sequence = self._build_hole_sequence(minutes_per_loop)

                step_per_minute = num_points / float(minutes_per_loop)
                pos = num_points * 0.5 if self.starting_hole == 9 else 0.0
                for i, t in enumerate(timestamps[1:]):
                    idx0 = int(math.floor(pos)) % num_points
                    idx1 = (idx0 + 1) % num_points
                    frac = pos - math.floor(pos)
                    lon = rotated[idx0][0] + frac * (rotated[idx1][0] - rotated[idx0][0])
                    lat = rotated[idx0][1] + frac * (rotated[idx1][1] - rotated[idx0][1])

                    minutes_into_loop = i % minutes_per_loop
                    current_hole = hole_sequence[minutes_into_loop]

                    self.coordinates.append(
                        {
                            "latitude": float(lat),
                            "longitude": float(lon),
                            "timestamp": int(t),
                            "type": "bev_cart",
                            "current_hole": current_hole,
                        }
                    )
                    pos += step_per_minute

            self.log_activity(
                "coordinates_generated",
                f"Generated {len(self.coordinates)} GPS coordinates for beverage cart route using loop points",
            )
            logger.info("Generated %d beverage cart GPS coordinates (start %s, end %s)", len(self.coordinates), self.service_start_s, self.service_end_s)
        except Exception as e:  # noqa: BLE001
            self.log_activity("coordinates_error", f"Error generating beverage cart coordinates: {str(e)}")
            logger.error("Error generating beverage cart coordinates: %s", e)

        while self.env.now <= self.service_end_s:
            yield self.env.timeout(60)

        self.log_activity("service_closed", "Beverage cart service ended for the day")


