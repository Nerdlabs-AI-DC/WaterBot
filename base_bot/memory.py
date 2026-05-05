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
import json
import time
import base64
import storage
import numpy as np
from config import MEMORY_LIMIT, MEMORY_KEY_B64
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from api_client import embed_text

MEMORIES_FILE = 'memories_enc'  # storage blob key
_USER_MEMORIES_FILE = 'user_memories_enc'

_MEMORIES_CACHE = None
_USER_MEMORIES_CACHE = None

def _get_key() -> bytes:
    if not MEMORY_KEY_B64:
        raise RuntimeError("MEMORY_KEY is not set!")
    key = base64.urlsafe_b64decode(MEMORY_KEY_B64)
    if len(key) != 32:
        raise ValueError("MEMORY key must be 32 bytes for AES-256")
    return key

def _encrypt_bytes(plaintext: bytes) -> bytes:
    key = _get_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return base64.urlsafe_b64encode(nonce + ciphertext)

def _decrypt_bytes(data_b64: bytes) -> bytes:
    raw = base64.urlsafe_b64decode(data_b64)
    if len(raw) < 12:
        raise ValueError("Invalid encrypted data")
    nonce = raw[:12]
    ciphertext = raw[12:]
    key = _get_key()
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)

def _read_json_encrypted(path_or_key):
    key = str(path_or_key)
    if key == str('memories.json') or key.endswith('memories.json'):
        key = MEMORIES_FILE
    if key == str('user_memories.json') or key.endswith('user_memories.json'):
        key = _USER_MEMORIES_FILE
    b = storage.get_blob(key) if key in (MEMORIES_FILE, _USER_MEMORIES_FILE) else storage.get_encrypted_blob_for_path(key)
    if not b:
        return None
    try:
        dec = _decrypt_bytes(b)
        return json.loads(dec.decode('utf-8'))
    except Exception:
        try:
            return json.loads(b.decode('utf-8'))
        except Exception:
            return None

def _write_json_encrypted(path_or_key, obj):
    key = str(path_or_key)
    if key == str('memories.json') or key.endswith('memories.json'):
        key = MEMORIES_FILE
    if key == str('user_memories.json') or key.endswith('user_memories.json'):
        key = _USER_MEMORIES_FILE
    plain = json.dumps(obj, indent=2, ensure_ascii=False).encode('utf-8')
    enc = _encrypt_bytes(plain)
    storage.set_blob(key, enc)

def init_memory_files():
    if _read_json_encrypted(MEMORIES_FILE) is None:
        _write_json_encrypted(MEMORIES_FILE, {"summaries": [], "memories": []})
    if _read_json_encrypted(_USER_MEMORIES_FILE) is None:
        _write_json_encrypted(_USER_MEMORIES_FILE, {})

def load_memory_cache():
    global _MEMORIES_CACHE, _USER_MEMORIES_CACHE
    data = _read_json_encrypted(MEMORIES_FILE) or {"summaries": [], "memories": []}
    if isinstance(data, dict):
        summaries = list(data.get("summaries", []))
        memories = list(data.get("memories", []))
    else:
        summaries = []
        memories = []
    _MEMORIES_CACHE = {"summaries": summaries, "memories": memories}

    udata = _read_json_encrypted(_USER_MEMORIES_FILE) or {}
    _USER_MEMORIES_CACHE = {}
    if isinstance(udata, dict):
        for k, v in udata.items():
            if isinstance(v, dict):
                usum = list(v.get("summaries", []))
                umem = list(v.get("memories", []))
            else:
                usum = []
                umem = []
            _USER_MEMORIES_CACHE[k] = {"summaries": usum, "memories": umem}
    else:
        _USER_MEMORIES_CACHE = {}

def _encode_embedding(emb: list) -> str:
    arr = np.array(emb, dtype=np.float32)
    return base64.urlsafe_b64encode(arr.tobytes()).decode('ascii')

