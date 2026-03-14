# ========================= engines/memory_engine.py =========================
import json
import os
import re
import threading
from ollama import Client
import config

client = Client(host='http://localhost:11434')
MIN_SIMILARITY = 0.60
_MIN_MEANINGFUL_LEN = 20    # Characters — ignore casual short messages
MAX_VECTOR_MEMORIES = 5000  # Prune oldest entries beyond this limit

# In-memory cache to avoid re-parsing vector_store.json on every call
_vs_cache: list | None = None
_vs_mtime: float = 0.0
_vs_lock = threading.Lock()
_write_lock = threading.Lock()   # serialise read-modify-write in add_memory


def _load_vector_store() -> list:
    """Load vector store with mtime-based caching."""
    global _vs_cache, _vs_mtime
    path = config.VECTOR_STORE
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return []
    mtime = os.path.getmtime(path)
    with _vs_lock:
        if _vs_cache is not None and mtime == _vs_mtime:
            return _vs_cache
    data = config.safe_load_json(path, [])
    if not isinstance(data, list):
        data = []
    with _vs_lock:
        _vs_cache = data
        _vs_mtime = mtime
    return data


def _invalidate_cache():
    """Mark cache as stale after a write."""
    global _vs_cache, _vs_mtime
    with _vs_lock:
        _vs_cache = None
        _vs_mtime = 0.0


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
    data = _load_vector_store()
    if not data:
        return []

    q_emb = get_embedding(query)
    if not q_emb: return []

    scored = []
    for item in data:
        if 'embedding' not in item: continue
        score = similarity(q_emb, item['embedding'])
        if score >= MIN_SIMILARITY:
            scored.append((score, item['text']))

    scored.sort(reverse=True)
    return [text for sc, text in scored[:top_k]]


def add_memory(text: str) -> bool:
    """
    Store a meaningful statement in the vector store for later retrieval.
    Returns True if stored, False if skipped (too short or embedding failed).

    Only stores text >= _MIN_MEANINGFUL_LEN characters.
    Embedding is generated and stored alongside the text.
    """
    if not text or len(text.strip()) < _MIN_MEANINGFUL_LEN:
        return False

    embedding = get_embedding(text)
    if not embedding:
        return False

    import tempfile

    with _write_lock:
        # Load existing store (list of {text, embedding} dicts)
        data = _load_vector_store()

        data.append({"text": text.strip(), "embedding": embedding})

        # Prune oldest entries to stay within the size limit
        if len(data) > MAX_VECTOR_MEMORIES:
            data = data[-MAX_VECTOR_MEMORIES:]

        dir_name = os.path.dirname(config.VECTOR_STORE) or '.'
        os.makedirs(dir_name, exist_ok=True)
        try:
            fd, tmp = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
            try:
                with os.fdopen(fd, 'w') as f:
                    json.dump(data, f)
                os.replace(tmp, config.VECTOR_STORE)
            except Exception:
                os.unlink(tmp)
                raise
            _invalidate_cache()
            return True
        except Exception as e:
            print(f"[MemoryEngine] Failed to save vector store: {e}")
            return False
