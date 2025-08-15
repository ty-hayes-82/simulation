#!/usr/bin/env python3
"""
Comprehensive Optimization Runner

Tests combinations of:
- Total orders: 5-40 (both bev cart and delivery)
- Bev carts: 1-5
- Delivery blocking scenarios: Full course, block up to hole 3, block up to hole 6
- Only typical_weekday tee scenario

Generates all output files including coordinates for each configuration.

Windows PowerShell friendly: one short command per line, no piping/chaining.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
import subprocess
import sys

from golfsim.logging import init_logging, get_logger
from golfsim.config.loaders import load_simulation_config

logger = get_logger(__name__)

def _backup_and_modify_config(course_dir: str, bev_order_prob: float, delivery_total_orders: int) -> Path:
    """Backup original config and create modified version with new bev prob and delivery orders."""
    config_path = Path(course_dir) / "config" / "simulation_config.json"
    backup_path = config_path.with_suffix('.json.backup')
    
    # Backup original if not already done
    if not backup_path.exists():
        shutil.copy2(config_path, backup_path)
        logger.info("Backed up original config to: %s", backup_path)
    
    # Load and modify config
    config = load_simulation_config(course_dir)
    config_dict = config.__dict__.copy()
    config_dict['bev_cart_order_probability_per_9_holes'] = float(bev_order_prob)
    config_dict['delivery_total_orders'] = int(delivery_total_orders)
    
    # Write modified config
    with config_path.open('w', encoding='utf-8') as f:
        json.dump(config_dict, f, indent=2)
    
    logger.info("Modified config: bev_cart_order_probability_per_9_holes=%.2f, delivery_total_orders=%d", 
                bev_order_prob, delivery_total_orders)
    return backup_path

def _restore_config(course_dir: str, backup_path: Path) -> None:
    """Restore original configuration."""
    config_path = Path(course_dir) / "config" / "simulation_config.json"
    if backup_path.exists():
        shutil.copy2(backup_path, config_path)
        logger.info("Restored original config")

def _run_unified_simulation(mode: str, use_blocking: bool = False, **kwargs) -> int:
    """Run the unified simulation script with given parameters."""
    script_name = "scripts/sim/run_unified_simulation_with_blocking.py" if use_blocking else "scripts/sim/run_unified_simulation.py"
    cmd = [sys.executable, script_name, "--mode", mode]
    
    # Add common parameters
    common_params = {
        "course_dir": "courses/pinetree_country_club",
        "tee_scenario": "typical_weekday",
        "num_runs": 3,  # Reduced for comprehensive testing
        "log_level": "WARNING",  # Reduce log noise
    }
    
    # Override with provided kwargs
    params = {**common_params, **kwargs}
    
    # Convert parameters to command line arguments
    for key, value in params.items():
        cmd.extend([f"--{key.replace('_', '-')}", str(value)])
    
    logger.info("Running: %s", " ".join(cmd))
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        return result.returncode
    except subprocess.CalledProcessError as e:
        logger.error("Command failed with return code %d", e.returncode)
        if e.stdout:
            logger.error("STDOUT: %s", e.stdout[-1000:])  # Last 1000 chars
        if e.stderr:
            logger.error("STDERR: %s", e.stderr[-1000:])
        return e.returncode

def _create_run_summary(output_root: Path, total_orders_list: List[int], 
                       bev_carts_list: List[int], delivery_blocking_scenarios: List[Dict]) -> None:
    """Create comprehensive summary of all runs."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    summary_lines = [
        "# Comprehensive Optimization Summary",
        "",
        f"**Generated:** {timestamp}",
        f"**Total Configurations:** {len(total_orders_list) * len(bev_carts_list) * len(delivery_blocking_scenarios)}",
        "",
        "## Test Parameters",
        "",
        f"- **Total Orders Range:** {min(total_orders_list)}-{max(total_orders_list)}",
        f"- **Beverage Carts Range:** {min(bev_carts_list)}-{max(bev_carts_list)}",
        f"- **Tee Scenario:** typical_weekday only",
        f"- **Delivery Blocking Scenarios:** {len(delivery_blocking_scenarios)} variants",
        "",
        "## Delivery Blocking Scenarios",
        "",
    ]
    
    for scenario in delivery_blocking_scenarios:
        summary_lines.append(f"- **{scenario['name']}:** {scenario['description']}")
    
    summary_lines.extend([
        "",
        "## Directory Structure",
        "",
        "Each configuration creates outputs in format:",
        "`{timestamp}_{total_orders}orders_{num_carts}bevcarts_{blocking_scenario}/`",
        "",
        "Contains:",
        "- `bev_cart_*` directories: Beverage cart simulations (1-5 carts)",
        "- `delivery_*` directories: Delivery runner simulations with blocking",
        "- Coordinate CSV files for visualization",
        "- Metrics and analysis files",
        "",
        "## Navigation",
        "",
        "- Look for `coordinates.csv` files for GPS tracking data",
        "- Check `summary.md` files in each subdirectory for metrics",
        "- Review `events.csv` files for detailed simulation timelines",
    ])
    
    summary_path = output_root / "comprehensive_optimization_summary.md"
    summary_path.write_text("\n".join(summary_lines), encoding="utf-8")
    logger.info("Comprehensive summary written to: %s", summary_path)

