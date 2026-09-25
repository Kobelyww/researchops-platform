"""Runtime wiring: builds a fully-connected RunContext from Settings."""

from __future__ import annotations

from pathlib import Path

from .agents.loop import RunContext
from .config import Settings
from .core.events import EventBus
from .guardrails.gateway import ApprovalLedger, ToolGateway
from .guardrails.policy import PolicyEngine
from .llm.mock import MockProvider
from .llm.openai_compat import OpenAICompatProvider
from .llm.router import ModelRouter
from .memory.retrieval import HybridRetriever
from .memory.semantic import create_embedder
from .memory.store import MemoryStore
from .observability.metrics import RunMetrics
from .observability.tracing import TraceCollector
from .sandbox.manager import SandboxPolicy, create_sandbox
from .tools.browser import BROWSER_TOOLS
from .tools.filesystem import FILESYSTEM_TOOLS
from .tools.github import GITHUB_TOOLS
from .tools.memory_search import MEMORY_TOOLS
from .tools.registry import ToolExecContext, ToolRegistry
from .tools.search import RESEARCH_TOOLS
from .tools.shell import SHELL_TOOLS


def build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for fn in [*FILESYSTEM_TOOLS, *SHELL_TOOLS, *RESEARCH_TOOLS, *GITHUB_TOOLS, *MEMORY_TOOLS, *BROWSER_TOOLS]:
        registry.register_fn(fn)
    return registry


def build_llm_router(settings: Settings) -> tuple[ModelRouter, MockProvider | None]:
    """Returns (router, mock_provider_or_none). Mock provider is returned so
    callers can script offline demos/tests."""
    mock_provider: MockProvider | None = None
    if settings.llm_provider == "mock":
        mock_provider = MockProvider()
        default_provider: OpenAICompatProvider | MockProvider = mock_provider
    else:
        default_provider = OpenAICompatProvider(
            model=settings.llm_model, api_key=settings.llm_api_key,
            base_url=settings.llm_base_url, timeout_s=settings.llm_timeout_s,
        )
    routes: dict[str, tuple[object, str]] = {}
    for kind, model in settings.model_routes_map.items():
        if isinstance(default_provider, OpenAICompatProvider):
            routes[kind] = (OpenAICompatProvider(
                model=model, api_key=settings.llm_api_key, base_url=settings.llm_base_url,
                timeout_s=settings.llm_timeout_s), model)
        else:
            routes[kind] = (default_provider, model)
    router = ModelRouter(default_provider, routes)  # type: ignore[arg-type]
    return router, mock_provider


async def build_run_context(
    settings: Settings,
    store: MemoryStore,
    run_id: str,
    task_id: str,
    goal: str,
    requirements: list[str],
    auto_approve: bool,
) -> RunContext:
    workspace = settings.workspace_path / run_id
    workspace.mkdir(parents=True, exist_ok=True)

    events = EventBus()
    metrics = RunMetrics()
    tracer = TraceCollector(run_id, events, metrics)

    async def persist_event(event: dict) -> None:
        await store.add_event(run_id, event)

    events.subscribe(run_id, persist_event)

    ledger = ApprovalLedger(auto_approve=auto_approve)
    # Approval rows are persisted by graph nodes (single creation point);
    # the ledger only tracks granted/rejected signatures per run.

    registry = build_registry()
    policy = PolicyEngine(auto_approve=auto_approve, allow_high_risk_auto=auto_approve)
    gateway = ToolGateway(registry, policy, ledger, metrics, tracer, max_tool_calls=settings.max_tool_calls)

    sandbox = create_sandbox(
        workspace, settings.sandbox_backend, settings.sandbox_image,
        SandboxPolicy(timeout_s=settings.sandbox_timeout_s, mem_limit_mb=settings.sandbox_mem_limit_mb, cpus=settings.sandbox_cpus),
    )

    embedder = create_embedder(settings.embedding_provider, settings.embedding_model, settings.llm_api_key, settings.llm_base_url)
    retriever = HybridRetriever(embedder)
    tctx = ToolExecContext(
        run_id=run_id, workspace=workspace, sandbox=sandbox, memory=store, retriever=retriever,
        browser_domains=settings.browser_domains, browser_max_pages=settings.browser_max_pages,
    )

    router, _mock = build_llm_router(settings)

    return RunContext(
        run_id=run_id, task_id=task_id, goal=goal, requirements=requirements, auto_approve=auto_approve,
        llm=router, registry=registry, tools=gateway, tctx=tctx, sandbox=sandbox, memory=store,
        events=events, metrics=metrics, tracer=tracer, ledger=ledger, settings=settings,
        workspace=Path(workspace),
    )
