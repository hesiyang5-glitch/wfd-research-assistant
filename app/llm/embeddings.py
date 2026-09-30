"""Optional embeddings for semantic retrieval via an OpenAI-compatible /embeddings endpoint.
Set EMBEDDING_MODEL (and EMBEDDING_BASE_URL / EMBEDDING_API_KEY, defaulting to the OPENAI_* values).
Works with a local Ollama server (e.g. EMBEDDING_BASE_URL=http://localhost:11434/v1, EMBEDDING_MODEL=nomic-embed-text)."""
from __future__ import annotations

import httpx

from .. import db
from ..config import env


def embed_texts(texts: list[str], cache_ids: list[str] | None = None) -> list[list[float]]:
    model = env("EMBEDDING_MODEL")
    base = env("EMBEDDING_BASE_URL", env("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
    key = env("EMBEDDING_API_KEY", env("OPENAI_API_KEY"))
    out: list = [None] * len(texts)
    todo = []
    for i, t in enumerate(texts):
        if cache_ids:
            c = db.cache_get(f"emb:{model}:{cache_ids[i]}")
            if c:
                out[i] = c
                continue
        todo.append(i)
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    for start in range(0, len(todo), 64):
        batch = todo[start:start + 64]
        r = httpx.post(f"{base}/embeddings", json={"model": model, "input": [texts[i] for i in batch]},
                       headers=headers, timeout=120)
        r.raise_for_status()
        for i, item in zip(batch, r.json()["data"]):
            out[i] = item["embedding"]
            if cache_ids:
                db.cache_put(f"emb:{model}:{cache_ids[i]}", item["embedding"])
    return out
