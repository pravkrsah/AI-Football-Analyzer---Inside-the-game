import json
import math
import os
from backend.ai_client import get_embed_client
import backend.config as config

_moments: list[dict] = []
_embeddings: list[list[float]] = []
_cache_path = os.path.join(os.path.dirname(__file__), "..", "data", "embeddings_cache.json")

def _embed(texts: list[str]) -> list[list[float]]:
    resp = get_embed_client().embeddings.create(
        model=config.AZURE_OPENAI_EMBEDDING_DEPLOYMENT,
        input=texts,
    )
    return [item.embedding for item in resp.data]

def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    return dot / (norm_a * norm_b + 1e-10)

def load_historical_moments():
    global _moments, _embeddings

    data_path = os.path.join(os.path.dirname(__file__), "..", "data", "historical_moments.json")
    with open(data_path) as f:
        _moments = json.load(f)

    if os.path.exists(_cache_path):
        with open(_cache_path) as f:
            cache = json.load(f)
        if len(cache) == len(_moments):
            _embeddings = cache
            print(f"[EmbeddingSearch] Loaded {len(_moments)} cached embeddings")
            return

    print(f"[EmbeddingSearch] Computing embeddings for {len(_moments)} historical moments...")
    texts = [f"{m['match']} minute {m['minute']}: {m['description']}" for m in _moments]
    _embeddings = _embed(texts)

    with open(_cache_path, "w") as f:
        json.dump(_embeddings, f)
    print("[EmbeddingSearch] Embeddings cached.")

def find_similar_moments(query: str, top_k: int = 3) -> list[dict]:
    if not _embeddings or not _moments:
        return []

    try:
        query_vec = _embed([query])[0]
    except Exception:
        # Embeddings API unavailable — return top moments by recency as fallback
        return [{**m, "similarity_score": 0.0} for m in _moments[:top_k]]

    scores = [_cosine_similarity(query_vec, _embeddings[i]) for i in range(len(_moments))]
    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
    return [{**_moments[i], "similarity_score": round(scores[i], 4)} for i in top_indices]

def find_similar_to_event(event: dict, top_k: int = 3) -> list[dict]:
    query = f"minute {event['minute']} {event.get('type', '')} {event.get('player', '')} {event.get('description', '')}"
    return find_similar_moments(query, top_k)
