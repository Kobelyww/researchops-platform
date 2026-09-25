"""OpenAI-compatible chat-completions client (hand-rolled on httpx).

Deliberately small: explicit retries, full usage capture, tool-call parsing —
no SDK lock-in, works against any /v1/chat/completions endpoint.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from .base import LLMResponse, ToolCallReq, Usage


class OpenAICompatProvider:
    def __init__(
        self,
        model: str,
        api_key: str = "",
        base_url: str = "https://api.openai.com/v1",
        timeout_s: float = 90.0,
        max_retries: int = 3,
    ):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s
        self.max_retries = max_retries

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        hints: dict[str, Any] | None = None,
    ) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        json=payload,
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                    )
                if resp.status_code in (429, 500, 502, 503, 504):
                    last_exc = RuntimeError(f"upstream {resp.status_code}: {resp.text[:200]}")
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                resp.raise_for_status()
                return self._parse(resp.json())
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                await asyncio.sleep(0.5 * (2**attempt))
        raise RuntimeError(f"LLM request failed after {self.max_retries} retries: {last_exc}")

    def _parse(self, data: dict) -> LLMResponse:
        choice = data["choices"][0]
        msg = choice.get("message", {})
        tool_calls = [
            ToolCallReq(
                id=tc.get("id", f"call_{i}"),
                name=tc["function"]["name"],
                arguments=json.loads(tc["function"].get("arguments") or "{}"),
            )
            for i, tc in enumerate(msg.get("tool_calls") or [])
        ]
        usage = data.get("usage", {}) or {}
        return LLMResponse(
            content=msg.get("content"),
            tool_calls=tool_calls,
            usage=Usage(
                input_tokens=int(usage.get("prompt_tokens", 0)),
                output_tokens=int(usage.get("completion_tokens", 0)),
            ),
            finish_reason=choice.get("finish_reason", "stop"),
            model=data.get("model", self.model),
        )