def _decode_embedding(b64: str) -> np.ndarray:
    raw = base64.urlsafe_b64decode(b64.encode('ascii'))
    return np.frombuffer(raw, dtype=np.float32)

def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    if a.size == 0 or b.size == 0:
        return 0.0
    da = np.linalg.norm(a)
    db = np.linalg.norm(b)
    if da == 0 or db == 0:
        return 0.0
    return float(np.dot(a, b) / (da * db))


def add_memory_to_cache(summary: str, full_memory: str) -> int:
    global _MEMORIES_CACHE
    if _MEMORIES_CACHE is None:
        load_memory_cache()
    if _MEMORIES_CACHE is None:
        _MEMORIES_CACHE = {"summaries": [], "memories": []}

    try:
        emb = embed_text(summary)
        emb_b64 = _encode_embedding(emb)
    except Exception:
        emb_b64 = ""

    summaries = _MEMORIES_CACHE.setdefault("summaries", [])
    memories = _MEMORIES_CACHE.setdefault("memories", [])
    if len(summaries) >= MEMORY_LIMIT:
        summaries.pop(0)
        memories.pop(0)
    summaries.append({"text": summary, "embedding": emb_b64})
    memories.append(full_memory)
    return len(summaries)

def add_user_memory_to_cache(user_id: str, summary: str, full_memory: str) -> int:
    global _USER_MEMORIES_CACHE
    user_key = str(user_id)
    if _USER_MEMORIES_CACHE is None:
        load_memory_cache()
    if _USER_MEMORIES_CACHE is None:
        _USER_MEMORIES_CACHE = {}
    if user_key not in _USER_MEMORIES_CACHE:
        _USER_MEMORIES_CACHE[user_key] = {"summaries": [], "memories": []}

    try:
        emb = embed_text(summary)
        emb_b64 = _encode_embedding(emb)
    except Exception:
        emb_b64 = ""

    usum = _USER_MEMORIES_CACHE[user_key].setdefault("summaries", [])
    umem = _USER_MEMORIES_CACHE[user_key].setdefault("memories", [])
    if len(usum) >= MEMORY_LIMIT:
        usum.pop(0)
        umem.pop(0)
    usum.append({"text": summary, "embedding": emb_b64})
    umem.append(full_memory)
    return len(usum)

def flush_memory_cache():
    global _MEMORIES_CACHE, _USER_MEMORIES_CACHE
    if _MEMORIES_CACHE is not None:
        try:
            _write_json_encrypted(MEMORIES_FILE, {"summaries": _MEMORIES_CACHE.get("summaries", []), "memories": _MEMORIES_CACHE.get("memories", [])})
        except Exception:
            raise
    if _USER_MEMORIES_CACHE is not None:
        try:
            _write_json_encrypted(_USER_MEMORIES_FILE, _USER_MEMORIES_CACHE)
        except Exception:
            raise

def save_memory(summary: str, full_memory: str) -> int:
    global _MEMORIES_CACHE
    data = _read_json_encrypted(MEMORIES_FILE)
    if data is None:
        data = {"summaries": [], "memories": []}
    stored_summaries = data.get("summaries", [])
    new_summaries = []
    for s in stored_summaries:
        if isinstance(s, str):
            new_summaries.append({"text": s, "embedding": ""})
        else:
            new_summaries.append(s)
    data["summaries"] = new_summaries
    if len(data.get("summaries", [])) >= MEMORY_LIMIT:
        data["summaries"].pop(0)
        data["memories"].pop(0)

    try:
        emb = embed_text(summary)
        emb_b64 = _encode_embedding(emb)
    except Exception:
        emb_b64 = ""

    data.setdefault("summaries", []).append({"text": summary, "embedding": emb_b64})
    data.setdefault("memories", []).append(full_memory)
    _write_json_encrypted(MEMORIES_FILE, data)

    if _MEMORIES_CACHE is not None:
        _MEMORIES_CACHE.setdefault("summaries", []).append({"text": summary, "embedding": emb_b64})
        _MEMORIES_CACHE.setdefault("memories", []).append(full_memory)
        if len(_MEMORIES_CACHE.get("summaries", [])) > MEMORY_LIMIT:
            _MEMORIES_CACHE["summaries"].pop(0)
            _MEMORIES_CACHE["memories"].pop(0)
    return len(data["summaries"])

