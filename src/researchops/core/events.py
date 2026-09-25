"""Lightweight event bus for live run progress (SSE / audit trail)."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from .types import utcnow

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class EventBus:
    """Broadcasts run events to async subscribers.

    The worker publishes; the API subscribes and streams to browsers over SSE.
    In worker mode the DB event table is the cross-process transport, this bus
    serves same-process subscribers (tests, inline mode, log tailing).
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = defaultdict(list)

    def subscribe(self, run_id: str, handler: EventHandler) -> Callable[[], None]:
        self._handlers[run_id].append(handler)

        def unsubscribe() -> None:
            self._handlers[run_id].remove(handler)

        return unsubscribe

    async def publish(
        self,
        run_id: str,
        type: str,
        message: str = "",
        agent: str | None = None,
        level: str = "info",
        data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = {
            "ts": utcnow().isoformat(),
            "type": type,
            "agent": agent,
            "level": level,
            "message": message,
            "data": data or {},
        }
        for handler in list(self._handlers.get(run_id, [])):
            try:
                await handler(event)
            except Exception:  # a broken subscriber must never kill a run
                pass
        return event
