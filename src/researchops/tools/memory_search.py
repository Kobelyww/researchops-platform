"""memory_search tool: semantic lookup over everything the run has collected."""

from __future__ import annotations

from .registry import ToolExecContext, tool


@tool(name="memory_search", description="Semantic search over this run's collected papers, docs and code summaries.", parameters={
    "type": "object", "properties": {"query": {"type": "string"}, "k": {"type": "integer"}}, "required": ["query"]})
async def memory_search(tctx: ToolExecContext, query: str, k: int = 5) -> list[dict]:
    if tctx.retriever is None:
        return []
    hits = await tctx.retriever.search(query, k=max(1, min(k, 10)))
    return [{"text": h["text"], "meta": h["meta"]} for h in hits]


MEMORY_TOOLS = [memory_search]
