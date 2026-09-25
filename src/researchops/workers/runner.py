"""Worker: claims queued tasks, executes/resumes runs, persists results.

Modes:
- worker: standalone process loop (`python -m researchops.workers.runner`)
- inline: the API process executes runs as background asyncio tasks
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timezone

from ..config import Settings, load_settings
from ..core.errors import BudgetExceeded
from ..core.types import RunStatus
from ..graph.report import build_report
from ..graph.workflow import build_workflow
from ..memory.store import MemoryStore
from ..runtime import build_run_context

logger = logging.getLogger("researchops.worker")


class CheckpointHandle:
    """Owns the AsyncSqliteSaver context-manager lifecycle."""

    def __init__(self, path: str):
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        self._cm = AsyncSqliteSaver.from_conn_string(path)
        self._saver = None

    async def __aenter__(self) -> CheckpointHandle:
        self._saver = await self._cm.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self._cm.__aexit__(*exc)

    @property
    def saver(self):
        assert self._saver is not None
        return self._saver


async def execute_run(store: MemoryStore, settings: Settings, run_id: str, ctx=None) -> None:
    """Runs (or resumes) a workflow to completion for the given run.

    `ctx` lets tests/demo inject a pre-built RunContext (e.g. scripted mock
    provider); production always builds a fresh one.
    """
    run = await store.get_run(run_id)
    if run is None:
        logger.error("run %s not found", run_id)
        return
    task = await store.get_task(run.task_id)
    if task is None:
        logger.error("task %s for run %s not found", run.task_id, run_id)
        return

    resuming = run.status == RunStatus.AWAITING_APPROVAL.value

    if ctx is None:
        ctx = await build_run_context(
            settings, store, run_id, task.id, task.goal, list(task.requirements or []), bool(task.auto_approve),
        )
    # re-apply past operator decisions so gateway approvals survive process restarts
    for a in await store.get_decided_approvals(run_id):
        if a.signature:
            if a.status in ("approved", "modified"):
                ctx.ledger.granted.add(a.signature)
            elif a.status == "rejected":
                ctx.ledger.rejected.add(a.signature)

    async with CheckpointHandle(settings.checkpoint_db) as handle:
        graph = build_workflow(checkpointer=handle.saver)
        config = {"configurable": {"ctx": ctx, "thread_id": run_id}, "recursion_limit": 150}
        started = asyncio.get_event_loop().time()
        try:
            initial = {
                "task_id": task.id, "run_id": run_id, "user_goal": task.goal,
                "requirements": list(task.requirements or []), "auto_approve": bool(task.auto_approve),
            }
            await ctx.sandbox.ensure()
            if resuming:
                resume_input = await _resume_input(graph, store, config, run_id)
                if resume_input is None:
                    logger.info("run %s still waiting on an undecided approval", run_id)
                    return
                final_state = await graph.ainvoke(resume_input, config=config)
            else:
                final_state = await graph.ainvoke(initial, config=config)
        except BudgetExceeded as exc:
            await _fail_run(store, ctx, run_id, f"budget exceeded: {exc}")
            return
        except Exception as exc:  # noqa: BLE001 — a run must never die silently
            logger.exception("run %s crashed", run_id)
            await _fail_run(store, ctx, run_id, f"{type(exc).__name__}: {exc}")
            return
        finally:
            ctx.metrics.latency_s = asyncio.get_event_loop().time() - started
            await _persist_telemetry(store, ctx, run_id)

        status = final_state.get("status", RunStatus.FAILED.value)
        await store.update_run(
            run_id,
            status=status,
            report_md=final_state.get("report_md"),
            plan=final_state.get("plan") or [],
            metrics=ctx.metrics.to_dict(),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
        await store.set_task_status(task.id, status)


async def _resume_input(graph, store: MemoryStore, config: dict, run_id: str):
    """Build the Command(resume=...) for a paused approval gate, or None if
    the operator hasn't decided yet."""
    from langgraph.types import Command

    snapshot = await graph.aget_state(config)
    values = snapshot.values or {}
    pending = values.get("pending_approval") or {}
    approval_id = pending.get("approval_id")
    if not approval_id:
        return None
    approval = await store.get_approval(approval_id)
    if approval is None or approval.status == "pending":
        return None
    decision = {
        "kind": approval.status,  # approved | rejected | modified
        "note": approval.note or "",
        "approval_id": approval.id,
        "resume_node": pending.get("resume_node", "report"),
    }
    return Command(resume=decision)


async def _fail_run(store: MemoryStore, ctx, run_id: str, message: str) -> None:
    state = {"user_goal": ctx.goal, "status": "failed", "requirements": ctx.requirements,
             "plan": [], "errors": [{"node": "runner", "message": message}]}
    md = build_report(state, ctx.metrics.to_dict())
    await store.update_run(run_id, status=RunStatus.FAILED.value, error=message[:1000], report_md=md,
                           metrics=ctx.metrics.to_dict(), finished_at=datetime.now(timezone.utc).isoformat())
    await ctx.tracer.event("status", f"Run failed: {message}", level="error")


async def _persist_telemetry(store: MemoryStore, ctx, run_id: str) -> None:
    for record in ctx.tools.audit:
        await store.add_tool_call(run_id, record)
    trace = ctx.tracer.export()
    await store.update_run(run_id, metrics=ctx.metrics.to_dict(), trace_json=trace,
                           cost_usd=ctx.metrics.cost_usd, input_tokens=ctx.metrics.input_tokens,
                           output_tokens=ctx.metrics.output_tokens, latency_s=ctx.metrics.latency_s)


async def _resolve_task_id(store: MemoryStore, run_id: str) -> str | None:
    run = await store.get_run(run_id)
    return run.task_id if run else None


async def resume_run(store: MemoryStore, settings: Settings, run_id: str) -> None:
    await execute_run(store, settings, run_id)


async def run_worker_loop(settings: Settings | None = None, poll_interval_s: float = 1.0) -> None:
    """Standalone worker: claim queued tasks + resume decided approvals."""
    settings = settings or load_settings()
    store = MemoryStore(settings.database_url)
    await store.connect()
    logger.info("worker started (db=%s)", settings.database_url)
    while True:
        try:
            tasks = await store.list_tasks(limit=20)
            for task in tasks:
                if task.status != "queued":
                    continue
                existing = await store.get_active_run_for_task(task.id)
                if existing is None:
                    run_id = f"run_{task.id.split('_', 1)[-1]}"
                    await store.create_run(run_id, task.id)
                    existing = await store.get_run(run_id)
                await store.set_task_status(task.id, "running")
                await execute_run(store, settings, existing.id)
            # resume runs whose pending approval got decided
            await _resume_awaiting(store, settings)
        except Exception:  # noqa: BLE001
            logger.exception("worker loop iteration failed")
        await asyncio.sleep(poll_interval_s)


async def _resume_awaiting(store: MemoryStore, settings: Settings) -> None:
    tasks = await store.list_tasks(limit=50)
    for task in tasks:
        if task.status not in ("running", "awaiting_approval"):
            continue
        run = await store.get_active_run_for_task(task.id)
        if run is None or run.status != RunStatus.AWAITING_APPROVAL.value:
            continue
        approvals = await store.list_approvals(run.id)
        pending = [a for a in approvals if a.status == "pending"]
        if pending:
            continue  # still waiting on a decision
        decided_recently = [a for a in approvals if a.status != "pending"]
        if decided_recently:
            await store.set_task_status(task.id, "running")
            await resume_run(store, settings, run.id)


def main() -> None:  # console entrypoint
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run_worker_loop())


if __name__ == "__main__":
    main()
