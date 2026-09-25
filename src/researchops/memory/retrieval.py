"""Hybrid retrieval: BM25 (lexical) + dense vectors, fused with Reciprocal
Rank Fusion, then optional context selection. Deliberately dependency-free.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from .semantic import Embedder, cosine


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


class BM25Index:
    """Okapi BM25 (k1=1.5, b=0.75)."""

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.doc_tokens: list[list[str]] = []
        self.doc_freq: dict[str, int] = {}
        self.avgdl = 0.0

    def fit(self, docs: list[str]) -> None:
        self.doc_tokens = [tokenize(d) for d in docs]
        self.avgdl = sum(len(t) for t in self.doc_tokens) / max(len(self.doc_tokens), 1)
        self.doc_freq = {}
        for tokens in self.doc_tokens:
            for term in set(tokens):
                self.doc_freq[term] = self.doc_freq.get(term, 0) + 1

    def _idf(self, term: str) -> float:
        n = len(self.doc_tokens)
        df = self.doc_freq.get(term, 0)
        return math.log((n - df + 0.5) / (df + 0.5) + 1)

    def scores(self, query: str) -> list[float]:
        q_tokens = tokenize(query)
        out = []
        for tokens in self.doc_tokens:
            tf: dict[str, int] = {}
            for t in tokens:
                tf[t] = tf.get(t, 0) + 1
            score = 0.0
            for term in q_tokens:
                if term in tf:
                    score += self._idf(term) * tf[term] * (self.k1 + 1) / (
                        tf[term] + self.k1 * (1 - self.b + self.b * len(tokens) / max(self.avgdl, 1))
                    )
            out.append(score)
        return out


def rrf_fuse(rankings: list[list[int]], k: int = 60) -> list[int]:
    """Reciprocal Rank Fusion over multiple ranked id lists."""
    scores: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return [doc_id for doc_id, _ in sorted(scores.items(), key=lambda kv: -kv[1])]


@dataclass
class Chunk:
    text: str
    meta: dict[str, Any] = field(default_factory=dict)
    embedding: np.ndarray | None = None


class HybridRetriever:
    """In-process hybrid retriever over added chunks (per-run / per-workspace).

    Production swaps the vector half for pgvector; the BM25+RRF half is identical.
    """

    def __init__(self, embedder: Embedder):
        self.embedder = embedder
        self.chunks: list[Chunk] = []
        self._bm25 = BM25Index()

    async def add(self, text: str, meta: dict[str, Any] | None = None) -> None:
        emb = (await self.embedder.embed([text]))[0]
        self.chunks.append(Chunk(text=text, meta=meta or {}, embedding=emb))
        self._bm25.fit([c.text for c in self.chunks])

    async def search(self, query: str, k: int = 5, candidates: int = 20) -> list[dict[str, Any]]:
        if not self.chunks:
            return []
        n = min(candidates, len(self.chunks))
        bm25 = self._bm25.scores(query)
        bm25_rank = [i for i, _ in sorted(enumerate(bm25), key=lambda kv: -kv[1])][:n]
        q_emb = (await self.embedder.embed([query]))[0]
        vec_scores = [cosine(q_emb, c.embedding) if c.embedding is not None else 0.0 for c in self.chunks]
        vec_rank = [i for i, _ in sorted(enumerate(vec_scores), key=lambda kv: -kv[1])][:n]
        fused = rrf_fuse([bm25_rank, vec_rank])[:k]
        return [
            {"text": self.chunks[i].text, "meta": self.chunks[i].meta, "bm25": bm25[i], "vector": vec_scores[i]}
            for i in fused
        ]
