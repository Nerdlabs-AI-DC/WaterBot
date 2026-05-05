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

import sys
import os
from pathlib import Path


def get_app_data_dir() -> Path:
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        data_dir = Path(xdg_data_home) / "waterbot"
    else:
        data_dir = Path.home() / ".local" / "share" / "waterbot"
    
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_installation_dir() -> Path:
    return Path(__file__).parent.parent


def main():
    data_dir = get_app_data_dir()
    os.environ["WATERBOT_DATA_DIR"] = str(data_dir)

    from . import start
    
    try:
        start.main()
    except KeyboardInterrupt:
        print("\n\nWaterBot launcher shutting down...")
        sys.exit(0)
    except Exception as e:
        print(f"\nError: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
