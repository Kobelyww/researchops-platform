"""API integration tests: task creation, run polling, approval flow, SSE."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from researchops_api.main import create_app


@pytest.fixture()
def client(settings, store):
    app = create_app(settings)
    with TestClient(app) as c:
        yield c


def test_healthz(client):
    resp = client.get("/api/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True and body["llm_provider"] == "mock"


def test_api_key_enforcement(settings, store):
    strict = settings.model_copy(update={"api_key": "sekret"})
    with TestClient(create_app(strict)) as c:
        assert c.get("/api/tasks").status_code == 401
        assert c.get("/api/tasks", headers={"X-API-Key": "sekret"}).status_code == 200


def test_run_lifecycle_with_approval(client, settings, store):
    """Create → (mock agent hits approval gate) → approve → resume."""
    # scripted inline execution is driven manually below, not via background task:
    # create the task via API with execution deferred (we call execute_run directly)
    resp = client.post("/api/tasks", json={"goal": "research and reproduce a baseline", "requirements": ["cite"], "auto_approve": True})
    assert resp.status_code == 201
    body = resp.json()
    task_id, run_id = body["task_id"], body["run_id"]

    # drive the run to the approval gate
    from researchops.runtime import build_run_context
    from researchops.workers.runner import execute_run

    ctx = None

    async def drive():
        nonlocal ctx
        ctx = await build_run_context(settings, store, run_id, task_id, "research and reproduce a baseline", ["cite"], False)
        ctx.llm.default_provider.scripts.update({
            "planner": [("final", '{"tasks": [{"id": "t1", "kind": "research", "title": "search"}]}')],
            "researcher": [("final", '```json {"summary": "s", "citations": [{"claim": "c", "title": "t", "url": "https://arxiv.org/abs/1"}]} ```')],
        })
        await execute_run(store, settings, run_id, ctx=ctx)

    import asyncio

    asyncio.run(drive())

    # drive to a terminal state (decide pending approvals + resume) so the SSE
    # endpoint sees a finished run and terminates immediately instead of idling
    for _ in range(5):
        approvals = asyncio.run(store.list_approvals(run_id))
        pending = [a for a in approvals if a.status == "pending"]
        if not pending:
            break
        asyncio.run(store.decide_approval(pending[0].id, "approved", "test"))
        asyncio.run(execute_run(store, settings, run_id, ctx=ctx))

    detail = client.get(f"/api/runs/{run_id}").json()
    assert detail["status"] in ("completed", "awaiting_approval")
    assert detail["run_id"] == run_id and detail["goal"].startswith("research")

    runs_by_task = client.get(f"/api/runs/{task_id}").json()
    assert runs_by_task["run_id"] == run_id

    events = client.get(f"/api/runs/{run_id}/events?after=0")
    assert events.status_code == 200
    assert "data:" in events.text
