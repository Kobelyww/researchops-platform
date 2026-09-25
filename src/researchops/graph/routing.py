"""Routing functions — pure, deterministic state transitions (no LLM)."""

from __future__ import annotations

from typing import Any

from ..core.types import TaskStatus

NODE_BY_KIND = {
    "research": "research",
    "repository": "repository",
    "code": "code",
    "experiment": "synthesize",  # experiment tasks enter via synthesize
}


def _tasks(state: dict[str, Any]) -> list[dict[str, Any]]:
    return list(state.get("plan") or [])


def next_ready_task(state: dict[str, Any]) -> dict[str, Any] | None:
    """First pending task whose dependencies are done (topological order)."""
    done = {t["id"] for t in _tasks(state) if t.get("status") == TaskStatus.DONE.value}
    for t in _tasks(state):
        if t.get("status") != TaskStatus.PENDING.value:
            continue
        if set(t.get("depends_on") or []) <= done:
            return t
    return None


def route_by_kind(state: dict[str, Any]) -> str:
    """After `select`: dispatch the chosen task, or move to synthesis/eval."""
    if state.get("pending_approval"):
        return "await_approval"
    if state.get("status") == "failed":
        return "evaluate"
    current = state.get("current_task")
    if current:
        task = next((t for t in _tasks(state) if t.get("id") == current), None)
        if task:
            return NODE_BY_KIND.get(str(task.get("kind")), "research")
    if any(t.get("kind") == "experiment" and t.get("status") != TaskStatus.DONE.value for t in _tasks(state)):
        return "synthesize"
    return "evaluate"


def route_after_experiment(state: dict[str, Any]) -> str:
    if state.get("pending_approval"):
        return "await_approval"
    return "evaluate"


def route_after_evaluate(state: dict[str, Any]) -> str:
    evaluation = state.get("evaluation") or {}
    if evaluation.get("success"):
        return "approve"
    if state.get("repair_attempts", 0) < evaluation.get("max_repair_attempts", 0):
        return "diagnose"
    return "approve"  # human decides whether a failure report is still useful


def route_after_await_approval(state: dict[str, Any]) -> str:
    decision = state.get("approval_decision") or {}
    kind = decision.get("kind", "")
    if kind == "modified":
        return "plan"
    if kind == "rejected":
        return "finalize_rejected"
    if kind == "approved":
        return str(decision.get("resume_node", "report"))
    return END_SENTINEL  # still waiting on the operator


END_SENTINEL = "__end__"


def route_after_approve(state: dict[str, Any]) -> str:
    if state.get("pending_approval"):
        return "await_approval"  # human sign-off needed
    decision = state.get("approval_decision") or {}
    if decision:
        return "finalize_rejected" if decision.get("kind") == "rejected" else "report"
    return "await_approval"
