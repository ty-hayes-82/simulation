#!/usr/bin/env python3
"""
Convenience script to automatically generate reports for all runs in a scenario.
Can be run after optimize_staffing_policy_two_pass.py completes.
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List


def find_run_directories(scenario_dir: Path) -> List[Path]:
    """Find all run_XX directories within a scenario (handles both flat and two-pass structures)"""
    run_dirs = []
    
    # Check for two-pass structure (first_pass/, second_pass/ subdirectories)
    pass_dirs = [d for d in scenario_dir.iterdir() if d.is_dir() and d.name.endswith("_pass")]
    
    if pass_dirs:
        # Two-pass structure: scan within first_pass/ and second_pass/
        for pass_dir in pass_dirs:
            for orders_dir in pass_dir.glob("orders_*"):
                for runners_dir in orders_dir.glob("runners_*"):
                    for variant_dir in runners_dir.iterdir():
                        if not variant_dir.is_dir():
                            continue
                        for run_dir in variant_dir.glob("run_*"):
                            if (run_dir / "results.json").exists():
                                run_dirs.append(run_dir)
    else:
        # Flat structure: scan directly under scenario_dir
        for orders_dir in scenario_dir.glob("orders_*"):
            for runners_dir in orders_dir.glob("runners_*"):
                for variant_dir in runners_dir.iterdir():
                    if not variant_dir.is_dir():
                        continue
                    for run_dir in variant_dir.glob("run_*"):
                        if (run_dir / "results.json").exists():
                            run_dirs.append(run_dir)
    
    return sorted(run_dirs)


def generate_report(run_dir: Path) -> bool:
    """Generate report for a single run directory"""
    try:
        cmd = [
            sys.executable, "scripts/report/build_report.py",
            "--run-dir", str(run_dir),
            "--emit-csv", "--html"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path.cwd())
        
        if result.returncode != 0:
            print(f"❌ Failed to generate report for {run_dir}")
            print(f"   Error: {result.stderr}")
            return False
        else:
            print(f"✅ Generated report for {run_dir}")
            return True
            
    except Exception as e:
        print(f"❌ Exception generating report for {run_dir}: {e}")
        return False


def generate_index(scenario_dir: Path) -> bool:
    """Generate scenario comparison index"""
    try:
        cmd = [
            sys.executable, "scripts/report/build_index.py",
            "--scenario-dir", str(scenario_dir),
            "--html"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path.cwd())
        
        if result.returncode != 0:
            print(f"❌ Failed to generate index for {scenario_dir}")
            print(f"   Error: {result.stderr}")
            return False
        else:
            print(f"✅ Generated index for {scenario_dir}")
            return True
            
    except Exception as e:
        print(f"❌ Exception generating index for {scenario_dir}: {e}")
        return False


def main(argv: List[str] = None) -> int:
    parser = argparse.ArgumentParser(description="Auto-generate reports for all runs in a scenario")
    parser.add_argument("--scenario-dir", required=True, help="Path to scenario directory")
    parser.add_argument("--skip-existing", action="store_true", help="Skip runs that already have reports")
    args = parser.parse_args(argv)
    
    scenario_dir = Path(args.scenario_dir).resolve()
    
    if not scenario_dir.exists():
        print(f"❌ Scenario directory not found: {scenario_dir}")
        return 1
    
    print(f"🔍 Scanning for run directories in {scenario_dir}")
    run_dirs = find_run_directories(scenario_dir)
    
    if not run_dirs:
        print("❌ No run directories found with results.json")
        return 1
    
    print(f"📊 Found {len(run_dirs)} run directories")
    
    success_count = 0
    for run_dir in run_dirs:
        # Skip if report already exists and --skip-existing is set
        if args.skip_existing and (run_dir / "report" / "report.html").exists():
            print(f"⏭️  Skipping {run_dir} (report exists)")
            continue
            
        if generate_report(run_dir):
            success_count += 1
    
    print(f"\n📈 Generated {success_count}/{len(run_dirs)} reports")
    
    # Generate scenario index
    if success_count > 0:
        if generate_index(scenario_dir):
            print(f"🎯 Scenario index: {scenario_dir / 'index.html'}")
    
    return 0 if success_count == len(run_dirs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
