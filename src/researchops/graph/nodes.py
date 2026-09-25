"""Graph node implementations.

Design rules:
- Deterministic decisions (routing, evaluation pre-checks, reports) are code.
- LLM agents only do the creative steps: planning, research, coding, review.
- Every node persists visible progress (events + run status) as it goes.
"""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.runnables import RunnableConfig

from ..agents import (
    CoderAgent,
    ExperimenterAgent,
    PlannerAgent,
    RepositoryAgent,
    ResearchAgent,
    ReviewerAgent,
)
from ..agents.loop import RunContext
from ..core.errors import ApprovalRequired, BudgetExceeded
from ..core.types import TaskStatus, new_id
from .report import build_report
from .state import AgentState

URL_RE = re.compile(r"https?://[^\s)\"'\]<>]+")


def _ctx(config: RunnableConfig) -> RunContext:
    return config["configurable"]["ctx"]


async def _emit(ctx: RunContext, type_: str, message: str, agent: str = "", level: str = "info", data: dict | None = None) -> None:
    await ctx.tracer.event(type_, message, agent=agent, level=level, data=data)


def _mark_task(state: AgentState, task_id: str, status: str, output: dict | None = None) -> list[dict[str, Any]]:
    plan = [dict(t) for t in (state.get("plan") or [])]
    for t in plan:
        if t.get("id") == task_id:
            t["status"] = status
    if output is not None:
        outputs = dict(state.get("task_outputs") or {})
        outputs[task_id] = output
        state = dict(state)
        state["task_outputs"] = outputs  # type: ignore[assignment]
        return plan
    return plan


def _grounded_urls(ctx: RunContext) -> set[str]:
    urls: set[str] = set()
    for obs in ctx.observations:
        urls.update(m.rstrip(".,;") for m in URL_RE.findall(obs))
    return urls


