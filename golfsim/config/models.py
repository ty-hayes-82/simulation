from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class ServiceHours:
    start_hour: int
    end_hour: int

    def validate(self) -> None:
        if not (0 <= self.start_hour <= 23 and 0 <= self.end_hour <= 24):
            raise ValueError("ServiceHours must be within 0..24h range")
        if self.end_hour <= self.start_hour:
            raise ValueError("ServiceHours.end_hour must be after start_hour")


@dataclass
class NetworkParams:
    runner_speed_mps: float = 6.0
    broaden_paths: bool = False

    def validate(self) -> None:
        if self.runner_speed_mps <= 0:
            raise ValueError("runner_speed_mps must be positive")


@dataclass
class SimulationConfig:
    course_name: str
    clubhouse: Tuple[float, float]
    service_hours: Optional[ServiceHours] = None
    bev_cart_hours: Optional[ServiceHours] = None
    network: NetworkParams = field(default_factory=NetworkParams)
    # Extended config values (optional)
    # Minute-based configuration (preferred and required)
    golfer_18_holes_minutes: int = 240  # default 4.25h
    bev_cart_18_holes_minutes: int = 180  # default 3.0h
    delivery_runner_speed_mps: float = 6.0
    delivery_prep_time_sec: int = 600
    bev_cart_avg_order_usd: float = 12.5
    delivery_avg_order_usd: float = 30.0
    bev_cart_order_probability: float = 0.4
    delivery_order_probability_per_9_holes: float = 0.2

    @staticmethod
    def from_dict(data: Dict) -> "SimulationConfig":
        try:
            clubhouse_raw = data["clubhouse"]
            clubhouse = (clubhouse_raw["longitude"], clubhouse_raw["latitude"])  # (lon, lat)
        except Exception as exc:
            raise ValueError("Invalid or missing 'clubhouse' in simulation config") from exc

        service_hours: Optional[ServiceHours] = None
        # Support legacy 'service_hours' {start, end}
        if isinstance(data.get("service_hours"), dict):
            sh = data["service_hours"]
            service_hours = ServiceHours(start_hour=int(sh["start"]), end_hour=int(sh["end"]))
            service_hours.validate()
        # Map delivery_service_hours {open_time, close_time} → ServiceHours
        elif isinstance(data.get("delivery_service_hours"), dict):
            dsh = data["delivery_service_hours"]
            def _parse_hour(hhmm: str) -> int:
                try:
                    return int(str(hhmm).split(":")[0])
                except Exception:
                    return 7
            service_hours = ServiceHours(start_hour=_parse_hour(dsh.get("open_time", "07:00")), end_hour=_parse_hour(dsh.get("close_time", "18:00")))
            service_hours.validate()

        # Beverage cart service hours
        bev_cart_hours: Optional[ServiceHours] = None
        if isinstance(data.get("bev_cart_service_hours"), dict):
            bch = data["bev_cart_service_hours"]
            def _parse_hour2(hhmm: str) -> int:
                try:
                    return int(str(hhmm).split(":")[0])
                except Exception:
                    return 9
            bev_cart_hours = ServiceHours(start_hour=_parse_hour2(bch.get("start_time", "09:00")), end_hour=_parse_hour2(bch.get("end_time", "17:00")))
            bev_cart_hours.validate()

        # Backward compatibility for network params
        network = NetworkParams(
            runner_speed_mps=float(data.get("runner_speed_mps", 6.0)),
            broaden_paths=bool(data.get("broaden_paths", False)),
        )
        network.validate()

        # Extended defaults
        mph = float(data.get("delivery_runner_speed_mph", 6.0))
        delivery_runner_speed_mps = float(data.get("delivery_runner_speed_mps", mph * 0.44704))

        # Parse minutes-only (hours fields are deprecated and unsupported)
        try:
            golfer_minutes = int(data.get("golfer_18_holes_minutes", 240))
        except Exception:
            golfer_minutes = 240
        try:
            bev_minutes = int(data.get("bev_cart_18_holes_minutes", 180))
        except Exception:
            bev_minutes = 180

        cfg = SimulationConfig(
            course_name=str(data.get("course_name", "Unknown Course")),
            clubhouse=clubhouse,
            service_hours=service_hours,
            bev_cart_hours=bev_cart_hours,
            network=network,
            golfer_18_holes_minutes=golfer_minutes,
            bev_cart_18_holes_minutes=bev_minutes,
            delivery_runner_speed_mps=delivery_runner_speed_mps,
            delivery_prep_time_sec=int(data.get("delivery_prep_time_sec", 600)),
            bev_cart_avg_order_usd=float(data.get("bev_cart_avg_order_usd", 12.5)),
            delivery_avg_order_usd=float(data.get("delivery_avg_order_usd", 30.0)),
            bev_cart_order_probability=float(data.get("bev_cart_order_probability", 0.4)),
            delivery_order_probability_per_9_holes=float(data.get("delivery_order_probability_per_9_holes", 0.2)),
        )
        return cfg


@dataclass
class TeeTimesConfig:
    scenarios: Dict[str, Dict]

    @staticmethod
    def from_dict(data: Dict) -> "TeeTimesConfig":
        # Handle both old format (scenarios directly at root) and new format (under "scenarios" key)
        if "scenarios" in data:
            scenarios = data["scenarios"]
        else:
            scenarios = data
        
        if not isinstance(scenarios, dict) or not scenarios:
            raise ValueError("Tee times config is empty or invalid")
        return TeeTimesConfig(scenarios=scenarios)


