"""Embeddings: OpenAI-compatible endpoint or offline feature-hashing fallback."""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

import httpx
import numpy as np

DIM = 256


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[np.ndarray]: ...


class HashEmbedder:
    """Deterministic offline embedder (feature hashing over token frequencies).

    Not semantically deep, but stable and dependency-free — enough for hybrid
    retrieval in dev mode and for the offline demo/test-suite.
    """

    def __init__(self, dim: int = DIM):
        self.dim = dim

    async def embed(self, texts: list[str]) -> list[np.ndarray]:
        return [self._one(t) for t in texts]

    def _one(self, text: str) -> np.ndarray:
        vec = np.zeros(self.dim, dtype=np.float32)
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            h = int.from_bytes(hashlib.md5(token.encode()).digest()[:8], "big")
            idx = h % self.dim
            sign = 1.0 if (h >> 63) & 1 == 0 else -1.0
            vec[idx] += sign
        norm = float(np.linalg.norm(vec))
        return vec / norm if norm > 0 else vec


class OpenAIEmbedder:
    def __init__(self, model: str, api_key: str, base_url: str = "https://api.openai.com/v1"):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def embed(self, texts: list[str]) -> list[np.ndarray]:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/embeddings",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": self.model, "input": texts},
            )
            resp.raise_for_status()
            return [np.array(d["embedding"], dtype=np.float32) for d in resp.json()["data"]]


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    denom = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom > 0 else 0.0


def create_embedder(provider: str, model: str, api_key: str, base_url: str) -> Embedder:
    if provider == "openai" and api_key:
        return OpenAIEmbedder(model=model, api_key=api_key, base_url=base_url)
    return HashEmbedder()
