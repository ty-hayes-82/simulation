"""
Performance logging infrastructure for identifying simulation bottlenecks.

This module provides decorators and context managers to track time spent in 
different operations and report percentage breakdowns of execution time.
"""

from __future__ import annotations

import time
import functools
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from contextlib import contextmanager

from .logging import get_logger

logger = get_logger(__name__)


@dataclass
class OperationTimer:
    """Tracks timing for a specific operation type."""
    name: str
    total_time: float = 0.0
    call_count: int = 0
    start_time: Optional[float] = None
    
    def start(self) -> None:
        """Start timing this operation."""
        if self.start_time is not None:
            logger.warning("Timer %s already started, resetting", self.name)
        self.start_time = time.perf_counter()
    
    def stop(self) -> float:
        """Stop timing and return elapsed time."""
        if self.start_time is None:
            logger.warning("Timer %s not started", self.name)
            return 0.0
        
        elapsed = time.perf_counter() - self.start_time
        self.total_time += elapsed
        self.call_count += 1
        self.start_time = None
        return elapsed
    
    @property
    def average_time(self) -> float:
        """Average time per operation."""
        return self.total_time / max(self.call_count, 1)


@dataclass
class PerformanceTracker:
    """Global performance tracking for simulation operations."""
    timers: Dict[str, OperationTimer] = field(default_factory=dict)
    session_start: float = field(default_factory=time.perf_counter)
    
    def get_timer(self, name: str) -> OperationTimer:
        """Get or create a timer for the given operation."""
        if name not in self.timers:
            self.timers[name] = OperationTimer(name)
        return self.timers[name]
    
    def start_timer(self, name: str) -> None:
        """Start timing an operation."""
        self.get_timer(name).start()
    
    def stop_timer(self, name: str) -> float:
        """Stop timing an operation and return elapsed time."""
        return self.get_timer(name).stop()
    
    @contextmanager
    def time_operation(self, name: str):
        """Context manager for timing operations."""
        self.start_timer(name)
        try:
            yield
        finally:
            elapsed = self.stop_timer(name)
            logger.debug("Operation '%s' took %.3f seconds", name, elapsed)
    
    def reset(self) -> None:
        """Reset all timers."""
        self.timers.clear()
        self.session_start = time.perf_counter()
    
    def get_total_tracked_time(self) -> float:
        """Get total time across all tracked operations."""
        return sum(timer.total_time for timer in self.timers.values())
    
    def get_session_time(self) -> float:
        """Get total session time since reset."""
        return time.perf_counter() - self.session_start
    
    def log_summary(self, title: str = "Performance Summary") -> None:
        """Log a detailed performance summary."""
        if not self.timers:
            logger.info("%s: No operations tracked", title)
            return
        
        total_tracked = self.get_total_tracked_time()
        session_time = self.get_session_time()
        
        logger.info("=" * 60)
        logger.info("%s", title)
        logger.info("=" * 60)
        logger.info("Session time: %.2f seconds", session_time)
        logger.info("Tracked time: %.2f seconds (%.1f%% of session)", 
                   total_tracked, (total_tracked / max(session_time, 0.001)) * 100)
        logger.info("-" * 60)
        
        # Sort by total time descending
        sorted_timers = sorted(self.timers.values(), key=lambda t: t.total_time, reverse=True)
        
        for timer in sorted_timers:
            percentage = (timer.total_time / max(total_tracked, 0.001)) * 100
            avg_time = timer.average_time
            
            logger.info("%-30s: %7.2fs (%5.1f%%) | %3d calls | %6.3fs avg", 
                       timer.name, timer.total_time, percentage, timer.call_count, avg_time)
        
        logger.info("=" * 60)
    
    def get_summary_dict(self) -> Dict[str, Any]:
        """Get performance summary as a dictionary."""
        total_tracked = self.get_total_tracked_time()
        session_time = self.get_session_time()
        
        summary = {
            "session_time_s": session_time,
            "tracked_time_s": total_tracked,
            "tracked_percentage": (total_tracked / max(session_time, 0.001)) * 100,
            "operations": []
        }
        
        # Sort by total time descending
        sorted_timers = sorted(self.timers.values(), key=lambda t: t.total_time, reverse=True)
        
        for timer in sorted_timers:
            percentage = (timer.total_time / max(total_tracked, 0.001)) * 100
            summary["operations"].append({
                "name": timer.name,
                "total_time_s": timer.total_time,
                "percentage": percentage,
                "call_count": timer.call_count,
                "average_time_s": timer.average_time
            })
        
        return summary


# Global performance tracker instance
_global_tracker = PerformanceTracker()


def get_performance_tracker() -> PerformanceTracker:
    """Get the global performance tracker instance."""
    return _global_tracker


def reset_performance_tracking() -> None:
    """Reset global performance tracking."""
    _global_tracker.reset()


def log_performance_summary(title: str = "Performance Summary") -> None:
    """Log performance summary using global tracker."""
    _global_tracker.log_summary(title)


def time_operation(name: str):
    """Decorator to time function calls."""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            with _global_tracker.time_operation(f"{func.__module__}.{func.__name__}_{name}"):
                return func(*args, **kwargs)
        return wrapper
    return decorator


def time_function(func: Callable) -> Callable:
    """Decorator to time function calls using the function name."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        operation_name = f"{func.__module__}.{func.__name__}"
        with _global_tracker.time_operation(operation_name):
            return func(*args, **kwargs)
    return wrapper


# Context manager for the global tracker
@contextmanager
def timed_operation(name: str):
    """Context manager for timing operations using global tracker."""
    with _global_tracker.time_operation(name):
        yield


# Convenience functions for common operation categories
@contextmanager
def timed_file_io(operation: str, filename: str = ""):
    """Time file I/O operations."""
    name = f"file_io_{operation}"
    if filename:
        name += f"_{filename}"
    with timed_operation(name):
        yield


@contextmanager
def timed_visualization(viz_type: str):
    """Time visualization operations."""
    with timed_operation(f"visualization_{viz_type}"):
        yield


@contextmanager
def timed_computation(comp_type: str):
    """Time computation operations."""
    with timed_operation(f"computation_{comp_type}"):
        yield


@contextmanager
def timed_simulation(phase: str):
    """Time simulation phases."""
    with timed_operation(f"simulation_{phase}"):
        yield
