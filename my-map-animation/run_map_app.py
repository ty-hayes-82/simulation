#!/usr/bin/env python3
"""
GPS Coordinate Processor and Map App Runner

This script scans for simulation directories and loads coordinate files 
for map visualization with hierarchical selection.
"""

from __future__ import annotations

import os
import glob
import shutil
import subprocess
import sys
import json
import re
from pathlib import Path
from typing import List, Tuple, Dict, Optional
from datetime import datetime
import socket
try:
    # Make stdout UTF-8 capable on Windows PowerShell to avoid emoji crash
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')  # type: ignore[attr-defined]
except Exception:
    pass

# --- Start of new path configuration ---
# Make paths robust to script's location and execution directory
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = (SCRIPT_DIR / "..").resolve()

# Configuration - Copy to my-map-animation/public only
PUBLIC_DIRS = [str(SCRIPT_DIR / "public")]
# Setup app public directory (for required lightweight assets only)
SETUP_PUBLIC_DIR = PROJECT_ROOT / "my-map-setup" / "public"
COORDINATES_DIR = "coordinates"
LOCAL_CSV_FILE = str(SCRIPT_DIR / "public" / "coordinates.csv")

# Determine outputs directory dynamically, with env override
# Falls back to ../outputs relative to this script
DEFAULT_OUTPUTS_DIR = str(PROJECT_ROOT / "outputs")
SIM_BASE_DIR = os.environ.get("SIM_BASE_DIR", DEFAULT_OUTPUTS_DIR)
# --- End of new path configuration ---

def _humanize(name: str) -> str:
    name = name.replace('-', ' ').replace('_', ' ').strip()
    parts = [p for p in name.split(' ') if p]
    return ' '.join(w.capitalize() for w in parts) if parts else name


def _is_port_in_use(port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False

def _find_available_port(preferred_port: int, avoid_ports: Optional[set[int]] = None, max_tries: int = 5) -> int:
    avoid = avoid_ports or set()
    port = preferred_port
    tries = 0
    while tries < max_tries and (port in avoid or _is_port_in_use(port)):
        port += 1
        tries += 1
    return port

def run_react_app(setup_only: bool = False) -> bool:
    """
    Start the React development server(s).
    
    Args:
        setup_only: If True, only start the setup app. If False, start both apps.
    
    Returns:
        True if app(s) started successfully, False otherwise
    """
    try:
        if setup_only:
            print("\n🚀 Starting React setup app...")
            print("📍 Setup app will open at http://localhost:3001")
            print("🔄 Use Ctrl+C to stop the server when done")
            print("-" * 60)
            
            # Start only the setup app
            setup_dir = SCRIPT_DIR.parent / "my-map-setup"
            env = os.environ.copy()
            # Pin Setup app to port 3001 to keep UX consistent
            env["PORT"] = "3001"
            result = subprocess.run(
                ["npm", "start"],
                cwd=str(setup_dir),
                shell=True,
                env=env,
            )
            return result.returncode == 0
        else:
            print("\n🚀 Starting both React apps...")
            # Resolve animation app port automatically if 3000 is busy
            animation_port = _find_available_port(3000, avoid_ports={3001})
            print(f"📍 Animation app will open at http://localhost:{animation_port}")
            print("📍 Setup app will open at http://localhost:3001")
            print("🔄 Use Ctrl+C to stop both servers when done")
            print("-" * 60)
            
            import threading
            import time
            
            # Function to run a single app
            def run_single_app(app_dir: str, app_name: str, env: Optional[Dict[str, str]] = None):
                try:
                    print(f"Starting {app_name}...")
                    subprocess.run(
                        ["npm", "start"],
                        cwd=app_dir,
                        shell=True,
                        env=env,
                    )
                except Exception as e:
                    print(f"❌ Error starting {app_name}: {e}")
            
            # Prepare envs
            animation_env = os.environ.copy()
            animation_env["PORT"] = str(animation_port)
            setup_env = os.environ.copy()
            setup_env["PORT"] = "3001"

            # Start animation app in a thread
            animation_thread = threading.Thread(
                target=run_single_app,
                args=[str(SCRIPT_DIR), "Animation App", animation_env],
                daemon=True
            )
            animation_thread.start()
            
            # Wait a moment before starting the second app
            time.sleep(2)
            
            # Start setup app in a thread
            setup_dir = SCRIPT_DIR.parent / "my-map-setup"
            setup_thread = threading.Thread(
                target=run_single_app,
                args=[str(setup_dir), "Setup App", setup_env],
                daemon=True
            )
            setup_thread.start()
            
            # Keep main thread alive
            try:
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\n⏹️  Both apps stopped by user")
                return True
        
    except KeyboardInterrupt:
        print("\n⏹️  App stopped by user")
        return True
    except Exception as e:
        print(f"❌ Error starting React app: {e}")
        print("💡 Make sure you have Node.js and npm installed")
        print("💡 Try running 'npm install' first if this is a fresh setup")
        return False

def main():
    """Main function."""
    import argparse
    parser = argparse.ArgumentParser(description="Prepare map app coordinates and manifest")
    parser.add_argument("--default-id", dest="default_id", default=None, help="Preferred default simulation id (manifest id)")
    parser.add_argument("--setup-only", action="store_true", help="Only start the setup app (shortcuts)")
    parser.add_argument("--both-apps", action="store_true", help="Start both animation and setup apps")
    args = parser.parse_args()

    print("This script is now only for launching the React development servers.")
    print("The simulation data processing has been moved to the optimization scripts.")

    # Launch apps based on arguments
    if args.setup_only:
        run_react_app(setup_only=True)
    elif args.both_apps:
        run_react_app(setup_only=False)
    else:
        # Default to starting just the main animation app if no data processing is done.
        print("\n🚀 Starting React animation app...")
        animation_port = _find_available_port(3000, avoid_ports={3001})
        print(f"📍 Animation app will open at http://localhost:{animation_port}")
        print("🔄 Use Ctrl+C to stop the server when done")
        print("-" * 60)
        
        env = os.environ.copy()
        env["PORT"] = str(animation_port)
        
        try:
            subprocess.run(
                ["npm", "start"],
                cwd=str(SCRIPT_DIR),
                shell=True,
                env=env,
            )
        except KeyboardInterrupt:
            print("\n⏹️  App stopped by user")
        except Exception as e:
            print(f"❌ Error starting React app: {e}")
            print("💡 Make sure you have Node.js and npm installed")
            print("💡 Try running 'npm install' first if this is a fresh setup")


if __name__ == "__main__":
    main()
