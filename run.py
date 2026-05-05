"""
WaterBot - AI Discord bot manager
Copyright (C) 2026  Nerdlabs AI

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>.
"""

import os
import subprocess
import sys
from pathlib import Path

# Paths

PROJECT_DIR  = Path(__file__).resolve().parent
VENV_DIR     = PROJECT_DIR / ".venv"
REQUIREMENTS = PROJECT_DIR / "requirements.txt"
START_PY     = PROJECT_DIR / "src" / "start.py"

VENV_PYTHON  = VENV_DIR / ("bin/python")
VENV_PIP     = VENV_DIR / ("bin/pip")

MIN_PYTHON   = (3, 10)

# Helpers

def banner(text: str):
    width = 52
    print()
    print("─" * width)
    print(f"  {text}")
    print("─" * width)

def ok(text: str):
    print(f"  ✓  {text}")

def info(text: str):
    print(f"  •  {text}")

def warn(text: str):
    print(f"  ⚠  {text}")

def die(text: str):
    print(f"\n  ✗  ERROR: {text}\n")
    sys.exit(1)

def run(*cmd, capture: bool = False, **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        **kwargs,
    )
    if result.returncode != 0:
        if capture:
            err = (result.stderr or result.stdout or b"").decode(errors="replace").strip()
            die(err or f"Command failed: {' '.join(str(c) for c in cmd)}")
        else:
            sys.exit(result.returncode)
    return result


# Steps

def check_python():
    if sys.version_info < MIN_PYTHON:
        die(
            f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required "
            f"(running {sys.version.split()[0]})"
        )
    ok(f"Python {sys.version.split()[0]}")


def create_venv():
    if VENV_PYTHON.exists():
        info("Virtual environment already exists, skipping creation")
        return

    info("Creating virtual environment at .venv/ …")
    run(sys.executable, "-m", "venv", str(VENV_DIR))
    ok("Virtual environment created")


def install_requirements():
    if not REQUIREMENTS.exists():
        warn(f"requirements.txt not found at {REQUIREMENTS}, skipping install")
        return

    info("Installing packages from requirements.txt …")
    result = run(
        str(VENV_PYTHON), "-m", "pip", "install",
        "--upgrade", "--quiet",
        "-r", str(REQUIREMENTS),
        capture=True,
    )
    ok("Packages up to date")


def check_start_py():
    if not START_PY.exists():
        die(f"src/start.py not found. Expected at {START_PY}")
    ok("src/start.py found")


# Entry point

def main():
    banner("Welcome to WaterBot")

    check_python()
    create_venv()
    install_requirements()
    check_start_py()

    banner("Starting WaterBot...")
    print()

    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(START_PY)])


if __name__ == "__main__":
    main()