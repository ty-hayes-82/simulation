#!/usr/bin/env python3
"""
Busy Weekend Simulation Matrix Runner

Runs a comprehensive matrix of simulations for busy_weekend scenario:
- Delivery orders: 20, 30, 40
- Runners: 1, 2, 3
- With and without beverage cart
- Generates coordinates.csv files for each simulation
- Creates descriptive folder names with order counts

Each simulation combination is run with full outputs including coordinates,
visualizations, and metrics for detailed analysis.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Dict, Any

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
    if not backup_path.exists():
        logger.warning("Backup file not found: %s", backup_path)
        return
    
    config_path = Path(course_dir) / "config" / "simulation_config.json"
    shutil.copy2(backup_path, config_path)
    backup_path.unlink()  # Remove backup file
    logger.info("Restored original config from backup")


def run_simulation(mode: str, scenario: str, runners: int, orders: int, 
                  with_bev_cart: bool, course_dir: str, output_root: Path, 
                  num_runs: int = 2, no_visualization: bool = False,
                  block_up_to_hole: int = 0) -> bool:
    """Run a single simulation configuration."""
    
    # Create descriptive folder name
    bev_suffix = "with_bev" if with_bev_cart else "no_bev"
    block_suffix = f"_block{block_up_to_hole}" if block_up_to_hole > 0 else "_full"
    folder_name = f"busy_weekend_delivery_{runners}r_{orders}orders_{bev_suffix}{block_suffix}"
    output_dir = output_root / folder_name
    
    # Build command based on mode
    if mode == "delivery-runner":
        # Use the blocking-capable runner for all delivery runs
        cmd = [
            sys.executable, "scripts/sim/run_unified_simulation_with_blocking.py",
            "--mode", "delivery-runner",
            "--tee-scenario", scenario,
            "--num-runners", str(runners),
            "--num-runs", str(num_runs),
            "--output-dir", str(output_dir),
            "--log-level", "INFO",
            "--block-up-to-hole", str(int(block_up_to_hole)),
        ]
        
        # Add beverage cart flag
        if not with_bev_cart:
            cmd.append("--no-bev-cart")
            
    elif mode == "bev-with-golfers":
        # For beverage cart mode, we ignore the runners parameter
        cmd = [
            sys.executable, "scripts/sim/run_unified_simulation.py",
            "--mode", "bev-with-golfers",
            "--tee-scenario", scenario,
            "--num-runs", str(num_runs),
            "--output-dir", str(output_dir),
            "--log-level", "INFO"
        ]
    # Visuals toggle
    if no_visualization:
        cmd.append("--no-visualization")
    else:
        logger.error("Unknown mode: %s", mode)
        return False
    
    try:
        logger.info("Running: %s", " ".join(cmd))
        print(f"\n{'='*60}")
        print(f"RUNNING: {folder_name}")
        print(f"Mode: {mode}, Runners: {runners}, Orders: {orders}, Bev Cart: {with_bev_cart}")
        print(f"{'='*60}")
        
        result = subprocess.run(cmd, check=True, text=True)
        logger.info("✓ Completed: %s", folder_name)
        print(f"✓ SUCCESS: {folder_name}")
        return True
        
    except subprocess.CalledProcessError as e:
        logger.error("✗ Failed: %s (exit code: %d)", folder_name, e.returncode)
        print(f"✗ FAILED: {folder_name} (exit code: {e.returncode})")
        return False
    except Exception as e:
        logger.error("✗ Error running %s: %s", folder_name, e)
        print(f"✗ ERROR: {folder_name} - {e}")
        return False


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run comprehensive busy weekend simulation matrix"
    )
    parser.add_argument("--course-dir", default="courses/pinetree_country_club", 
                       help="Course directory")
    parser.add_argument("--output-root", default="outputs/busy_weekend_matrix", 
                       help="Root output directory")
    parser.add_argument("--num-runs", type=int, default=2, 
                       help="Number of simulation runs per configuration")
    parser.add_argument("--log-level", default="INFO", help="Log level")
    parser.add_argument("--no-visualization", action="store_true", help="Skip creating visualizations for all sims")
    parser.add_argument("--block-up-to-holes", default="0", help="Comma-separated list of hole blocking caps to test (e.g. '0,3,6')")
    
    # Matrix parameters
    parser.add_argument("--delivery-orders", default="20,30,40",
                       help="Comma-separated delivery order counts")
    parser.add_argument("--runner-counts", default="1,2,3",
                       help="Comma-separated runner counts") 
    parser.add_argument("--scenario", default="busy_weekend",
                       help="Tee time scenario to use")
    parser.add_argument("--skip-bev-only", action="store_true",
                       help="Skip beverage-cart-only simulations")
    
    args = parser.parse_args()
    init_logging(args.log_level)
    
    # Parse parameters
    delivery_orders = [int(x.strip()) for x in args.delivery_orders.split(",")]
    runner_counts = [int(x.strip()) for x in args.runner_counts.split(",")]
    block_caps = [int(x.strip()) for x in args.block_up_to_holes.split(",")]
    output_root = Path(args.output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    
    logger.info("Starting busy weekend simulation matrix")
    logger.info("Delivery orders: %s", delivery_orders)
    logger.info("Runner counts: %s", runner_counts)
    logger.info("Output root: %s", output_root)
    
    # Track results
    total_sims = 0
    successful_sims = 0
    failed_sims = []
    
    original_backup = None
    
    try:
        # Run the simulation matrix
        for orders in delivery_orders:
            logger.info("\n" + "="*50)
            logger.info("DELIVERY ORDERS: %d", orders)
            logger.info("="*50)
            
            # Update config for this order count
            backup_path = backup_and_modify_config(args.course_dir, orders)
            if original_backup is None:
                original_backup = backup_path
            
            try:
                # Run delivery runner simulations (with and without bev cart) across blocking caps
                for runners in runner_counts:
                    for block_cap in block_caps:
                        for with_bev in [False, True]:
                            # Only run bev-with-delivery when blocking cap is zero; blocking script does not model bev interaction
                            if with_bev and block_cap > 0:
                                continue
                            total_sims += 1
                            success = run_simulation(
                                mode="delivery-runner",
                                scenario=args.scenario,
                                runners=runners,
                                orders=orders,
                                with_bev_cart=with_bev,
                                course_dir=args.course_dir,
                                output_root=output_root,
                                num_runs=args.num_runs,
                                no_visualization=bool(args.no_visualization),
                                block_up_to_hole=int(block_cap),
                            )
                            
                            if success:
                                successful_sims += 1
                            else:
                                failed_sims.append(f"delivery_{runners}r_{orders}orders_{'with' if with_bev else 'no'}_bev_block{block_cap}")
                
                # Run beverage cart only simulation (if not skipped) — blocking not applicable, run once
                if not args.skip_bev_only:
                    total_sims += 1
                    success = run_simulation(
                        mode="bev-with-golfers", 
                        scenario=args.scenario,
                        runners=1,  # Ignored for bev-cart mode
                        orders=orders,
                        with_bev_cart=True,
                        course_dir=args.course_dir,
                        output_root=output_root,
                        num_runs=args.num_runs,
                        no_visualization=bool(args.no_visualization),
                        block_up_to_hole=0,
                    )
                    
                    if success:
                        successful_sims += 1
                    else:
                        failed_sims.append(f"bevcart_only_{orders}orders")
                        
            finally:
                # Clean up this iteration's backup (keep original)
                if backup_path != original_backup and backup_path.exists():
                    backup_path.unlink()
    
    finally:
        # Restore original config
        if original_backup:
            restore_config(args.course_dir, original_backup)
    
    # Summary
    print(f"\n{'='*60}")
    print("SIMULATION MATRIX COMPLETE")
    print(f"{'='*60}")
    print(f"Total simulations: {total_sims}")
    print(f"Successful: {successful_sims}")
    print(f"Failed: {len(failed_sims)}")
    
    if failed_sims:
        print(f"\nFailed simulations:")
        for sim in failed_sims:
            print(f"  ✗ {sim}")
    
    print(f"\nResults saved to: {output_root}")
    
    # Write summary file
    summary = {
        "matrix_parameters": {
            "delivery_orders": delivery_orders,
            "runner_counts": runner_counts,
            "scenario": args.scenario,
            "num_runs_per_config": args.num_runs,
            "block_caps": block_caps,
        },
        "results": {
            "total_simulations": total_sims,
            "successful": successful_sims,
            "failed": len(failed_sims),
            "failed_configurations": failed_sims
        },
        "output_directories": [
            f"busy_weekend_delivery_{r}r_{o}orders_{b}{('_block'+str(c)) if c>0 else '_full'}"
            for o in delivery_orders
            for r in runner_counts  
            for b in ["no_bev", "with_bev"]
            for c in block_caps if not (b == "with_bev" and c > 0)
        ]
    }
    
    summary_path = output_root / "matrix_summary.json"
    with summary_path.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    
    logger.info("Matrix summary saved to: %s", summary_path)
    
    return 0 if len(failed_sims) == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
