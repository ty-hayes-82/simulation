"""
Golfer-beverage cart visibility tracking service.

This module provides functionality to track when golfers last saw a beverage cart
and apply time-based color coding to GPS points based on time-since-last-sighting.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum

from golfsim.logging import get_logger

logger = get_logger(__name__)


class VisibilityStatus(Enum):
    """Color codes for golfer visibility status."""
    GREEN = "green"      # Recently saw beverage cart (< 20 min)
    YELLOW = "yellow"    # Moderate time since last sighting (20-40 min)
    ORANGE = "orange"    # Long time since last sighting (40-60 min)
    RED = "red"          # Very long time since last sighting (> 60 min)


@dataclass
class VisibilityThresholds:
    """Configurable thresholds for visibility status transitions."""
    proximity_threshold_m: float = 100.0      # Distance for considering "seeing" cart
    green_to_yellow_min: float = 20.0         # Green → Yellow transition
    yellow_to_orange_min: float = 40.0        # Yellow → Orange transition
    orange_to_red_min: float = 60.0           # Orange → Red transition
    red_pulsing_enabled: bool = True          # Enable pulsing/glow for red status


@dataclass
class VisibilityEvent:
    """Record of a golfer seeing a beverage cart."""
    timestamp_s: int
    golfer_id: str
    cart_id: str
    distance_m: float
    golfer_position: Tuple[float, float]  # (lat, lon)
    cart_position: Tuple[float, float]    # (lat, lon)
    hole_num: Optional[int] = None


@dataclass
class GolferVisibilityTracker:
    """Tracks visibility history for a single golfer."""
    golfer_id: str
    last_sighting_timestamp_s: Optional[int] = None
    last_sighting_cart_id: Optional[str] = None
    visibility_events: List[VisibilityEvent] = field(default_factory=list)
    
    def get_visibility_status(self, current_timestamp_s: int, thresholds: VisibilityThresholds) -> VisibilityStatus:
        """Determine the current visibility status based on time since last sighting."""
        if self.last_sighting_timestamp_s is None:
            # Never seen a cart - start with red
            return VisibilityStatus.RED
        
        time_since_sighting_min = (current_timestamp_s - self.last_sighting_timestamp_s) / 60.0
        
        # If the last sighting was in the future (cart seen before golfer started), 
        # treat as if just seen (green status)
        if time_since_sighting_min < 0:
            return VisibilityStatus.GREEN
        
        if time_since_sighting_min < thresholds.green_to_yellow_min:
            return VisibilityStatus.GREEN
        elif time_since_sighting_min < thresholds.yellow_to_orange_min:
            return VisibilityStatus.YELLOW
        elif time_since_sighting_min < thresholds.orange_to_red_min:
            return VisibilityStatus.ORANGE
        else:
            return VisibilityStatus.RED
    
    def record_sighting(self, event: VisibilityEvent) -> None:
        """Record a new sighting event."""
        self.last_sighting_timestamp_s = event.timestamp_s
        self.last_sighting_cart_id = event.cart_id
        self.visibility_events.append(event)
        
        logger.debug(
            "Golfer %s saw cart %s at %s (distance: %.1fm)",
            self.golfer_id, event.cart_id, event.timestamp_s, event.distance_m
        )


class VisibilityTrackingService:
    """Service for tracking golfer-beverage cart visibility across entire simulation."""
    
    def __init__(self, thresholds: Optional[VisibilityThresholds] = None):
        self.thresholds = thresholds or VisibilityThresholds()
        self.golfer_trackers: Dict[str, GolferVisibilityTracker] = {}
        self.all_visibility_events: List[VisibilityEvent] = []
        
    def _haversine_distance_m(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate the great circle distance between two points in meters."""
        R = 6371000.0  # Earth's radius in meters
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return R * c
    
    def get_or_create_tracker(self, golfer_id: str) -> GolferVisibilityTracker:
        """Get or create a visibility tracker for a golfer."""
        if golfer_id not in self.golfer_trackers:
            self.golfer_trackers[golfer_id] = GolferVisibilityTracker(golfer_id=golfer_id)
        return self.golfer_trackers[golfer_id]
    
    def process_coordinates_batch(
        self,
        golfer_points: List[Dict[str, Any]],
        cart_points: List[Dict[str, Any]]
    ) -> None:
        """Process a batch of coordinates to detect visibility events."""
        # Create timestamp-indexed lookups for cart points
        cart_by_time_and_id: Dict[int, Dict[str, Dict]] = {}
        cart_timestamps = set()
        
        for point in cart_points:
            timestamp = int(point.get("timestamp", 0))
            cart_id = point.get("id", "unknown_cart")
            cart_timestamps.add(timestamp)
            
            if timestamp not in cart_by_time_and_id:
                cart_by_time_and_id[timestamp] = {}
            cart_by_time_and_id[timestamp][cart_id] = point
        
        # Sort cart timestamps for efficient nearest-neighbor search
        sorted_cart_timestamps = sorted(cart_timestamps)
        
        # Find the earliest golfer timestamp to establish round start
        golfer_start_times = {}
        for golfer_point in golfer_points:
            golfer_id = golfer_point.get("id", "unknown_golfer")
            timestamp = int(golfer_point.get("timestamp", 0))
            if golfer_id not in golfer_start_times:
                golfer_start_times[golfer_id] = timestamp
            else:
                golfer_start_times[golfer_id] = min(golfer_start_times[golfer_id], timestamp)
        
        # Process each golfer point
        for golfer_point in golfer_points:
            golfer_timestamp = int(golfer_point.get("timestamp", 0))
            golfer_id = golfer_point.get("id", "unknown_golfer")
            golfer_lat = float(golfer_point.get("latitude", 0.0))
            golfer_lon = float(golfer_point.get("longitude", 0.0))
            hole_num = golfer_point.get("hole")
            
            # Find the nearest cart timestamp (within 5 minutes)
            nearest_cart_timestamp = self._find_nearest_timestamp(
                golfer_timestamp, sorted_cart_timestamps, max_diff_s=300
            )
            
            if nearest_cart_timestamp is not None and nearest_cart_timestamp in cart_by_time_and_id:
                for cart_id, cart_point in cart_by_time_and_id[nearest_cart_timestamp].items():
                    cart_lat = float(cart_point.get("latitude", 0.0))
                    cart_lon = float(cart_point.get("longitude", 0.0))
                    
                    distance_m = self._haversine_distance_m(
                        golfer_lat, golfer_lon, cart_lat, cart_lon
                    )
                    
                    if distance_m <= self.thresholds.proximity_threshold_m:
                        # Only record sightings that happen during or after the golfer's round
                        golfer_start_time = golfer_start_times.get(golfer_id, golfer_timestamp)
                        if nearest_cart_timestamp >= golfer_start_time:
                            # Record visibility event (use golfer timestamp for consistency)
                            event = VisibilityEvent(
                                timestamp_s=golfer_timestamp,
                                golfer_id=golfer_id,
                                cart_id=cart_id,
                                distance_m=distance_m,
                                golfer_position=(golfer_lat, golfer_lon),
                                cart_position=(cart_lat, cart_lon),
                                hole_num=hole_num
                            )
                            
                            tracker = self.get_or_create_tracker(golfer_id)
                            tracker.record_sighting(event)
                            self.all_visibility_events.append(event)
    
    def _find_nearest_timestamp(
        self, 
        target_timestamp: int, 
        sorted_timestamps: List[int], 
        max_diff_s: int = 300
    ) -> Optional[int]:
        """Find the nearest timestamp within max_diff_s seconds."""
        if not sorted_timestamps:
            return None
        
        # Binary search for the closest timestamp
        left, right = 0, len(sorted_timestamps) - 1
        best_timestamp = None
        min_diff = float('inf')
        
        while left <= right:
            mid = (left + right) // 2
            timestamp = sorted_timestamps[mid]
            diff = abs(timestamp - target_timestamp)
            
            if diff < min_diff:
                min_diff = diff
                best_timestamp = timestamp
            
            if timestamp < target_timestamp:
                left = mid + 1
            else:
                right = mid - 1
        
        # Return the best timestamp if within the allowed difference
        if min_diff <= max_diff_s:
            return best_timestamp
        return None
    
    def annotate_golfer_points_with_visibility(
        self,
        golfer_points: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Add visibility status fields to golfer GPS points."""
        annotated_points = []
        
        for point in golfer_points:
            # Copy original point
            annotated_point = dict(point)
            
            golfer_id = point.get("id", "unknown_golfer")
            timestamp = int(point.get("timestamp", 0))
            
            tracker = self.get_or_create_tracker(golfer_id)
            status = tracker.get_visibility_status(timestamp, self.thresholds)
            
            # Add visibility fields
            annotated_point.update({
                "visibility_status": status.value,
                "visibility_color": status.value,
                "time_since_last_sighting_min": self._calculate_time_since_last_sighting(tracker, timestamp),
                "pulsing": (status == VisibilityStatus.RED and self.thresholds.red_pulsing_enabled)
            })
            
            annotated_points.append(annotated_point)
        
        return annotated_points
    
    def _calculate_time_since_last_sighting(
        self,
        tracker: GolferVisibilityTracker,
        current_timestamp_s: int
    ) -> Optional[float]:
        """Calculate minutes since last sighting, or None if never saw cart during their round."""
        if tracker.last_sighting_timestamp_s is None:
            return None
        
        time_diff_min = (current_timestamp_s - tracker.last_sighting_timestamp_s) / 60.0
        
        # If the sighting was in the past (negative means cart was seen before golfer started),
        # return None to indicate no valid sightings during this golfer's round
        if time_diff_min < 0:
            return None
            
        return time_diff_min
    
    def get_visibility_summary(self) -> Dict[str, Any]:
        """Get a summary of visibility tracking results."""
        summary = {
            "total_golfers": len(self.golfer_trackers),
            "total_visibility_events": len(self.all_visibility_events),
            "thresholds": {
                "proximity_threshold_m": self.thresholds.proximity_threshold_m,
                "green_to_yellow_min": self.thresholds.green_to_yellow_min,
                "yellow_to_orange_min": self.thresholds.yellow_to_orange_min,
                "orange_to_red_min": self.thresholds.orange_to_red_min,
                "red_pulsing_enabled": self.thresholds.red_pulsing_enabled,
            },
            "golfer_stats": {}
        }
        
        for golfer_id, tracker in self.golfer_trackers.items():
            summary["golfer_stats"][golfer_id] = {
                "total_sightings": len(tracker.visibility_events),
                "last_sighting_timestamp_s": tracker.last_sighting_timestamp_s,
                "last_cart_seen": tracker.last_sighting_cart_id,
            }
        
        return summary


def create_visibility_service(
    proximity_threshold_m: float = 100.0,
    green_to_yellow_min: float = 20.0,
    yellow_to_orange_min: float = 40.0,
    orange_to_red_min: float = 60.0,
    red_pulsing_enabled: bool = True
) -> VisibilityTrackingService:
    """Factory function to create a visibility tracking service with custom thresholds."""
    thresholds = VisibilityThresholds(
        proximity_threshold_m=proximity_threshold_m,
        green_to_yellow_min=green_to_yellow_min,
        yellow_to_orange_min=yellow_to_orange_min,
        orange_to_red_min=orange_to_red_min,
        red_pulsing_enabled=red_pulsing_enabled
    )
    return VisibilityTrackingService(thresholds)
