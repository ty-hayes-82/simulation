#!/usr/bin/env python3
"""
Comprehensive Simulation Matrix Runner

Runs all combinations of:
- Tee scenario: typical_weekday
- Orders: 20, 30  
- Runners: 1, 2
- Blocking: none, 0-3, 0-6

Total combinations: 1 scenario × 2 order counts × 2 runner counts × 3 blocking variants = 12 simulations

Each simulation generates:
- Coordinates CSV files for visualization
- Delivery metrics and performance data
- Heatmaps and executive summaries
- Event logs for replay analysis
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from golfsim.logging import init_logging, get_logger
 

logger = get_logger(__name__)


def backup_and_modify_config(course_dir: str, delivery_orders: int) -> Path:
    """Backup simulation config and modify delivery_total_orders."""
    config_path = Path(course_dir) / "config" / "simulation_config.json"
    backup_path = config_path.with_suffix(f".backup_{int(time.time())}.json")
    
    # Create backup
    shutil.copy2(config_path, backup_path)
    logger.info("Backed up config to: %s", backup_path)
    
    # Modify delivery orders
    with config_path.open("r", encoding="utf-8") as f:
        config = json.load(f)
    
    config["delivery_total_orders"] = delivery_orders
    
    with config_path.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    
    logger.info("Updated delivery_total_orders to: %d", delivery_orders)
    return backup_path


def restore_config(course_dir: str, backup_path: Path) -> None:
    """Restore original simulation config from backup."""
    config_path = Path(course_dir) / "config" / "simulation_config.json"
    shutil.copy2(backup_path, config_path)
    backup_path.unlink()
    logger.info("Restored original config and cleaned up backup")


def run_delivery_simulation_with_blocking(
    course_dir: str,
    num_runners: int,
    delivery_orders: int,
    blocking_variant: str,
    output_dir: Path,
    num_runs: int = 3,
    random_seed: Optional[int] = None,
) -> bool:
    """Run delivery runner simulation with specified blocking configuration.
    
    Args:
        course_dir: Course directory path
        num_runners: Number of delivery runners (1 or 2)
        delivery_orders: Total delivery orders (20 or 30)
        blocking_variant: 'none', '0-3', or '0-6'
        output_dir: Output directory for results
        num_runs: Number of simulation runs
        random_seed: Optional random seed for reproducibility
        
    Returns:
        True if simulation completed successfully, False otherwise
    """
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Prepare arguments for unified simulation
        cmd_args = [
            sys.executable,
            "-m", "scripts.sim.run_unified_simulation",
            "--mode", "delivery-runner",
            "--course-dir", str(course_dir),
            "--num-runs", str(num_runs),
            "--output-dir", str(output_dir),
            "--tee-scenario", "typical_weekday",
            "--num-runners", str(num_runners),
            "--log-level", "INFO",
            "--no-visualization",  # Skip individual delivery maps for batch processing
            "--service-hours", "10.0",
            "--revenue-per-order", "30.0",
            "--sla-minutes", "30",
            "--prep-time", "10",
            "--runner-speed", "6.0",
            "--no-bev-cart",
        ]
        
        # Add random seed if provided
        if random_seed is not None:
            cmd_args.extend(["--random-seed", str(random_seed)])
        
        # Handle blocking variants
        if blocking_variant == "none":
            # No blocking - use default delivery-runner mode
            pass
        elif blocking_variant in ["0-3", "0-6"]:
            # For blocking, we need to use a custom approach since unified_simulation 
            # doesn't directly support hole blocking. We'll need to modify the order generation
            # This requires using run_batch_experiments.py approach or implementing blocking in unified
            logger.warning("Blocking variants ('%s') require custom implementation", blocking_variant)
            logger.info("Running without blocking for now - this functionality needs to be added")
            # For now, run without blocking but log the intended variant
            pass
        
        logger.info("Running simulation: %d runners, %d orders, blocking=%s", 
                   num_runners, delivery_orders, blocking_variant)
        logger.info("Command: %s", " ".join(cmd_args))
        
        # Run the simulation
        result = subprocess.run(
            cmd_args,
            cwd=Path.cwd(),
            capture_output=True,
            text=True,
            timeout=1800  # 30 minute timeout
        )
        
        if result.returncode == 0:
            logger.info("Simulation completed successfully")
            return True
        else:
            logger.error("Simulation failed with return code %d", result.returncode)
            logger.error("STDERR: %s", result.stderr)
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("Simulation timed out after 30 minutes")
        return False
    except Exception as e:
        logger.error("Simulation failed with exception: %s", e)
        return False


def create_comprehensive_summary(results_dir: Path, simulation_results: List[Dict[str, Any]]) -> None:
    """Create a comprehensive summary of all simulation results."""
    # Ensure directory still exists (defensive against external deletion)
    results_dir.mkdir(parents=True, exist_ok=True)

    summary_lines = [
        "# Comprehensive Simulation Matrix Results",
        "",
        f"Total simulations: {len(simulation_results)}",
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "## Configuration Matrix",
        "",
        "| Scenario | Orders | Runners | Blocking | Status | Output Directory |",
        "|----------|--------|---------|----------|--------|------------------|",
    ]
    
    # Sort results for consistent reporting
    simulation_results.sort(key=lambda x: (x['orders'], x['runners'], x['blocking']))
    
    for result in simulation_results:
        status = "Success" if result['success'] else "Failed"
        summary_lines.append(
            f"| typical_weekday | {result['orders']} | {result['runners']} | "
            f"{result['blocking']} | {status} | `{result['output_dir'].name}` |"
        )
    
    summary_lines.extend([
        "",
        "## Success Summary",
        "",
    ])
    
    successful = [r for r in simulation_results if r['success']]
    failed = [r for r in simulation_results if not r['success']]
    
    summary_lines.append(f"- **Successful**: {len(successful)}/{len(simulation_results)}")
    summary_lines.append(f"- **Failed**: {len(failed)}/{len(simulation_results)}")
    
    if failed:
        summary_lines.extend([
            "",
            "### Failed Simulations",
            "",
        ])
        for result in failed:
            summary_lines.append(
                f"- {result['orders']} orders, {result['runners']} runners, "
                f"blocking={result['blocking']}"
            )
    
    summary_lines.extend([
        "",
        "## Output Structure",
        "",
        "Each simulation directory contains:",
        "- `run_XX/results.json` - Raw simulation results",
        "- `run_XX/coordinates.csv` - GPS coordinates for visualization",
        "- `run_XX/events.csv` - Event timeline for replay",
        "- `run_XX/delivery_heatmap.png` - Delivery location heatmap",
        "- `run_XX/delivery_runner_metrics_*.md` - Performance metrics",
        "- `summary.md` - Per-simulation summary",
        "- `executive_summary_gemini.md` - AI-generated analysis",
        "",
        "## Next Steps",
        "",
        "1. Review individual simulation results in each output directory",
        "2. Compare performance metrics across different configurations",
        "3. Use coordinates.csv files for visualization in React app",
        "4. Analyze event logs for operational insights",
        "",
        "For visualization, use:",
        "```bash",
        "cd my-map-animation",
        "python run_map_app.py",
        "npm start",
        "```",
    ])
    
    summary_file = results_dir / "comprehensive_summary.md"
    summary_file.write_text("\n".join(summary_lines), encoding="utf-8")
    logger.info("Created comprehensive summary: %s", summary_file)


def main() -> int:
    """Main execution function."""
    parser = argparse.ArgumentParser(
        description="Run comprehensive simulation matrix for all order/runner/blocking combinations"
    )
    
    parser.add_argument(
        "--course-dir", 
        default="courses/pinetree_country_club", 
        help="Course directory path"
    )
    parser.add_argument(
        "--output-dir", 
        default=None, 
        help="Base output directory (default: outputs/comprehensive_matrix_TIMESTAMP)"
    )
    parser.add_argument(
        "--num-runs", 
        type=int, 
        default=3, 
        help="Number of runs per simulation combination"
    )
    parser.add_argument(
        "--log-level", 
        default="INFO", 
        help="Logging level"
    )
    parser.add_argument(
        "--random-seed", 
        type=int, 
        default=42, 
        help="Base random seed for reproducibility"
    )
    parser.add_argument(
        "--block-variants",
        type=str,
        default="none,0-3,0-6",
        help="Comma-separated blocking variants to test (e.g., 'none,0-3,0-6'). Note: blocking is currently logged only and not enforced."
    )
    parser.add_argument(
        "--dry-run", 
        action="store_true", 
        help="Show what would be run without executing"
    )
    
    args = parser.parse_args()
    
    # Initialize logging
    init_logging(args.log_level)
    
    # Set up output directory
    if args.output_dir:
        results_dir = Path(args.output_dir)
    else:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        results_dir = Path("outputs") / f"comprehensive_matrix_{timestamp}"
    
    results_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info("Starting comprehensive simulation matrix")
    logger.info("Results will be saved to: %s", results_dir)
    
    # Define simulation matrix
    order_counts = [20, 30]
    runner_counts = [1, 2] 
    blocking_variants = [bv.strip() for bv in str(args.block_variants).split(",") if str(bv).strip()]
    
    total_combinations = len(order_counts) * len(runner_counts) * len(blocking_variants)
    logger.info("Total combinations to run: %d", total_combinations)
    
    if args.dry_run:
        logger.info("DRY RUN - showing what would be executed:")
        for i, (orders, runners, blocking) in enumerate(
            [(o, r, b) for o in order_counts for r in runner_counts for b in blocking_variants], 
            1
        ):
            output_name = f"sim_{i:02d}_{orders}orders_{runners}runners_block{blocking}"
            logger.info("  %d/%d: %s", i, total_combinations, output_name)
        return 0
    
    # Track all simulation results
    simulation_results: List[Dict[str, Any]] = []
    
    # Run all combinations
    combination_index = 1
    for orders in order_counts:
        # Backup and modify config for this order count
        backup_path: Optional[Path] = None
        try:
            backup_path = backup_and_modify_config(args.course_dir, orders)
            
            for runners in runner_counts:
                for blocking in blocking_variants:
                    logger.info(
                        "=== Combination %d/%d: %d orders, %d runners, blocking=%s ===",
                        combination_index, total_combinations, orders, runners, blocking
                    )
                    
                    # Create output directory for this combination
                    output_name = f"sim_{combination_index:02d}_{orders}orders_{runners}runners_block{blocking}"
                    sim_output_dir = results_dir / output_name
                    
                    # Calculate seed for this combination to ensure reproducibility
                    combination_seed = args.random_seed + combination_index
                    
                    # Run the simulation
                    success = run_delivery_simulation_with_blocking(
                        course_dir=args.course_dir,
                        num_runners=runners,
                        delivery_orders=orders,
                        blocking_variant=blocking,
                        output_dir=sim_output_dir,
                        num_runs=args.num_runs,
                        random_seed=combination_seed,
                    )
                    
                    # Record result
                    simulation_results.append({
                        'combination_index': combination_index,
                        'orders': orders,
                        'runners': runners,
                        'blocking': blocking,
                        'success': success,
                        'output_dir': sim_output_dir,
                        'seed': combination_seed,
                    })
                    
                    combination_index += 1
                    
                    if success:
                        logger.info("Combination completed successfully")
                    else:
                        logger.error("Combination failed")
                    
                    logger.info("")  # Add spacing between combinations
                    
        finally:
            # Restore original config
            if backup_path and backup_path.exists():
                restore_config(args.course_dir, backup_path)
    
    # Generate comprehensive summary
    create_comprehensive_summary(results_dir, simulation_results)
    
    # Final summary
    successful_count = sum(1 for r in simulation_results if r['success'])
    logger.info("=== FINAL SUMMARY ===")
    logger.info("Total combinations: %d", len(simulation_results))
    logger.info("Successful: %d", successful_count)
    logger.info("Failed: %d", len(simulation_results) - successful_count)
    logger.info("Results directory: %s", results_dir)
    
    if successful_count == len(simulation_results):
        logger.info("All simulations completed successfully")
        return 0
    else:
        logger.warning("Some simulations failed. Check the summary for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
