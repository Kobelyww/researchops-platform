"""Offline end-to-end demo: runs the full ResearchOps pipeline (plan → research
→ experiment → review → approval gate → report) with the mock LLM provider and
the local sandbox — zero API keys, zero network.

    .venv/bin/python scripts/demo_offline.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from researchops.config import Settings  # noqa: E402
from researchops.core.types import new_id  # noqa: E402
from researchops.memory.store import MemoryStore  # noqa: E402
from researchops.runtime import build_run_context  # noqa: E402
from researchops.tools.registry import Tool  # noqa: E402
from researchops.workers.runner import execute_run  # noqa: E402

FAKE_PAPERS = [
    {"id": "2401.00001", "title": "Contrastive Learning for Cross-lingual Speaker Verification",
     "url": "https://arxiv.org/abs/2401.00001", "abstract": "Contrastive objectives improve cross-lingual robustness.",
     "authors": ["A. Author", "B. Author"], "year": 2024},
    {"id": "2402.00002", "title": "Reproducibility in Speech Model Research",
     "url": "https://arxiv.org/abs/2402.00002", "abstract": "A study of baseline reproduction failures.",
     "authors": ["C. Author"], "year": 2024},
]


async def fake_search_papers(tctx, query: str, max_results: int = 8):
    return FAKE_PAPERS


async def main() -> None:
    tmp = Path("./.data/demo").resolve()
    tmp.mkdir(parents=True, exist_ok=True)
    settings = Settings(
        llm_provider="mock", execution_mode="inline",
        database_url=f"sqlite+aiosqlite:///{tmp}/demo.db", checkpoint_db=str(tmp / "ckpt.db"),
        workspace_root=str(tmp / "ws"), sandbox_backend="local",
    )
    store = MemoryStore(settings.database_url)
    await store.connect()

    task_id = new_id("task")
    run_id = f"run_{task_id.split('_', 1)[-1]}"
    goal = ("Reproduce the baseline of a cross-lingual speaker verification paper, "
            "run a tiny experiment, and generate a cited technical report")
    await store.create_task(task_id, goal, ["find papers", "run baseline", "cite sources"], auto_approve=False)
    await store.create_run(run_id, task_id)

    ctx = await build_run_context(settings, store, run_id, task_id, goal, ["find papers", "run baseline", "cite sources"], False)
    ctx.registry.tools["search_papers"] = Tool(  # offline: stub the arXiv client
        name="search_papers", description="offline arXiv stub", timeout_s=5,
        parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        handler=fake_search_papers,
    )
    ctx.llm.default_provider.scripts.update({
        "planner": [("final", '{"tasks": ['
                              '{"id": "t1", "kind": "research", "title": "Survey cross-lingual speaker verification papers"}, '
                              '{"id": "t2", "kind": "experiment", "title": "Run baseline extraction", "depends_on": ["t1"]}]}')],
        "researcher": [
            ("tool", "search_papers", {"query": "cross-lingual speaker verification"}),
            ("final", 'Recent work applies contrastive objectives to cross-lingual speaker verification. '
                      '```json {"summary": "Contrastive learning improves cross-lingual speaker verification robustness; '
                      'reproducibility remains a challenge.", "citations": ['
                      '{"claim": "contrastive objectives improve cross-lingual robustness", '
                      '"title": "Contrastive Learning for Cross-lingual Speaker Verification", '
                      '"url": "https://arxiv.org/abs/2401.00001"}, '
                      '{"claim": "baseline reproduction is a common failure point", '
                      '"title": "Reproducibility in Speech Model Research", '
                      '"url": "https://arxiv.org/abs/2402.00002"}]} ```'),
        ],
        "experimenter": [
            ("tool", "run_command", {"command": "python3 -c \"print('epoch 1 done'); print('acc=0.82')\" > train.log 2>&1; cat train.log"}),
            ("final", '```json {"experiment": "baseline extraction", "command": "python3 -c ...", "status": "success", '
                      '"metrics": {"accuracy": 0.82}, "log_excerpt": "epoch 1 done / acc=0.82"} ```'),
        ],
        "reviewer": [("final", '```json {"approved": true, "confidence": 0.9, "issues": []} ```')],
    })

    print("▶ ResearchOps offline demo")
    print(f"  task: {task_id}\n  run:  {run_id}\n  goal: {goal}\n")

    async def show_events():
        last = 0
        while True:
            for e in await store.get_events(run_id, after_id=last):
                last = e["id"]
                agent = (e.get("agent") or "system").ljust(14)
                icon = {"tool": "🔧", "tool_error": "⚠️ ", "approval": "🖐 ", "status": "★"}.get(e["type"], "·")
                print(f"  {icon} {agent} {e['message'][:96]}")
            run = await store.get_run(run_id)
            if run and run.status not in ("queued", "running", "awaiting_approval"):
                return
            await asyncio.sleep(0.15)

    watcher = asyncio.create_task(show_events())
    await execute_run(store, settings, run_id, ctx=ctx)

    run = await store.get_run(run_id)
    if run.status == "awaiting_approval":
        pending = [a for a in await store.list_approvals(run_id) if a.status == "pending"]
        for a in pending:
            print(f"\n  🖁  approval gate: {a.action} (risk={a.risk}) — auto-approving for demo")
            await store.decide_approval(a.id, "approved", "demo")
        await execute_run(store, settings, run_id, ctx=ctx)
        run = await store.get_run(run_id)
        while run.status == "awaiting_approval":
            pending = [a for a in await store.list_approvals(run_id) if a.status == "pending"]
            for a in pending:
                print(f"\n  🖁  approval gate: {a.action} (risk={a.risk}) — auto-approving for demo")
                await store.decide_approval(a.id, "approved", "demo")
            await execute_run(store, settings, run_id, ctx=ctx)
            run = await store.get_run(run_id)

    await watcher
    print(f"\n★ final status: {run.status}")
    print(f"  report: {ctx.workspace / 'report.md'}")
    print(f"  cost: ${ctx.metrics.cost_usd:.4f}  tool calls: {ctx.metrics.tool_calls}  "
          f"tokens: {ctx.metrics.input_tokens}+{ctx.metrics.output_tokens}")
    await store.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
