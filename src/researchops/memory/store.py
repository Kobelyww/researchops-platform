"""Persistence: tasks, runs, events, approvals, tool-call audit, artifacts.

SQLAlchemy 2.0 async. SQLite by default (zero-config dev); switch to Postgres
+ pgvector in production via RESEARCHOPS_DATABASE_URL.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from sqlalchemy import JSON, String, Text, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from ..core.types import RunStatus, utcnow


class Base(DeclarativeBase):
    pass


class TaskRow(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    goal: Mapped[str] = mapped_column(Text)
    requirements: Mapped[list] = mapped_column(JSON, default=list)
    auto_approve: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    created_at: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[str] = mapped_column(String(32))


class RunRow(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(24), default="queued", index=True)
    error: Mapped[str] = mapped_column(Text, default="")
    plan: Mapped[list] = mapped_column(JSON, default=list)
    agents: Mapped[list] = mapped_column(JSON, default=list)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    report_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[float] = mapped_column(default=0.0)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    latency_s: Mapped[float] = mapped_column(default=0.0)
    trace_json: Mapped[dict] = mapped_column(JSON, default=dict)
    started_at: Mapped[str | None] = mapped_column(String(32), nullable=True)
    finished_at: Mapped[str | None] = mapped_column(String(32), nullable=True)


class EventRow(Base):
    __tablename__ = "events"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    ts: Mapped[str] = mapped_column(String(32))
    type: Mapped[str] = mapped_column(String(24))
    agent: Mapped[str | None] = mapped_column(String(40), nullable=True)
    level: Mapped[str] = mapped_column(String(8), default="info")
    message: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class ApprovalRow(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    action: Mapped[str] = mapped_column(String(120))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    risk: Mapped[str] = mapped_column(String(8))
    signature: Mapped[str] = mapped_column(String(32), default="")
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    decided_by: Mapped[str] = mapped_column(String(40), default="")
    estimated_cost_usd: Mapped[float] = mapped_column(default=0.0)
    estimated_minutes: Mapped[float] = mapped_column(default=0.0)
    created_at: Mapped[str] = mapped_column(String(32))
    decided_at: Mapped[str | None] = mapped_column(String(32), nullable=True)


class ToolCallRow(Base):
    __tablename__ = "tool_calls"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    tool: Mapped[str] = mapped_column(String(80))
    caller: Mapped[str] = mapped_column(String(40), default="")
    args: Mapped[dict] = mapped_column(JSON, default=dict)
    risk: Mapped[str] = mapped_column(String(8), default="low")
    status: Mapped[str] = mapped_column(String(12), default="ok")
    latency_ms: Mapped[float] = mapped_column(default=0.0)


class ArtifactRow(Base):
    __tablename__ = "artifacts"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(40), index=True)
    kind: Mapped[str] = mapped_column(String(24), default="file")
    path: Mapped[str] = mapped_column(Text)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)


def _json_loads(raw: Any) -> Any:  # helper kept private
    if raw is None or raw == "":
        return None
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw


class MemoryStore:
    """Async facade over the relational store + event feed."""

    def __init__(self, database_url: str):
        kwargs: dict[str, Any] = {}
        if database_url.startswith("sqlite"):
            kwargs["connect_args"] = {"timeout": 30}
        self.engine = create_async_engine(database_url, pool_pre_ping=True, **kwargs)
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def connect(self) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def disconnect(self) -> None:
        await self.engine.dispose()

    # -- tasks ---------------------------------------------------------------
    async def create_task(self, task_id: str, goal: str, requirements: list[str], auto_approve: bool) -> TaskRow:
        now = utcnow().isoformat()
        row = TaskRow(id=task_id, goal=goal, requirements=requirements, auto_approve=auto_approve, status="queued", created_at=now, updated_at=now)
        async with self.session_factory() as s:
            s.add(row)
            await s.commit()
        return row

    async def get_task(self, task_id: str) -> TaskRow | None:
        async with self.session_factory() as s:
            return await s.get(TaskRow, task_id)

    async def list_tasks(self, limit: int = 50) -> list[TaskRow]:
        async with self.session_factory() as s:
            rows = await s.execute(select(TaskRow).order_by(TaskRow.created_at.desc()).limit(limit))
            return list(rows.scalars())

    async def set_task_status(self, task_id: str, status: str) -> None:
        async with self.session_factory() as s:
            row = await s.get(TaskRow, task_id)
            if row:
                row.status = status
                row.updated_at = utcnow().isoformat()
                await s.commit()

    # -- runs ----------------------------------------------------------------
    async def create_run(self, run_id: str, task_id: str) -> RunRow:
        row = RunRow(id=run_id, task_id=task_id, status=RunStatus.QUEUED.value, started_at=utcnow().isoformat())
        async with self.session_factory() as s:
            s.add(row)
            await s.commit()
        return row

    async def get_run(self, run_id: str) -> RunRow | None:
        async with self.session_factory() as s:
            return await s.get(RunRow, run_id)

    async def update_run(self, run_id: str, **fields: Any) -> None:
        async with self.session_factory() as s:
            row = await s.get(RunRow, run_id)
            if not row:
                return
            for k, v in fields.items():
                if hasattr(row, k):
                    setattr(row, k, v)
            await s.commit()

    async def get_active_run_for_task(self, task_id: str) -> RunRow | None:
        async with self.session_factory() as s:
            rows = await s.execute(
                select(RunRow).where(RunRow.task_id == task_id).order_by(RunRow.started_at.desc()).limit(1)
            )
            return rows.scalars().first()

    # -- events (SSE transport across processes) ------------------------------
    async def add_event(self, run_id: str, event: dict[str, Any]) -> int:
        row = EventRow(
            run_id=run_id, ts=event.get("ts", utcnow().isoformat()), type=event.get("type", "info"),
            agent=event.get("agent"), level=event.get("level", "info"),
            message=event.get("message", ""), data=event.get("data", {}),
        )
        async with self.session_factory() as s:
            s.add(row)
            await s.commit()
            return row.id

    async def get_events(self, run_id: str, after_id: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        async with self.session_factory() as s:
            rows = await s.execute(
                select(EventRow).where(EventRow.run_id == run_id, EventRow.id > after_id).order_by(EventRow.id).limit(limit)
            )
            return [
                {
                    "id": r.id, "ts": r.ts, "type": r.type, "agent": r.agent,
                    "level": r.level, "message": r.message, "data": _json_loads(r.data),
                }
                for r in rows.scalars()
            ]

    # -- approvals -------------------------------------------------------------
    async def create_approval(self, request: dict[str, Any], approval_id: str) -> ApprovalRow:
        row = ApprovalRow(
            id=approval_id, run_id=request["run_id"], action=request["action"], detail=request.get("detail", {}),
            risk=request.get("risk", "medium"), signature=request.get("signature", ""), status="pending",
            estimated_cost_usd=request.get("estimated_cost_usd", 0.0),
            estimated_minutes=request.get("estimated_minutes", 0.0), created_at=utcnow().isoformat(),
        )
        async with self.session_factory() as s:
            s.add(row)
            await s.commit()
        return row

    async def get_approval(self, approval_id: str) -> ApprovalRow | None:
        async with self.session_factory() as s:
            return await s.get(ApprovalRow, approval_id)

    async def list_approvals(self, run_id: str) -> list[ApprovalRow]:
        async with self.session_factory() as s:
            rows = await s.execute(select(ApprovalRow).where(ApprovalRow.run_id == run_id).order_by(ApprovalRow.created_at))
            return list(rows.scalars())

    async def decide_approval(self, approval_id: str, decision: str, note: str = "", decided_by: str = "operator") -> ApprovalRow | None:
        async with self.session_factory() as s:
            row = await s.get(ApprovalRow, approval_id)
            if not row:
                return None
            row.status = decision  # approved | rejected | modified
            row.note = note or ""
            row.decided_by = decided_by
            row.decided_at = utcnow().isoformat()
            await s.commit()
            return row

    async def get_decided_approvals(self, run_id: str) -> list[ApprovalRow]:
        async with self.session_factory() as s:
            rows = await s.execute(
                select(ApprovalRow).where(ApprovalRow.run_id == run_id, ApprovalRow.status != "pending")
            )
            return list(rows.scalars())

    # -- audit / artifacts -------------------------------------------------------
    async def add_tool_call(self, run_id: str, record: dict[str, Any]) -> None:
        row = ToolCallRow(
            run_id=run_id, tool=record.get("tool", ""), caller=record.get("caller", ""),
            args=record.get("args", {}), risk=record.get("risk", "low"),
            status=record.get("status", "ok"), latency_ms=record.get("latency_ms", 0.0),
        )
        async with self.session_factory() as s:
            s.add(row)
            await s.commit()

    async def add_artifact(self, run_id: str, kind: str, path: str, meta: dict | None = None) -> None:
        row = ArtifactRow(run_id=run_id, kind=kind, path=path, meta=meta or {})
        async with self.session_factory() as s:
            s.add(row)
            await s.commit()


async def stream_events(store: MemoryStore, run_id: str, poll_s: float = 0.7) -> AsyncIterator[dict]:
    """DB-backed event stream consumed by the SSE endpoint."""
    last_id = 0
    while True:
        events = await store.get_events(run_id, after_id=last_id)
        for e in events:
            last_id = e["id"]
            yield e
        await asyncio.sleep(poll_s)
