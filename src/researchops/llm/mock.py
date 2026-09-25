"""Deterministic offline mock provider.

Drives agents with scripted responses so the entire platform — planning,
research, experiments, HITL interrupts, reports — runs end-to-end with zero
API keys. Powers the test-suite and the offline demo.
"""

from __future__ import annotations

from typing import Any

from .base import LLMResponse, ToolCallReq, Usage

# A scripted turn: either ("tool", name, args) or ("final", content).
MockTurn = tuple


class MockProvider:
    """Returns scripted responses per agent name (from `hints["agent"]`).

    When the script is exhausted the provider falls back to a benign final
    answer, so unscripted agents always terminate.
    """

    def __init__(self, scripts: dict[str, list[MockTurn]] | None = None):
        self.scripts: dict[str, list[MockTurn]] = scripts or {}
        self._cursor: dict[str, int] = {}
        self.calls: list[dict[str, Any]] = []

    def script(self, agent: str) -> list[MockTurn]:
        return self.scripts.setdefault(agent, [])

    def _next(self, agent: str) -> MockTurn:
        agent_key = agent or "__default__"
        idx = self._cursor.get(agent_key, 0)
        self._cursor[agent_key] = idx + 1
        seq = self.scripts.get(agent_key, [])
        if idx < len(seq):
            return seq[idx]
        return ("final", "Done.")

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        hints: dict[str, Any] | None = None,
    ) -> LLMResponse:
        hints = hints or {}
        agent = str(hints.get("agent", ""))
        self.calls.append({"agent": agent, "messages": len(messages)})
        turn = self._next(agent)
        usage = Usage(input_tokens=120, output_tokens=40)
        if turn[0] == "tool":
            return LLMResponse(
                content=None,
                tool_calls=[ToolCallReq(id=f"mock_{len(self.calls)}", name=turn[1], arguments=turn[2])],
                usage=usage,
                finish_reason="tool_calls",
                model="mock-1",
            )
        return LLMResponse(
            content=turn[1],
            tool_calls=[],
            usage=usage,
            finish_reason="stop",
            model="mock-1",
        )

    # -- convenience for building scripts -----------------------------------
    @staticmethod
    def tool(name: str, **args: Any) -> MockTurn:
        return ("tool", name, args)

    @staticmethod
    def final(content: str) -> MockTurn:
        return ("final", content)
