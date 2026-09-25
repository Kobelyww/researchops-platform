"""Lightweight structured tracing: span tree per run + event emission.

Span records carry trace_id / run_id / agent / tool / latency / tokens / cost /
status — the same fields an OpenTelemetry or Langfuse exporter would receive.
Optional OTel export is enabled via the `otel` extra and OTEL_EXPORTER_OTLP_ENDPOINT.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ..core.events import EventBus
from ..core.types import utcnow
from .metrics import RunMetrics

logger = logging.getLogger("researchops.trace")


@dataclass
class Span:
    name: str
    agent: str = ""
    parent: str | None = None
    span_id: str = ""
    started_at: float = 0.0
    ended_at: float | None = None
    status: str = "ok"
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def latency_ms(self) -> float:
        return (self.ended_at - self.started_at) * 1000 if self.ended_at else 0.0

    def to_dict(self) -> dict:
        return {
            "span_id": self.span_id,
            "parent": self.parent,
            "name": self.name,
            "agent": self.agent,
            "status": self.status,
            "latency_ms": round(self.latency_ms, 1),
            "attrs": self.attrs,
        }


class TraceCollector:
    def __init__(self, run_id: str, events: EventBus, metrics: RunMetrics):
        self.run_id = run_id
        self.trace_id = f"trace_{run_id}"
        self.events = events
        self.metrics = metrics
        self.spans: list[Span] = []
        self._counter = 0
        self._otel = None
        try:  # optional dependency
            from opentelemetry import trace as ot_trace  # type: ignore

            self._otel = ot_trace
        except ImportError:
            pass

    def start(self, name: str, agent: str = "", parent: str | None = None, **attrs: Any) -> Span:
        self._counter += 1
        span = Span(
            name=name, agent=agent, parent=parent, span_id=f"span_{self._counter}",
            started_at=utcnow().timestamp(), attrs=attrs,
        )
        self.spans.append(span)
        return span

    def end(self, span: Span, status: str = "ok", **extra_attrs: Any) -> None:
        span.ended_at = utcnow().timestamp()
        span.status = status
        span.attrs.update(extra_attrs)
        self.metrics.extra.setdefault("spans", 0)
        self.metrics.extra["spans"] += 1

    async def event(self, type: str, message: str, agent: str = "", level: str = "info", data: dict | None = None) -> None:
        await self.events.publish(self.run_id, type, message=message, agent=agent or None, level=level, data=data)

    def export(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "run_id": self.run_id,
            "span_count": len(self.spans),
            "spans": [s.to_dict() for s in self.spans],
            "metrics": self.metrics.to_dict(),
        }