# ---------------------------------------------------------------- ingest ----
async def ingest(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    await ctx.memory.update_run(ctx.run_id, status="running")
    await _emit(ctx, "status", f"Ingesting goal: {ctx.goal[:120]}")
    return {"run_id": ctx.run_id, "task_id": ctx.task_id, "user_goal": ctx.goal,
            "requirements": list(ctx.requirements), "auto_approve": ctx.auto_approve,
            "status": "running", "errors": [], "repair_attempts": 0, "task_outputs": {}}


# ------------------------------------------------------------------ plan ----
async def plan(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    await _emit(ctx, "step", "Planner: decomposing goal into task graph", agent="planner")
    feedback: list[str] = list(state.get("feedback") or [])
    decision = state.get("approval_decision") or {}
    if decision.get("kind") == "modified" and decision.get("note"):
        feedback.append(str(decision["note"]))
    tasks = await PlannerAgent().plan(ctx, feedback=feedback or None)
    plan_dump = [t.model_dump(mode="json") for t in tasks]
    await _emit(ctx, "step", f"Plan: {len(plan_dump)} tasks → " + ", ".join(f"{t['id']}:{t['kind']}" for t in plan_dump), agent="planner")
    await ctx.memory.update_run(ctx.run_id, plan=plan_dump)
    return {"plan": plan_dump, "feedback": [], "approval_decision": None,
            "pending_approval": None, "repair_attempts": 0, "status": "running"}


# ------------------------------------------------------- task execution ----
async def _run_task_node(state: AgentState, config: dict, node_name: str) -> dict[str, Any]:
    ctx = _ctx(config)
    task_id = state.get("current_task")
    tasks = {t.get("id"): t for t in (state.get("plan") or [])}
    task = tasks.get(task_id) if task_id else None
    if task is None or task.get("status") != TaskStatus.RUNNING.value:
        return {}

    await _emit(ctx, "step", f"{node_name} agent: {task.get('title', '')}", agent=f"{node_name}_agent")
    try:
        if node_name == "research":
            result = await ResearchAgent().run(ctx, (
                f"Research task: {task.get('title')}\nDescription: {task.get('description')}\n"
                f"Overall goal: {ctx.goal}\nRequirements: {json.dumps(ctx.requirements)}\n"
                "Search arXiv and the allowlisted web. Produce findings with citations."
            ))
            summary = result.output
            papers = []
            for obj in [_extract_json(summary)]:
                if obj and isinstance(obj.get("papers"), list):
                    papers = obj["papers"]
            citations = [c.model_dump() for c in result.citations]
            grounded = _grounded_urls(ctx)
            for c in citations:
                c["verified"] = c.get("url") in grounded
            # feed semantic memory for later nodes
            if ctx.tctx.retriever is not None and summary:
                await ctx.tctx.retriever.add(summary[:4000], {"kind": "research", "task_id": task_id})
            return {"papers": papers or (state.get("papers") or []), "citations": citations,
                    "plan": _mark_task(state, str(task_id), TaskStatus.DONE.value, {"kind": "research", "summary": summary}),
                    "current_task": None, "status": "running"}
        if node_name == "repository":
            result = await RepositoryAgent().run(ctx, (
                f"Repository task: {task.get('title')}\nDescription: {task.get('description')}\n"
                f"Goal context: {ctx.goal}\nClone the repo, inspect it, report entrypoints and install command."
            ))
            obj = _extract_json(result.output) or {}
            repo_info = {"url": str(obj.get("repo_url", task.get("description", ""))[:300]), "name": str(obj.get("repo_url", "")).rsplit("/", 1)[-1],
                         "summary": str(obj.get("summary", result.output[:500])), "entrypoints": list(obj.get("entrypoints", []))[:10]}
            return {"repositories": list(state.get("repositories") or []) + [repo_info],
                    "plan": _mark_task(state, str(task_id), TaskStatus.DONE.value, {"kind": "repository", **repo_info}),
                    "current_task": None, "status": "running"}
        # code
        result = await CoderAgent().run(ctx, (
            f"Coding task: {task.get('title')}\nDescription: {task.get('description')}\nGoal: {ctx.goal}\n"
            "Implement/repair inside the workspace and verify by running the code."
        ))
        obj = _extract_json(result.output) or {}
        files = [str(f) for f in obj.get("files", [])][:20]
        return {"artifacts": list(state.get("artifacts") or []) + [{"path": f, "kind": "code"} for f in files],
                "plan": _mark_task(state, str(task_id), TaskStatus.DONE.value, {"kind": "code", "summary": str(obj.get("summary", result.output[:500]))}),
                "current_task": None, "status": "running"}
    except ApprovalRequired as exc:
        approval_id = await _request_approval(ctx, exc, resume_node=node_name)
        return {"pending_approval": {"approval_id": approval_id, "resume_node": node_name, "kind": "tool",
                                     "action": exc.action, "risk": exc.risk, "detail": exc.detail},
                "status": "awaiting_approval"}
    except BudgetExceeded as exc:
        return {"status": "failed", "errors": list(state.get("errors") or []) + [{"node": node_name, "message": str(exc)}]}


def _extract_json(text: str) -> dict | None:
    from ..agents.loop import extract_json_objects

    objs = extract_json_objects(text or "")
    return objs[0] if objs else None


async def _request_approval(ctx: RunContext, exc: ApprovalRequired, resume_node: str) -> str:
    approval_id = new_id("apr")
    await ctx.memory.create_approval({
        "run_id": ctx.run_id, "action": exc.action, "detail": exc.detail, "risk": exc.risk,
        "signature": exc.signature, "estimated_cost_usd": exc.estimated_cost_usd,
        "estimated_minutes": exc.estimated_minutes,
    }, approval_id)
    await _emit(ctx, "approval", f"Approval required: {exc.action} (risk={exc.risk})", level="warn",
                data={"approval_id": approval_id, "risk": exc.risk, "detail": exc.detail})
    await ctx.memory.update_run(ctx.run_id, status="awaiting_approval")
    return approval_id


async def research(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    return await _run_task_node(state, config, "research")


async def repository(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    return await _run_task_node(state, config, "repository")


async def code(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    return await _run_task_node(state, config, "code")


async def route_select(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Picks the next ready task before the router maps it to a node."""
    ctx = _ctx(config)
    from .routing import next_ready_task

    if state.get("pending_approval"):
        # suspended for approval: keep current_task so the resume node re-enters
        return {}
    task = next_ready_task(state)
    if task is None:
        return {"current_task": None}
    plan = [dict(t) for t in (state.get("plan") or [])]
    for t in plan:
        if t.get("id") == task.get("id"):
            t["status"] = TaskStatus.RUNNING.value
    await _emit(ctx, "step", f"Routing to task {task.get('id')} ({task.get('kind')})", agent="orchestrator")
    return {"current_task": task.get("id"), "plan": plan}


# ------------------------------------------------------------ synthesis ----
async def synthesize(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    outputs = state.get("task_outputs") or {}
    findings = "\n\n".join(str(v.get("summary", ""))[:1500] for v in outputs.values() if v.get("kind") == "research")
    repos = state.get("repositories") or []
    repo_lines = "\n".join(f"- {r.get('name')}: entrypoints={r.get('entrypoints')}" for r in repos)
    experiment_task = next((t for t in (state.get("plan") or []) if t.get("kind") == "experiment" and t.get("status") == TaskStatus.PENDING.value), None)
    instruction = (
        f"Experiment task: {experiment_task.get('title') if experiment_task else 'baseline run'}\n"
        f"Description: {experiment_task.get('description') if experiment_task else 'run a baseline'}\n"
        f"Goal: {ctx.goal}\nRequirements: {json.dumps(ctx.requirements)}\n\n"
        f"Research findings to verify empirically:\n{findings[:3000]}\n\n"
        f"Known repositories:\n{repo_lines}\n\n"
        "Create any needed files in the workspace, then run the experiment and parse real numeric metrics from output."
    )
    plan = [dict(t) for t in (state.get("plan") or [])]
    current = None
    if experiment_task:
        for t in plan:
            if t.get("id") == experiment_task.get("id"):
                t["status"] = TaskStatus.RUNNING.value
        current = experiment_task.get("id")
    await _emit(ctx, "step", "Synthesizing experiment spec from findings", agent="orchestrator")
    return {"experiment_instruction": instruction, "plan": plan, "current_task": current}


async def experiment(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    instruction = state.get("experiment_instruction") or f"Run a baseline experiment for: {ctx.goal}"
    task_id = state.get("current_task") or next(
        (t.get("id") for t in (state.get("plan") or []) if t.get("kind") == "experiment"), None
    )
    await _emit(ctx, "step", "Experimenter: executing in sandbox", agent="experimenter")
    try:
        result = await ExperimenterAgent().run(ctx, instruction)
    except ApprovalRequired as exc:
        approval_id = await _request_approval(ctx, exc, resume_node="experiment")
        return {"pending_approval": {"approval_id": approval_id, "resume_node": "experiment", "kind": "tool",
                                     "action": exc.action, "risk": exc.risk, "detail": exc.detail},
                "status": "awaiting_approval"}
    except BudgetExceeded as exc:
        return {"status": "failed", "errors": list(state.get("errors") or []) + [{"node": "experiment", "message": str(exc)}]}

    obj = _extract_json(result.output) or {}
    status = "success" if str(obj.get("status", "")).lower() == "success" and result.ok else "failed"
    experiment_result = {
        "name": str(obj.get("experiment", "experiment"))[:120],
        "command": str(obj.get("command", ""))[:500],
        "status": status,
        "metrics": {str(k): v for k, v in (obj.get("metrics") or {}).items() if isinstance(v, (int, float))},
        "log_excerpt": str(obj.get("log_excerpt", ""))[:2000],
    }
    new_status = TaskStatus.DONE.value if status == "success" else TaskStatus.FAILED.value
    updates: dict[str, Any] = {
        "experiments": list(state.get("experiments") or []) + [experiment_result],
        "plan": _mark_task(state, str(task_id) if task_id else "", new_status,
                           {"kind": "experiment", "status": status, "metrics": experiment_result["metrics"]}),
        "current_task": None, "status": "running",
    }
    await _emit(ctx, "step", f"Experiment {experiment_result['name']}: {status} metrics={experiment_result['metrics']}", agent="experimenter",
                data=experiment_result)
    return updates


# ----------------------------------------------------------- evaluation ----
async def evaluate(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    outputs = state.get("task_outputs") or {}
    experiments = state.get("experiments") or []
    had_experiment_task = any(t.get("kind") == "experiment" for t in (state.get("plan") or []))

    if had_experiment_task:
        success = any(e.get("status") == "success" and e.get("metrics") for e in experiments)
    else:
        success = bool(outputs) and state.get("status") != "failed"

    # citation verification (deterministic grounding check)
    grounded = _grounded_urls(ctx)
    citations = [dict(c) for c in (state.get("citations") or [])]
    for c in citations:
        c["verified"] = c.get("url") in grounded

    findings = "\n\n".join(str(v.get("summary", ""))[:1500] for v in outputs.values() if v.get("kind") == "research")
    experiment_summary = json.dumps([{"name": e.get("name"), "status": e.get("status"), "metrics": e.get("metrics")} for e in experiments])
    review = await ReviewerAgent().review(ctx, findings, experiment_summary, grounded, citations)

    if state.get("status") == "failed":
        success = False
    await _emit(ctx, "step", f"Evaluation: success={success} confidence={review['confidence']:.2f}", agent="reviewer", data=review)
    return {"evaluation": {"success": success, "review": review, "max_repair_attempts": ctx.settings.max_repair_attempts},
            "citations": citations, "status": "running" if state.get("status") != "failed" else "failed"}


# ----------------------------------------------------- diagnose & repair ----
async def diagnose(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    experiments = state.get("experiments") or []
    last_error = next((e for e in reversed(experiments) if e.get("status") == "failed"), {"log_excerpt": "unknown failure"})
    error_text = f"{last_error.get('command', '')}\n{last_error.get('log_excerpt', '')}"[:2000]

    episodes = []
    if ctx.tctx.retriever is not None:
        from ..memory.episodic import EpisodicMemory

        episodes = await EpisodicMemory(ctx.tctx.retriever).recall_similar(error_text)
    known = "\n".join(f"- {ep.solution[:200]}" for ep in episodes)

    messages = [
        {"role": "system", "content": "You are the failure diagnostician. Analyze the failure and prescribe the minimal repair."},
        {"role": "user", "content": f"Experiment failed.\nCommand/context:\n{error_text}\n\nKnown similar fixes from memory:\n{known or '(none)'}\n\nPrescribe a repair."},
    ]
    resp = await ctx.llm.complete(messages, hints={"agent": "diagnostician", "task_kind": "debugging"})
    ctx.metrics.add_usage(resp.usage.input_tokens, resp.usage.output_tokens, getattr(resp, "cost_usd", 0.0))
    diagnosis = (resp.content or "no diagnosis available")[:2000]
    attempts = int(state.get("repair_attempts", 0)) + 1
    ctx.metrics.repairs += 1
    await _emit(ctx, "step", f"Diagnosis (attempt {attempts}): {diagnosis[:160]}...", agent="diagnostician", level="warn")
    await ctx.memory.update_run(ctx.run_id, metrics=ctx.metrics.to_dict())
    return {"diagnosis": diagnosis, "repair_attempts": attempts,
            "errors": list(state.get("errors") or []) + [{"node": "experiment", "message": diagnosis[:300]}]}


async def repair(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    instruction = (
        f"Repair task. Diagnosis: {state.get('diagnosis', '')}\n"
        "Fix the code/files in the workspace so the experiment can succeed, then verify."
    )
    try:
        result = await CoderAgent().run(ctx, instruction)
    except ApprovalRequired as exc:
        approval_id = await _request_approval(ctx, exc, resume_node="repair")
        return {"pending_approval": {"approval_id": approval_id, "resume_node": "repair", "kind": "tool",
                                     "action": exc.action, "risk": exc.risk, "detail": exc.detail},
                "status": "awaiting_approval"}
    await _emit(ctx, "step", f"Repair applied: {result.output[:160]}", agent="coder")
    return {}


# ------------------------------------------------------- approval gates ----
async def await_approval(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Human-approval gate via LangGraph's interrupt() primitive.

    First execution: publishes the pending approval and PAUSES the graph
    (durable checkpoint). The worker later resumes with Command(resume=...)
    after the operator decides; this node then re-executes, interrupt()
    returns the decision, and the router dispatches to the resume node.
    """
    from langgraph.types import interrupt

    ctx = _ctx(config)
    pending = state.get("pending_approval")
    decision: dict[str, Any] | None = None
    if pending:
        decision = interrupt({
            "type": "approval_required",
            "approval_id": pending.get("approval_id"),
            "action": pending.get("action"),
            "risk": pending.get("risk"),
            "detail": pending.get("detail", {}),
            "resume_node": pending.get("resume_node", "report"),
        })

    # apply every decided approval signature to the ledger (idempotent)
    for a in await ctx.memory.get_decided_approvals(ctx.run_id):
        if not a.signature:
            continue
        if a.status in ("approved", "modified"):
            if a.signature not in ctx.ledger.granted:
                ctx.ledger.granted.add(a.signature)
                ctx.metrics.approvals_granted += 1
        elif a.status == "rejected" and a.signature not in ctx.ledger.rejected:
            ctx.ledger.rejected.add(a.signature)

    if decision is None:
        return {"status": "running"}  # auto path (approve node pre-decided)
    await _emit(ctx, "approval", f"Operator decision: {decision.get('kind')}", data={"note": decision.get("note", "")})
    await ctx.memory.update_run(ctx.run_id, status="running")
    return {"approval_decision": decision, "pending_approval": None, "status": "running"}


async def approve(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Final human sign-off before the report is published."""
    ctx = _ctx(config)
    evaluation = state.get("evaluation") or {}
    review = evaluation.get("review") or {}
    needs_signoff = (ctx.metrics.approvals_requested > 0) or (review.get("confidence", 0) < 0.8)
    if state.get("status") == "failed":
        needs_signoff = False
    if ctx.auto_approve or not needs_signoff:
        await _emit(ctx, "approval", "Final sign-off: automatic (low-risk run or pre-approved)")
        return {"approval_decision": {"kind": "approved", "resume_node": "report"},
                "pending_approval": None, "status": "running"}
    # route through await_approval for the human decision
    from ..core.types import stable_hash

    sig = stable_hash({"action": "publish_report", "run": ctx.run_id})
    approval_id = new_id("apr")
    await ctx.memory.create_approval({
        "run_id": ctx.run_id, "action": "publish_report", "risk": "medium", "signature": sig,
        "detail": {"note": "Final report sign-off", "confidence": review.get("confidence")},
    }, approval_id)
    await _emit(ctx, "approval", "Final sign-off required before publishing the report", level="warn", data={"approval_id": approval_id})
    await ctx.memory.update_run(ctx.run_id, status="awaiting_approval")
    return {"pending_approval": {"approval_id": approval_id, "resume_node": "report", "kind": "final",
                                 "action": "publish_report", "risk": "medium", "detail": {}},
            "approval_decision": None,  # clear stale decisions from earlier gates
            "status": "awaiting_approval"}


# ---------------------------------------------------------------- report ----
async def report(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    final_status = "rejected" if (state.get("approval_decision") or {}).get("kind") == "rejected" else "completed"
    if state.get("status") == "failed" and final_status == "completed":
        final_status = "completed"
    state = dict(state)
    state["status"] = final_status  # type: ignore[index]
    md = build_report(state, ctx.metrics.to_dict(), (state.get("evaluation") or {}).get("review"))
    report_path = ctx.workspace / "report.md"
    report_path.write_text(md)
    await ctx.memory.add_artifact(ctx.run_id, kind="report", path=str(report_path))
    await ctx.memory.update_run(ctx.run_id, status=final_status, report_md=md, metrics=ctx.metrics.to_dict())
    await _emit(ctx, "status", f"Report published ({final_status})", data={"path": str(report_path)})
    return {"report_md": md, "status": final_status}


async def finalize_rejected(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    ctx = _ctx(config)
    state = dict(state)
    state["status"] = "rejected"  # type: ignore[index]
    md = build_report(state, ctx.metrics.to_dict(), (state.get("evaluation") or {}).get("review"))
    await ctx.memory.update_run(ctx.run_id, status="rejected", report_md=md, metrics=ctx.metrics.to_dict())
    await _emit(ctx, "status", "Run rejected by operator", level="warn")
    return {"report_md": md, "status": "rejected"}
