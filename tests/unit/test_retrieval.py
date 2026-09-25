"""Hybrid retrieval: BM25, RRF fusion, embeddings, episodic memory."""

from __future__ import annotations

from researchops.memory.episodic import EpisodicMemory
from researchops.memory.retrieval import BM25Index, HybridRetriever, rrf_fuse
from researchops.memory.semantic import HashEmbedder


def test_bm25_ranking():
    docs = [
        "contrastive learning for cross-lingual speaker verification",
        "vector databases for recommendation systems",
        "speaker verification with deep neural networks",
    ]
    idx = BM25Index()
    idx.fit(docs)
    scores = idx.scores("speaker verification contrastive")
    assert scores[0] > scores[1]
    assert scores[2] > scores[1]


def test_rrf_fusion():
    fused = rrf_fuse([[0, 1, 2], [1, 0, 2]])
    assert fused[0] in (0, 1)
    assert len(fused) == 3


async def test_hybrid_retriever_end_to_end():
    retriever = HybridRetriever(HashEmbedder())
    await retriever.add("Contrastive learning improves cross-lingual speaker verification robustness.", {"kind": "paper"})
    await retriever.add("The Evaluator III benchmark measures LLM agent task success.", {"kind": "paper"})
    await retriever.add("Pineapple pizza is a controversial culinary topic.", {"kind": "noise"})

    hits = await retriever.search("cross-lingual speaker verification", k=2)
    assert "speaker verification" in hits[0]["text"]
    assert len(hits) == 2


async def test_episodic_memory_roundtrip():
    retriever = HybridRetriever(HashEmbedder())
    memory = EpisodicMemory(retriever)
    await memory.record("ModuleNotFoundError: no module named torch", "pip install torch in the sandbox first", run_id="r1")
    await memory.record("CUDA out of memory", "reduce batch size", run_id="r2")

    episodes = await memory.recall_similar("ModuleNotFoundError: no module named torch", k=2)
    assert episodes and "torch" in episodes[0].solution
