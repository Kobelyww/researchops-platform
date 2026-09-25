"""FastAPI gateway: task submission, run inspection, SSE event stream,
human-approval endpoints. Thin layer over the worker + memory store.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from researchops.config import Settings, load_settings
from researchops.core.types import new_id
from researchops.memory.store import MemoryStore
from researchops.workers.runner import execute_run, resume_run


@dataclass
class AppState:
    settings: Settings
    store: MemoryStore


class TaskCreate(BaseModel):
    goal: str = Field(min_length=8, max_length=4000)
    requirements: list[str] = Field(default_factory=list, max_length=20)
    auto_approve: bool = False


class ApprovalDecision(BaseModel):
    decision: str  # approved | rejected | modified
    note: str = ""


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    store = MemoryStore(settings.database_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        await store.connect()
        yield
        await store.disconnect()

    app = FastAPI(title="ResearchOps API", version="0.1.0", lifespan=lifespan)
    app.state.ops = AppState(settings=settings, store=store)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def require_key(x_api_key: str = Header(default="")) -> None:
        if settings.api_key and x_api_key != settings.api_key:
            raise HTTPException(status_code=401, detail="invalid API key")

    # ---------------------------------------------------------------- handlers
    def _public_task(row) -> dict[str, Any]:
        return {"task_id": row.id, "goal": row.goal, "status": row.status, "created_at": row.created_at}

    def _derive_agents(events: list[dict]) -> list[dict[str, Any]]:
        per: dict[str, dict[str, Any]] = {}
        order = ["planner", "research_agent", "repo_agent", "coder", "experimenter", "reviewer"]
        for e in events:
            agent = e.get("agent") or ""
            if not agent:
                continue
            slot = per.setdefault(agent, {"name": agent, "status": "done", "steps": 0, "last_message": ""})
            slot["steps"] += 1
            slot["last_message"] = e.get("message", "")[:200]
            if e.get("level") == "error":
                slot["status"] = "failed"
        ordered = [per.pop(name, None) for name in order if name in per]
        return [a for a in ordered if a] + list(per.values())

    def _public_run(run_row, approvals: list, events: list[dict]) -> dict[str, Any]:
        import json as _json

        metrics = run_row.metrics if isinstance(run_row.metrics, dict) else _json.loads(run_row.metrics or "{}")
        plan = run_row.plan if isinstance(run_row.plan, list) else _json.loads(run_row.plan or "[]")
        return {
            "run_id": run_row.id,
            "task_id": run_row.task_id,
            "goal": "",  # filled by caller
            "status": run_row.status,
            "plan": plan,
            "agents": _derive_agents(events),
            "approvals": [
                {
                    "id": a.id, "action": a.action, "detail": a.detail if isinstance(a.detail, str) else _json.dumps(a.detail),
                    "risk": a.risk, "status": a.status,
                    "estimated_cost_usd": a.estimated_cost_usd, "estimated_minutes": a.estimated_minutes,
                }
                for a in approvals
            ],
            "metrics": metrics,
            "report_md": run_row.report_md,
            "error": run_row.error or None,
        }

    # ------------------------------------------------------------- endpoints
    @app.get("/api/healthz")
    async def healthz() -> dict:
        return {"ok": True, "mode": settings.execution_mode, "llm_provider": settings.llm_provider}

    @app.post("/api/tasks", status_code=201, dependencies=[Depends(require_key)])
    async def create_task(body: TaskCreate, request: Request) -> dict:
        state: AppState = request.app.state.ops
        task_id = new_id("task")
        run_id = f"run_{task_id.split('_', 1)[-1]}"
        await state.store.create_task(task_id, body.goal, body.requirements, body.auto_approve)
        await state.store.create_run(run_id, task_id)
        if settings.execution_mode == "inline":
            asyncio.get_running_loop().create_task(
                execute_run(state.store, settings, run_id)
            )
        return {"task_id": task_id, "run_id": run_id, "status": "queued"}

    @app.get("/api/tasks", dependencies=[Depends(require_key)])
    async def list_tasks(request: Request, limit: int = 50) -> list[dict]:
        state: AppState = request.app.state.ops
        rows = await state.store.list_tasks(limit=min(limit, 200))
        return [_public_task(r) for r in rows]

    async def _resolve_run(request: Request, run_or_task_id: str):
        state: AppState = request.app.state.ops
        run = await state.store.get_run(run_or_task_id)
        if run is None:
            run = await state.store.get_active_run_for_task(run_or_task_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        task = await state.store.get_task(run.task_id)
        return state, run, task

    @app.get("/api/runs/{run_or_task_id}", dependencies=[Depends(require_key)])
    async def get_run(run_or_task_id: str, request: Request) -> dict:
        state, run, task = await _resolve_run(request, run_or_task_id)
        events = await state.store.get_events(run.id, after_id=0, limit=500)
        approvals = await state.store.list_approvals(run.id)
        detail = _public_run(run, approvals, events)
        detail["goal"] = task.goal if task else ""
        return detail

    @app.get("/api/runs/{run_or_task_id}/events")
    async def run_events(run_or_task_id: str, request: Request, after: int = 0) -> StreamingResponse:
        state, run, _task = await _resolve_run(request, run_or_task_id)

        async def gen() -> AsyncIterator[str]:
            last = after
            idle = 0
            while True:
                events = await state.store.get_events(run.id, after_id=last)
                for e in events:
                    last = e["id"]
                    payload = {"ts": e["ts"], "type": e["type"], "agent": e["agent"],
                               "level": e["level"], "message": e["message"], "data": e["data"]}
                    yield f"id: {e['id']}\ndata: {json.dumps(payload)}\n\n"
                    idle = 0
                idle += 1
                run_row = await state.store.get_run(run.id)
                if run_row and run_row.status in ("completed", "failed", "rejected") and not events:
                    yield 'data: {"type": "end_of_stream"}\n\n'
                    return
                if idle > 600:  # ~10 min without any event
                    return
                await asyncio.sleep(1.0)

        return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.post("/api/approvals/{approval_id}", dependencies=[Depends(require_key)])
    async def decide_approval(approval_id: str, body: ApprovalDecision, request: Request) -> dict:
        state: AppState = request.app.state.ops
        if body.decision not in ("approved", "rejected", "modified"):
            raise HTTPException(status_code=422, detail="decision must be approved|rejected|modified")
        approval = await state.store.decide_approval(approval_id, body.decision, body.note)
        if approval is None:
            raise HTTPException(status_code=404, detail="approval not found")
        await state.store.add_event(approval.run_id, {
            "type": "approval", "level": "warn", "message": f"Operator {body.decision}: {approval.action}",
            "data": {"approval_id": approval_id, "note": body.note},
        })
        if settings.execution_mode == "inline":
            asyncio.get_running_loop().create_task(
                resume_run(state.store, settings, approval.run_id)
            )
        return {"ok": True, "run_id": approval.run_id, "status": body.decision}

    @app.get("/api/runs/{run_or_task_id}/trace", dependencies=[Depends(require_key)])
    async def get_trace(run_or_task_id: str, request: Request) -> dict:
        state, run, _task = await _resolve_run(request, run_or_task_id)
        trace = run.trace_json if isinstance(run.trace_json, dict) else json.loads(run.trace_json or "{}")
        return trace or {"note": "trace available after run finishes"}

    return app


# Module-level app for `uvicorn researchops_api.main:app`
app = create_app()
