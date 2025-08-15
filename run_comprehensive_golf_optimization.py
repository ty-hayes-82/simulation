#!/usr/bin/env python3
"""
Quick runner script for comprehensive golf simulation optimization.

Runs the comprehensive optimization for:
- typical_weekday scenario only
- Total orders: 5-40 
- Bev carts: 1-5
- Delivery blocking: Full course, block up to hole 3, block up to hole 6
- All output files including coordinates

This is a convenience script that calls the comprehensive optimization
with the exact parameters requested.
"""

import subprocess
import sys
from pathlib import Path

def main():
    print("🏌️ Starting Comprehensive Golf Simulation Optimization")
    print("=" * 60)
    print("Testing configurations:")
    print("- Scenario: typical_weekday only")
    print("- Total orders: 5, 10, 15, 20, 25, 30, 35, 40")
    print("- Beverage carts: 1, 2, 3, 4, 5")
    print("- Delivery blocking: Full course, up to hole 3, up to hole 6")
    print("- Output: All files including coordinates")
    print("=" * 60)
    
    # Build command
    cmd = [
        sys.executable,
        "scripts/sim/run_comprehensive_optimization.py",
        "--total-orders-range", "5,10,15,20,25,30,35,40",
        "--bev-carts-range", "1,2,3,4,5",
        "--log-level", "INFO"
    ]
    
    print(f"Running: {' '.join(cmd)}")
    print()
    
    try:
        # Run the comprehensive optimization
        result = subprocess.run(cmd, check=True)
        
        print("\n" + "=" * 60)
        print("✅ Comprehensive optimization completed successfully!")
        print("Check the outputs/ directory for results.")
        print("Look for directories named: comprehensive_optimization_YYYYMMDD_HHMMSS")
        print("=" * 60)
        
        return result.returncode
        
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Optimization failed with return code: {e.returncode}")
        return e.returncode
    except KeyboardInterrupt:
        print("\n⚠️ Optimization interrupted by user")
        return 130
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())