def get_memory_detail(index: int) -> str:
    global _MEMORIES_CACHE
    if _MEMORIES_CACHE is not None:
        memories = _MEMORIES_CACHE.get("memories", [])
    else:
        data = _read_json_encrypted(MEMORIES_FILE) or {"memories": []}
        memories = data.get("memories", [])
    if 1 <= index <= len(memories):
        return memories[index - 1]
    return ""

def delete_memory(index: int) -> bool:
    try:
        idx = int(index)
    except Exception:
        return False

    if idx < 1:
        return False

    data = _read_json_encrypted(MEMORIES_FILE) or {"summaries": [], "memories": []}
    summaries = data.get("summaries", [])
    memories = data.get("memories", [])

    if 1 <= idx <= len(memories):
        try:
            memories.pop(idx - 1)
            if idx - 1 < len(summaries):
                summaries.pop(idx - 1)
            data["summaries"] = summaries
            data["memories"] = memories
            _write_json_encrypted(MEMORIES_FILE, data)
            load_memory_cache()
            return True
        except Exception:
            raise
    return False

def get_all_summaries() -> list:
    global _MEMORIES_CACHE
    if _MEMORIES_CACHE is not None:
        items = _MEMORIES_CACHE.get("summaries", [])
    else:
        data = _read_json_encrypted(MEMORIES_FILE) or {"summaries": []}
        items = data.get("summaries", [])
    return [s["text"] if isinstance(s, dict) else s for s in items]

def save_user_memory(user_id: str, summary: str, full_memory: str) -> int:
    global _USER_MEMORIES_CACHE
    user_key = str(user_id)
    data = _read_json_encrypted(_USER_MEMORIES_FILE) or {}
    if user_key not in data:
        data[user_key] = {"summaries": [], "memories": []}

    usum = data[user_key].get("summaries", [])
    new_usum = []
    for s in usum:
        if isinstance(s, str):
            new_usum.append({"text": s, "embedding": ""})
        else:
            new_usum.append(s)
    data[user_key]["summaries"] = new_usum

    try:
        emb = embed_text(summary)
        emb_b64 = _encode_embedding(emb)
    except Exception:
        emb_b64 = ""

    if len(data[user_key].get("summaries", [])) >= MEMORY_LIMIT:
        data[user_key]["summaries"].pop(0)
        data[user_key]["memories"].pop(0)
    data[user_key].setdefault("summaries", []).append({"text": summary, "embedding": emb_b64})
    data[user_key].setdefault("memories", []).append(full_memory)
    _write_json_encrypted(_USER_MEMORIES_FILE, data)

    if _USER_MEMORIES_CACHE is not None:
        if user_key not in _USER_MEMORIES_CACHE:
            _USER_MEMORIES_CACHE[user_key] = {"summaries": [], "memories": []}
        _USER_MEMORIES_CACHE[user_key].setdefault("summaries", []).append({"text": summary, "embedding": emb_b64})
        _USER_MEMORIES_CACHE[user_key].setdefault("memories", []).append(full_memory)
        if len(_USER_MEMORIES_CACHE[user_key].get("summaries", [])) > MEMORY_LIMIT:
            _USER_MEMORIES_CACHE[user_key]["summaries"].pop(0)
            _USER_MEMORIES_CACHE[user_key]["memories"].pop(0)
    return len(data[user_key]["summaries"])

