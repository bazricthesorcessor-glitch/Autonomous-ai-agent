# ========================= engines/memory_engine.py =========================
import json
import os
import re
from ollama import Client
import config

client = Client(host='http://localhost:11434')
MIN_SIMILARITY = 0.60

def get_embedding(text):
    if not text.strip(): return None
    try:
        clean_text = re.sub(r'\s+', ' ', text).strip()
        response = client.embeddings(model=config.EMBED_MODEL, prompt=clean_text)
        return response['embedding']
    except Exception as e:
        print(f"Embedding error: {e}")
        return None

def similarity(vec1, vec2):
    dot = sum(a * b for a, b in zip(vec1, vec2))
    norm1 = sum(a * a for a in vec1) ** 0.5
    norm2 = sum(b * b for b in vec2) ** 0.5
    return dot / (norm1 * norm2) if norm1 and norm2 else 0

def search_memory(query, top_k=3):
    if not os.path.exists(config.VECTOR_STORE) or os.path.getsize(config.VECTOR_STORE) == 0:
        return []

    q_emb = get_embedding(query)
    if not q_emb: return []

    data = config.safe_load_json(config.VECTOR_STORE, [])
    if not isinstance(data, list): return []

    scored = []
    for item in data:
        if 'embedding' not in item: continue
        score = similarity(q_emb, item['embedding'])
        if score >= MIN_SIMILARITY:
            scored.append((score, item['text']))

    scored.sort(reverse=True)
    return [text for sc, text in scored[:top_k]]
