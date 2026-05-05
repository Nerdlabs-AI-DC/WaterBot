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
import base64
from pathlib import Path

SECRETS_DIR = Path("secret")
MEMORY_KEY_FILE = SECRETS_DIR / "memory_key.b64"


def _ensure_secrets_dir():
    SECRETS_DIR.mkdir(parents=True, exist_ok=True)


def get_or_create_memory_key_b64() -> str:
    _ensure_secrets_dir()
    
    if MEMORY_KEY_FILE.exists():
        try:
            with open(MEMORY_KEY_FILE, 'r') as f:
                key_b64 = f.read().strip()
            key = base64.urlsafe_b64decode(key_b64)
            if len(key) != 32:
                raise ValueError("Stored key is not 32 bytes for AES-256")
            return key_b64
        except Exception as e:
            raise RuntimeError(f"Failed to read memory key from {MEMORY_KEY_FILE}: {e}")

    try:
        key = os.urandom(32)
        key_b64 = base64.urlsafe_b64encode(key).decode('ascii')

        with open(MEMORY_KEY_FILE, 'w') as f:
            f.write(key_b64)
        os.chmod(MEMORY_KEY_FILE, 0o600)

        return key_b64
    except Exception as e:
        raise RuntimeError(f"Failed to generate memory key: {e}")


def validate_key_file():
    if not MEMORY_KEY_FILE.exists():
        raise RuntimeError(
            f"Memory key file not found at {MEMORY_KEY_FILE}. "
            "Run bot initialization to generate it."
        )
    
    try:
        with open(MEMORY_KEY_FILE, 'r') as f:
            key_b64 = f.read().strip()
        key = base64.urlsafe_b64decode(key_b64)
        if len(key) != 32:
            raise ValueError("Stored key is not 32 bytes for AES-256")
        return True
    except Exception as e:
        raise RuntimeError(f"Memory key file validation failed: {e}")
