"""Seed the local dashboard with demo runs so http://localhost:3000 has data.

Creates two completed runs (research+experiment e2e, repository analysis) and
one run paused at the approval gate so the approval panel can be tried.

    .venv/bin/python scripts/seed_dashboard.py
    # then: npm run dev (apps/web) + uvicorn researchops_api.main:app
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from researchops.config import Settings  # noqa: E402
from researchops.core.types import new_id  # noqa: E402
from researchops.evals.offline import apply_offline  # noqa: E402
from researchops.memory.store import MemoryStore  # noqa: E402
from researchops.runtime import build_run_context  # noqa: E402
from researchops.workers.runner import execute_run  # noqa: E402


async def seed_run(store, settings, goal, kind, auto_approve, stop_at_approval=False):
    task_id = new_id("task")
    run_id = f"run_{task_id.split('_', 1)[-1]}"
    await store.create_task(task_id, goal, ["cited findings", "sandboxed execution"], auto_approve)
    await store.create_run(run_id, task_id)
    await store.set_task_status(task_id, "running")

    ctx = await build_run_context(settings, store, run_id, task_id, goal, [], auto_approve)
    apply_offline(ctx, kind)
    await execute_run(store, settings, run_id, ctx=ctx)

    if stop_at_approval:
        run = await store.get_run(run_id)
        print(f"  {run_id}: {run.status} (left paused for the approval panel)")
        return run_id

    # headless: approve every gate until terminal
    for _ in range(8):
        run = await store.get_run(run_id)
        if run.status != "awaiting_approval":
            break
        pending = [a for a in await store.list_approvals(run_id) if a.status == "pending"]
        for a in pending:
            await store.decide_approval(a.id, "approved", "demo seed")
        await execute_run(store, settings, run_id, ctx=ctx)

    run = await store.get_run(run_id)
    print(f"  {run_id}: {run.status}")
    return run_id


async def main() -> None:
    data_dir = Path("./.data").resolve()
    data_dir.mkdir(exist_ok=True)
    settings = Settings(
        llm_provider="mock", execution_mode="inline",
        database_url=f"sqlite+aiosqlite:///{data_dir}/researchops.db",
        checkpoint_db=str(data_dir / "checkpoints.db"),
        workspace_root=str(data_dir / "workspaces"),
        sandbox_backend="local",
    )
    store = MemoryStore(settings.database_url)
    await store.connect()
    print("seeding demo runs →")
    await seed_run(store, settings,
                   "Reproduce a cross-lingual speaker verification baseline, run a tiny experiment, and generate a cited report",
                   "e2e", auto_approve=True)
    await seed_run(store, settings,
                   "Clone and analyze the architecture of the tiny-asr GitHub repository",
                   "repository", auto_approve=True)
    await seed_run(store, settings,
                   "Run a baseline extraction experiment on the training data",
                   "experiment", auto_approve=False, stop_at_approval=True)
    await store.disconnect()
    print("done. start the API (uvicorn researchops_api.main:app) and web (npm run dev).")


if __name__ == "__main__":
    asyncio.run(main())
