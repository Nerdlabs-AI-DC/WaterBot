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

import sqlite3
import json
import threading
import time
import os
import base64
from pathlib import Path
from datetime import datetime, timezone, timedelta
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_DB_PATH = Path("data") / "storage.db"
_LOCK = threading.Lock()
_CONN = None


def _get_conn():
    global _CONN
    if _CONN is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CONN = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _CONN.execute("PRAGMA journal_mode=WAL;")
        _init_db(_CONN)
    return _CONN


def _init_db(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS kv (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS blobs (
        key TEXT PRIMARY KEY,
        value BLOB
    )
    """)
    conn.commit()


def get_json(key: str, default=None):
    try:
        with _LOCK:
            cur = _get_conn().cursor()
            cur.execute("SELECT value FROM kv WHERE key = ?", (key,))
            row = cur.fetchone()
            if not row:
                return default
            return json.loads(row[0])
    except Exception:
        return default


def set_json(key: str, obj) -> None:
    try:
        val = json.dumps(obj, ensure_ascii=False)
        with _LOCK:
            conn = _get_conn()
            conn.execute("REPLACE INTO kv (key, value) VALUES (?, ?)", (key, val))
            conn.commit()
    except Exception:
        raise


def get_blob(key: str):
    try:
        with _LOCK:
            cur = _get_conn().cursor()
            cur.execute("SELECT value FROM blobs WHERE key = ?", (key,))
            row = cur.fetchone()
            if not row:
                return None
            return row[0]
    except Exception:
        return None


def set_blob(key: str, data: bytes) -> None:
    try:
        with _LOCK:
            conn = _get_conn()
            conn.execute("REPLACE INTO blobs (key, value) VALUES (?, ?)", (key, data))
            conn.commit()
    except Exception:
        raise


def load_settings():
    return get_json('serversettings', {}) or {}


def save_settings(settings: dict):
    set_json('serversettings', settings or {})


def load_daily_counts():
    return get_json('daily_message_counts', {}) or {}


def save_daily_counts(data: dict):
    set_json('daily_message_counts', data or {})


def load_recent_questions():
    return get_json('recent_questions', {}) or {}


def save_recent_questions(data: dict):
    set_json('recent_questions', data or {})


def load_daily_quiz_records():
    return get_json('daily_quiz_records', {}) or {}


def save_daily_quiz_records(data: dict):
    set_json('daily_quiz_records', data or {})


def load_metrics():
    return get_json('metrics', {}) or {}


def save_metrics(data: dict):
    set_json('metrics', data or {})


def load_user_metrics():
    return get_json('user_metrics', {}) or {}


def save_user_metrics(data: dict):
    set_json('user_metrics', data or {})


def get_freewill_attempts():
    return get_json('recent_freewill', {}) or {}


def save_freewill_attempts(data: dict):
    set_json('recent_freewill', data or {})


def get_context():
    return get_json('context_memory', {}) or {}


def save_context(data: dict):
    set_json('context_memory', data or {})


def get_blob_key_for_path(path_name: str) -> str:
    # map legacy filenames to blob keys
    if 'memories' in path_name:
        return 'memories_enc'
    if 'user_memories' in path_name:
        return 'user_memories_enc'
    return path_name


def get_encrypted_blob_for_path(path_name: str):
    return get_blob(get_blob_key_for_path(path_name))


def set_encrypted_blob_for_path(path_name: str, data: bytes):
    return set_blob(get_blob_key_for_path(path_name), data)


def load_knowledge():
    return get_json('knowledge_data', {}) or {}

def save_knowledge(data: dict):
    set_json('knowledge_data', data or {})


def load_banned_users():
    data = get_json('banned_users', []) or []
    try:
        if isinstance(data, dict):
            return [int(k) for k in data.keys()]
        return [int(x) for x in data]
    except Exception:
        return []


def save_banned_users(user_list):
    try:
        data = [int(x) for x in (user_list or [])]
    except Exception:
        data = []
    set_json('banned_users', data)


def load_banned_map():
    raw = get_json('banned_users', {}) or {}
    try:
        if isinstance(raw, dict):
            out = {}
            for k, v in raw.items():
                try:
                    out[int(k)] = v or {}
                except Exception:
                    continue
            return out
        if isinstance(raw, list):
            return {int(x): {'notified': False} for x in raw}
    except Exception:
        pass
    return {}


def save_banned_map(banned_map: dict):
    try:
        serial = {str(int(k)): (v or {}) for k, v in (banned_map or {}).items()}
        set_json('banned_users', serial)
    except Exception:
        raise


def mark_banned_user_notified(user_id: int):
    try:
        bm = load_banned_map()
        if int(user_id) in bm:
            bm[int(user_id)]['notified'] = True
            save_banned_map(bm)
    except Exception:
        pass


def is_banned_user_notified(user_id: int) -> bool:
    try:
        bm = load_banned_map()
        meta = bm.get(int(user_id))
        if not meta:
            return False
        return bool(meta.get('notified'))
    except Exception:
        return False


def _get_image_key() -> bytes | None:
    try:
        from config import MEMORY_KEY_B64
        if not MEMORY_KEY_B64:
            return None
        key = base64.urlsafe_b64decode(MEMORY_KEY_B64)
        if len(key) != 32:
            raise ValueError("MEMORY key must be 32 bytes for AES-256")
        return key
    except Exception:
        return None


def _encrypt_image_description(plaintext: str) -> str:
    key = _get_image_key()
    if not key:
        return plaintext
    try:
        aesgcm = AESGCM(key)
        nonce = os.urandom(12)
        plaintext_bytes = plaintext.encode('utf-8')
        ciphertext = aesgcm.encrypt(nonce, plaintext_bytes, None)
        return base64.urlsafe_b64encode(nonce + ciphertext).decode('utf-8')
    except Exception:
        return plaintext


def _decrypt_image_description(encrypted: str) -> str:
    key = _get_image_key()
    if not key:
        return encrypted
    try:
        raw = base64.urlsafe_b64decode(encrypted.encode('utf-8'))
        if len(raw) < 12:
            return encrypted
        nonce = raw[:12]
        ciphertext = raw[12:]
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode('utf-8')
    except Exception:
        return encrypted


def load_image_descriptions() -> dict:
    return get_json('image_descriptions', {}) or {}


def get_image_description(attach_id) -> str | None:
    try:
        imgs = load_image_descriptions()
        ent = imgs.get(str(attach_id))
        if not ent:
            return None
        try:
            ent['last_used'] = datetime.now(timezone.utc).isoformat()
            imgs[str(attach_id)] = ent
            set_json('image_descriptions', imgs)
        except Exception:
            pass
        description = ent.get('description')
        if description:
            description = _decrypt_image_description(description)
        return description
    except Exception:
        return None


def save_image_description(attach_id, description: str) -> None:
    try:
        imgs = load_image_descriptions()
        encrypted_description = _encrypt_image_description(description)
        imgs[str(attach_id)] = {
            'description': encrypted_description,
            'last_used': datetime.now(timezone.utc).isoformat()
        }
        set_json('image_descriptions', imgs)
    except Exception:
        raise


def prune_image_descriptions(age_hours: int = 24) -> list:
    try:
        imgs = load_image_descriptions()
        now = datetime.now(timezone.utc)
        removed = []
        for k, v in list(imgs.items()):
            lu = v.get('last_used') if isinstance(v, dict) else None
            if not lu:
                removed.append(k)
                del imgs[k]
                continue
            try:
                last_used = datetime.fromisoformat(lu)
                if last_used.tzinfo is None:
                    last_used = last_used.replace(tzinfo=timezone.utc)
            except Exception:
                removed.append(k)
                del imgs[k]
                continue
            if (now - last_used) > timedelta(hours=age_hours):
                removed.append(k)
                del imgs[k]
        if removed:
            set_json('image_descriptions', imgs)
        return removed
    except Exception:
        return []


def load_rpa_history() -> dict:
    return get_json('rpa_history', {}) or {}


def save_rpa_history(data: dict):
    set_json('rpa_history', data or {})


def get_rpa_user_history(user_id: int) -> list:
    all_history = load_rpa_history()
    return all_history.get(str(user_id), [])


def append_rpa_match(user_id: int, match: dict) -> None:
    all_history = load_rpa_history()
    key = str(user_id)
    matches = all_history.get(key, [])
    matches.append(match)
    if len(matches) > 10:
        matches = matches[-10:]
    all_history[key] = matches
    save_rpa_history(all_history)