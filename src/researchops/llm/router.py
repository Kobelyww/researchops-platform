"""Model routing: cheap models for routing/extraction, strong models for
planning/debugging/review. Cost & usage per call are recorded for the
observability layer.
"""

from __future__ import annotations

from typing import Any

from ..observability.cost import estimate_cost
from .base import LLMProvider, LLMResponse

TASK_KINDS = ("routing", "extraction", "planning", "debugging", "review", "general")


class ModelRouter:
    """Routes each completion to the configured provider/model for its task kind."""

    def __init__(self, default_provider: LLMProvider, routes: dict[str, tuple[LLMProvider, str]] | None = None):
        self.default_provider = default_provider
        # kind -> (provider, model); unmapped kinds use the default provider.
        self.routes: dict[str, tuple[LLMProvider, str]] = routes or {}

    def resolve(self, hints: dict[str, Any] | None = None) -> tuple[LLMProvider, str]:
        hints = hints or {}
        kind = str(hints.get("task_kind", "general"))
        if kind in self.routes:
            provider, model = self.routes[kind]
            return provider, model
        return self.default_provider, getattr(self.default_provider, "model", "default")

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        hints: dict[str, Any] | None = None,
    ) -> LLMResponse:
        provider, _model = self.resolve(hints)
        response = await provider.complete(
            messages, tools=tools, temperature=temperature, max_tokens=max_tokens, hints=hints
        )
        response.cost_usd = estimate_cost(  # type: ignore[attr-defined]
            response.model, response.usage.input_tokens, response.usage.output_tokens
        )
        return response
