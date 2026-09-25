"""Mock provider scripting, model routing, cost accounting, store basics."""

from __future__ import annotations

import pytest

from researchops.core.events import EventBus
from researchops.llm.base import Usage
from researchops.llm.mock import MockProvider
from researchops.llm.openai_compat import OpenAICompatProvider
from researchops.llm.router import ModelRouter
from researchops.observability.cost import estimate_cost
from researchops.observability.metrics import RunMetrics


async def test_mock_provider_scripts_per_agent():
    provider = MockProvider({
        "planner": [MockProvider.final('{"tasks": [{"id": "t1", "kind": "research"}]}')],
        "researcher": [MockProvider.tool("search_papers", query="x"), MockProvider.final("done")],
    })
    resp = await provider.complete([{"role": "user", "content": "go"}], hints={"agent": "planner"})
    assert resp.content and "tasks" in resp.content

    resp = await provider.complete([{"role": "user", "content": "go"}], hints={"agent": "researcher"})
    assert resp.tool_calls[0].name == "search_papers"
    resp = await provider.complete([{"role": "user", "content": "go"}], hints={"agent": "researcher"})
    assert resp.content == "done"
    # unscripted agent falls back to benign final answer
    resp = await provider.complete([], hints={"agent": "stranger"})
    assert resp.content == "Done."


async def test_model_router_routes_and_costs():
    routed = MockProvider({"review": []})
    default = MockProvider({})
    router = ModelRouter(default, routes={"review": (routed, "review-model")})

    await router.complete([{"role": "user", "content": "x"}], hints={"agent": "reviewer", "task_kind": "review"})
    assert routed.calls, "review kind should hit the routed provider"

    resp = await router.complete([], hints={"task_kind": "general"})
    assert resp.model == "mock-1"


def test_cost_estimation():
    assert estimate_cost("gpt-4o-mini", 1_000_000, 1_000_000) == pytest.approx(0.75)
    assert estimate_cost("unknown-model", 1000, 1000) == 0.0
    assert estimate_cost("gpt-4o-mini-2024", 1_000_000, 0) == pytest.approx(0.15)


def test_metrics_roundtrip():
    m = RunMetrics()
    m.add_usage(10, 5, 0.01)
    m.tool_calls = 3
    d = m.to_dict()
    assert RunMetrics.from_dict(d).tool_calls == 3
    assert RunMetrics.from_dict(d).cost_usd == 0.01


def test_openai_provider_parses_payload():
    provider = OpenAICompatProvider(model="m")
    parsed = provider._parse({
        "model": "m",
        "choices": [{
            "message": {
                "content": None,
                "tool_calls": [{"id": "c1", "function": {"name": "search", "arguments": '{"query": "x"}'}}],
            },
            "finish_reason": "tool_calls",
        }],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    })
    assert parsed.tool_calls[0].arguments == {"query": "x"}
    assert parsed.usage.input_tokens == 11 and parsed.usage.output_tokens == 7
    assert isinstance(Usage(), Usage)
    assert EventBus() is not None
