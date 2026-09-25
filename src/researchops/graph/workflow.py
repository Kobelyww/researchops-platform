"""LangGraph workflow assembly: START → ingest → plan → select ⟶ agents ⟶
evaluate ⟶ (diagnose→repair)* ⟶ approve ⟶ report → END, with DB-backed
human-approval gates woven in.
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from . import nodes
from .routing import (
    NODE_BY_KIND,
    route_after_approve,
    route_after_await_approval,
    route_after_evaluate,
    route_after_experiment,
    route_by_kind,
)
from .state import AgentState


def build_workflow(checkpointer: BaseCheckpointSaver | None = None):
    g = StateGraph(AgentState)

    g.add_node("ingest", nodes.ingest)
    g.add_node("plan", nodes.plan)
    g.add_node("select", nodes.route_select)
    g.add_node("research", nodes.research)
    g.add_node("repository", nodes.repository)
    g.add_node("code", nodes.code)
    g.add_node("synthesize", nodes.synthesize)
    g.add_node("experiment", nodes.experiment)
    g.add_node("evaluate", nodes.evaluate)
    g.add_node("diagnose", nodes.diagnose)
    g.add_node("repair", nodes.repair)
    g.add_node("await_approval", nodes.await_approval)
    g.add_node("approve", nodes.approve)
    g.add_node("report", nodes.report)
    g.add_node("finalize_rejected", nodes.finalize_rejected)

    g.add_edge(START, "ingest")
    g.add_edge("ingest", "plan")
    g.add_edge("plan", "select")

    g.add_conditional_edges("select", route_by_kind, list(NODE_BY_KIND.values()) + ["await_approval", "evaluate"])
    for task_node in ("research", "repository", "code"):
        g.add_edge(task_node, "select")

    g.add_edge("synthesize", "experiment")
    g.add_conditional_edges("experiment", route_after_experiment, ["await_approval", "evaluate"])
    g.add_conditional_edges("evaluate", route_after_evaluate, ["approve", "diagnose"])
    g.add_edge("diagnose", "repair")
    g.add_edge("repair", "experiment")

    # approval gates: END while a decision is missing; worker resumes via invoke(None)
    g.add_conditional_edges(
        "await_approval",
        route_after_await_approval,
        ["plan", "report", "finalize_rejected", "research", "repository", "code", "experiment", "repair", END],
    )
    g.add_conditional_edges("approve", route_after_approve, ["await_approval", "report", "finalize_rejected"])

    g.add_edge("report", END)
    g.add_edge("finalize_rejected", END)

    return g.compile(checkpointer=checkpointer)
