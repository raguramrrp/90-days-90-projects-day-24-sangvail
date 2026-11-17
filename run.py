"""Convenience launcher for SANGVAIL on Windows, macOS, and Linux."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent


def main() -> int:
    print("Initializing SANGVAIL database and synthetic demonstration dataset...")
    seed_proc = subprocess.run([sys.executable, str(ROOT_DIR / "database" / "seed_data.py")], cwd=str(ROOT_DIR))
    if seed_proc.returncode != 0:
        print("Database initialization failed. Check output above.")
        return seed_proc.returncode

    print("Starting SANGVAIL workstation at http://localhost:8501 ...")
    cmd = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(ROOT_DIR / "app" / "main.py"),
        "--server.port=8501",
        "--server.address=localhost",
        "--server.headless=false",
    ]
    return subprocess.call(cmd, cwd=str(ROOT_DIR))


if __name__ == "__main__":
    raise SystemExit(main())
