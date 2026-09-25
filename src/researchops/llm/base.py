"""LLM provider abstraction.

A minimal, framework-free protocol so the agent loop stays provider-agnostic.
Any OpenAI-compatible endpoint works (OpenAI, DeepSeek, Together, vLLM,
Ollama); the MockProvider makes the whole system runnable offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class ToolCallReq:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    content: str | None
    tool_calls: list[ToolCallReq]
    usage: Usage
    finish_reason: str
    model: str


def tool_schema(name: str, description: str, parameters: dict) -> dict:
    """JSON-schema tool definition (OpenAI function-calling format)."""
    return {
        "type": "function",
        "function": {"name": name, "description": description, "parameters": parameters},
    }


class LLMProvider(Protocol):
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        hints: dict[str, Any] | None = None,
    ) -> LLMResponse: ...
