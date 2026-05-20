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
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ENCRYPTED_VALUE_PREFIX = "$enc$v1$"


def _get_key() -> bytes:
    try:
        from config import MEMORY_KEY_B64
        if not MEMORY_KEY_B64:
            return None
        key = base64.urlsafe_b64decode(MEMORY_KEY_B64)
        if len(key) != 32:
            return None
        return key
    except Exception:
        return None


def is_encrypted_value(value: str) -> bool:
    if not isinstance(value, str):
        return False
    return value.startswith(ENCRYPTED_VALUE_PREFIX)


def encrypt_config_value(value: str) -> str:
    if not value:
        return ""

    if isinstance(value, str) and is_encrypted_value(value):
        return value

    value_str = str(value).strip()
    if not value_str:
        return ""

    try:
        key = _get_key()
        if key is None:
            return value_str

        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        plaintext = value_str.encode('utf-8')
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        encrypted_data = base64.urlsafe_b64encode(nonce + ciphertext).decode('ascii')
        return ENCRYPTED_VALUE_PREFIX + encrypted_data
    except Exception:
        print("Encryption failed, returning original value")
        return value_str


def decrypt_config_value(value: str) -> str:
    if not value:
        return ""

    value_str = str(value).strip()
    if not value_str:
        return ""

    if not is_encrypted_value(value_str):
        return value_str

    try:
        key = _get_key()
        if key is None:
            return value_str

        encrypted_data = value_str[len(ENCRYPTED_VALUE_PREFIX):]
        raw = base64.urlsafe_b64decode(encrypted_data.encode('ascii'))

        if len(raw) < 12:
            return value_str

        nonce = raw[:12]
        ciphertext = raw[12:]
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode('utf-8')
    except Exception:
        return value_str

