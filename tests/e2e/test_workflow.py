"""End-to-end workflow tests: full LangGraph pipeline with a scripted mock
provider, fake arXiv tool, and the local sandbox — including the HITL
approval gates (tool approval, rejection, final sign-off) and the
diagnose→repair loop.
"""

from __future__ import annotations

from researchops.core.types import new_id
from researchops.memory.store import MemoryStore
from researchops.runtime import build_run_context
from researchops.tools.registry import Tool
from researchops.workers.runner import execute_run

FAKE_PAPER = {
    "id": "2401.00001", "title": "Contrastive Speaker Verification",
    "url": "https://arxiv.org/abs/2401.00001", "abstract": "Contrastive learning helps.",
    "authors": ["A. Author"], "year": 2024,
}


def fake_search_papers(tctx, query: str, max_results: int = 8):
    return [FAKE_PAPER]


async def make_ctx(settings, store, run_id, task_id, goal, scripts: dict):
    ctx = await build_run_context(settings, store, run_id, task_id, goal, [], False)
    # offline: replace the network-bound arXiv tool with a deterministic fake
    ctx.registry.tools["search_papers"] = Tool(
        name="search_papers", description="fake arxiv", timeout_s=5,
        parameters={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        handler=fake_search_papers,
    )
    ctx.llm.default_provider.scripts.update(scripts)
    return ctx


async def create_task_and_run(store: MemoryStore, goal: str, auto_approve=False):
    task_id = new_id("task")
    run_id = f"run_{task_id.split('_', 1)[-1]}"
    await store.create_task(task_id, goal, [], auto_approve)
    await store.create_run(run_id, task_id)
    return task_id, run_id


async def test_full_run_with_approvals(settings, store):
    scripts = {
        "planner": [("final", '{"tasks": [{"id": "t1", "kind": "research", "title": "find papers"}, '
                                '{"id": "t2", "kind": "experiment", "title": "run baseline", "depends_on": ["t1"]}]}')],
        "researcher": [
            ("tool", "search_papers", {"query": "contrastive speaker verification"}),
            ("final", 'Found a paper. ```json {"summary": "Contrastive learning improves speaker verification.", '
                      '"citations": [{"claim": "contrastive helps", "title": "CSV", '
                      '"url": "https://arxiv.org/abs/2401.00001"}]} ```'),
        ],
        "experimenter": [
            ("tool", "run_command", {"command": "echo 'acc=0.82' > metrics.txt && cat metrics.txt"}),
            ("final", '```json {"experiment": "baseline", "command": "echo", "status": "success", '
                      '"metrics": {"acc": 0.82}, "log_excerpt": "acc=0.82"} ```'),
        ],
        "reviewer": [("final", '```json {"approved": true, "confidence": 0.9, "issues": []} ```')],
    }
    task_id, run_id = await create_task_and_run(store, "reproduce a contrastive speaker verification baseline")
    ctx = await make_ctx(settings, store, run_id, task_id, "reproduce a contrastive speaker verification baseline", scripts)

    await execute_run(store, settings, run_id, ctx=ctx)
    run = await store.get_run(run_id)
    assert run.status == "awaiting_approval", f"expected tool approval gate, got {run.status}"

    approvals = await store.list_approvals(run_id)
    assert len(approvals) == 1 and approvals[0].action == "run_command" and approvals[0].risk == "medium"
    await store.decide_approval(approvals[0].id, "approved", "ok")
    await execute_run(store, settings, run_id, ctx=ctx)

    run = await store.get_run(run_id)
    # second gate: final report sign-off (a MEDIUM action happened)
    assert run.status == "awaiting_approval"
    approvals = [a for a in await store.list_approvals(run_id) if a.status == "pending"]
    assert approvals[0].action == "publish_report"
    await store.decide_approval(approvals[0].id, "approved")
    await execute_run(store, settings, run_id, ctx=ctx)

    run = await store.get_run(run_id)
    assert run.status == "completed"
    assert run.report_md and "0.82" in run.report_md
    assert "https://arxiv.org/abs/2401.00001" in run.report_md
    assert "✅" in run.report_md  # citation was grounded in real tool output
    assert run.metrics["tool_calls"] >= 1 and run.cost_usd >= 0
    report_file = ctx.workspace / "report.md"
    assert report_file.exists()


async def test_tool_rejection_stops_run(settings, store):
    scripts = {
        "planner": [("final", '{"tasks": [{"id": "t1", "kind": "experiment", "title": "run"}]}')],
        "experimenter": [
            ("tool", "run_command", {"command": "echo hi > out.txt"}),
            ("final", '```json {"experiment": "x", "status": "success", "metrics": {"a": 1}} ```'),
        ],
    }
    task_id, run_id = await create_task_and_run(store, "run an experiment")
    ctx = await make_ctx(settings, store, run_id, task_id, "run an experiment", scripts)
    await store.set_task_status(task_id, "running")

    await execute_run(store, settings, run_id, ctx=ctx)
    approvals = await store.list_approvals(run_id)
    await store.decide_approval(approvals[0].id, "rejected", "not today")
    await execute_run(store, settings, run_id, ctx=ctx)

    run = await store.get_run(run_id)
    assert run.status == "rejected"
    assert run.report_md


async def test_diagnose_repair_loop_succeeds(settings, store):
    settings = settings.model_copy(update={"max_repair_attempts": 2})
    scripts = {
        "planner": [("final", '{"tasks": [{"id": "t1", "kind": "experiment", "title": "train"}]}')],
        "experimenter": [
            ("tool", "run_command", {"command": "python3 missing_script.py"}),
            ("final", '```json {"experiment": "train", "command": "python3 missing_script.py", "status": "failed", "metrics": {}, "log_excerpt": "can not open file"} ```'),
            # continuation after repair: same provider instance, cursor persists
            ("tool", "run_command", {"command": "echo 'acc=0.75' > metrics.txt && cat metrics.txt"}),
            ("final", '```json {"experiment": "train", "command": "echo", "status": "success", "metrics": {"acc": 0.75}, "log_excerpt": "acc=0.75"} ```'),
        ],
        "diagnostician": [("final", "The script missing_script.py does not exist in the workspace; create it.")],
        "coder": [
            ("tool", "fs_write", {"path": "missing_script.py", "content": "print('acc=0.75')"}),
            ("final", '```json {"summary": "created missing script", "files": ["missing_script.py"], "tests_passed": true} ```'),
        ],
        "reviewer": [("final", '```json {"approved": true, "confidence": 0.85, "issues": []} ```')],
    }
    task_id, run_id = await create_task_and_run(store, "train and repair")
    ctx = await make_ctx(settings, store, run_id, task_id, "train and repair", scripts)
    await store.set_task_status(task_id, "running")

    # the repair loop crosses several approval gates (failed command, the
    # repair write, the successful rerun, final sign-off) — approve each
    for _ in range(8):
        await execute_run(store, settings, run_id, ctx=ctx)
        run = await store.get_run(run_id)
        if run.status != "awaiting_approval":
            break
        pending = [a for a in await store.list_approvals(run_id) if a.status == "pending"]
        assert pending, "run awaiting approval but no pending approval row"
        await store.decide_approval(pending[0].id, "approved")

    assert run.status == "completed"
    assert "0.75" in run.report_md
    assert ctx.metrics.repairs == 1
