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

import hashlib
import numpy as np
from config import KNOWLEDGE_ITEMS
from memory import _cosine
from api_client import embed_text
from storage import load_knowledge, save_knowledge

def _hash_text(text: str) -> str:
    return hashlib.sha256(text.strip().encode("utf-8")).hexdigest()

def sync_knowledge():
    knowledge_data = load_knowledge()
    current_hashes = {}
    changed = False

    for item in KNOWLEDGE_ITEMS:
        h = _hash_text(item)
        current_hashes[item] = h

        if item not in knowledge_data:
            print(f"Found new knowledge: {item[:60]}...")
            emb = embed_text(item)
            knowledge_data[item] = {"hash": h, "embedding": emb}
            changed = True
        elif knowledge_data[item].get("hash") != h:
            print(f"Found edited knowledge: {item[:60]}...")
            emb = embed_text(item)
            knowledge_data[item] = {"hash": h, "embedding": emb}
            changed = True

    to_remove = [k for k in knowledge_data.keys() if k not in current_hashes]
    for k in to_remove:
        print(f"Deleted knowledge: {k[:60]}...")
        del knowledge_data[k]
        changed = True

    if changed:
        save_knowledge(knowledge_data)
        print(f"Updated knowledge database ({len(KNOWLEDGE_ITEMS)} items).")
    else:
        print("Knowledge up-to-date.")

def find_relevant_knowledge(query_emb, top_k: int = 3) -> list:
    try:
        q_vec = np.array(query_emb, dtype=np.float32)
    except Exception:
        q_vec = None

    data = load_knowledge()
    scored = []

    for i, (text, info) in enumerate(data.items()):
        emb = np.array(info.get("embedding", []), dtype=np.float32)
        if q_vec is None or emb.size == 0:
            score = 0.0
        else:
            try:
                score = _cosine(q_vec, emb)
            except Exception:
                score = 0.0

        scored.append((i + 1, text, float(score)))

    scored.sort(key=lambda x: x[2], reverse=True)

    results = []
    for idx, text, score in scored[:top_k]:
        results.append({
            "index": idx,
            "text": text,
            "score": score,
        })

    return results