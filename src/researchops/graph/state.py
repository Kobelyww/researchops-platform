"""LangGraph state schema — the durable, serializable brain of a run."""

from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    # identity
    task_id: str
    run_id: str
    user_goal: str
    requirements: list[str]
    auto_approve: bool

    # plan & progress
    plan: list[dict[str, Any]]  # TaskNode.model_dump()
    current_task: str | None
    task_outputs: dict[str, Any]  # task_id -> summary dict
    feedback: list[str]  # operator "modify" feedback for re-planning

    # collected knowledge
    papers: list[dict[str, Any]]
    repositories: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    artifacts: list[dict[str, Any]]

    # experiments
    experiment_instruction: str
    experiments: list[dict[str, Any]]
    evaluation: dict[str, Any]
    diagnosis: str
    repair_attempts: int

    # human-in-the-loop
    pending_approval: dict[str, Any] | None
    approval_decision: dict[str, Any] | None

    # lifecycle
    status: str
    errors: list[dict[str, Any]]
    report_md: str | None
