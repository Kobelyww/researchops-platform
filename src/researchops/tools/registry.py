"""Tool registry with JSON-schema validation.

Tools are plain async functions plus a JSON-schema contract; the registry
validates arguments, enforces timeouts, and exposes OpenAI tool-call schemas.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.errors import ToolError

Handler = Callable[..., Awaitable[Any]]


@dataclass
class ToolExecContext:
    """Runtime context handed to every tool invocation."""

    run_id: str
    workspace: Path
    sandbox: Any = None  # SandboxManager
    memory: Any = None  # MemoryStore
    retriever: Any = None  # HybridRetriever (semantic memory)
    browser_domains: Any = None  # list[str]
    browser_max_pages: int = 10


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON schema
    handler: Handler
    timeout_s: float = 60.0

    def validate(self, args: dict[str, Any]) -> dict[str, Any]:
        """Minimal JSON-schema validation: required keys + primitive types."""
        props = self.parameters.get("properties", {})
        required = self.parameters.get("required", [])
        missing = [k for k in required if k not in args]
        if missing:
            raise ToolError(f"tool '{self.name}' missing required args: {missing}")
        type_map = {"string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict}
        for key, value in args.items():
            if key not in props:
                continue  # allow extra keys (models get creative); handler ignores them
            expected = type_map.get(props[key].get("type"))
            if expected and not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
                raise ToolError(f"tool '{self.name}' arg '{key}' expected {props[key].get('type')}, got {type(value).__name__}")
        return args

    def openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {"name": self.name, "description": self.description, "parameters": self.parameters},
        }


def tool(
    name: str,
    description: str,
    parameters: dict,
    timeout_s: float = 60.0,
) -> Callable[[Handler], Handler]:
    """Decorator that registers metadata on an async function for later registration."""

    def decorate(fn: Handler) -> Handler:
        fn.__tool_meta__ = {"name": name, "description": description, "parameters": parameters, "timeout_s": timeout_s}
        return fn

    return decorate


@dataclass
class ToolRegistry:
    tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, t: Tool) -> None:
        if t.name in self.tools:
            raise ValueError(f"duplicate tool name: {t.name}")
        self.tools[t.name] = t

    def register_fn(self, fn: Handler) -> Tool:
        meta = getattr(fn, "__tool_meta__", None)
        if not meta:
            raise ValueError(f"{fn!r} is not decorated with @tool")
        t = Tool(handler=fn, **meta)
        self.register(t)
        return t

    def get(self, name: str) -> Tool:
        if name not in self.tools:
            raise ToolError(f"unknown tool: {name}")
        return self.tools[name]

    def schemas(self, names: list[str] | None = None) -> list[dict]:
        selected = [self.tools[n] for n in names if n in self.tools] if names else list(self.tools.values())
        return [t.openai_schema() for t in selected]

    async def execute(self, name: str, args: dict[str, Any], tctx: ToolExecContext, timeout_s: float | None = None) -> Any:
        t = self.get(name)
        args = t.validate(args)
        try:
            coro = t.handler(tctx, **args)
            if inspect.iscoroutinefunction(t.handler):
                return await asyncio.wait_for(coro, timeout=timeout_s or t.timeout_s)
            return await asyncio.wait_for(asyncio.to_thread(lambda: asyncio.run(t.handler(tctx, **args))), timeout_s or t.timeout_s)
        except asyncio.TimeoutError:
            raise ToolError(f"tool '{name}' timed out after {timeout_s or t.timeout_s}s") from None

    @staticmethod
    def observation(result: Any, max_chars: int = 8000) -> str:
        if isinstance(result, str):
            text = result
        else:
            try:
                text = json.dumps(result, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                text = str(result)
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n... [truncated {len(text) - max_chars} chars]"
        return text
