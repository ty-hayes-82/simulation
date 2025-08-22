from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import argparse
import json
import inspect


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
class SpeedSettings:
    """Unified speed configuration for all simulation timing."""
    runner_mps: float = 6.0
    time_quantum_s: int = 60
    golfer_total_minutes: int = 240

    def validate(self) -> None:
        if self.runner_mps <= 0:
            raise ValueError("runner_mps must be positive")
        if self.time_quantum_s <= 0:
            raise ValueError("time_quantum_s must be positive")
        if self.golfer_total_minutes <= 0:
            raise ValueError("golfer_total_minutes must be positive")


@dataclass
class NetworkParams:
    runner_speed_mps: float = 6.0
    broaden_paths: bool = False

    def validate(self) -> None:
        if self.runner_speed_mps <= 0:
            raise ValueError("runner_speed_mps must be positive")


@dataclass
class SimulationConfig:
    course_dir: str
    output_dir: Path
    course_name: str
    clubhouse: Tuple[float, float]
    num_runs: int
    log_level: str

    # Mode-specific params
    num_carts: int
    num_runners: int
    
    # Group scheduling
    groups_count: int
    tee_scenario: str

    service_hours: Optional[ServiceHours] = None
    bev_cart_hours: Optional[ServiceHours] = None
    network: NetworkParams = field(default_factory=NetworkParams)
    speeds: SpeedSettings = field(default_factory=SpeedSettings)
    # Extended config values (optional)
    # Minute-based configuration (preferred and required)
    golfer_18_holes_minutes: int = 240  # default 4.25h
    # Deprecated: fixed node pacing now; bev cart timing is derived from nodes per minute
    delivery_runner_speed_mps: float = 6.0
    delivery_prep_time_sec: int = 600
    bev_cart_avg_order_usd: float = 12.5
    delivery_avg_order_usd: float = 30.0
    bev_cart_order_probability_per_9_holes: float = 0.35
    delivery_total_orders: int = 10
    # New: orders that are not taken out for delivery within N minutes should fail
    minutes_for_delivery_order_failure: int = 60
    # Optional: defer initial order arrivals past service open to avoid unrealistic spikes
    delivery_opening_ramp_minutes: int = 0

    # From CLI args, not in JSON config usually
    first_tee: str = "09:00"
    groups_interval_min: float = 15.0
    sla_minutes: int = 30
    service_hours_duration: float = 10.0 # for metrics scaling
    random_seed: Optional[int] = None
    open_viewer: bool = False
    regenerate_travel_times: bool = False
    include_delivery_maps: bool = False
    no_heatmap: bool = False
    skip_executive_summary: bool = False


    @staticmethod
    def from_dict(data: Dict) -> "SimulationConfig":
        import inspect
        
        # Get the constructor parameters
        sig = inspect.signature(SimulationConfig)
        valid_keys = {p.name for p in sig.parameters.values()}
        
        # Filter the input data to only include valid keys
        filtered_data = {k: v for k, v in data.items() if k in valid_keys}
        
        # Special handling for clubhouse coordinates
        if "clubhouse" in data and isinstance(data["clubhouse"], dict):
            clubhouse_raw = data["clubhouse"]
            filtered_data["clubhouse"] = (clubhouse_raw["longitude"], clubhouse_raw["latitude"])  # (lon, lat)
        
        # Ensure all required arguments are present by providing defaults
        for p in sig.parameters.values():
            if p.default is p.empty and p.name not in filtered_data:
                # Provide a default value for missing required arguments
                if p.annotation == str:
                    filtered_data[p.name] = ""
                elif p.annotation == int:
                    filtered_data[p.name] = 0
                elif p.annotation == float:
                    filtered_data[p.name] = 0.0
                elif p.annotation == bool:
                    filtered_data[p.name] = False
                elif p.annotation == list:
                    filtered_data[p.name] = []
                elif p.annotation == dict:
                    filtered_data[p.name] = {}
                else:
                    filtered_data[p.name] = None
        
        return SimulationConfig(**filtered_data)

    @staticmethod
    def from_args(args: argparse.Namespace) -> "SimulationConfig":
        """Create a SimulationConfig from command-line arguments and course config file."""
        
        # Load the base config from the course directory
        course_config_path = Path(args.course_dir) / "config" / "simulation_config.json"
        if not course_config_path.exists():
            raise FileNotFoundError(f"simulation_config.json not found in {args.course_dir}")
        
        with open(course_config_path, "r") as f:
            data = json.load(f)

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

        # Extended defaults (mph config removed; use mps only)
        delivery_runner_speed_mps = float(data.get("delivery_runner_speed_mps", 6.0))

        # Parse minutes-only (hours fields are deprecated and unsupported)
        try:
            golfer_minutes = int(data.get("golfer_18_holes_minutes", 240))
        except Exception:
            golfer_minutes = 240
        # Deprecated: bev_cart_18_holes_minutes removed

        # New unified speed configuration with legacy key mapping
        speeds = SpeedSettings(
            runner_mps=float(data.get("speeds", {}).get("runner_mps", 
                                    data.get("delivery_runner_speed_mps", 6.0))),
            time_quantum_s=int(data.get("speeds", {}).get("time_quantum_s", 60)),
            golfer_total_minutes=int(data.get("speeds", {}).get("golfer_total_minutes", 
                                           data.get("golfer_18_holes_minutes", 240)))
        )
        speeds.validate()

        # Issue deprecation warnings for legacy keys
        import warnings
        if "delivery_runner_speed_mps" in data and "speeds" not in data:
            warnings.warn(
                "delivery_runner_speed_mps is deprecated. Use speeds.runner_mps instead.",
                DeprecationWarning,
                stacklevel=2
            )
        if "golfer_18_holes_minutes" in data and "speeds" not in data:
            warnings.warn(
                "golfer_18_holes_minutes is deprecated. Use speeds.golfer_total_minutes instead.",
                DeprecationWarning,
                stacklevel=2
            )

        # Determine output directory
        if args.output_dir:
            output_dir = Path(args.output_dir)
        else:
            from golfsim.utils import generate_standardized_output_name # circular import
            default_name = generate_standardized_output_name(
                mode="delivery-runner" if args.num_runners > 0 else "bev-with-golfers",
                num_bev_carts=args.num_carts,
                num_runners=args.num_runners,
                num_golfers=args.groups_count,
                tee_scenario=args.tee_scenario,
            )
            output_dir = Path("outputs") / default_name

        cfg = SimulationConfig(
            course_dir=args.course_dir,
            output_dir=output_dir,
            course_name=str(data.get("course_name", "Unknown Course")),
            clubhouse=clubhouse,
            num_runs=args.num_runs,
            log_level=args.log_level,
            num_carts=args.num_carts,
            num_runners=args.num_runners,
            groups_count=args.groups_count,
            tee_scenario=args.tee_scenario,
            service_hours=service_hours,
            bev_cart_hours=bev_cart_hours,
            network=network,
            speeds=speeds,
            golfer_18_holes_minutes=golfer_minutes,
            delivery_runner_speed_mps=delivery_runner_speed_mps,
            delivery_prep_time_sec=int(data.get("delivery_prep_time_sec", 600)),
            bev_cart_avg_order_usd=float(data.get("bev_cart_avg_order_usd", 12.5)),
            delivery_avg_order_usd=float(data.get("delivery_avg_order_usd", 30.0)),
            bev_cart_order_probability_per_9_holes=float(data.get("bev_cart_order_probability_per_9_holes", 0.35)),
            delivery_total_orders=int(data.get("delivery_total_orders", 10)),
            minutes_for_delivery_order_failure=int(data.get("minutes_for_delivery_order_failure", 60)),
            delivery_opening_ramp_minutes=int(data.get("delivery_opening_ramp_minutes", 0)),
            first_tee=getattr(args, "first_tee", "09:00"),
            groups_interval_min=getattr(args, "groups_interval_min", 15.0),
            sla_minutes=getattr(args, "sla_minutes", 30),
            service_hours_duration=getattr(args, "service_hours", 10.0),
            random_seed=getattr(args, "random_seed", None),
            open_viewer=getattr(args, "open_viewer", False),
            regenerate_travel_times=getattr(args, "regenerate_travel_times", False),
            include_delivery_maps=getattr(args, "include_delivery_maps", False),
            no_heatmap=getattr(args, "no_heatmap", False),
            skip_executive_summary=getattr(args, "skip_executive_summary", False),
        )

        # Override with CLI arguments where provided
        if hasattr(args, 'runner_speed') and args.runner_speed is not None:
            cfg.delivery_runner_speed_mps = float(args.runner_speed)
            cfg.speeds.runner_mps = float(args.runner_speed)  # Update unified config too
        if hasattr(args, 'runner_speed_mph') and args.runner_speed_mph is not None:
            speed_mps = float(args.runner_speed_mph) * 0.44704
            cfg.delivery_runner_speed_mps = speed_mps
            cfg.speeds.runner_mps = speed_mps  # Update unified config too
        if hasattr(args, 'golfer_total_minutes') and args.golfer_total_minutes is not None:
            cfg.speeds.golfer_total_minutes = int(args.golfer_total_minutes)
        if hasattr(args, 'prep_time') and args.prep_time is not None:
            cfg.delivery_prep_time_sec = int(args.prep_time) * 60
        if hasattr(args, 'revenue_per_order') and args.revenue_per_order is not None:
            cfg.delivery_avg_order_usd = float(args.revenue_per_order)
            
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


