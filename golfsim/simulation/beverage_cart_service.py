from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import simpy

from ..config.loaders import load_simulation_config
from ..logging import get_logger
from .. import utils


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

    clubhouse_coords: Optional[Tuple[float, float]] = None
    service_start_s: int = 0
    service_end_s: int = 0

    def __post_init__(self) -> None:
        self._load_course_config()
        if self.track_coordinates:
            self.env.process(self.beverage_cart_process())

    def _load_course_config(self) -> None:
        sim_cfg = load_simulation_config(self.course_dir)
        self.clubhouse_coords = sim_cfg.clubhouse
        # Service hours for beverage cart (prefer config, else defaults)
        if getattr(sim_cfg, "bev_cart_hours", None) is not None:
            start_time = f"{int(sim_cfg.bev_cart_hours.start_hour):02d}:00"
            end_time = f"{int(sim_cfg.bev_cart_hours.end_hour):02d}:00"
        else:
            start_time = "09:00"
            end_time = "17:00"
        self.service_start_s = utils.time_str_to_seconds(start_time)
        self.service_end_s = utils.time_str_to_seconds(end_time)
        logger.info(
            "Beverage cart service hours: %s - %s (%.1fh - %.1fh)",
            start_time,
            end_time,
            self.service_start_s / 3600,
            self.service_end_s / 3600,
        )



    def _resample_uniform(self, coords: List[Tuple[float, float]], num_points: int) -> List[Tuple[float, float]]:
        if num_points <= 0 or len(coords) < 2:
            return list(coords)
        # cumulative distances
        cum = [0.0]
        total = 0.0
        for i in range(1, len(coords)):
            d = utils.haversine_m(*coords[i - 1], *coords[i])
            total += d
            cum.append(total)
        if total <= 0:
            return [coords[0]] * num_points
        step = total / max(num_points - 1, 1)
        targets = [i * step for i in range(num_points)]
        res: List[Tuple[float, float]] = []
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

    def _generate_coordinates(self) -> None:
        """Generate coordinates using simple node-per-minute logic."""
        # Load golfer nodes and reverse for bev cart
        loop_points, loop_holes = self._load_or_build_loop_points()
        if not loop_points:
            return
            
        # Reverse for bev cart (18→1 direction)
        bev_points = list(reversed(loop_points))
        bev_holes = list(reversed(loop_holes)) if loop_holes else None
        
        # Generate one point per minute from service start to end
        current_time_s = self.service_start_s
        point_index = 0
        
        while current_time_s <= self.service_end_s:
            node_idx = point_index % len(bev_points)
            lon, lat = bev_points[node_idx]
            
            # Get hole number if available
            current_hole = None
            if bev_holes and node_idx < len(bev_holes):
                current_hole = bev_holes[node_idx]
            
            self.coordinates.append({
                "latitude": float(lat),
                "longitude": float(lon), 
                "timestamp": int(current_time_s),
                "type": "bev_cart",
                "current_hole": current_hole,
                "cart_id": self.cart_id,
            })
            
            current_time_s += 60  # One minute per node
            point_index += 1

    def _load_or_build_loop_points(self) -> Tuple[List[Tuple[float, float]], List[Optional[int]]]:
        """Load per-minute loop points and hole labels from holes_connected.geojson."""
        coords, holes = utils.load_connected_points(self.course_dir)
        if coords:
            logger.info("Loaded %d loop points from holes_connected.geojson", len(coords))
            return coords, holes
        logger.warning("holes_connected.geojson missing or empty; no loop points loaded")
        return [], []

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
        # Wait until service starts
        if self.env.now < self.service_start_s:
            wait_time = self.service_start_s - self.env.now
            self.log_activity("service_closed", f"Beverage cart waiting {wait_time/60:.0f} minutes until service starts")
            yield self.env.timeout(wait_time)
            self.log_activity("service_opened", "Beverage cart service started")

        # Generate coordinates using simple node-per-minute traversal
        try:
            self._generate_coordinates()
            self.log_activity(
                "coordinates_generated",
                f"Generated {len(self.coordinates)} GPS coordinates for beverage cart route",
            )
            logger.info("Generated %d beverage cart GPS coordinates", len(self.coordinates))
        except Exception as e:  # noqa: BLE001
            self.log_activity("coordinates_error", f"Error generating beverage cart coordinates: {str(e)}")
            logger.error("Error generating beverage cart coordinates: %s", e)

        # Continue running until service ends
        while self.env.now <= self.service_end_s:
            yield self.env.timeout(60)

        self.log_activity("service_closed", "Beverage cart service ended for the day")