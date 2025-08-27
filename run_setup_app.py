#!/usr/bin/env python3
"""
Golf Course Setup App Runner

This script runs only the setup application for creating shortcuts and other setup tasks.
"""

import subprocess
import sys
from pathlib import Path

def main():
    """Run the setup app."""
    try:
        setup_dir = Path(__file__).resolve().parent / "my-map-setup"
        
        if not setup_dir.exists():
            print("❌ Setup app directory not found: my-map-setup")
            print("💡 Make sure you've run the split strategy first")
            sys.exit(1)
        
        print("🚀 Starting Golf Course Setup App...")
        print("📍 Setup app will open at http://localhost:3001")
        print("🔄 Use Ctrl+C to stop the server when done")
        print("-" * 60)
        
        # Start the setup app
        result = subprocess.run(
            ["npm", "start"],
            cwd=str(setup_dir),
            shell=True
        )
        
        return result.returncode == 0
        
    except KeyboardInterrupt:
        print("\n⏹️  Setup app stopped by user")
        return True
    except Exception as e:
        print(f"❌ Error starting setup app: {e}")
        print("💡 Make sure you have Node.js and npm installed")
        print("💡 Try running 'npm install' in my-map-setup directory first")
        return False

if __name__ == "__main__":
    main()
