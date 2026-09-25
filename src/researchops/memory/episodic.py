"""Episodic memory: past errors and their fixes, retrievable by similarity."""

from __future__ import annotations

from dataclasses import dataclass

from .retrieval import HybridRetriever


@dataclass
class Episode:
    error_summary: str
    solution: str
    run_id: str = ""


class EpisodicMemory:
    def __init__(self, retriever: HybridRetriever):
        self.retriever = retriever

    async def record(self, error_summary: str, solution: str, run_id: str = "") -> None:
        await self.retriever.add(
            f"error: {error_summary}\nsolution: {solution}",
            {"kind": "episode", "run_id": run_id},
        )

    async def recall_similar(self, error_text: str, k: int = 3) -> list[Episode]:
        hits = await self.retriever.search(error_text, k=k)
        episodes = []
        for h in hits:
            if h["meta"].get("kind") != "episode":
                continue
            body = h["text"]
            if "\nsolution: " in body:
                err, sol = body.split("\nsolution: ", 1)
                episodes.append(Episode(error_summary=err.removeprefix("error: "), solution=sol, run_id=h["meta"].get("run_id", "")))
        return episodes
