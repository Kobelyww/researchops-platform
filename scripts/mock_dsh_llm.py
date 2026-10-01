"""Deterministic OpenAI-compatible mock LLM for the dsh vertical slice.

Serves scripted streaming chat.completions so the dsh researchops profile runs
fully offline (no API key): the model first calls the mounted Python research
MCP tool (real arXiv data flows back), then attempts a bash command (which the
ResearchOps guardrail policy gates), then produces a final cited answer keyed
on what it actually observed.

Run:  .venv/bin/python scripts/mock_dsh_llm.py --port 8901
"""

from __future__ import annotations

import argparse
import json
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()
STATE: dict[str, dict[str, Any]] = {}  # conversation key -> counters


def _extract(messages: list[dict]) -> dict[str, Any]:
    """Classify where this request sits in the scripted conversation."""
    tool_results = [m for m in messages if m.get("role") == "tool"]
    tool_blob = json.dumps(tool_results, default=str)
    searched = any("search_papers" in json.dumps(m.get("tool_calls") or [], default=str) for m in messages)
    ran_bash = any('"bash"' in json.dumps(m.get("tool_calls") or [], default=str) for m in messages)
    return {
        "tool_results": tool_results,
        "tool_blob": tool_blob,
        "searched": searched,
        "ran_bash": ran_bash,
        "n_tools": len(tool_results),
    }


def _paper_title(state: dict[str, Any]) -> str:
    """Pull a real paper title out of the MCP tool result (proves data flowed)."""
    import re

    blob = state["tool_blob"]
    for marker in ('"title": "', '\\"title\\": \\"', '"title":"'):
        idx = blob.find(marker)
        if idx >= 0:
            start = idx + len(marker)
            end = start
            while end < len(blob) and blob[end] not in '"\\':
                end += 1
            title = blob[start:end].strip()
            if title:
                return title[:120]
    m = re.search(r"(Contrastive|Speaker|Verification)[^\"]{5,90}", blob)
    if m:
        return m.group(0)[:120]
    return "the surveyed paper"


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    state = _extract(messages)

    tool_calls: list[dict] | None = None
    content: str | None = None
    finish = "tool_calls"

    if not state["searched"]:
        tool_calls = [{
            "id": "call_search_1", "type": "function", "index": 0,
            "function": {"name": "mcp__research__search_papers",
                         "arguments": json.dumps({"query": "contrastive learning speaker verification", "max_results": 3})},
        }]
    elif not state["ran_bash"]:
        tool_calls = [{
            "id": "call_bash_1", "type": "function", "index": 0,
            "function": {"name": "bash",
                         "arguments": json.dumps({
                             "command": "echo 'baseline extraction check: acc=0.82' > metrics.txt && cat metrics.txt",
                             "description": "Run the baseline extraction check inside the sandbox"})},
        }]
    else:
        finish = "stop"
        denied = "requires approval" in state["tool_blob"] or "DENIED by policy" in state["tool_blob"]
        title = _paper_title(state)
        gate = ("The bash verification step was gated by the ResearchOps guardrail policy in this run; "
                "with auto-approval the metrics step would execute in the sandbox." if denied else
                "The sandbox command executed and its output is included in the run log.")
        content = (
            f"## ResearchOps report\n\nBased on arXiv evidence retrieved through the research MCP server, "
            f"the leading result is \u201c{title}\u201d. {gate}\n\n"
            f"Sources: [arXiv search results retrieved this session]."
        )

    async def sse():
        chunk_id = f"chatcmpl-mock-{int(time.time()*1000)}"
        base = {"id": chunk_id, "object": "chat.completion.chunk", "created": int(time.time()), "model": "researchops-mock-1"}

        def chunk(delta: dict, finish_reason: str | None = None) -> str:
            return "data: " + json.dumps({
                **base,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
            }) + "\n\n"

        yield chunk({"role": "assistant"})

        if tool_calls:
            for i, tc in enumerate(tool_calls):
                yield chunk({"tool_calls": [{"index": i, "id": tc["id"], "type": "function",
                                             "function": {"name": tc["function"]["name"], "arguments": ""}}]})
                yield chunk({"tool_calls": [{"index": i, "function": {"arguments": tc["function"]["arguments"]}}]})
        elif content:
            for line in content.split("\n"):
                yield chunk({"content": line + "\n"})

        yield chunk({}, finish_reason=finish)
        if body.get("stream_options", {}).get("include_usage"):
            usage = {**base, "choices": [], "usage": {"prompt_tokens": 220, "completion_tokens": 60, "total_tokens": 280}}
            yield "data: " + json.dumps(usage) + "\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(sse(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/v1/models")
async def models():
    return {"object": "list", "data": [{"id": "researchops-mock-1", "object": "model", "owned_by": "researchops"}]}


if __name__ == "__main__":
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8901)
    args = parser.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port)
