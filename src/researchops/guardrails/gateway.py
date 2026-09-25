"""The Tool Gateway — every tool call passes through here, never straight from
the LLM to the world.

Pipeline per call:
    registry lookup → argument-injection scan → risk classification →
    budget check → policy decision (auto / approve / deny) →
    audit record → sandboxed execution with timeout → audit result
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from ..core.errors import ApprovalRequired, BudgetExceeded, PolicyViolation
from ..core.types import stable_hash
from ..observability.metrics import RunMetrics
from ..observability.tracing import TraceCollector
from ..tools.registry import ToolExecContext, ToolRegistry
from .injection import scan as injection_scan
from .permissions import classify
from .policy import PolicyEngine

ApprovalCreator = Callable[[dict[str, Any]], Awaitable[str]]


@dataclass
class ApprovalLedger:
    """Per-run approval state (DB-backed in production, in-memory in tests)."""

    auto_approve: bool = False
    granted: set[str] = field(default_factory=set)
    rejected: set[str] = field(default_factory=set)
    creator: ApprovalCreator | None = None


class ToolGateway:
    def __init__(
        self,
        registry: ToolRegistry,
        policy: PolicyEngine,
        ledger: ApprovalLedger,
        metrics: RunMetrics,
        tracer: TraceCollector,
        max_tool_calls: int = 200,
    ):
        self.registry = registry
        self.policy = policy
        self.ledger = ledger
        self.metrics = metrics
        self.tracer = tracer
        self.max_tool_calls = max_tool_calls
        self.audit: list[dict[str, Any]] = []

    def signature(self, tool_name: str, args: dict[str, Any]) -> str:
        return stable_hash({"tool": tool_name, "args": args})

    async def execute(self, caller: str, tool_name: str, args: dict[str, Any], tctx: ToolExecContext) -> Any:
        # 1. allowlist
        try:
            t = self.registry.get(tool_name)
        except Exception as exc:
            raise PolicyViolation(f"unknown tool '{tool_name}'") from exc

        # 2. argument injection scan (forged role tags are hard-denied)
        report = injection_scan(str(args))
        if "tool_forge" in report.findings:
            raise PolicyViolation("forged role/system tag in tool arguments")

        # 3. risk + budget
        risk = classify(tool_name, args)
        if self.metrics.tool_calls >= self.max_tool_calls:
            raise BudgetExceeded(f"tool-call budget exhausted ({self.max_tool_calls})")

        # 4. policy decision
        sig = self.signature(tool_name, args)
        decision = self.policy.evaluate(tool_name, risk, sig in self.ledger.granted, sig in self.ledger.rejected)
        if not decision.allowed and decision.needs_approval:
            # The graph node that catches this exception owns approval-row
            # persistence (single creation point); the gateway only gates.
            self.metrics.approvals_requested += 1
            raise ApprovalRequired(
                action=tool_name, detail=args, risk=risk.value, signature=sig,
                estimated_cost_usd=0.0, estimated_minutes=round((t.timeout_s or 60) / 60, 1),
            )
        if not decision.allowed:
            raise PolicyViolation(decision.reason)

        # 5. execute with audit trail
        self.metrics.tool_calls += 1
        span = self.tracer.start(f"tool:{tool_name}", agent=caller, tool=tool_name, risk=risk.value)
        await self.tracer.event("tool", f"{caller} → {tool_name}", agent=caller, data={"args": args, "risk": risk.value})
        record: dict[str, Any] = {"tool": tool_name, "caller": caller, "risk": risk.value, "args": args, "status": "ok"}
        started = time.monotonic()
        try:
            result = await self.registry.execute(tool_name, args, tctx, timeout_s=t.timeout_s)
        except Exception as exc:
            self.metrics.failed_calls += 1
            record.update({"status": "error", "error": str(exc)[:300]})
            self.tracer.end(span, status="error", error=str(exc)[:200])
            await self.tracer.event("tool_error", f"{tool_name} failed: {exc}", agent=caller, level="warn")
            raise
        finally:
            record["latency_ms"] = round((time.monotonic() - started) * 1000, 1)
            self.audit.append(record)
        self.tracer.end(span)
        return result