def main() -> int:
    parser = argparse.ArgumentParser(description="Comprehensive optimization testing")
    parser.add_argument("--course-dir", default="courses/pinetree_country_club", help="Course directory")
    parser.add_argument("--output-dir", type=str, default=None, help="Output directory root")
    parser.add_argument("--log-level", type=str, default="INFO", help="Log level")
    parser.add_argument("--bev-order-prob-range", type=str, default="0.2,0.3,0.35,0.4,0.5", 
                       help="Comma-separated list of bev-cart order probability per 9-holes values to test")
    parser.add_argument("--bev-carts-range", type=str, default="1,2,3,4,5",
                       help="Comma-separated list of beverage cart counts to test")
    parser.add_argument("--skip-bev-carts", action="store_true", 
                       help="Skip beverage cart simulations (delivery only)")
    parser.add_argument("--skip-delivery", action="store_true",
                       help="Skip delivery simulations (bev carts only)")
    
    args = parser.parse_args()
    init_logging(args.log_level)
    
    # Parse ranges
    bev_prob_list = [float(x.strip()) for x in args.bev_order_prob_range.split(",")]
    bev_carts_list = [int(x.strip()) for x in args.bev_carts_range.split(",")]
    
    # Define delivery blocking scenarios
    delivery_blocking_scenarios = [
        {"name": "full_course", "block_up_to_hole": 0, "description": "Full course delivery (no blocking)"},
        {"name": "block_to_hole3", "block_up_to_hole": 3, "description": "Block orders up to hole 3"},
        {"name": "block_to_hole6", "block_up_to_hole": 6, "description": "Block orders up to hole 6"},
    ]
    
    # Create output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    default_name = f"comprehensive_optimization_{timestamp}"
    output_root = Path(args.output_dir or (Path("outputs") / default_name))
    output_root.mkdir(parents=True, exist_ok=True)
    
    logger.info("Starting comprehensive optimization")
    logger.info("Output directory: %s", output_root)
    logger.info("Bev order probabilities to test: %s", bev_prob_list)
    logger.info("Bev carts to test: %s", bev_carts_list)
    logger.info("Delivery scenarios: %d", len(delivery_blocking_scenarios))
    
    total_configs = len(bev_prob_list) * (
        (len(bev_carts_list) if not args.skip_bev_carts else 0) + 
        (len(delivery_blocking_scenarios) if not args.skip_delivery else 0)
    )
    current_config = 0
    
    # Backup original config
    backup_path = None
    
    try:
        for bev_prob in bev_prob_list:
            # Backup and modify config for this bev order prob value
            backup_path = _backup_and_modify_config(args.course_dir, bev_prob, 20)
            
            for num_carts in bev_carts_list:
                if args.skip_bev_carts:
                    continue
                    
                current_config += 1
                config_name = f"{int(bev_prob*100)}p_{num_carts}bevcarts"
                logger.info("\n[%d/%d] Testing %s", current_config, total_configs, config_name)
                
                # Create subdirectory for this configuration
                config_output = output_root / config_name
                config_output.mkdir(parents=True, exist_ok=True)
                
                # Run beverage cart simulations
                bev_cart_output = config_output / "bev_cart_only"
                try:
                    result = _run_unified_simulation(
                        mode="bev-carts",
                        num_carts=num_carts,
                        output_dir=str(bev_cart_output)
                    )
                    if result != 0:
                        logger.warning("Beverage cart simulation failed for %s", config_name)
                except Exception as e:
                    logger.error("Failed to run bev-carts for %s: %s", config_name, e)
                
                # Run beverage cart with golfers
                bev_with_golfers_output = config_output / "bev_with_golfers"
                try:
                    result = _run_unified_simulation(
                        mode="bev-with-golfers",
                        output_dir=str(bev_with_golfers_output)
                    )
                    if result != 0:
                        logger.warning("Bev-with-golfers simulation failed for %s", config_name)
                except Exception as e:
                    logger.error("Failed to run bev-with-golfers for %s: %s", config_name, e)
            
            # Run delivery simulations with different blocking scenarios
            if not args.skip_delivery:
                for scenario in delivery_blocking_scenarios:
                    current_config += 1
                    config_name = f"{int(bev_prob*100)}p_delivery_{scenario['name']}"
                    logger.info("\n[%d/%d] Testing %s", current_config, total_configs, config_name)
                    
                    # Create subdirectory for this configuration  
                    config_output = output_root / config_name
                    config_output.mkdir(parents=True, exist_ok=True)
                    
                    # Use the enhanced script with blocking support
                    try:
                        result = _run_unified_simulation(
                            mode="delivery-runner",
                            use_blocking=True,
                            num_runners=1,
                            block_up_to_hole=scenario['block_up_to_hole'],
                            output_dir=str(config_output)
                        )
                        if result != 0:
                            logger.warning("Delivery simulation failed for %s", config_name)
                        
                        # Save scenario metadata
                        scenario_note = config_output / "blocking_scenario.json"
                        scenario_note.write_text(json.dumps(scenario, indent=2), encoding="utf-8")
                            
                    except Exception as e:
                        logger.error("Failed to run delivery for %s: %s", config_name, e)
            
            # Restore config after each total_orders iteration
            if backup_path:
                _restore_config(args.course_dir, backup_path)
    
    finally:
        # Ensure config is restored
        if backup_path:
            _restore_config(args.course_dir, backup_path)
    
    # Create comprehensive summary
    _create_run_summary(output_root, bev_prob_list, bev_carts_list, delivery_blocking_scenarios)
    
    logger.info("Comprehensive optimization complete!")
    logger.info("Results saved to: %s", output_root)
    logger.info("Check comprehensive_optimization_summary.md for overview")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