def get_user_memory_detail(user_id: str, index: int) -> str:
    user_key = str(user_id)
    global _USER_MEMORIES_CACHE
    if _USER_MEMORIES_CACHE is not None and user_key in _USER_MEMORIES_CACHE:
        memories = _USER_MEMORIES_CACHE[user_key].get("memories", [])
        if 1 <= index <= len(memories):
            return memories[index - 1]
    data = _read_json_encrypted(_USER_MEMORIES_FILE) or {}
    if user_key in data:
        memories = data[user_key].get("memories", [])
        if 1 <= index <= len(memories):
            return memories[index - 1]
    return ""

def get_user_summaries(user_id: str) -> list:
    user_key = str(user_id)
    global _USER_MEMORIES_CACHE
    if _USER_MEMORIES_CACHE is not None and user_key in _USER_MEMORIES_CACHE:
        return [s["text"] if isinstance(s, dict) else s for s in _USER_MEMORIES_CACHE[user_key].get("summaries", [])]
    data = _read_json_encrypted(_USER_MEMORIES_FILE) or {}
    if user_key in data:
        return [s["text"] if isinstance(s, dict) else s for s in data[user_key].get("summaries", [])]
    return []

def find_relevant_memories(query: str, top_k: int = 5, user_id: str = None) -> list:
    try:
        q_vec = np.array(query, dtype=np.float32)
    except Exception:
        q_vec = None

    if user_id is not None:
        data = _USER_MEMORIES_CACHE if _USER_MEMORIES_CACHE is not None else (_read_json_encrypted(_USER_MEMORIES_FILE) or {})
        user_key = str(user_id)
        items = []
        if isinstance(data, dict) and user_key in data:
            items = data[user_key].get("summaries", [])
    else:
        data = _MEMORIES_CACHE if _MEMORIES_CACHE is not None else (_read_json_encrypted(MEMORIES_FILE) or {"summaries": []})
        items = data.get("summaries", [])

    scored = []
    for i, s in enumerate(items):
        if isinstance(s, dict):
            text = s.get("text", "")
            emb_b64 = s.get("embedding", "")
            if q_vec is None or not emb_b64:
                score = 0.0
            else:
                try:
                    emb_vec = _decode_embedding(emb_b64)
                    score = _cosine(q_vec, emb_vec)
                except Exception:
                    score = 0.0
        else:
            text = s
            score = 0.0
        scored.append((i + 1, text, float(score)))
    scored.sort(key=lambda x: x[2], reverse=True)
    results = []
    for idx, text, score in scored[:top_k]:
        results.append({"index": idx, "summary": text, "score": score})
    return results

def save_context(user_id: str, channel_id: str) -> None:
    current_time = time.time()
    context = storage.get_context() or {}
    context[str(user_id)] = {"channel_id": channel_id, "timestamp": current_time}
    storage.save_context(context)

def get_channel_by_user(user_id: str):
    context = storage.get_context() or {}
    data = context.get(str(user_id), {})
    if isinstance(data, dict):
        return data.get("channel_id", ""), data.get("timestamp", 0)
    return "", 0

def delete_user_memory(user_id: str, index: int) -> bool:
    try:
        idx = int(index)
    except Exception:
        return False

    if idx < 1:
        return False

    key = str(user_id)
    data = _read_json_encrypted(_USER_MEMORIES_FILE) or {}
    if key not in data:
        return False

    usum = data[key].get("summaries", [])
    umem = data[key].get("memories", [])

    if 1 <= idx <= len(umem):
        try:
            umem.pop(idx - 1)
            if idx - 1 < len(usum):
                usum.pop(idx - 1)
            data[key]["summaries"] = usum
            data[key]["memories"] = umem
            _write_json_encrypted(_USER_MEMORIES_FILE, data)
            load_memory_cache()
            return True
        except Exception:
            raise
    return False

def delete_user_memories(user_id: str) -> bool:
    key = str(user_id)
    data = _read_json_encrypted(_USER_MEMORIES_FILE) or {}
    if key in data:
        try:
            del data[key]
            _write_json_encrypted(_USER_MEMORIES_FILE, data)
            load_memory_cache()
            return True
        except Exception:
            raise
    return False