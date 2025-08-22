from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import simpy

from ..config.loaders import load_simulation_config
from ..logging import get_logger
from ..io.results import SimulationResult
from .. import utils
from .order_generation import simulate_golfer_orders
from .delivery_service_base import BaseDeliveryService, DeliveryOrder
from .single_runner_service import SingleRunnerDeliveryService
from .multi_runner_service import MultiRunnerDeliveryService
from .beverage_cart_service import BeverageCartService


logger = get_logger(__name__)


def run_multi_golfer_simulation(
    course_dir: str,
    groups: List[Dict[str, Any]],
    order_probability_per_9_holes: float = 0.3,
    prep_time_min: int = 10,
    runner_speed_mps: float = 6.0,
    env: Optional[simpy.Environment] = None,
    output_dir: Optional[str] = None,
    create_visualization: bool = True,
    rng_seed: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Run a simple multi-golfer simulation using a single runner queue.

    Parameters
    ----------
    course_dir: str
        Path to course directory with config files.
    groups: list of dict
        Each group: {"group_id": int, "tee_time_s": int, "num_golfers": int}
    order_probability_per_9_holes: float
        Probability (0..1) of an order per golfer per 9 holes.
    prep_time_min: int
        Food preparation time per order in minutes.
    runner_speed_mps: float
        Runner speed in meters per second.
    env: simpy.Environment | None
        Optional external environment for composition/testing.
    output_dir: str | None
        Directory to save visualization PNG. If None, no visualization created.
    create_visualization: bool
        Whether to create delivery visualization PNG map.

    Returns
    -------
    dict
        Summary including orders, activity log, and delivery stats.
    """
    simulation_env = env or simpy.Environment()

    service = SingleRunnerDeliveryService(
        env=simulation_env,
        course_dir=course_dir,
        runner_speed_mps=runner_speed_mps,
        prep_time_min=prep_time_min,
    )

    # Generate synthetic orders based on groups and probabilities
    orders = simulate_golfer_orders(groups, order_probability_per_9_holes, rng_seed=rng_seed)

    def order_arrival_process():  # simpy process
        last_time = simulation_env.now
        for order in orders:
            target_time = max(order.order_time_s, service.service_open_s)
            if target_time > last_time:
                yield simulation_env.timeout(target_time - last_time)
            service.place_order(order)
            last_time = target_time

    simulation_env.process(order_arrival_process())

    # Run until close of service or until queue drains after closing
    run_until = max(service.service_close_s + 1, max((o.order_time_s for o in orders), default=0) + 4 * 3600)
    simulation_env.run(until=run_until)

    # Summarize results
    results: Dict[str, Any] = {
        "success": True,
        "simulation_type": "multi_golfer_single_runner",
        "orders": [
            {
                "order_id": o.order_id,
                "golfer_group_id": o.golfer_group_id,
                "golfer_id": o.golfer_id,
                "hole_num": o.hole_num,
                "order_time_s": o.order_time_s,
                "status": o.status,
                "total_completion_time_s": o.total_completion_time_s,
            }
            for o in orders
        ],
        "delivery_stats": service.delivery_stats,
        "failed_orders": [
            {
                "order_id": o.order_id,
                "reason": o.failure_reason,
            }
            for o in service.failed_orders
        ],
        "activity_log": service.activity_log,
        "metadata": {
            "prep_time_min": prep_time_min,
            "runner_speed_mps": runner_speed_mps,
            "num_groups": len(groups),
            "course_dir": str(course_dir),
        },
    }

    # Compute simple aggregates
    if service.delivery_stats:
        total_order_time = sum(d.get("total_completion_time_s", 0.0) for d in service.delivery_stats)
        avg_order_time = total_order_time / max(len(service.delivery_stats), 1)
        total_distance = sum(d.get("delivery_distance_m", 0.0) for d in service.delivery_stats)
        avg_distance = total_distance / max(len(service.delivery_stats), 1)
        results["aggregate_metrics"] = {
            "average_order_time_s": avg_order_time,
            "total_delivery_distance_m": total_distance,
            "average_delivery_distance_m": avg_distance,
            "orders_processed": len(service.delivery_stats),
            "orders_failed": len(service.failed_orders),
        }
    else:
        results["aggregate_metrics"] = {
            "average_order_time_s": 0.0,
            "total_delivery_distance_m": 0.0,
            "average_delivery_distance_m": 0.0,
            "orders_processed": 0,
            "orders_failed": len(service.failed_orders),
        }

    # Create visualization if requested and we have orders
    if create_visualization and output_dir and results["orders"]:
        try:
            from ..viz.matplotlib_viz import render_delivery_plot, render_individual_delivery_plots
            from ..viz.matplotlib_viz import load_course_geospatial_data
            import networkx as nx
            
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            
            # Load course data for visualization
            sim_cfg = load_simulation_config(course_dir)
            clubhouse_coords = sim_cfg.clubhouse
            course_data = load_course_geospatial_data(course_dir)
            
            # Try to load cart graph
            cart_graph = None
            cart_graph_path = Path(course_dir) / "pkl" / "cart_graph.pkl"
            if cart_graph_path.exists():
                import pickle
                with open(cart_graph_path, "rb") as f:
                    cart_graph = pickle.load(f)
            
            # Create main visualization (all orders together)
            viz_path = output_path / "delivery_orders_map.png"
            render_delivery_plot(
                results=results,
                course_data=course_data,
                clubhouse_coords=clubhouse_coords,
                cart_graph=cart_graph,
                save_path=viz_path,
                style="detailed"
            )
            
            logger.info("Created delivery visualization: %s", viz_path)
            results["visualization_path"] = str(viz_path)
            
            # Create individual delivery visualizations unless disabled
            if not bool(getattr(results, "no_individual_plots", False)):
                individual_paths = render_individual_delivery_plots(
                    results=results,
                    course_data=course_data,
                    clubhouse_coords=clubhouse_coords,
                    cart_graph=cart_graph,
                    output_dir=output_path,
                    filename_prefix="delivery_order",
                    style="detailed"
                )
                
                if individual_paths:
                    logger.info("Created %d individual delivery visualizations", len(individual_paths))
                    results["individual_visualization_paths"] = [str(p) for p in individual_paths]
            
        except Exception as e:
            logger.warning("Failed to create visualization: %s", e)
            results["visualization_error"] = str(e)

    return results