"""Shared domain types for the ResearchOps agent system."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def new_id(prefix: str) -> str:
    return f"{prefix}_{hashlib.sha1(f'{utcnow().timestamp()}{id(object())}'.encode()).hexdigest()[:12]}"


def stable_hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


class RunStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

    @property
    def rank(self) -> int:
        return {"low": 0, "medium": 1, "high": 2}[self.value]


class TaskKind(str, Enum):
    RESEARCH = "research"
    REPOSITORY = "repository"
    CODE = "code"
    EXPERIMENT = "experiment"
    REPORT = "report"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    SKIPPED = "skipped"


class TaskNode(BaseModel):
    """A node in the planner's task graph."""

    id: str
    kind: TaskKind
    title: str
    description: str = ""
    depends_on: list[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING


class Paper(BaseModel):
    id: str
    title: str
    url: str = ""
    abstract: str = ""
    authors: list[str] = Field(default_factory=list)
    year: int | None = None


class Citation(BaseModel):
    claim: str
    title: str
    url: str
    verified: bool = False


class RepoInfo(BaseModel):
    url: str
    name: str
    path: str = ""
    summary: str = ""
    entrypoints: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)


class ArtifactInfo(BaseModel):
    path: str
    kind: str = "file"
    sha256: str = ""


class ExperimentResult(BaseModel):
    name: str
    command: str = ""
    status: str = "pending"  # pending | running | success | failed
    metrics: dict[str, Any] = Field(default_factory=dict)
    log_excerpt: str = ""
    started_at: str | None = None
    finished_at: str | None = None


class AgentError(BaseModel):
    node: str
    message: str
    context: dict[str, Any] = Field(default_factory=dict)


class Finding(BaseModel):
    """A research finding with its supporting citation."""

    statement: str
    citation: Citation | None = None
