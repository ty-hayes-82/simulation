#!/usr/bin/env python3
"""
Blocking Optimization Runner

Tests blocking scenarios with different runner counts:
- Blocking scenarios: 
  * Full course (0) - no blocking
  * Block up to hole 3 (1-3 blocked)
  * Block up to hole 6 (1-6 blocked) 
  * Block holes 10-12 (10,11,12 blocked)
  * Block holes 0-5 (1-5 blocked)
- Runner counts: 1, 2, 3, 4
- Tee scenario: busy_weekend
- 5 simulations per scenario

Windows PowerShell friendly: one short command per line, no piping/chaining.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any
import subprocess
import sys

from golfsim.logging import init_logging, get_logger

logger = get_logger(__name__)

def _run_unified_simulation(mode: str, **kwargs) -> int:
    """Run the unified simulation with given parameters."""
    cmd = [
        sys.executable, "scripts/sim/run_unified_simulation.py",
        "--mode", mode,
        "--tee-scenario", "busy_weekend",
        "--num-runs", "5",
        "--skip-executive-summary"
    ]
    
    # Add mode-specific parameters
    if mode == "delivery-runner":
        cmd.extend(["--num-runners", str(kwargs.get("num_runners", 1))])
        if kwargs.get("block_up_to_hole", 0) > 0:
            cmd.extend(["--block-up-to-hole", str(kwargs["block_up_to_hole"])])
        if kwargs.get("block_holes_10_12", False):
            cmd.extend(["--block-holes-10-12"])
    
    # Add output directory
    cmd.extend(["--output-dir", str(kwargs.get("output_dir", "outputs"))])
    
    logger.info("Running command: %s", " ".join(cmd))
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        logger.info("Simulation completed successfully")
        return 0
    except subprocess.CalledProcessError as e:
        logger.error("Simulation failed with exit code %d", e.returncode)
        logger.error("STDOUT: %s", e.stdout)
        logger.error("STDERR: %s", e.stderr)
        return e.returncode

def main():
    parser = argparse.ArgumentParser(description="Run blocking optimization scenarios")
    parser.add_argument("--runner-counts", default="1,2,3,4", 
                       help="Comma-separated list of runner counts to test")
    parser.add_argument("--output-dir", default="outputs", 
                       help="Base output directory")
    parser.add_argument("--log-level", default="INFO", 
                       help="Logging level")
    
    args = parser.parse_args()
    
    # Initialize logging
    init_logging(level=args.log_level)
    
    # Parse runner counts
    runner_counts = [int(x.strip()) for x in args.runner_counts.split(",")]
    
    # Define blocking scenarios
    blocking_scenarios = [
        {"name": "full_course", "description": "No blocking (full course)", "block_up_to_hole": 0, "block_holes_10_12": False},
        {"name": "block_to_hole3", "description": "Block holes 1-3", "block_up_to_hole": 3, "block_holes_10_12": False},
        {"name": "block_to_hole6", "description": "Block holes 1-6", "block_up_to_hole": 6, "block_holes_10_12": False},
        {"name": "block_holes_10_12", "description": "Block holes 10-12", "block_up_to_hole": 0, "block_holes_10_12": True},
        {"name": "block_holes_0_5", "description": "Block holes 1-5", "block_up_to_hole": 5, "block_holes_10_12": False},
        {"name": "block_holes_1_5_and_10_12", "description": "Block holes 1-5 AND 10-12", "block_up_to_hole": 5, "block_holes_10_12": True},
    ]
    
    # Create timestamped output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_output_dir = Path(args.output_dir) / f"blocking_optimization_{timestamp}"
    base_output_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info("Starting blocking optimization with %d scenarios and %d runner counts", 
               len(blocking_scenarios), len(runner_counts))
    logger.info("Output directory: %s", base_output_dir)
    
    # Track results
    results = []
    
    # Run each scenario
    for scenario in blocking_scenarios:
        for num_runners in runner_counts:
            scenario_name = f"{scenario['name']}_{num_runners}runners"
            scenario_dir = base_output_dir / scenario_name
            scenario_dir.mkdir(parents=True, exist_ok=True)
            
            logger.info("Running scenario: %s (%s) with %d runners", 
                       scenario_name, scenario['description'], num_runners)
            
            # Save scenario configuration
            scenario_config = {
                "scenario_name": scenario_name,
                "description": scenario['description'],
                "num_runners": num_runners,
                "block_up_to_hole": scenario['block_up_to_hole'],
                "block_holes_10_12": scenario['block_holes_10_12'],
                "timestamp": datetime.now().isoformat()
            }
            
            with open(scenario_dir / "blocking_scenario.json", 'w') as f:
                json.dump(scenario_config, f, indent=2)
            
            # Run simulation
            start_time = time.time()
            exit_code = _run_unified_simulation(
                mode="delivery-runner",
                num_runners=num_runners,
                block_up_to_hole=scenario['block_up_to_hole'],
                block_holes_10_12=scenario['block_holes_10_12'],
                output_dir=str(scenario_dir)
            )
            end_time = time.time()
            
            result = {
                "scenario_name": scenario_name,
                "description": scenario['description'],
                "num_runners": num_runners,
                "block_up_to_hole": scenario['block_up_to_hole'],
                "block_holes_10_12": scenario['block_holes_10_12'],
                "exit_code": exit_code,
                "duration_seconds": end_time - start_time,
                "success": exit_code == 0
            }
            
            results.append(result)
            
            if exit_code == 0:
                logger.info("✓ Scenario %s completed successfully in %.1f seconds", 
                           scenario_name, result['duration_seconds'])
            else:
                logger.error("✗ Scenario %s failed with exit code %d", scenario_name, exit_code)
    
    # Generate summary
    summary_path = base_output_dir / "blocking_optimization_summary.md"
    with open(summary_path, 'w', encoding='utf-8') as f:
        f.write("# Blocking Optimization Summary\n\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write("## Scenarios Tested\n\n")
        for scenario in blocking_scenarios:
            f.write(f"- **{scenario['name']}**: {scenario['description']}\n")
        
        f.write(f"\n## Runner Counts Tested\n\n")
        f.write(f"- {', '.join(map(str, runner_counts))}\n\n")
        
        f.write("## Results\n\n")
        f.write("| Scenario | Runners | Block Up To | Block 10-12 | Status | Duration |\n")
        f.write("|----------|---------|-------------|-------------|--------|----------|\n")
        
        for result in results:
            status = "✓ Success" if result['success'] else "✗ Failed"
            f.write(f"| {result['scenario_name']} | {result['num_runners']} | "
                   f"{result['block_up_to_hole']} | {result['block_holes_10_12']} | "
                   f"{status} | {result['duration_seconds']:.1f}s |\n")
        
        f.write(f"\n## Summary Statistics\n\n")
        successful = sum(1 for r in results if r['success'])
        total = len(results)
        f.write(f"- Total scenarios: {total}\n")
        f.write(f"- Successful: {successful}\n")
        f.write(f"- Failed: {total - successful}\n")
        f.write(f"- Success rate: {successful/total*100:.1f}%\n")
        
        if successful > 0:
            avg_duration = sum(r['duration_seconds'] for r in results if r['success']) / successful
            f.write(f"- Average duration: {avg_duration:.1f} seconds\n")
    
    logger.info("Optimization completed. Summary written to: %s", summary_path)
    logger.info("Results: %d/%d scenarios successful", successful, total)

if __name__ == "__main__":
    main()
