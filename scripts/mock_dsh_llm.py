"""Deterministic OpenAI-compatible mock LLM for the dsh ResearchOps profile.

Routes on the [ResearchOps STAGE:<name>] marker the orchestrator puts in each
stage agent's first user message, so the full pipeline (planner → research →
experiment → repair → review) runs offline with zero API keys while REAL data
still flows (the search tool returns live arXiv results, bash runs in the
sandbox).

Run:  .venv/bin/python scripts/mock_dsh_llm.py --port 8901
"""

from __future__ import annotations

import argparse
import json
import re
import time
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

app = FastAPI()


def _last_user_text(messages: list[dict]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            content = m.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return "".join(b.get("text", "") for b in content if isinstance(b, dict))
    return ""


def _stage(messages: list[dict]) -> str:
    """The stage marker may not be in the LAST user message: dsh appends
    runtime-context user messages after the task prompt, so scan all of them."""
    for m in messages:
        if m.get("role") != "user":
            continue
        content = m.get("content")
        text = content if isinstance(content, str) else "".join(
            b.get("text", "") for b in content if isinstance(b, dict)) if isinstance(content, list) else ""
        found = re.search(r"\[ResearchOps STAGE:(\w+)\]", text or "")
        if found:
            return found.group(1)
    return "unknown"


def _tool_blob(messages: list[dict]) -> str:
    return json.dumps([m for m in messages if m.get("role") == "tool"], default=str)


def _ran_tool(messages: list[dict], name: str) -> bool:
    return any(name in json.dumps(m.get("tool_calls") or [], default=str) for m in messages)


def _paper_title(blob: str) -> str:
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
    return m.group(0)[:120] if m else "the surveyed paper"


def _decide(messages: list[dict]) -> tuple[list[dict] | None, str | None, str]:
    """Returns (tool_calls, content, finish_reason) for this stage request."""
    stage = _stage(messages)
    blob = _tool_blob(messages)
    finish = "tool_calls"

    if stage == "planner":
        return None, (
            '{"tasks": ['
            '{"id": "t1", "kind": "research", "title": "Survey contrastive speaker verification papers"}, '
            '{"id": "t2", "kind": "experiment", "title": "Run the baseline extraction check", "depends_on": ["t1"]}]}'
        ), "stop"

    if stage == "research":
        if not _ran_tool(messages, "search_papers"):
            return [{
                "id": "call_search_1", "type": "function", "index": 0,
                "function": {"name": "mcp__research__search_papers",
                             "arguments": json.dumps({"query": "contrastive learning speaker verification", "max_results": 3})},
            }], None, finish
        title = _paper_title(blob)
        return None, (
            f'Found relevant arXiv evidence. ```json {{"summary": "Contrastive objectives improve cross-lingual '
            f'speaker verification robustness; leading result: {title}.", "citations": ['
            f'{{"claim": "contrastive objectives improve cross-lingual robustness", "title": "{title}", '
            f'"url": "https://arxiv.org/abs/1705.03670v1"}}]}} ```'
        ), "stop"

    if stage in ("experiment", "repair"):
        if not _ran_tool(messages, "bash"):
            return [{
                "id": "call_bash_1", "type": "function", "index": 0,
                "function": {"name": "bash",
                             "arguments": json.dumps({
                                 "command": "echo 'baseline extraction check: acc=0.82' > metrics.txt && cat metrics.txt",
                                 "description": "Run the baseline extraction check inside the sandbox"})},
            }], None, finish
        executed = "acc=0.82" in blob
        metrics = {"accuracy": 0.82} if executed else {}
        report = {
            "experiment": "baseline extraction",
            "command": "echo 'baseline extraction check: acc=0.82' > metrics.txt && cat metrics.txt",
            "status": "success" if executed else "failed",
            "metrics": metrics,
            "log_excerpt": "baseline extraction check: acc=0.82" if executed else blob[-200:],
        }
        return None, f'```json {json.dumps(report)} ```', "stop"

    if stage == "review":
        # the reviewer is toolless: its evidence is the experiment JSON embedded
        # in the prompt (json.dumps escapes quotes, so match on plain tokens)
        everything = json.dumps(messages, default=str).replace("\\", "")
        approved = ('"status": "success"' in everything) or ('"status":"success"' in everything)
        return None, (
            '```json {"approved": ' + str(approved).lower() + ', "confidence": 0.9, "issues": []} ```'
        ), "stop"

    return None, "Done.", "stop"


@app.post("/v1/chat/completions")
async def chat(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    tool_calls, content, finish = _decide(messages)

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
