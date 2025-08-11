from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


PHASE_TESTS = [
    "tests/phase_01_beverage_cart_only",
    "tests/phase_02_golfer_only",
    "tests/phase_11_two_beverage_carts",
    "tests/phase_12_golfer_and_bev_cart",
]

PHASE_RUNNERS = [
    "scripts/sim/phase_01_beverage_cart_only/run_bev_cart_phase1.py",
    "scripts/sim/phase_02_golfer_only/run_golfer_only_phase2.py",
    "scripts/sim/phase_11_two_beverage_carts/run_bev_cart_phase11.py",
    "scripts/sim/phase_12_golfer_and_bev_cart/run_phase12_golfer_and_bev.py",
]


def clear_outputs() -> None:
    outputs = Path("outputs")
    if outputs.exists():
        # Remove all contents inside outputs but keep the directory itself
        for child in outputs.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                try:
                    child.unlink()
                except Exception:
                    pass
    else:
        outputs.mkdir(parents=True, exist_ok=True)


def run_tests() -> int:
    overall_rc = 0
    for test_path in PHASE_TESTS:
        print(f"\n=== Running {test_path} ===")
        rc = subprocess.run([sys.executable, "-m", "pytest", "-q", test_path]).returncode
        if rc != 0:
            overall_rc = rc
            print(f"FAILED: {test_path} (rc={rc})")
            break
        else:
            print(f"PASSED: {test_path}")
    return overall_rc


def run_simulations() -> int:
    overall_rc = 0
    for script in PHASE_RUNNERS:
        print(f"\n=== Running simulation: {script} ===")
        rc = subprocess.run([sys.executable, script]).returncode
        if rc != 0:
            overall_rc = rc
            print(f"FAILED: {script} (rc={rc})")
            break
        else:
            print(f"COMPLETED: {script}")
    return overall_rc


def main() -> int:
    print("Clearing outputs/ ...")
    clear_outputs()
    sim_rc = run_simulations()
    if sim_rc != 0:
        return sim_rc
    return run_tests()


if __name__ == "__main__":
    sys.exit(main())


